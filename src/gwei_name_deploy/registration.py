from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol

from gwei_name_deploy.gns import GnsReader, TransactionResult, plan_name
from gwei_name_deploy.models import NamePlan

MIN_COMMITMENT_AGE = 60
MAX_COMMITMENT_AGE = 86_400
RegistrationStatus = Literal["planned", "committed", "revealed"]


class RegistrationError(RuntimeError):
    """Raised when a registration run cannot advance safely."""


@dataclass(slots=True)
class RegistrationItem:
    input_name: str
    name: str
    label: str
    token_id: int
    secret: str
    planned_value_wei: int
    status: RegistrationStatus = "planned"
    commitment: str | None = None
    commit_tx_hash: str | None = None
    committed_at: int | None = None
    min_reveal_at: int | None = None
    commitment_expires_at: int | None = None
    reveal_tx_hash: str | None = None


@dataclass(slots=True)
class RegistrationRun:
    version: int
    run_id: str
    network: str
    chain_id: int
    owner: str
    created_at: str
    items: list[RegistrationItem]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> RegistrationRun:
        items = [RegistrationItem(**item) for item in value["items"]]
        return cls(
            version=value["version"],
            run_id=value["run_id"],
            network=value["network"],
            chain_id=value["chain_id"],
            owner=value["owner"],
            created_at=value["created_at"],
            items=items,
        )


class RegistrationWriter(GnsReader, Protocol):
    @property
    def address(self) -> str: ...

    def make_commitment(self, label: str, secret: str) -> str: ...

    def commitment_time(self, commitment: str) -> int: ...

    def latest_timestamp(self) -> int: ...

    def broadcast_commit(self, commitment: str) -> str: ...

    def broadcast_reveal(self, label: str, secret: str, value: int) -> str: ...

    def wait_transaction(self, tx_hash: str) -> TransactionResult: ...


SaveRun = Callable[[RegistrationRun], None]


def prepare_run(
    plans: list[NamePlan], network: str, chain_id: int, owner: str
) -> RegistrationRun:
    unavailable = [plan.name for plan in plans if not plan.available]
    if unavailable:
        raise RegistrationError(
            "cannot register unavailable names: " + ", ".join(unavailable)
        )

    now = datetime.now(tz=UTC)
    run_id = f"{now:%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}"
    return RegistrationRun(
        version=1,
        run_id=run_id,
        network=network,
        chain_id=chain_id,
        owner=owner,
        created_at=now.isoformat(),
        items=[
            RegistrationItem(
                input_name=plan.input_name,
                name=plan.name,
                label=plan.label,
                token_id=plan.token_id,
                secret="0x" + secrets.token_hex(32),
                planned_value_wei=plan.total_wei,
            )
            for plan in plans
        ],
    )


def commit_pending(
    run: RegistrationRun, writer: RegistrationWriter, save: SaveRun
) -> None:
    _verify_owner(run, writer)
    for item in run.items:
        if item.status != "planned":
            continue
        if item.commitment is None:
            item.commitment = writer.make_commitment(item.label, item.secret)
            save(run)

        committed_at = writer.commitment_time(item.commitment)
        if committed_at == 0:
            if item.commit_tx_hash is None:
                item.commit_tx_hash = writer.broadcast_commit(item.commitment)
                save(run)
            result = writer.wait_transaction(item.commit_tx_hash)
            committed_at = result.block_timestamp

        item.status = "committed"
        item.committed_at = committed_at
        item.min_reveal_at = committed_at + MIN_COMMITMENT_AGE
        item.commitment_expires_at = committed_at + MAX_COMMITMENT_AGE
        save(run)


def reveal_ready(
    run: RegistrationRun, writer: RegistrationWriter, save: SaveRun
) -> int:
    """Reveal every ready commitment and return seconds until the next reveal."""
    _verify_owner(run, writer)
    now = writer.latest_timestamp()
    waits: list[int] = []

    for item in run.items:
        if item.status != "committed":
            continue
        if not item.commitment:
            raise RegistrationError(f"missing commitment for {item.name}")

        committed_at = writer.commitment_time(item.commitment)
        if committed_at == 0:
            if item.reveal_tx_hash:
                writer.wait_transaction(item.reveal_tx_hash)
                item.status = "revealed"
                save(run)
                continue
            current = plan_name(writer, item.name)
            if not current.available and current.owner == run.owner:
                item.status = "revealed"
                save(run)
                continue
            raise RegistrationError(
                f"commitment for {item.name} is missing and ownership was not recovered"
            )

        if now < committed_at + MIN_COMMITMENT_AGE:
            waits.append(committed_at + MIN_COMMITMENT_AGE - now)
            continue
        if now > committed_at + MAX_COMMITMENT_AGE:
            raise RegistrationError(f"commitment for {item.name} expired")

        current = plan_name(writer, item.name)
        if not current.available:
            raise RegistrationError(f"{item.name} became unavailable before reveal")
        if item.reveal_tx_hash is None:
            item.reveal_tx_hash = writer.broadcast_reveal(
                item.label, item.secret, current.total_wei
            )
            save(run)
        writer.wait_transaction(item.reveal_tx_hash)
        item.status = "revealed"
        save(run)

    return min(waits) if waits else 0


def _verify_owner(run: RegistrationRun, writer: RegistrationWriter) -> None:
    if writer.address.lower() != run.owner.lower():
        raise RegistrationError(
            f"signer {writer.address} does not match run owner {run.owner}"
        )
