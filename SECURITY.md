# Security Policy

Gwei Name Deploy signs transactions, persists commit/reveal secrets, uploads
public content, and creates payment requests. Treat it as pre-1.0 software and
test every workflow with a dedicated low-value wallet on Sepolia first.

## Supported versions

Only the latest commit on `main` is currently supported. There are no stable
release branches yet.

## Reporting a vulnerability

Do not include private keys, seed phrases, API tokens, commitment secrets, or
other exploitable details in a public issue. Prefer GitHub's private
vulnerability reporting flow for this repository. If that flow is unavailable,
open a minimal issue asking the maintainers for a private contact channel and
omit all sensitive technical details.

Include the affected commit, network, command, expected behavior, observed
behavior, and a minimal reproduction that uses test credentials. Never send a
real secret, even privately.

## Trust and storage model

- GNS ownership, availability, fees, resolution, and transaction outcomes come
  from the configured JSON-RPC endpoint. A dishonest or stale RPC can mislead
  the operator; use a trusted endpoint and independently inspect transactions.
- `GWEI_PRIVATE_KEY` is read from the process environment and used only for
  local signing. This is an MVP compromise, not a durable secret store. A
  hardware wallet, OS keychain, or encrypted JSON keystore signer is preferred
  for future releases.
- Registration recovery files contain random commitment secrets. They are
  created as owner-only files and excluded from Git, but any process running as
  the same OS user may still read them.
- `history.sqlite3` stores public address/name mappings and site history.
  `payments.sqlite3` stores recipient addresses, amounts, and transaction
  hashes. Both are owner-only to limit local metadata exposure, but neither is
  suitable for wallet keys or API credentials.
- Pinata tokens stay in the environment. Local Kubo RPC endpoints are accepted
  only on loopback because an exposed Kubo RPC can permit remote node control.
- Website uploads are public and content-addressed. Removing an on-chain
  contenthash or rolling back does not guarantee deletion from IPFS gateways or
  third-party pins.

## Operator safeguards

- Write commands require `--broadcast` and interactive confirmation unless
  `--yes` is explicitly supplied.
- Registration supports a `--max-registration-eth` ceiling. Quoted registration
  value does not include gas.
- Commit/reveal runs persist transaction hashes before waiting for receipts so
  interrupted commands can be resumed safely.
- Publishing checks that the signer owns the name and refuses symlinks,
  environment files, and common private-key file types.
- Payment URIs include the chain ID and amount in wei. Verification checks the
  receipt status, mined block, exact recipient, and exact value, and prevents a
  transaction hash from satisfying two requests.

These checks reduce common operator mistakes; they do not replace reviewing the
resolved address, wallet confirmation screen, transaction calldata, gas, and
explorer result before and after every mainnet write.

## Secret response

If a wallet key or seed phrase may have been exposed, move assets to a new
wallet immediately; deleting a file or Git commit does not revoke the key. If a
Pinata token is exposed, revoke and replace it. If an unrevealed commitment
secret is exposed, assume the run is compromised and avoid relying on it until
the contract-level consequences have been assessed.
