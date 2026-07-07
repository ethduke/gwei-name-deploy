# Operator Guide

This guide covers the path from a fresh checkout to a registered mainnet
`.gwei` name, an IPFS website, and an ETH payment request. Use a dedicated
wallet and review every transaction.

## Install and configure

Requirements are Python 3.11+, an Ethereum RPC endpoint, and either a
local Kubo node or a Pinata account for publishing.

```console
git clone https://github.com/ethduke/gwei-name-deploy.git
cd gwei-name-deploy
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
cp .env.example .env
chmod 600 .env
```

The CLI automatically reads the owner-only `.env` in the current directory.
Configure mainnet and map each private key to the name it should register:

```dotenv
GWEI_NETWORK=mainnet
GWEI_RPC_URL=https://your-mainnet-rpc.example
GWEI_ACCOUNTS=0xprivatekey1:alice.gwei,0xprivatekey2:bob.gwei
```

Never commit `.env`, pass a key as a CLI argument, or place it in a website
directory. Use one registration command per mapping when keys differ.

## Check names and cost

Inspect one name:

```console
python3 -m gwei_name_deploy plan alice --network mainnet
```

For a batch, use a newline-delimited file or a CSV with `name` as the first
column:

```console
python3 -m gwei_name_deploy plan --file names.csv --network mainnet
python3 -m gwei_name_deploy plan --file names.csv --network mainnet --json
```

Review normalized names, availability, owner, expiry, and registration value.
The displayed total excludes gas.

Check forward and reverse resolution in one command:

```console
python3 -m gwei_name_deploy check 0xAddress1, 0xAddress2, alice.gwei
```

A name returns its active resolved ETH address. An address returns only its
explicitly configured on-chain primary `.gwei` name, so an empty reverse result
does not prove the wallet owns no names.

## Register and resume

Preview is the default. Add a value ceiling so a fee change cannot exceed the
operator's budget:

```console
python3 -m gwei_name_deploy register alice --network mainnet \
  --max-registration-eth 0.01
```

After reviewing the plan, send the commitment:

```console
python3 -m gwei_name_deploy register alice --network mainnet \
  --max-registration-eth 0.01 --broadcast
```

The command prints a run ID and writes a `0600` recovery file below
`GWEI_STATE_DIR/runs`. The default state directory is
`~/.local/share/gwei-name-deploy`. The recovery file contains the commitment
secret: back it up to encrypted storage after the commitment confirms.

Wait at least 60 seconds, but no longer than 24 hours, then reveal:

```console
python3 -m gwei_name_deploy resume RUN_ID --broadcast
```

Both commands are resumable. If the process stops after broadcasting, invoke
the same `resume` command rather than creating another registration run. The
signer must match the address recorded in the run.

## Publish a static website

The site must have `index.html` at its root. Preview validates the directory and
checks current ownership without uploading anything:

```console
python3 -m gwei_name_deploy publish alice ./website --network mainnet
```

For local Kubo, keep its RPC bound to localhost and use:

```console
export GWEI_IPFS_PROVIDER=local
export GWEI_IPFS_API=http://127.0.0.1:5001
python3 -m gwei_name_deploy publish alice ./website --network mainnet --broadcast
```

For Pinata, set the token in the environment:

```console
export GWEI_IPFS_PROVIDER=pinata
export GWEI_IPFS_TOKEN='...'
python3 -m gwei_name_deploy publish alice ./website --network mainnet --broadcast
```

The uploader refuses symlinks, environment files, and common key formats, but
the operator must still inspect every file before publishing. IPFS content is
public and may remain available after a later rollback.

List locally recorded revisions or restore one:

```console
python3 -m gwei_name_deploy site-history alice --network mainnet
python3 -m gwei_name_deploy rollback alice REVISION_ID --network mainnet --broadcast
```

Rollback changes the on-chain contenthash; it does not delete the newer IPFS
content.

## Create and verify payments

Payment creation reads the address resolved by the registered name and stores
an exact-value, chain-specific ERC-681 request:

```console
python3 -m gwei_name_deploy pay create alice --amount 0.01 --network mainnet
```

Share the printed URI or QR only after independently checking the name,
recipient, chain, and amount. After payment, verify the transaction:

```console
python3 -m gwei_name_deploy pay verify REQUEST_ID TX_HASH
```

Verification accepts only a successful, mined transaction with the exact
recipient and exact wei value. A transaction can satisfy only one local
request.

## State, backups, and maintenance

The state directory contains:

| Path | Contents | Sensitivity |
| --- | --- | --- |
| `runs/*.json` | Commitment secrets and registration progress | Secret |
| `address_book.json` | Direct `chain:address` to name mapping | Public data |
| `site_history.json` | Published site revisions | Private metadata |
| `payments.json` | Payment requests and transaction hashes | Private metadata |
| `payments/*.png` | Payment QR codes | Private metadata |

Directories are set to `0700` and files to `0600`. Preserve those permissions
in backups. `address_book.json` uses a direct JSON
`"chain_id:address": "name.gwei"` mapping. It is not a wallet: never put private
keys, seed phrases, or Pinata tokens in either state file.

Before upgrading, back up the complete state directory to encrypted storage.
After upgrading, run:

```console
python3 -m pip install -e .
python3 -m gwei_name_deploy --help
```

For mainnet, repeat the read-only plan immediately before every write, use a
registration ceiling, verify the signer and chain, and retain transaction links
from the command output.
