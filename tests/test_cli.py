from typer.testing import CliRunner

from gwei_name_deploy import __version__
from gwei_name_deploy.cli import app

runner = CliRunner()


def test_help_describes_project() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "Register .gwei names and deploy their websites" in result.stdout


def test_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"gwei-name {__version__}"


def test_plan_requires_rpc(monkeypatch) -> None:
    monkeypatch.delenv("GWEI_RPC_URL", raising=False)

    result = runner.invoke(app, ["plan", "alice"])

    assert result.exit_code == 2
    assert "GWEI_RPC_URL is required" in result.output
