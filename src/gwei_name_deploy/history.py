from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


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
    def __init__(self, state_dir: Path) -> None:
        self.path = state_dir / "history.sqlite3"

    def initialize(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
        if not self.path.exists():
            try:
                descriptor = os.open(
                    self.path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                os.close(descriptor)
            except FileExistsError:
                pass
            except OSError as exc:
                raise HistoryError(f"could not create history database: {exc}") from exc
        self.path.chmod(0o600)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS address_names (
                    chain_id INTEGER NOT NULL,
                    address TEXT NOT NULL,
                    name TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (chain_id, address)
                );

                CREATE TABLE IF NOT EXISTS site_revisions (
                    revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chain_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    token_id TEXT NOT NULL,
                    cid TEXT NOT NULL,
                    contenthash_hex TEXT NOT NULL,
                    tx_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS site_revision_lookup
                ON site_revisions (chain_id, name, revision_id DESC);
                """
            )

    def record_revision(
        self,
        chain_id: int,
        name: str,
        token_id: int,
        cid: str,
        contenthash: bytes,
        tx_hash: str,
    ) -> SiteRevision:
        self.initialize()
        created_at = datetime.now(tz=UTC).isoformat()
        contenthash_hex = "0x" + contenthash.hex()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO site_revisions
                    (chain_id, name, token_id, cid,
                     contenthash_hex, tx_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chain_id,
                    name,
                    str(token_id),
                    cid,
                    contenthash_hex,
                    tx_hash,
                    created_at,
                ),
            )
            revision_id = int(cursor.lastrowid)
        return SiteRevision(
            revision_id=revision_id,
            chain_id=chain_id,
            name=name,
            token_id=str(token_id),
            cid=cid,
            contenthash_hex=contenthash_hex,
            tx_hash=tx_hash,
            created_at=created_at,
        )

    def list_revisions(self, chain_id: int, name: str) -> list[SiteRevision]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT revision_id, chain_id, name, token_id, cid,
                       contenthash_hex, tx_hash, created_at
                FROM site_revisions
                WHERE chain_id = ? AND name = ?
                ORDER BY revision_id DESC
                """,
                (chain_id, name),
            ).fetchall()
        return [SiteRevision(*row) for row in rows]

    def get_revision(self, revision_id: int) -> SiteRevision:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT revision_id, chain_id, name, token_id, cid,
                       contenthash_hex, tx_hash, created_at
                FROM site_revisions WHERE revision_id = ?
                """,
                (revision_id,),
            ).fetchone()
        if row is None:
            raise HistoryError(f"site revision not found: {revision_id}")
        return SiteRevision(*row)

    def upsert_address_name(self, chain_id: int, address: str, name: str) -> None:
        self.initialize()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO address_names (chain_id, address, name, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(chain_id, address) DO UPDATE SET
                    name = excluded.name,
                    updated_at = excluded.updated_at
                """,
                (chain_id, address.lower(), name, datetime.now(tz=UTC).isoformat()),
            )

    def _connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(self.path)
            connection.execute("PRAGMA foreign_keys = ON")
            return connection
        except (OSError, sqlite3.Error) as exc:
            raise HistoryError(f"could not open history database: {exc}") from exc
