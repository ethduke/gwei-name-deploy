import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from gwei_name_deploy import __version__
from gwei_name_deploy.config import ConfigurationError, Settings
from gwei_name_deploy.constants import NETWORKS
from gwei_name_deploy.gns import GnsError, Web3GnsReader, plan_name
from gwei_name_deploy.inputs import InputError, collect_names
from gwei_name_deploy.models import NamePlan

app = typer.Typer(
    name="gwei-name",
    help="Register .gwei names and deploy their websites.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
error_console = Console(stderr=True)


def version_callback(value: bool) -> None:
    """Print the package version and exit."""
    if value:
        typer.echo(f"gwei-name {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            callback=version_callback,
            is_eager=True,
            help="Show the installed version and exit.",
        ),
    ] = None,
) -> None:
    """Gwei Name Deploy CLI."""


@app.command("plan")
def plan_command(
    name: Annotated[
        str | None,
        typer.Argument(help="Top-level name, with or without the .gwei suffix."),
    ] = None,
    input_file: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="Text or CSV file; name in first column."),
    ] = None,
    network_name: Annotated[
        str | None,
        typer.Option("--network", help="Read from sepolia or mainnet."),
    ] = None,
    rpc_url: Annotated[
        str | None,
        typer.Option("--rpc-url", envvar="GWEI_RPC_URL", help="Ethereum RPC URL."),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit machine-readable JSON."),
    ] = False,
) -> None:
    """Check GNS availability, ownership, expiry, and registration cost."""
    try:
        settings = Settings.from_env()
        selected_network = (network_name or settings.network).lower()
        if selected_network not in NETWORKS:
            raise ConfigurationError(
                f"unsupported network {selected_network!r}; choose mainnet or sepolia"
            )
        names = collect_names(name, input_file)
        reader = Web3GnsReader(
            rpc_url or settings.require_rpc_url(), NETWORKS[selected_network]
        )
        plans = [plan_name(reader, candidate) for candidate in names]
    except (ConfigurationError, GnsError, InputError, OSError) as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(2) from exc

    if json_output:
        typer.echo(json.dumps([plan.to_dict() for plan in plans], indent=2))
        return
    _render_plans(plans, selected_network)


def _render_plans(plans: list[NamePlan], network: str) -> None:
    table = Table(title=f"GNS registration plan ({network})")
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Bytes", justify="right")
    table.add_column("Fee (ETH)", justify="right")
    table.add_column("Premium", justify="right")
    table.add_column("Total", justify="right")
    table.add_column("Owner / Expiry")

    for plan in plans:
        status_style = "green" if plan.available else "yellow"
        owner_expiry = plan.owner or "—"
        if plan.expires_at:
            expiry = datetime.fromtimestamp(plan.expires_at, tz=UTC).date().isoformat()
            owner_expiry = f"{owner_expiry}\n{expiry}"
        table.add_row(
            plan.name,
            f"[{status_style}]{plan.status}[/{status_style}]",
            str(plan.label_bytes),
            _format_eth(plan.fee_wei),
            _format_eth(plan.premium_wei),
            _format_eth(plan.total_wei),
            owner_expiry,
        )

    console.print(table)
    console.print("[dim]Registration totals exclude network gas.[/dim]")


def _format_eth(value: int) -> str:
    amount = Decimal(value) / Decimal(10**18)
    return f"{amount:f}".rstrip("0").rstrip(".") or "0"
