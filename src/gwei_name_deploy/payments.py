from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import qrcode

from gwei_name_deploy.json_store import JsonStoreError, load_json, save_json

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
    """Owner-only JSON store for a small number of payment requests."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.path = state_dir / "payments.json"

    def create(
        self, chain_id: int, name: str, recipient: str, amount_wei: int
    ) -> PaymentRequest:
        state = self._load()
        request = PaymentRequest(
            request_id=uuid.uuid4().hex,
            chain_id=chain_id,
            name=name,
            recipient=recipient,
            amount_wei=amount_wei,
            uri=build_payment_uri(recipient, chain_id, amount_wei),
            created_at=datetime.now(tz=UTC).isoformat(),
            status="open",
            tx_hash=None,
            verified_at=None,
            block_number=None,
        )
        state["requests"][request.request_id] = asdict(request)
        self._save(state)
        return request

    def get(self, request_id: str) -> PaymentRequest:
        _validate_request_id(request_id)
        item = self._load()["requests"].get(request_id)
        if item is None:
            raise PaymentError(f"payment request not found: {request_id}")
        try:
            return PaymentRequest(**item)
        except TypeError as exc:
            raise PaymentError(f"invalid payment request: {request_id}") from exc

    def mark_paid(
        self, request_id: str, tx_hash: str, block_number: int
    ) -> PaymentRequest:
        _validate_request_id(request_id)
        state = self._load()
        item = state["requests"].get(request_id)
        if item is None:
            raise PaymentError(f"payment request not found: {request_id}")
        if item.get("status") != "open":
            raise PaymentError("payment request is already satisfied")
        if any(
            request.get("tx_hash", "").lower() == tx_hash.lower()
            for request in state["requests"].values()
            if request.get("tx_hash")
        ):
            raise PaymentError(
                "transaction hash already satisfies another payment request"
            )
        item.update(
            status="paid",
            tx_hash=tx_hash.lower(),
            verified_at=datetime.now(tz=UTC).isoformat(),
            block_number=block_number,
        )
        self._save(state)
        return PaymentRequest(**item)

    def qr_path(self, request_id: str) -> Path:
        _validate_request_id(request_id)
        return self.state_dir / "payments" / f"{request_id}.png"

    def _load(self) -> dict:
        try:
            state = load_json(self.path, {"version": 1, "requests": {}})
            if not isinstance(state.get("requests"), dict):
                raise PaymentError(f"invalid payment state: {self.path}")
            return state
        except JsonStoreError as exc:
            raise PaymentError(str(exc)) from exc

    def _save(self, state: dict) -> None:
        try:
            save_json(self.path, state)
        except JsonStoreError as exc:
            raise PaymentError(str(exc)) from exc


def _validate_request_id(request_id: str) -> None:
    if not REQUEST_ID_PATTERN.fullmatch(request_id):
        raise PaymentError("invalid payment request ID")
