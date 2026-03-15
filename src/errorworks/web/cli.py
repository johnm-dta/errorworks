"""CLI for ChaosWeb fake web server.

Provides command-line interface for starting and managing the ChaosWeb
server for web scraping resilience testing and fault injection.

Usage:
    chaosweb serve                                    # Start with defaults
    chaosweb serve --preset=stress_scraping           # Use a preset
    chaosweb serve --config=my_chaos.yaml --port=8200 # Custom config
    chaosweb serve --rate-limit-pct=10 --forbidden-pct=5  # Override rates
    chaosweb presets                                  # List presets
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import pydantic
import typer
import yaml

from errorworks.web.config import (
    DEFAULT_MEMORY_DB,
    list_presets,
    load_config,
)

app = typer.Typer(
    name="chaosweb",
    help="ChaosWeb: Fake web server for scraping pipeline resilience testing.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        from importlib.metadata import PackageNotFoundError, version

        try:
            typer.echo(f"chaosweb (errorworks {version('errorworks')})")
        except PackageNotFoundError:
            typer.echo("chaosweb (version unknown)")
        raise typer.Exit()


@app.command()
def serve(
    # Configuration sources
    preset: Annotated[
        str | None,
        typer.Option(
            "--preset",
            "-p",
            help="Preset configuration to use. Use 'chaosweb presets' to list available.",
        ),
    ] = None,
    config_file: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to YAML configuration file.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
    # Server binding
    host: Annotated[
        str | None,
        typer.Option("--host", "-h", help="Host address to bind to (default: 127.0.0.1)."),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option("--port", "-P", help="Port to listen on (default: 8200).", min=1, max=65535),
    ] = None,
    workers: Annotated[
        int | None,
        typer.Option("--workers", "-w", help="Number of uvicorn workers (default: from preset or 1).", min=1),
    ] = None,
    # Metrics
    database: Annotated[
        str | None,
        typer.Option("--database", "-d", help="SQLite database path for metrics."),
    ] = None,
    # Error injection overrides
    rate_limit_pct: Annotated[
        float | None,
        typer.Option("--rate-limit-pct", help="429 Rate Limit error percentage.", min=0.0, max=100.0),
    ] = None,
    forbidden_pct: Annotated[
        float | None,
        typer.Option("--forbidden-pct", help="403 Forbidden error percentage.", min=0.0, max=100.0),
    ] = None,
    not_found_pct: Annotated[
        float | None,
        typer.Option("--not-found-pct", help="404 Not Found error percentage.", min=0.0, max=100.0),
    ] = None,
    service_unavailable_pct: Annotated[
        float | None,
        typer.Option("--service-unavailable-pct", help="503 Service Unavailable percentage.", min=0.0, max=100.0),
    ] = None,
    internal_error_pct: Annotated[
        float | None,
        typer.Option("--internal-error-pct", help="500 Internal Error percentage.", min=0.0, max=100.0),
    ] = None,
    timeout_pct: Annotated[
        float | None,
        typer.Option("--timeout-pct", help="Connection timeout percentage.", min=0.0, max=100.0),
    ] = None,
    ssrf_redirect_pct: Annotated[
        float | None,
        typer.Option("--ssrf-redirect-pct", help="SSRF redirect injection percentage.", min=0.0, max=100.0),
    ] = None,
    selection_mode: Annotated[
        str | None,
        typer.Option("--selection-mode", help="Error selection: priority or weighted."),
    ] = None,
    # Latency
    base_ms: Annotated[
        int | None,
        typer.Option("--base-ms", help="Base latency in milliseconds.", min=0),
    ] = None,
    jitter_ms: Annotated[
        int | None,
        typer.Option("--jitter-ms", help="Latency jitter in milliseconds.", min=0),
    ] = None,
    # Content mode
    content_mode: Annotated[
        str | None,
        typer.Option("--content-mode", help="Content generation: random, template, echo, preset."),
    ] = None,
    # Burst
    burst_enabled: Annotated[
        bool | None,
        typer.Option("--burst-enabled/--no-burst", help="Enable burst pattern injection."),
    ] = None,
    burst_interval_sec: Annotated[
        int | None,
        typer.Option("--burst-interval-sec", help="Time between burst starts.", min=1),
    ] = None,
    burst_duration_sec: Annotated[
        int | None,
        typer.Option("--burst-duration-sec", help="Burst duration in seconds.", min=1),
    ] = None,
    # Misc
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-v",
            callback=_version_callback,
            is_eager=True,
            help="Show version.",
        ),
    ] = False,
) -> None:
    """Start the ChaosWeb fake web server.

    Serves HTML pages with configurable error injection, content malformations,
    redirect loops, and SSRF injection for web scraping pipeline testing.

    Configuration precedence (highest to lowest):
    1. Command-line flags
    2. Config file (--config)
    3. Preset (--preset)
    4. Built-in defaults

    Examples:

        chaosweb serve
        chaosweb serve --preset=stress_scraping
        chaosweb serve --rate-limit-pct=10 --forbidden-pct=5
        chaosweb serve --port=9000 --database=./web-metrics.db
    """
    # Build CLI overrides dict — only include explicitly provided values
    # so that preset/config file settings are preserved for unspecified flags.
    cli_overrides: dict[str, Any] = {}

    server_overrides: dict[str, Any] = {}
    if host is not None:
        server_overrides["host"] = host
    if port is not None:
        server_overrides["port"] = port
    if workers is not None:
        server_overrides["workers"] = workers
    if server_overrides:
        cli_overrides["server"] = server_overrides

    if database is not None:
        cli_overrides["metrics"] = {"database": database}

    # Error injection overrides
    error_overrides: dict[str, Any] = {}
    if rate_limit_pct is not None:
        error_overrides["rate_limit_pct"] = rate_limit_pct
    if forbidden_pct is not None:
        error_overrides["forbidden_pct"] = forbidden_pct
    if not_found_pct is not None:
        error_overrides["not_found_pct"] = not_found_pct
    if service_unavailable_pct is not None:
        error_overrides["service_unavailable_pct"] = service_unavailable_pct
    if internal_error_pct is not None:
        error_overrides["internal_error_pct"] = internal_error_pct
    if timeout_pct is not None:
        error_overrides["timeout_pct"] = timeout_pct
    if ssrf_redirect_pct is not None:
        error_overrides["ssrf_redirect_pct"] = ssrf_redirect_pct
    if selection_mode is not None:
        error_overrides["selection_mode"] = selection_mode

    # Burst overrides
    burst_overrides: dict[str, Any] = {}
    if burst_enabled is not None:
        burst_overrides["enabled"] = burst_enabled
    if burst_interval_sec is not None:
        burst_overrides["interval_sec"] = burst_interval_sec
    if burst_duration_sec is not None:
        burst_overrides["duration_sec"] = burst_duration_sec
    if burst_overrides:
        error_overrides["burst"] = burst_overrides

    if error_overrides:
        cli_overrides["error_injection"] = error_overrides

    # Latency overrides
    latency_overrides: dict[str, int] = {}
    if base_ms is not None:
        latency_overrides["base_ms"] = base_ms
    if jitter_ms is not None:
        latency_overrides["jitter_ms"] = jitter_ms
    if latency_overrides:
        cli_overrides["latency"] = latency_overrides

    # Content mode
    if content_mode is not None:
        cli_overrides["content"] = {"mode": content_mode}

    # Load config
    try:
        config = load_config(preset=preset, config_file=config_file, cli_overrides=cli_overrides)
    except FileNotFoundError as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e
    except (pydantic.ValidationError, yaml.YAMLError, ValueError) as e:
        typer.secho(f"Configuration error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e

    # Startup info
    typer.secho(
        f"Starting ChaosWeb server on {config.server.host}:{config.server.port}",
        fg=typer.colors.GREEN,
    )
    if preset:
        typer.echo(f"  Preset: {preset}")
    if config_file:
        typer.echo(f"  Config: {config_file}")
    typer.echo(f"  Metrics DB: {config.metrics.database}")
    typer.echo(f"  Workers: {config.server.workers}")
    typer.echo(f"  Content mode: {config.content.mode}")

    # Error injection summary
    error_cfg = config.error_injection
    active_errors = []
    for name in type(error_cfg).model_fields:
        if name.endswith("_pct"):
            val = getattr(error_cfg, name)
            if val > 0:
                label = name.removesuffix("_pct")
                active_errors.append(f"{label}:{val:.1f}%")

    if active_errors:
        typer.echo(f"  Error injection: {', '.join(active_errors)}")
    else:
        typer.echo("  Error injection: disabled")

    if error_cfg.burst.enabled:
        typer.echo(f"  Burst mode: every {error_cfg.burst.interval_sec}s for {error_cfg.burst.duration_sec}s")

    typer.echo()

    # Start uvicorn
    try:
        import uvicorn
    except ImportError as e:
        typer.secho(
            "Error: uvicorn is not installed. Install with: uv pip install uvicorn",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1) from e

    from errorworks.web.server import create_app

    web_app = create_app(config)
    uvicorn.run(
        web_app,
        host=config.server.host,
        port=config.server.port,
        workers=config.server.workers,
        log_level="info",
    )


@app.command()
def presets() -> None:
    """List available preset configurations."""
    available = list_presets()
    if not available:
        typer.echo("No presets found.")
        return

    typer.secho("Available presets:", fg=typer.colors.GREEN)
    for name in sorted(available):
        typer.echo(f"  - {name}")

    typer.echo()
    typer.echo("Use with: chaosweb serve --preset=<name>")


@app.command()
def show_config(
    preset: Annotated[
        str | None,
        typer.Option("--preset", "-p", help="Preset to show configuration for."),
    ] = None,
    config_file: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            help="Config file to show.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
        ),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option("--format", "-f", help="Output format: json or yaml."),
    ] = "yaml",
) -> None:
    """Show the effective configuration."""
    try:
        config = load_config(preset=preset, config_file=config_file)
    except FileNotFoundError as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e
    except (pydantic.ValidationError, yaml.YAMLError, ValueError) as e:
        typer.secho(f"Configuration error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e

    config_dict = config.model_dump()
    if output_format == "json":
        typer.echo(json.dumps(config_dict, indent=2))
    else:
        typer.echo(yaml.dump(config_dict, default_flow_style=False, sort_keys=False))


def main() -> None:
    """Entry point for chaosweb CLI."""
    app()


if __name__ == "__main__":
    main()
