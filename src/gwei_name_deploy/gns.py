from __future__ import annotations

from typing import Protocol

from ens_normalize import ens_normalize
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import ContractLogicError

from gwei_name_deploy.constants import GWEI_NODE, Network
from gwei_name_deploy.models import NamePlan

NAME_NFT_ABI = [
    {
        "type": "function",
        "name": "isAvailable",
        "stateMutability": "view",
        "inputs": [
            {"name": "label", "type": "string"},
            {"name": "parentId", "type": "uint256"},
        ],
        "outputs": [{"name": "available", "type": "bool"}],
    },
    {
        "type": "function",
        "name": "getFee",
        "stateMutability": "pure",
        "inputs": [{"name": "length", "type": "uint256"}],
        "outputs": [{"name": "fee", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "getPremium",
        "stateMutability": "view",
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "outputs": [{"name": "premium", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "expiresAt",
        "stateMutability": "view",
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "outputs": [{"name": "expiry", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "inGracePeriod",
        "stateMutability": "view",
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "outputs": [{"name": "inGrace", "type": "bool"}],
    },
    {
        "type": "function",
        "name": "ownerOf",
        "stateMutability": "view",
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "outputs": [{"name": "owner", "type": "address"}],
    },
]


class GnsError(RuntimeError):
    """Base error for GNS read operations."""


class NameValidationError(GnsError):
    """Raised when a requested name cannot be planned safely."""


class ChainMismatchError(GnsError):
    """Raised when an RPC endpoint serves an unexpected chain."""


class GnsReader(Protocol):
    def is_available(self, label: str) -> bool: ...

    def fee(self, label_bytes: int) -> int: ...

    def premium(self, token_id: int) -> int: ...

    def expiry(self, token_id: int) -> int: ...

    def in_grace(self, token_id: int) -> bool: ...

    def owner(self, token_id: int) -> str | None: ...


class Web3GnsReader:
    """Small read-only wrapper around the deployed GNS NameNFT."""

    def __init__(self, rpc_url: str, network: Network, timeout: float = 20.0) -> None:
        self.network = network
        self.web3 = Web3(
            Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": timeout})
        )
        try:
            chain_id = self.web3.eth.chain_id
        except Exception as exc:
            raise GnsError(f"could not connect to RPC endpoint: {exc}") from exc
        if chain_id != network.chain_id:
            raise ChainMismatchError(
                f"RPC chain ID is {chain_id}, expected {network.chain_id} "
                f"for {network.name}"
            )
        self.contract: Contract = self.web3.eth.contract(
            address=Web3.to_checksum_address(network.name_nft_address),
            abi=NAME_NFT_ABI,
        )

    def is_available(self, label: str) -> bool:
        return bool(self.contract.functions.isAvailable(label, 0).call())

    def fee(self, label_bytes: int) -> int:
        return int(self.contract.functions.getFee(label_bytes).call())

    def premium(self, token_id: int) -> int:
        return int(self.contract.functions.getPremium(token_id).call())

    def expiry(self, token_id: int) -> int:
        return int(self.contract.functions.expiresAt(token_id).call())

    def in_grace(self, token_id: int) -> bool:
        return bool(self.contract.functions.inGracePeriod(token_id).call())

    def owner(self, token_id: int) -> str | None:
        try:
            return Web3.to_checksum_address(
                self.contract.functions.ownerOf(token_id).call()
            )
        except (ContractLogicError, ValueError):
            return None


def normalize_top_level_name(value: str) -> tuple[str, str]:
    raw = value.strip()
    if not raw:
        raise NameValidationError("name cannot be empty")
    if raw.lower().endswith(".gwei"):
        raw = raw[:-5]

    try:
        normalized_name = ens_normalize(f"{raw}.gwei")
    except Exception as exc:
        raise NameValidationError(f"invalid ENSIP-15 name {value!r}: {exc}") from exc

    label = normalized_name[:-5]
    if "." in label:
        raise NameValidationError(
            "the initial planner supports top-level names only, not subdomains"
        )
    if not 1 <= len(label.encode()) <= 255:
        raise NameValidationError("label must contain between 1 and 255 UTF-8 bytes")
    return label, normalized_name


def token_id_for_label(label: str) -> int:
    parent_node = bytes.fromhex(GWEI_NODE[2:])
    label_hash = Web3.keccak(text=label)
    return int.from_bytes(Web3.keccak(parent_node + label_hash))


def plan_name(reader: GnsReader, input_name: str) -> NamePlan:
    label, name = normalize_top_level_name(input_name)
    label_bytes = len(label.encode())
    token_id = token_id_for_label(label)
    available = reader.is_available(label)
    fee = reader.fee(label_bytes)
    premium = reader.premium(token_id)
    expiry = reader.expiry(token_id)
    grace = reader.in_grace(token_id) if not available else False
    owner = reader.owner(token_id) if not available else None
    status = "available" if available else "grace" if grace else "registered"

    return NamePlan(
        input_name=input_name,
        name=name,
        label=label,
        label_bytes=label_bytes,
        token_id=token_id,
        status=status,
        available=available,
        owner=owner,
        expires_at=expiry or None,
        fee_wei=fee,
        premium_wei=premium,
    )
