from __future__ import annotations

import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import qrcode

REQUEST_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class PaymentError(RuntimeError):
    """Raised when a payment request is invalid or cannot be verified."""


@dataclass(frozen=True, slots=True)
class PaymentRequest:
    request_id: str
    chain_id: int
    name: str
    recipient: str
    amount_wei: int
    uri: str
    created_at: str
    status: str
    tx_hash: str | None
    verified_at: str | None
    block_number: int | None


def parse_eth_amount(value: str) -> int:
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise PaymentError("ETH amount must be a decimal number") from exc
    if not amount.is_finite() or amount <= 0:
        raise PaymentError("ETH amount must be greater than zero")
    wei = amount * Decimal(10**18)
    if wei != wei.to_integral_value():
        raise PaymentError("ETH amount cannot have more than 18 decimal places")
    return int(wei)


def build_payment_uri(recipient: str, chain_id: int, amount_wei: int) -> str:
    return f"ethereum:{recipient}@{chain_id}?value={amount_wei}"


def write_qr_code(uri: str, destination: Path) -> None:
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination.parent.chmod(0o700)
    image = qrcode.make(uri)
    image.save(destination)
    destination.chmod(0o600)


def verify_payment_transaction(
    request: PaymentRequest, transaction: dict, receipt: dict
) -> int:
    if int(receipt.get("status", 0)) != 1:
        raise PaymentError("transaction did not succeed")
    recipient = transaction.get("to")
    if not recipient or recipient.lower() != request.recipient.lower():
        raise PaymentError("transaction recipient does not match payment request")
    if int(transaction.get("value", -1)) != request.amount_wei:
        raise PaymentError("transaction value does not exactly match payment request")
    block_number = receipt.get("blockNumber")
    if block_number is None:
        raise PaymentError("transaction is not confirmed in a block")
    return int(block_number)


class PaymentStore:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.path = state_dir / "payments.sqlite3"

    def create(
        self, chain_id: int, name: str, recipient: str, amount_wei: int
    ) -> PaymentRequest:
        self.initialize()
        request_id = uuid.uuid4().hex
        created_at = datetime.now(tz=UTC).isoformat()
        uri = build_payment_uri(recipient, chain_id, amount_wei)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO payment_requests
                    (request_id, chain_id, name, recipient, amount_wei, uri,
                     created_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'open')
                """,
                (
                    request_id,
                    chain_id,
                    name,
                    recipient.lower(),
                    str(amount_wei),
                    uri,
                    created_at,
                ),
            )
        return self.get(request_id)

    def get(self, request_id: str) -> PaymentRequest:
        self.initialize()
        _validate_request_id(request_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT request_id, chain_id, name, recipient, amount_wei, uri,
                       created_at, status, tx_hash, verified_at, block_number
                FROM payment_requests WHERE request_id = ?
                """,
                (request_id,),
            ).fetchone()
        if row is None:
            raise PaymentError(f"payment request not found: {request_id}")
        values = list(row)
        values[4] = int(values[4])
        return PaymentRequest(*values)

    def mark_paid(
        self, request_id: str, tx_hash: str, block_number: int
    ) -> PaymentRequest:
        self.initialize()
        _validate_request_id(request_id)
        verified_at = datetime.now(tz=UTC).isoformat()
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE payment_requests
                    SET status = 'paid', tx_hash = ?, verified_at = ?, block_number = ?
                    WHERE request_id = ? AND status = 'open'
                    """,
                    (tx_hash.lower(), verified_at, block_number, request_id),
                )
                if cursor.rowcount != 1:
                    raise PaymentError("payment request is already satisfied")
        except sqlite3.IntegrityError as exc:
            raise PaymentError(
                "transaction hash already satisfies another payment request"
            ) from exc
        return self.get(request_id)

    def qr_path(self, request_id: str) -> Path:
        _validate_request_id(request_id)
        return self.state_dir / "payments" / f"{request_id}.png"

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
                raise PaymentError(f"could not create payment database: {exc}") from exc
        self.path.chmod(0o600)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS payment_requests (
                    request_id TEXT PRIMARY KEY,
                    chain_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    amount_wei TEXT NOT NULL,
                    uri TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('open', 'paid')),
                    tx_hash TEXT UNIQUE,
                    verified_at TEXT,
                    block_number INTEGER
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        try:
            return sqlite3.connect(self.path)
        except (OSError, sqlite3.Error) as exc:
            raise PaymentError(f"could not open payment database: {exc}") from exc


def _validate_request_id(request_id: str) -> None:
    if not REQUEST_ID_PATTERN.fullmatch(request_id):
        raise PaymentError("invalid payment request ID")
