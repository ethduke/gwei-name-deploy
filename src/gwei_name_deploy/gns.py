from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ens_normalize import ens_normalize
from eth_account import Account
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
    {
        "type": "function",
        "name": "makeCommitment",
        "stateMutability": "pure",
        "inputs": [
            {"name": "label", "type": "string"},
            {"name": "owner", "type": "address"},
            {"name": "secret", "type": "bytes32"},
        ],
        "outputs": [{"name": "commitment", "type": "bytes32"}],
    },
    {
        "type": "function",
        "name": "commitments",
        "stateMutability": "view",
        "inputs": [{"name": "commitment", "type": "bytes32"}],
        "outputs": [{"name": "timestamp", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "commit",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "commitment", "type": "bytes32"}],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "reveal",
        "stateMutability": "payable",
        "inputs": [
            {"name": "label", "type": "string"},
            {"name": "secret", "type": "bytes32"},
        ],
        "outputs": [{"name": "tokenId", "type": "uint256"}],
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


@dataclass(frozen=True, slots=True)
class TransactionResult:
    tx_hash: str
    block_number: int
    block_timestamp: int


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


class Web3GnsWriter(Web3GnsReader):
    """Locally signed GNS transactions with receipt verification."""

    def __init__(
        self,
        rpc_url: str,
        network: Network,
        private_key: str,
        timeout: float = 20.0,
    ) -> None:
        super().__init__(rpc_url, network, timeout=timeout)
        try:
            self.account = Account.from_key(private_key)
        except Exception as exc:
            raise GnsError(
                "GWEI_PRIVATE_KEY is not a valid Ethereum private key"
            ) from exc

    @property
    def address(self) -> str:
        return Web3.to_checksum_address(self.account.address)

    def make_commitment(self, label: str, secret: str) -> str:
        value = self.contract.functions.makeCommitment(
            label, self.address, bytes.fromhex(secret[2:])
        ).call()
        return Web3.to_hex(value)

    def commitment_time(self, commitment: str) -> int:
        return int(self.contract.functions.commitments(commitment).call())

    def latest_timestamp(self) -> int:
        return int(self.web3.eth.get_block("latest")["timestamp"])

    def broadcast_commit(self, commitment: str) -> str:
        return self._broadcast(self.contract.functions.commit(commitment))

    def broadcast_reveal(self, label: str, secret: str, value: int) -> str:
        return self._broadcast(
            self.contract.functions.reveal(label, bytes.fromhex(secret[2:])),
            value=value,
        )

    def wait_transaction(self, tx_hash: str) -> TransactionResult:
        try:
            receipt = self.web3.eth.wait_for_transaction_receipt(
                tx_hash, timeout=180, poll_latency=2
            )
        except Exception as exc:
            raise GnsError(f"transaction did not confirm: {exc}") from exc

        if receipt["status"] != 1:
            raise GnsError(f"transaction reverted: {tx_hash}")
        block = self.web3.eth.get_block(receipt["blockNumber"])
        return TransactionResult(
            tx_hash=tx_hash,
            block_number=int(receipt["blockNumber"]),
            block_timestamp=int(block["timestamp"]),
        )

    def _broadcast(self, function, value: int = 0) -> str:
        try:
            transaction = function.build_transaction(
                {
                    "from": self.address,
                    "nonce": self.web3.eth.get_transaction_count(
                        self.address, "pending"
                    ),
                    "chainId": self.network.chain_id,
                    "value": value,
                }
            )
            signed = self.account.sign_transaction(transaction)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
        except Exception as exc:
            raise GnsError(f"transaction could not be broadcast: {exc}") from exc
        return Web3.to_hex(tx_hash)


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
