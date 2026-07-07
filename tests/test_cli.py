from typer.testing import CliRunner

from gwei_name_deploy import __version__
from gwei_name_deploy.cli import app
from gwei_name_deploy.models import NamePlan

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


def test_publish_dry_run_does_not_upload(monkeypatch, tmp_path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("hello", encoding="utf-8")
    monkeypatch.setenv("GWEI_RPC_URL", "https://rpc.invalid")
    monkeypatch.setattr(
        "gwei_name_deploy.cli.Web3GnsReader", lambda endpoint, network: object()
    )
    monkeypatch.setattr(
        "gwei_name_deploy.cli.plan_name",
        lambda reader, name: NamePlan(
            input_name=name,
            name="alice.gwei",
            label="alice",
            label_bytes=5,
            token_id=123,
            status="registered",
            available=False,
            owner="0x1234567890123456789012345678901234567890",
            expires_at=1_900_000_000,
            fee_wei=500_000_000_000_000,
            premium_wei=0,
        ),
    )

    result = runner.invoke(app, ["publish", "alice", str(site)])

    assert result.exit_code == 0
    assert "Dry run only" in result.output
    assert "1 files" in result.output
