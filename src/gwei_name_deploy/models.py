from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AddressName:
    """Public address-to-primary-name mapping scoped to a chain."""

    chain_id: int
    address: str
    name: str
