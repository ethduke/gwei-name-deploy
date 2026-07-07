import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from gwei_name_deploy import __version__
from gwei_name_deploy.config import ConfigurationError, Settings
from gwei_name_deploy.constants import NETWORKS
from gwei_name_deploy.gns import GnsError, Web3GnsReader, Web3GnsWriter, plan_name
from gwei_name_deploy.inputs import InputError, collect_names
from gwei_name_deploy.models import NamePlan
from gwei_name_deploy.registration import (
    RegistrationError,
    commit_pending,
    prepare_run,
    reveal_ready,
)
from gwei_name_deploy.state import RunStore, StateError

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


@app.command("register")
def register_command(
    name: Annotated[
        str | None,
        typer.Argument(help="Top-level name, with or without the .gwei suffix."),
    ] = None,
    input_file: Annotated[
        Path | None,
        typer.Option("--file", "-f", help="Text or CSV file; name in first column."),
    ] = None,
    network_name: Annotated[
        str | None, typer.Option("--network", help="Use sepolia or mainnet.")
    ] = None,
    rpc_url: Annotated[
        str | None,
        typer.Option("--rpc-url", envvar="GWEI_RPC_URL", help="Ethereum RPC URL."),
    ] = None,
    broadcast: Annotated[
        bool,
        typer.Option(help="Sign and broadcast commit transactions."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip the final broadcast confirmation."),
    ] = False,
    max_registration_eth: Annotated[
        str | None,
        typer.Option(help="Abort if registration value exceeds this ETH amount."),
    ] = None,
) -> None:
    """Plan registration, then persist and broadcast resumable commitments."""
    try:
        settings = Settings.from_env()
        selected_network = _network_name(network_name, settings)
        network = NETWORKS[selected_network]
        names = collect_names(name, input_file)
        endpoint = rpc_url or settings.require_rpc_url()
        reader = Web3GnsReader(endpoint, network)
        plans = [plan_name(reader, candidate) for candidate in names]
        _ensure_registration_budget(plans, max_registration_eth)
        unavailable = [plan.name for plan in plans if not plan.available]
        if unavailable:
            raise RegistrationError(
                "cannot register unavailable names: " + ", ".join(unavailable)
            )
    except (
        ConfigurationError,
        GnsError,
        InputError,
        OSError,
        RegistrationError,
    ) as exc:
        _fail(exc)

    _render_plans(plans, selected_network)
    if not broadcast:
        console.print(
            "[yellow]Dry run only.[/yellow] Add --broadcast to send commitments."
        )
        return

    try:
        writer = Web3GnsWriter(endpoint, network, settings.require_private_key())
        _confirm_broadcast(selected_network, len(plans), yes)
        run = prepare_run(plans, selected_network, network.chain_id, writer.address)
        store = RunStore(settings.state_dir)
        store.save(run)
        commit_pending(run, writer, store.save)
    except (ConfigurationError, GnsError, RegistrationError, StateError) as exc:
        _fail(exc)

    console.print(
        f"[green]Commitments confirmed.[/green] Run ID: [bold]{run.run_id}[/bold]"
    )
    console.print(f"State: {store.path_for(run.run_id)}")
    console.print(
        f"After at least 60 seconds: gwei-name resume {run.run_id} --broadcast"
    )


@app.command("resume")
def resume_command(
    run_id: Annotated[str, typer.Argument(help="Registration run ID to resume.")],
    rpc_url: Annotated[
        str | None,
        typer.Option("--rpc-url", envvar="GWEI_RPC_URL", help="Ethereum RPC URL."),
    ] = None,
    broadcast: Annotated[
        bool, typer.Option(help="Sign and broadcast pending registration actions.")
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip the final broadcast confirmation."),
    ] = False,
) -> None:
    """Recover a registration run and reveal commitments when ready."""
    try:
        settings = Settings.from_env()
        store = RunStore(settings.state_dir)
        run = store.load(run_id)
        if run.network not in NETWORKS:
            raise RegistrationError(f"unsupported run network: {run.network}")
        statuses = ", ".join(f"{item.name}={item.status}" for item in run.items)
        console.print(f"Run [bold]{run.run_id}[/bold]: {statuses}")
        if not broadcast:
            console.print(
                "[yellow]Dry run only.[/yellow] Add --broadcast to advance the run."
            )
            return

        network = NETWORKS[run.network]
        writer = Web3GnsWriter(
            rpc_url or settings.require_rpc_url(),
            network,
            settings.require_private_key(),
        )
        _confirm_broadcast(run.network, len(run.items), yes)
        commit_pending(run, writer, store.save)
        wait_seconds = reveal_ready(run, writer, store.save)
    except (
        ConfigurationError,
        GnsError,
        RegistrationError,
        StateError,
    ) as exc:
        _fail(exc)

    if wait_seconds:
        console.print(
            "[yellow]Commitments are too new.[/yellow] "
            f"Retry in {wait_seconds} seconds."
        )
    elif all(item.status == "revealed" for item in run.items):
        console.print("[green]All names registered successfully.[/green]")
    else:
        console.print("Run advanced; invoke resume again to continue.")


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


def _network_name(requested: str | None, settings: Settings) -> str:
    selected = (requested or settings.network).lower()
    if selected not in NETWORKS:
        raise ConfigurationError(
            f"unsupported network {selected!r}; choose mainnet or sepolia"
        )
    return selected


def _ensure_registration_budget(plans: list[NamePlan], maximum_eth: str | None) -> None:
    if maximum_eth is None:
        return
    try:
        parsed_maximum = Decimal(maximum_eth)
    except InvalidOperation as exc:
        raise RegistrationError("--max-registration-eth must be a number") from exc
    if parsed_maximum < 0:
        raise RegistrationError("--max-registration-eth cannot be negative")
    maximum_wei = int(parsed_maximum * Decimal(10**18))
    total = sum(plan.total_wei for plan in plans)
    if total > maximum_wei:
        raise RegistrationError(
            f"registration value {_format_eth(total)} ETH exceeds "
            f"limit {parsed_maximum} ETH"
        )


def _confirm_broadcast(network: str, count: int, assume_yes: bool) -> None:
    if assume_yes:
        return
    confirmed = typer.confirm(
        f"Broadcast transactions for {count} name(s) on {network}?"
    )
    if not confirmed:
        raise RegistrationError("broadcast cancelled")


def _fail(exc: Exception) -> None:
    error_console.print(f"[red]Error:[/red] {exc}")
    raise typer.Exit(2) from exc
