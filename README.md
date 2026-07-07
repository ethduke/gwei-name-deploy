# Gwei Name Deploy

Register a `.gwei` name, publish an IPFS website, and create ETH payment links
from a Python command-line tool.

> [!IMPORTANT]
> This project is an early, unaffiliated community tool for the
> [Gwei Name Service](https://gwei.domains/). Transaction-writing features are
> preview-first and require `--broadcast`. Test the complete workflow on
> Sepolia before using Ethereum mainnet.

## Why

The Gwei Name Service web app is convenient for individual names. Gwei Name
Deploy is intended for repeatable operator workflows:

- inspect availability and registration cost before signing;
- register one name or a CSV batch with resumable commit/reveal state;
- upload a static site to IPFS and update its GNS contenthash;
- generate ETH payment links and QR codes, then verify payment transactions.

## Status and roadmap

- [x] Safe Python CLI scaffold and configuration
- [x] Read-only GNS planning and availability checks
- [x] Resumable commit/reveal registration
- [x] IPFS website publishing and rollback history
- [x] ETH payment links, QR codes, and verification
- [x] Operator and security guides

Implemented interface:

```console
gwei-name plan alice
gwei-name register alice
gwei-name register --file names.csv
gwei-name publish alice ./website
gwei-name pay create alice --amount 0.01
gwei-name pay verify REQUEST_ID TX_HASH
```

The implemented read-only planner accepts one name, a newline-delimited text
file, or a CSV whose first column is `name`:

```console
gwei-name plan alice --network sepolia --rpc-url "$GWEI_RPC_URL"
gwei-name plan --file names.csv --json
```

It reports ENSIP-15 normalization, UTF-8 byte length, deterministic token ID,
availability, current owner/expiry, fee, expiry premium, and total registration
value. The total deliberately excludes network gas.

Registration is split so no process must remain alive during the commit/reveal
delay:

```console
# Preview only (default)
gwei-name register alice --network sepolia

# Sign and send the commitment; writes an owner-only recovery file
gwei-name register alice --network sepolia --broadcast

# After 60 seconds, recover the run and reveal
gwei-name resume RUN_ID --broadcast
```

Use `--file names.csv` for a batch and `--max-registration-eth` to enforce a
hard cap on registration value. Each top-level reveal must be sent directly by
the intended owner because the GNS contract binds and mints to `msg.sender`.

Website publishing supports a local Kubo node or Pinata. It refuses symlinks,
environment files, private-key-like files, and directories without a root
`index.html`:

```console
# Inspect files and ownership without uploading
gwei-name publish alice examples/minimal-site --network sepolia

# Publish through local Kubo (localhost:5001 by default)
gwei-name publish alice ./website --broadcast

# Or use Pinata with GWEI_IPFS_TOKEN set
gwei-name publish alice ./website --provider pinata --broadcast

gwei-name site-history alice
gwei-name rollback alice REVISION_ID --broadcast
```

Successful contenthash transactions are recorded in an owner-only SQLite
database. The address-to-name cache is public data and also uses SQLite; wallet
private keys and commit secrets are never stored there.

Payment requests resolve the name's configured ETH address, encode an exact
amount as a chain-specific [ERC-681](https://eips.ethereum.org/EIPS/eip-681)
URI, and save a QR code locally:

```console
gwei-name pay create alice --amount 0.01 --network sepolia
gwei-name pay verify REQUEST_ID TX_HASH
```

Verification requires a successful, confirmed transaction whose recipient and
wei value exactly match the original request. Requests, status, and transaction
hashes are stored in owner-only local SQLite; the QR PNG is also owner-only.

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
See the [operator guide](docs/OPERATOR_GUIDE.md) for an end-to-end workflow and
[security policy](SECURITY.md) for the trust model and reporting process.

## Configuration

| Variable | Purpose |
| --- | --- |
| `GWEI_NETWORK` | `sepolia` by default; `mainnet` must be explicit |
| `GWEI_RPC_URL` | Ethereum JSON-RPC endpoint |
| `GWEI_PRIVATE_KEY` | Local transaction signer; never pass via CLI |
| `GWEI_STATE_DIR` | Optional local state directory override |
| `GWEI_IPFS_PROVIDER` | IPFS adapter: `local` or `pinata` |
| `GWEI_IPFS_API` | Local Kubo RPC; localhost only |
| `GWEI_IPFS_TOKEN` | Pinata JWT; never commit it |

## Storage and key safety

An address-to-name mapping is public blockchain data. The local cache uses
SQLite keyed by `(chain_id, checksummed_address)`, which provides
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
