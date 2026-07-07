from dataclasses import dataclass

import pytest

from gwei_name_deploy.gns import (
    NameValidationError,
    normalize_top_level_name,
    plan_name,
    token_id_for_label,
)


@dataclass
class FakeReader:
    available: bool = True
    fee_wei: int = 500_000_000_000_000
    premium_wei: int = 0
    expiry_value: int = 0
    grace: bool = False
    owner_value: str | None = None

    def is_available(self, label: str) -> bool:
        assert label == "alice"
        return self.available

    def fee(self, label_bytes: int) -> int:
        assert label_bytes == 5
        return self.fee_wei

    def premium(self, token_id: int) -> int:
        assert token_id == token_id_for_label("alice")
        return self.premium_wei

    def expiry(self, token_id: int) -> int:
        return self.expiry_value

    def in_grace(self, token_id: int) -> bool:
        return self.grace

    def owner(self, token_id: int) -> str | None:
        return self.owner_value


def test_normalizes_top_level_name() -> None:
    assert normalize_top_level_name("Alice.GWEI") == ("alice", "alice.gwei")


def test_rejects_subdomain() -> None:
    with pytest.raises(NameValidationError, match="top-level names only"):
        normalize_top_level_name("sub.alice.gwei")


def test_plans_available_name() -> None:
    result = plan_name(FakeReader(), "Alice.GWEI")

    assert result.name == "alice.gwei"
    assert result.status == "available"
    assert result.total_wei == 500_000_000_000_000
    assert result.owner is None
    assert len(result.token_id_hex) == 66


def test_plans_registered_name() -> None:
    owner = "0x1234567890123456789012345678901234567890"
    result = plan_name(
        FakeReader(
            available=False,
            expiry_value=1_800_000_000,
            owner_value=owner,
        ),
        "alice",
    )

    assert result.status == "registered"
    assert result.owner == owner
    assert result.expires_at == 1_800_000_000
