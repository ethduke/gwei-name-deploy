from __future__ import annotations

from dataclasses import dataclass

import pytest

from gwei_name_deploy.gns import TransactionResult
from gwei_name_deploy.models import NamePlan
from gwei_name_deploy.registration import (
    RegistrationError,
    commit_pending,
    prepare_run,
    reveal_ready,
)

OWNER = "0x1234567890123456789012345678901234567890"


def available_plan() -> NamePlan:
    return NamePlan(
        input_name="alice",
        name="alice.gwei",
        label="alice",
        label_bytes=5,
        token_id=123,
        status="available",
        available=True,
        owner=None,
        expires_at=None,
        fee_wei=500_000_000_000_000,
        premium_wei=0,
    )


@dataclass
class FakeWriter:
    address: str = OWNER
    chain_time: int = 1_000
    commitment_timestamp: int = 0
    available: bool = True
    current_owner: str | None = None
    commit_calls: int = 0
    reveal_calls: int = 0
    pending_kind: str | None = None

    def make_commitment(self, label: str, secret: str) -> str:
        return "0x" + "ab" * 32

    def commitment_time(self, commitment: str) -> int:
        return self.commitment_timestamp

    def latest_timestamp(self) -> int:
        return self.chain_time

    def broadcast_commit(self, commitment: str) -> str:
        self.commit_calls += 1
        self.pending_kind = "commit"
        return "0xcommit"

    def broadcast_reveal(self, label: str, secret: str, value: int) -> str:
        self.reveal_calls += 1
        self.pending_kind = "reveal"
        return "0xreveal"

    def wait_transaction(self, tx_hash: str) -> TransactionResult:
        if self.pending_kind == "commit" or tx_hash == "0xcommit":
            self.pending_kind = None
            self.commitment_timestamp = self.chain_time
            return TransactionResult(tx_hash, 10, self.chain_time)
        if self.pending_kind == "reveal" or tx_hash == "0xreveal":
            self.pending_kind = None
            self.commitment_timestamp = 0
            self.available = False
            self.current_owner = self.address
            return TransactionResult(tx_hash, 11, self.chain_time)
        raise AssertionError(f"unexpected transaction hash: {tx_hash}")

    def is_available(self, label: str) -> bool:
        return self.available

    def fee(self, label_bytes: int) -> int:
        return 500_000_000_000_000

    def premium(self, token_id: int) -> int:
        return 0

    def expiry(self, token_id: int) -> int:
        return 0

    def in_grace(self, token_id: int) -> bool:
        return False

    def owner(self, token_id: int) -> str | None:
        return self.current_owner


def test_commit_then_reveal_when_ready() -> None:
    run = prepare_run([available_plan()], "sepolia", 11155111, OWNER)
    writer = FakeWriter()
    saves: list[str] = []

    commit_pending(run, writer, lambda value: saves.append(value.items[0].status))

    assert run.items[0].status == "committed"
    assert run.items[0].min_reveal_at == 1_060
    assert writer.commit_calls == 1

    writer.chain_time = 1_060
    wait = reveal_ready(run, writer, lambda value: saves.append(value.items[0].status))

    assert wait == 0
    assert run.items[0].status == "revealed"
    assert writer.reveal_calls == 1


def test_reveal_reports_remaining_wait() -> None:
    run = prepare_run([available_plan()], "sepolia", 11155111, OWNER)
    writer = FakeWriter()
    commit_pending(run, writer, lambda value: None)
    writer.chain_time = 1_020

    assert reveal_ready(run, writer, lambda value: None) == 40
    assert writer.reveal_calls == 0


def test_recovers_onchain_commit_after_interruption() -> None:
    run = prepare_run([available_plan()], "sepolia", 11155111, OWNER)
    writer = FakeWriter(commitment_timestamp=900)
    run.items[0].commitment = writer.make_commitment("alice", run.items[0].secret)

    commit_pending(run, writer, lambda value: None)

    assert run.items[0].status == "committed"
    assert writer.commit_calls == 0
    assert run.items[0].committed_at == 900


def test_persists_transaction_hash_before_waiting() -> None:
    run = prepare_run([available_plan()], "sepolia", 11155111, OWNER)
    writer = FakeWriter()

    def interrupted_wait(tx_hash: str) -> TransactionResult:
        raise RuntimeError("simulated interruption")

    writer.wait_transaction = interrupted_wait  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="simulated interruption"):
        commit_pending(run, writer, lambda value: None)

    assert run.items[0].commit_tx_hash == "0xcommit"


def test_rejects_wrong_signer() -> None:
    run = prepare_run([available_plan()], "sepolia", 11155111, OWNER)
    writer = FakeWriter(address="0x0000000000000000000000000000000000000001")

    with pytest.raises(RegistrationError, match="does not match run owner"):
        commit_pending(run, writer, lambda value: None)
