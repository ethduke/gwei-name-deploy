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
from gwei_name_deploy.gns import (
    GnsError,
    Web3GnsReader,
    Web3GnsWriter,
    normalize_top_level_name,
    plan_name,
)
from gwei_name_deploy.history import HistoryError, HistoryStore
from gwei_name_deploy.inputs import InputError, collect_names
from gwei_name_deploy.ipfs import (
    IpfsError,
    build_manifest,
    create_uploader,
    encode_ipfs_contenthash,
)
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


@app.command("publish")
def publish_command(
    name: Annotated[str, typer.Argument(help="Registered top-level .gwei name.")],
    site_dir: Annotated[Path, typer.Argument(help="Static site directory.")],
    provider: Annotated[
        str | None,
        typer.Option(help="IPFS provider: local or pinata."),
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
        typer.Option(help="Upload the site and update the on-chain contenthash."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip the final publish confirmation."),
    ] = False,
) -> None:
    """Upload a static website to IPFS and set its GNS contenthash."""
    try:
        settings = Settings.from_env()
        selected_network = _network_name(network_name, settings)
        network = NETWORKS[selected_network]
        manifest = build_manifest(site_dir)
        endpoint = rpc_url or settings.require_rpc_url()
        reader = Web3GnsReader(endpoint, network)
        plan = plan_name(reader, name)
        if plan.available or plan.owner is None:
            raise IpfsError(f"{plan.name} is not an active registered name")
    except (ConfigurationError, GnsError, IpfsError, OSError) as exc:
        _fail(exc)

    console.print(
        f"Site: [bold]{manifest.root}[/bold] ({len(manifest.files)} files, "
        f"{manifest.total_bytes} bytes)"
    )
    console.print(f"Target: [bold]{plan.name}[/bold] owned by {plan.owner}")
    if not broadcast:
        console.print(
            "[yellow]Dry run only.[/yellow] Add --broadcast to upload and publish."
        )
        return

    try:
        writer = Web3GnsWriter(endpoint, network, settings.require_private_key())
        if writer.address.lower() != plan.owner.lower():
            raise IpfsError(
                f"signer {writer.address} does not own {plan.name} ({plan.owner})"
            )
        _confirm_publish(selected_network, plan.name, manifest.total_bytes, yes)
        uploader = create_uploader(
            provider or settings.ipfs_provider or "local",
            settings.ipfs_api,
            settings.ipfs_token,
        )
        cid = uploader.upload(manifest, plan.name)
        contenthash = encode_ipfs_contenthash(cid)
        tx_hash = writer.broadcast_contenthash(plan.token_id, contenthash)
        writer.wait_transaction(tx_hash)
        history = HistoryStore(settings.state_dir)
        revision = history.record_revision(
            network.chain_id,
            plan.name,
            plan.token_id,
            cid,
            contenthash,
            tx_hash,
        )
        history.upsert_address_name(network.chain_id, writer.address, plan.name)
    except (
        ConfigurationError,
        GnsError,
        HistoryError,
        IpfsError,
        OSError,
    ) as exc:
        _fail(exc)

    console.print(f"[green]Published revision {revision.revision_id}.[/green]")
    console.print(f"CID: {cid}")
    console.print(f"Gateway: https://{plan.label}.gwei.domains")
    console.print(f"Transaction: {network.explorer_url}/tx/{tx_hash}")


@app.command("site-history")
def site_history_command(
    name: Annotated[str, typer.Argument(help="Top-level .gwei name.")],
    network_name: Annotated[
        str | None, typer.Option("--network", help="Use sepolia or mainnet.")
    ] = None,
) -> None:
    """Show locally recorded successful website revisions."""
    try:
        settings = Settings.from_env()
        selected_network = _network_name(network_name, settings)
        label, normalized = normalize_top_level_name(name)
        revisions = HistoryStore(settings.state_dir).list_revisions(
            NETWORKS[selected_network].chain_id, normalized
        )
    except (ConfigurationError, HistoryError, GnsError, OSError) as exc:
        _fail(exc)

    table = Table(title=f"Site history: {label}.gwei ({selected_network})")
    table.add_column("Revision", justify="right")
    table.add_column("CID")
    table.add_column("Created")
    table.add_column("Transaction")
    for revision in revisions:
        table.add_row(
            str(revision.revision_id),
            revision.cid,
            revision.created_at,
            revision.tx_hash,
        )
    console.print(table)
    if not revisions:
        console.print("[dim]No locally recorded revisions.[/dim]")


@app.command("rollback")
def rollback_command(
    name: Annotated[str, typer.Argument(help="Registered top-level .gwei name.")],
    revision_id: Annotated[int, typer.Argument(help="Local revision to restore.")],
    network_name: Annotated[
        str | None, typer.Option("--network", help="Use sepolia or mainnet.")
    ] = None,
    rpc_url: Annotated[
        str | None,
        typer.Option("--rpc-url", envvar="GWEI_RPC_URL", help="Ethereum RPC URL."),
    ] = None,
    broadcast: Annotated[
        bool, typer.Option(help="Update the on-chain contenthash.")
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip the final rollback confirmation."),
    ] = False,
) -> None:
    """Restore a previously recorded IPFS website revision."""
    try:
        settings = Settings.from_env()
        selected_network = _network_name(network_name, settings)
        network = NETWORKS[selected_network]
        history = HistoryStore(settings.state_dir)
        revision = history.get_revision(revision_id)
        _, normalized = normalize_top_level_name(name)
        if revision.chain_id != network.chain_id or revision.name != normalized:
            raise HistoryError("revision does not belong to this name and network")
        contenthash = bytes.fromhex(revision.contenthash_hex[2:])
        endpoint = rpc_url or settings.require_rpc_url()
        reader = Web3GnsReader(endpoint, network)
        plan = plan_name(reader, normalized)
        if plan.owner is None:
            raise HistoryError(f"{normalized} has no active owner")
    except (ConfigurationError, GnsError, HistoryError, OSError) as exc:
        _fail(exc)

    console.print(f"Restore {normalized} to revision {revision_id}: {revision.cid}")
    if not broadcast:
        console.print(
            "[yellow]Dry run only.[/yellow] Add --broadcast to update contenthash."
        )
        return

    try:
        writer = Web3GnsWriter(endpoint, network, settings.require_private_key())
        if writer.address.lower() != plan.owner.lower():
            raise HistoryError(f"signer {writer.address} does not own {normalized}")
        _confirm_publish(selected_network, normalized, 0, yes)
        tx_hash = writer.broadcast_contenthash(plan.token_id, contenthash)
        writer.wait_transaction(tx_hash)
        restored = history.record_revision(
            network.chain_id,
            normalized,
            plan.token_id,
            revision.cid,
            contenthash,
            tx_hash,
        )
    except (ConfigurationError, GnsError, HistoryError) as exc:
        _fail(exc)

    console.print(f"[green]Restored as revision {restored.revision_id}.[/green]")
    console.print(f"Transaction: {network.explorer_url}/tx/{tx_hash}")


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


def _confirm_publish(
    network: str, name: str, total_bytes: int, assume_yes: bool
) -> None:
    if assume_yes:
        return
    suffix = f" after uploading {total_bytes} bytes" if total_bytes else ""
    if not typer.confirm(f"Update {name} on {network}{suffix}?"):
        raise IpfsError("publish cancelled")


def _fail(exc: Exception) -> None:
    error_console.print(f"[red]Error:[/red] {exc}")
    raise typer.Exit(2) from exc
