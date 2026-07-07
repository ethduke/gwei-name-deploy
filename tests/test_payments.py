import stat
from dataclasses import replace
from pathlib import Path

import pytest

from gwei_name_deploy.payments import (
    PaymentError,
    PaymentStore,
    build_payment_uri,
    parse_eth_amount,
    verify_payment_transaction,
    write_qr_code,
)

RECIPIENT = "0x1234567890123456789012345678901234567890"


def test_parse_eth_amount_and_build_erc681_uri() -> None:
    amount_wei = parse_eth_amount("0.010000000000000001")

    assert amount_wei == 10_000_000_000_000_001
    assert (
        build_payment_uri(RECIPIENT, 1, amount_wei)
        == f"ethereum:{RECIPIENT}@1?value={amount_wei}"
    )


@pytest.mark.parametrize(
    "value", ["0", "-1", "nan", "inf", "hello", "0.0000000000000000001"]
)
def test_parse_eth_amount_rejects_invalid_values(value: str) -> None:
    with pytest.raises(PaymentError):
        parse_eth_amount(value)


def test_qr_code_is_private_png(tmp_path: Path) -> None:
    destination = tmp_path / "private" / "request.png"

    write_qr_code("ethereum:0x1234@1?value=1", destination)

    assert destination.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700


def test_payment_store_round_trip_and_permissions(tmp_path: Path) -> None:
    store = PaymentStore(tmp_path / "state")

    request = store.create(1, "alice.gwei", RECIPIENT, 10**16)
    paid = store.mark_paid(request.request_id, "0xabc", 123)

    assert request.status == "open"
    assert paid.status == "paid"
    assert paid.tx_hash == "0xabc"
    assert paid.block_number == 123
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o700


def test_transaction_hash_can_only_satisfy_one_request(tmp_path: Path) -> None:
    store = PaymentStore(tmp_path)
    first = store.create(1, "one.gwei", RECIPIENT, 1)
    second = store.create(1, "two.gwei", RECIPIENT, 1)
    store.mark_paid(first.request_id, "0xsame", 10)

    with pytest.raises(PaymentError, match="another payment request"):
        store.mark_paid(second.request_id, "0xsame", 10)


def test_verify_payment_requires_exact_successful_transaction(tmp_path: Path) -> None:
    request = PaymentStore(tmp_path).create(1, "alice.gwei", RECIPIENT, 123)
    transaction = {"to": RECIPIENT, "value": 123}
    receipt = {"status": 1, "blockNumber": 456}

    assert verify_payment_transaction(request, transaction, receipt) == 456

    with pytest.raises(PaymentError, match="recipient"):
        verify_payment_transaction(
            request,
            {"to": "0x0000000000000000000000000000000000000001", "value": 123},
            receipt,
        )
    with pytest.raises(PaymentError, match="value"):
        verify_payment_transaction(request, {"to": RECIPIENT, "value": 124}, receipt)
    with pytest.raises(PaymentError, match="did not succeed"):
        verify_payment_transaction(
            request, transaction, {"status": 0, "blockNumber": 456}
        )
    with pytest.raises(PaymentError, match="not confirmed"):
        verify_payment_transaction(request, transaction, {"status": 1})


def test_paid_request_cannot_be_satisfied_twice(tmp_path: Path) -> None:
    store = PaymentStore(tmp_path)
    request = store.create(1, "alice.gwei", RECIPIENT, 1)
    store.mark_paid(request.request_id, "0xfirst", 10)

    with pytest.raises(PaymentError, match="already satisfied"):
        store.mark_paid(request.request_id, "0xsecond", 11)


def test_verifier_compares_recipient_case_insensitively(tmp_path: Path) -> None:
    request = PaymentStore(tmp_path).create(1, "alice.gwei", RECIPIENT.upper(), 1)
    request = replace(request, recipient=RECIPIENT.upper())

    assert (
        verify_payment_transaction(
            request,
            {"to": RECIPIENT.lower(), "value": 1},
            {"status": 1, "blockNumber": 2},
        )
        == 2
    )
