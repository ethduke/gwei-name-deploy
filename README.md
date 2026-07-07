# Gwei Name Deploy

Register a `.gwei` name, publish an IPFS website, and create ETH payment links
from a Python command-line tool.

> [!IMPORTANT]
> This project is an early, unaffiliated community tool for the
> [Gwei Name Service](https://gwei.domains/). Transaction-writing features are
> preview-first and require `--broadcast`. Review every mainnet transaction.

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
gwei-name check 0xAddress, alice.gwei
gwei-name register alice
gwei-name register --file names.csv
gwei-name publish alice ./website
gwei-name pay create alice --amount 0.01
gwei-name pay verify REQUEST_ID TX_HASH
```

The implemented read-only planner accepts one name, a newline-delimited text
file, or a CSV whose first column is `name`:

```console
python3 -m gwei_name_deploy plan alice --network mainnet
gwei-name plan --file names.csv --json
```

It reports ENSIP-15 normalization, UTF-8 byte length, deterministic token ID,
availability, current owner/expiry, fee, expiry premium, and total registration
value. The total deliberately excludes network gas.

Registration is split so no process must remain alive during the commit/reveal
delay:

```console
# .env contains GWEI_ACCOUNTS=0xprivatekey:alice.gwei
# Preview only (default)
python3 -m gwei_name_deploy register alice --network mainnet

# Sign and send the commitment; writes an owner-only recovery file
python3 -m gwei_name_deploy register alice --network mainnet --broadcast

# After 60 seconds, recover the run and reveal
python3 -m gwei_name_deploy resume RUN_ID --broadcast
```

Use `--file names.csv` for a batch and `--max-registration-eth` to enforce a
hard cap on registration value. Each top-level reveal must be sent directly by
the intended owner because the GNS contract binds and mints to `msg.sender`.

Bidirectional checks use the GNS contract directly:

```console
python3 -m gwei_name_deploy check 0xAddress1, 0xAddress2, alice.gwei
```

Names resolve to their active ETH address. Addresses resolve only to an
explicitly configured on-chain primary `.gwei` name.

Website publishing supports a local Kubo node or Pinata. It refuses symlinks,
environment files, private-key-like files, and directories without a root
`index.html`:

```console
# Inspect files and ownership without uploading
python3 -m gwei_name_deploy publish alice examples/minimal-site --network mainnet

# Publish through local Kubo (localhost:5001 by default)
python3 -m gwei_name_deploy publish alice ./website --broadcast

# Or use Pinata with GWEI_IPFS_TOKEN set
python3 -m gwei_name_deploy publish alice ./website --provider pinata --broadcast

python3 -m gwei_name_deploy site-history alice
python3 -m gwei_name_deploy rollback alice REVISION_ID --broadcast
```

Successful contenthash transactions and the address-to-name mapping are stored
in small owner-only JSON files. Wallet private keys and commit secrets are never
stored there.

Payment requests resolve the name's configured ETH address, encode an exact
amount as a chain-specific [ERC-681](https://eips.ethereum.org/EIPS/eip-681)
URI, and save a QR code locally:

```console
python3 -m gwei_name_deploy pay create alice --amount 0.01 --network mainnet
python3 -m gwei_name_deploy pay verify REQUEST_ID TX_HASH
```

Verification requires a successful, confirmed transaction whose recipient and
wei value exactly match the original request. Requests, status, and transaction
hashes are stored in owner-only local JSON; the QR PNG is also owner-only.

Commands that change chain state will default to dry-run/preview behavior and
require explicit confirmation before broadcast.

## Development

Requirements: Python 3.11+.

```console
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
python3 -m gwei_name_deploy --help
```

Copy `.env.example` to `.env`, run `chmod 600 .env`, and add the RPC plus account
mappings. The CLI loads this file automatically. `.env`, run state, commitment
secrets, generated sites, and payment artifacts are ignored by Git.
See the [operator guide](docs/OPERATOR_GUIDE.md) for an end-to-end workflow and
[security policy](SECURITY.md) for the trust model and reporting process.

## Configuration

| Variable | Purpose |
| --- | --- |
| `GWEI_NETWORK` | `mainnet` by default |
| `GWEI_RPC_URL` | Ethereum JSON-RPC endpoint |
| `GWEI_ACCOUNTS` | Comma-separated `0xprivatekey:name` mappings |
| `GWEI_PRIVATE_KEY` | Optional legacy single-signer fallback |
| `GWEI_STATE_DIR` | Optional local state directory override |
| `GWEI_IPFS_PROVIDER` | IPFS adapter: `local` or `pinata` |
| `GWEI_IPFS_API` | Local Kubo RPC; localhost only |
| `GWEI_IPFS_TOKEN` | Pinata JWT; never commit it |

## Storage and key safety

An address-to-name mapping is public blockchain data. `address_book.json` is a
direct JSON key-value mapping such as
`"1:0x1234...": "alice.gwei"`. Including the chain ID avoids collisions across
networks while keeping the file easy to inspect and back up.

Private keys will **never** be stored in these JSON files. The MVP reads a key
from the process environment and signs locally; encrypted JSON keystores or the
OS keychain are the preferred next signer backends. Commit/reveal secrets are
not wallet keys, but losing them prevents reveal, so resumable runs will store
them in owner-only (`0600`) local state and exclude them from Git.

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
