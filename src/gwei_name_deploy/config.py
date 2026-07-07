from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from gwei_name_deploy.constants import NETWORKS


class ConfigurationError(ValueError):
    """Raised when operator configuration is invalid or incomplete."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration loaded from environment variables."""

    network: str
    rpc_url: str | None
    private_key: str | None
    state_dir: Path
    ipfs_provider: str | None
    ipfs_token: str | None

    @classmethod
    def from_env(cls) -> Settings:
        network = os.getenv("GWEI_NETWORK", "sepolia").strip().lower()
        if network not in NETWORKS:
            choices = ", ".join(sorted(NETWORKS))
            raise ConfigurationError(
                f"Unsupported GWEI_NETWORK {network!r}; choose one of: {choices}"
            )

        state_override = _optional_env("GWEI_STATE_DIR")
        state_dir = (
            Path(state_override).expanduser()
            if state_override
            else Path.home() / ".local" / "share" / "gwei-name-deploy"
        )

        return cls(
            network=network,
            rpc_url=_optional_env("GWEI_RPC_URL"),
            private_key=_optional_env("GWEI_PRIVATE_KEY"),
            state_dir=state_dir,
            ipfs_provider=_optional_env("GWEI_IPFS_PROVIDER"),
            ipfs_token=_optional_env("GWEI_IPFS_TOKEN"),
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


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
