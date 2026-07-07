from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from gwei_name_deploy.json_store import JsonStoreError, load_json, save_json


class HistoryError(RuntimeError):
    """Raised when local site history cannot be read or written."""


@dataclass(frozen=True, slots=True)
class SiteRevision:
    revision_id: int
    chain_id: int
    name: str
    token_id: str
    cid: str
    contenthash_hex: str
    tx_hash: str
    created_at: str


class HistoryStore:
    """Small JSON address book and IPFS revision history."""

    def __init__(self, state_dir: Path) -> None:
        self.path = state_dir / "site_history.json"
        self.address_book_path = state_dir / "address_book.json"

    def record_revision(
        self,
        chain_id: int,
        name: str,
        token_id: int,
        cid: str,
        contenthash: bytes,
        tx_hash: str,
    ) -> SiteRevision:
        state = self._load()
        revisions = state["revisions"]
        revision = SiteRevision(
            revision_id=max((int(item["revision_id"]) for item in revisions), default=0)
            + 1,
            chain_id=chain_id,
            name=name,
            token_id=str(token_id),
            cid=cid,
            contenthash_hex="0x" + contenthash.hex(),
            tx_hash=tx_hash,
            created_at=datetime.now(tz=UTC).isoformat(),
        )
        revisions.append(asdict(revision))
        self._save(state)
        return revision

    def list_revisions(self, chain_id: int, name: str) -> list[SiteRevision]:
        revisions = [
            SiteRevision(**item)
            for item in self._load()["revisions"]
            if int(item["chain_id"]) == chain_id and item["name"] == name
        ]
        return sorted(revisions, key=lambda item: item.revision_id, reverse=True)

    def get_revision(self, revision_id: int) -> SiteRevision:
        for item in self._load()["revisions"]:
            if int(item["revision_id"]) == revision_id:
                return SiteRevision(**item)
        raise HistoryError(f"site revision not found: {revision_id}")

    def upsert_address_name(self, chain_id: int, address: str, name: str) -> None:
        try:
            address_book = load_json(self.address_book_path, {})
        except JsonStoreError as exc:
            raise HistoryError(str(exc)) from exc
        key = f"{chain_id}:{address.lower()}"
        address_book[key] = name
        try:
            save_json(self.address_book_path, address_book)
        except JsonStoreError as exc:
            raise HistoryError(str(exc)) from exc

    def _load(self) -> dict:
        try:
            state = load_json(
                self.path,
                {"version": 1, "revisions": []},
            )
            if not isinstance(state.get("revisions"), list):
                raise HistoryError(f"invalid history state: {self.path}")
            return state
        except JsonStoreError as exc:
            raise HistoryError(str(exc)) from exc

    def _save(self, state: dict) -> None:
        try:
            save_json(self.path, state)
        except JsonStoreError as exc:
            raise HistoryError(str(exc)) from exc
