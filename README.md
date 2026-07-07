# Gwei Name Deploy

Register a `.gwei` name, publish an IPFS website, and create ETH payment links
from a Python command-line tool.

> [!IMPORTANT]
> This project is an early, unaffiliated community tool for the
> [Gwei Name Service](https://gwei.domains/). No transaction-writing feature is
> implemented in the initial scaffold. Test all future write flows on Sepolia
> before using Ethereum mainnet.

## Why

The Gwei Name Service web app is convenient for individual names. Gwei Name
Deploy is intended for repeatable operator workflows:

- inspect availability and registration cost before signing;
- register one name or a CSV batch with resumable commit/reveal state;
- upload a static site to IPFS and update its GNS contenthash;
- generate ETH payment links and QR codes, then verify payment transactions.

## Status and roadmap

- [x] Safe Python CLI scaffold and configuration
- [ ] Read-only GNS planning and availability checks
- [ ] Resumable commit/reveal registration
- [ ] IPFS website publishing and rollback history
- [ ] ETH payment links, QR codes, and verification
- [ ] Operator and security guides

Planned interface:

```console
gwei-name plan alice
gwei-name register alice
gwei-name register --file names.csv
gwei-name publish alice ./website
gwei-name launch alice ./website
gwei-name pay create alice --amount 0.01
gwei-name pay verify REQUEST_ID TX_HASH
```

Commands that change chain state will default to dry-run/preview behavior and
require explicit confirmation before broadcast.

## Development

Requirements: Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```console
uv sync --dev
uv run gwei-name --help
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Copy `.env.example` to `.env` for local configuration. `.env`, run state,
commitment secrets, generated sites, and payment artifacts are ignored by Git.

## Configuration

| Variable | Purpose |
| --- | --- |
| `GWEI_NETWORK` | `sepolia` by default; `mainnet` must be explicit |
| `GWEI_RPC_URL` | Ethereum JSON-RPC endpoint |
| `GWEI_PRIVATE_KEY` | Local transaction signer; never pass via CLI |
| `GWEI_STATE_DIR` | Optional local state directory override |
| `GWEI_IPFS_PROVIDER` | Planned IPFS adapter selection |
| `GWEI_IPFS_TOKEN` | Planned provider token; never commit it |

## Storage and key safety

An address-to-name mapping is public blockchain data. The planned local cache
will use SQLite keyed by `(chain_id, checksummed_address)`, which provides
atomic updates and useful indexing without pretending the data needs secrecy.

Private keys will **never** be stored in SQLite. The MVP reads a key from the
process environment and signs locally; encrypted JSON keystores or the OS
keychain are the preferred next signer backends. Commit/reveal secrets are not
wallet keys, but losing them prevents reveal, so resumable runs will store them
in owner-only (`0600`) local state and exclude them from Git.

## GNS deployments

The current GNS contracts use the same deterministic addresses on mainnet and
Sepolia:

| Contract | Address |
| --- | --- |
| NameNFT | `0x9D51D507BC7264d4fE8Ad1cf7Fe191933A0a81d6` |
| Universal Resolver | `0xD658131FFB6D732335d37f199374289F1b31564F` |

Contract addresses are centralized in `gwei_name_deploy.constants` and will be
checked against the upstream repository before releases.

## License

[MIT](LICENSE)
