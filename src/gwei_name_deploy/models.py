from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class AddressName:
    """Public address-to-primary-name mapping scoped to a chain."""

    chain_id: int
    address: str
    name: str


@dataclass(frozen=True, slots=True)
class NamePlan:
    """Read-only registration facts for one top-level GNS name."""

    input_name: str
    name: str
    label: str
    label_bytes: int
    token_id: int
    status: Literal["available", "registered", "grace"]
    available: bool
    owner: str | None
    expires_at: int | None
    fee_wei: int
    premium_wei: int

    @property
    def total_wei(self) -> int:
        return self.fee_wei + self.premium_wei

    @property
    def token_id_hex(self) -> str:
        return f"0x{self.token_id:064x}"

    def to_dict(self) -> dict[str, str | int | bool | None]:
        return {
            "input_name": self.input_name,
            "name": self.name,
            "label": self.label,
            "label_bytes": self.label_bytes,
            "token_id": str(self.token_id),
            "token_id_hex": self.token_id_hex,
            "status": self.status,
            "available": self.available,
            "owner": self.owner,
            "expires_at": self.expires_at,
            "fee_wei": str(self.fee_wei),
            "premium_wei": str(self.premium_wei),
            "total_wei": str(self.total_wei),
        }
