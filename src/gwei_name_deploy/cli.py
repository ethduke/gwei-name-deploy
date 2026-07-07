from typing import Annotated

import typer

from gwei_name_deploy import __version__

app = typer.Typer(
    name="gwei-name",
    help="Register .gwei names and deploy their websites.",
    no_args_is_help=True,
    add_completion=False,
)


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
