from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from gwei_name_deploy.constants import NETWORKS


class ConfigurationError(ValueError):
    """Raised when operator configuration is invalid or incomplete."""


@dataclass(frozen=True, slots=True)
class AccountMapping:
    private_key: str
    name: str


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration loaded from environment variables."""

    network: str
    rpc_url: str | None
    private_key: str | None
    state_dir: Path
    ipfs_provider: str | None
    ipfs_api: str | None
    ipfs_token: str | None
    accounts: tuple[AccountMapping, ...]

    @classmethod
    def from_env(cls) -> Settings:
        dotenv = _load_project_dotenv()
        network = (_optional_env("GWEI_NETWORK", dotenv) or "mainnet").lower()
        if network not in NETWORKS:
            choices = ", ".join(sorted(NETWORKS))
            raise ConfigurationError(
                f"Unsupported GWEI_NETWORK {network!r}; choose one of: {choices}"
            )

        state_override = _optional_env("GWEI_STATE_DIR", dotenv)
        state_dir = (
            Path(state_override).expanduser()
            if state_override
            else Path.home() / ".local" / "share" / "gwei-name-deploy"
        )

        return cls(
            network=network,
            rpc_url=_optional_env("GWEI_RPC_URL", dotenv),
            private_key=_optional_env("GWEI_PRIVATE_KEY", dotenv),
            state_dir=state_dir,
            ipfs_provider=_optional_env("GWEI_IPFS_PROVIDER", dotenv) or "local",
            ipfs_api=_optional_env("GWEI_IPFS_API", dotenv) or "http://127.0.0.1:5001",
            ipfs_token=_optional_env("GWEI_IPFS_TOKEN", dotenv),
            accounts=_parse_account_mappings(_optional_env("GWEI_ACCOUNTS", dotenv)),
        )

    def require_rpc_url(self) -> str:
        if not self.rpc_url:
            raise ConfigurationError("GWEI_RPC_URL is required for network access")
        return self.rpc_url

    def require_private_key(self) -> str:
        if not self.private_key:
            raise ConfigurationError(
                "GWEI_PRIVATE_KEY is required for signing; never pass it via CLI"
            )
        return self.private_key


def _optional_env(
    name: str, dotenv: Mapping[str, str | None] | None = None
) -> str | None:
    value = os.getenv(name)
    if value is None and dotenv is not None:
        value = dotenv.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _load_project_dotenv() -> dict[str, str | None]:
    path = Path.cwd() / ".env"
    if not path.exists():
        return {}
    if path.is_symlink():
        raise ConfigurationError(".env must not be a symlink")
    if not path.is_file():
        raise ConfigurationError(f".env is not a regular file: {path}")
    if path.stat().st_mode & 0o077:
        raise ConfigurationError(
            ".env contains secrets and must be owner-only (chmod 600 .env)"
        )
    return dict(dotenv_values(path, interpolate=False))


def _parse_account_mappings(value: str | None) -> tuple[AccountMapping, ...]:
    if value is None:
        return ()
    mappings: list[AccountMapping] = []
    names: set[str] = set()
    for position, raw in enumerate(value.split(","), start=1):
        entry = raw.strip()
        if not entry:
            continue
        private_key, separator, name = entry.partition(":")
        private_key = private_key.strip()
        name = name.strip()
        if not separator or not private_key or not name:
            raise ConfigurationError(
                f"invalid GWEI_ACCOUNTS entry {position}; expected 0xprivatekey:name"
            )
        if name.lower() in names:
            raise ConfigurationError(f"duplicate name in GWEI_ACCOUNTS: {name}")
        names.add(name.lower())
        mappings.append(AccountMapping(private_key=private_key, name=name))
    if not mappings:
        raise ConfigurationError("GWEI_ACCOUNTS contains no account mappings")
    return tuple(mappings)
