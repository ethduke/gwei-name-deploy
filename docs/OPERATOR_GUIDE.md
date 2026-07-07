# Operator Guide

This guide covers the safe path from a fresh checkout to a registered `.gwei`
name, an IPFS website, and an ETH payment request. Start on Sepolia and use a
dedicated low-value wallet while evaluating the tool.

## Install and configure

Requirements are Python 3.11+, `uv`, an Ethereum RPC endpoint, and either a
local Kubo node or a Pinata account for publishing.

```console
git clone https://github.com/ethduke/gwei-name-deploy.git
cd gwei-name-deploy
uv sync --dev
cp .env.example .env
```

Set `GWEI_RPC_URL` in your shell or load `.env` with your preferred environment
manager. The CLI does not automatically read `.env`. Keep the default
`GWEI_NETWORK=sepolia` until the full workflow has been tested.

Read-only and dry-run commands do not need `GWEI_PRIVATE_KEY`. Before a write,
export the key for a dedicated signer in the current shell:

```console
export GWEI_PRIVATE_KEY='0x...'
```

Do not put the key in command history, CLI arguments, source files, CSV files,
or the website directory. Unset it when the write session is finished.

## Check names and cost

Inspect one name:

```console
uv run gwei-name plan alice --network sepolia
```

For a batch, use a newline-delimited file or a CSV with `name` as the first
column:

```console
uv run gwei-name plan --file names.csv --network sepolia
uv run gwei-name plan --file names.csv --network sepolia --json
```

Review normalized names, availability, owner, expiry, and registration value.
The displayed total excludes gas.

## Register and resume

Preview is the default. Add a value ceiling so a fee change cannot exceed the
operator's budget:

```console
uv run gwei-name register alice --network sepolia \
  --max-registration-eth 0.01
```

After reviewing the plan, send the commitment:

```console
uv run gwei-name register alice --network sepolia \
  --max-registration-eth 0.01 --broadcast
```

The command prints a run ID and writes a `0600` recovery file below
`GWEI_STATE_DIR/runs`. The default state directory is
`~/.local/share/gwei-name-deploy`. The recovery file contains the commitment
secret: back it up to encrypted storage after the commitment confirms.

Wait at least 60 seconds, but no longer than 24 hours, then reveal:

```console
uv run gwei-name resume RUN_ID --broadcast
```

Both commands are resumable. If the process stops after broadcasting, invoke
the same `resume` command rather than creating another registration run. The
signer must match the address recorded in the run.

## Publish a static website

The site must have `index.html` at its root. Preview validates the directory and
checks current ownership without uploading anything:

```console
uv run gwei-name publish alice ./website --network sepolia
```

For local Kubo, keep its RPC bound to localhost and use:

```console
export GWEI_IPFS_PROVIDER=local
export GWEI_IPFS_API=http://127.0.0.1:5001
uv run gwei-name publish alice ./website --network sepolia --broadcast
```

For Pinata, set the token in the environment:

```console
export GWEI_IPFS_PROVIDER=pinata
export GWEI_IPFS_TOKEN='...'
uv run gwei-name publish alice ./website --network sepolia --broadcast
```

The uploader refuses symlinks, environment files, and common key formats, but
the operator must still inspect every file before publishing. IPFS content is
public and may remain available after a later rollback.

List locally recorded revisions or restore one:

```console
uv run gwei-name site-history alice --network sepolia
uv run gwei-name rollback alice REVISION_ID --network sepolia --broadcast
```

Rollback changes the on-chain contenthash; it does not delete the newer IPFS
content.

## Create and verify payments

Payment creation reads the address resolved by the registered name and stores
an exact-value, chain-specific ERC-681 request:

```console
uv run gwei-name pay create alice --amount 0.01 --network sepolia
```

Share the printed URI or QR only after independently checking the name,
recipient, chain, and amount. After payment, verify the transaction:

```console
uv run gwei-name pay verify REQUEST_ID TX_HASH
```

Verification accepts only a successful, mined transaction with the exact
recipient and exact wei value. A transaction can satisfy only one local
request.

## State, backups, and maintenance

The state directory contains:

| Path | Contents | Sensitivity |
| --- | --- | --- |
| `runs/*.json` | Commitment secrets and registration progress | Secret |
| `history.sqlite3` | Public address/name cache and site revisions | Private metadata |
| `payments.sqlite3` | Payment requests and transaction hashes | Private metadata |
| `payments/*.png` | Payment QR codes | Private metadata |

Directories are set to `0700` and files to `0600`. Preserve those permissions
in backups. SQLite is appropriate for the public `(chain_id, address) -> name`
cache because it gives atomic updates and indexed lookup. It is not a wallet:
never put private keys, seed phrases, or Pinata tokens in either database.

Before upgrading, back up the complete state directory to encrypted storage.
After upgrading, run:

```console
uv sync --dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

For mainnet, repeat the read-only plan immediately before every write, use a
registration ceiling, verify the signer and chain, and retain transaction links
from the command output.
