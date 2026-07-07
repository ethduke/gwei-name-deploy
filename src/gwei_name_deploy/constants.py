from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Network:
    name: str
    chain_id: int
    explorer_url: str
    name_nft_address: str
    universal_resolver_address: str


NAME_NFT_ADDRESS = "0x9D51D507BC7264d4fE8Ad1cf7Fe191933A0a81d6"
UNIVERSAL_RESOLVER_ADDRESS = "0xD658131FFB6D732335d37f199374289F1b31564F"
GWEI_NODE = "0xcca9c7f2dbe2808af0de2982fc84314bfa68a82a6a60ad5cd757f91a233d7d7f"

NETWORKS = {
    "mainnet": Network(
        name="mainnet",
        chain_id=1,
        explorer_url="https://etherscan.io",
        name_nft_address=NAME_NFT_ADDRESS,
        universal_resolver_address=UNIVERSAL_RESOLVER_ADDRESS,
    ),
    "sepolia": Network(
        name="sepolia",
        chain_id=11155111,
        explorer_url="https://sepolia.etherscan.io",
        name_nft_address=NAME_NFT_ADDRESS,
        universal_resolver_address=UNIVERSAL_RESOLVER_ADDRESS,
    ),
}
