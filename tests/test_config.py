from pathlib import Path

import pytest

from gwei_name_deploy.config import ConfigurationError, Settings


def test_defaults_to_sepolia(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("GWEI_NETWORK", raising=False)
    monkeypatch.setenv("GWEI_STATE_DIR", str(tmp_path))

    settings = Settings.from_env()

    assert settings.network == "sepolia"
    assert settings.state_dir == tmp_path
    assert settings.private_key is None


def test_rejects_unknown_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GWEI_NETWORK", "somechain")

    with pytest.raises(ConfigurationError, match="Unsupported GWEI_NETWORK"):
        Settings.from_env()


def test_requires_rpc_when_requested(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GWEI_RPC_URL", raising=False)
    monkeypatch.setenv("GWEI_STATE_DIR", str(tmp_path))
    settings = Settings.from_env()

    with pytest.raises(ConfigurationError, match="GWEI_RPC_URL"):
        settings.require_rpc_url()
