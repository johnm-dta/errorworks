"""CLI for ChaosSMTP fake SMTP server."""

from __future__ import annotations

import typer

app = typer.Typer(
    name="chaossmtp",
    help="ChaosSMTP: Fake SMTP server for outbound email resilience testing.",
    no_args_is_help=True,
)


@app.command()
def serve() -> None:
    """Start the ChaosSMTP fake SMTP server."""
    typer.echo("ChaosSMTP serve requires the server implementation from Task 9.", err=True)
    raise typer.Exit(2)


@app.command()
def presets() -> None:
    """List available preset configurations."""
    typer.echo("No presets found.")


def main() -> None:
    """Entry point for chaossmtp CLI."""
    app()


if __name__ == "__main__":
    main()
