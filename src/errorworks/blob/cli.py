"""CLI for ChaosBlob fake object storage server."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import pydantic
import typer
import yaml
from starlette.applications import Starlette

from errorworks.blob.config import ChaosBlobConfig, list_presets, load_config

_CONFIG_ENV_VAR = "_ERRORWORKS_BLOB_CONFIG"
_CONFIG_FILE_ENV_VAR = "_ERRORWORKS_BLOB_CONFIG_FILE"

app = typer.Typer(
    name="chaosblob",
    help="ChaosBlob: Fake object storage server for blob pipeline resilience testing.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        from importlib.metadata import PackageNotFoundError, version

        try:
            typer.echo(f"chaosblob (errorworks {version('errorworks')})")
        except PackageNotFoundError:
            typer.echo("chaosblob (version unknown)")
        raise typer.Exit()


def _create_app_from_env() -> Starlette:
    """Factory for uvicorn multi-worker mode."""
    import os

    from errorworks.blob.server import create_app

    if config_file := os.environ.get(_CONFIG_FILE_ENV_VAR):
        config_json = Path(config_file).read_text()
    else:
        config_json = os.environ[_CONFIG_ENV_VAR]
    config = ChaosBlobConfig.model_validate_json(config_json)
    return create_app(config)


@app.command()
def serve(
    preset: Annotated[
        str | None,
        typer.Option("--preset", "-p", help="Preset configuration to use. Use 'chaosblob presets' to list available."),
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
    host: Annotated[
        str | None,
        typer.Option("--host", "-h", help="Host address to bind to (default: 127.0.0.1)."),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option("--port", "-P", help="Port to listen on (default: 8300).", min=1, max=65535),
    ] = None,
    workers: Annotated[
        int | None,
        typer.Option("--workers", "-w", help="Number of uvicorn workers (default: from preset or 1).", min=1),
    ] = None,
    database: Annotated[
        str | None,
        typer.Option("--database", "-d", help="SQLite database path for metrics."),
    ] = None,
    slow_down_pct: Annotated[
        float | None,
        typer.Option("--slow-down-pct", help="S3 SlowDown error percentage.", min=0.0, max=100.0),
    ] = None,
    access_denied_pct: Annotated[
        float | None,
        typer.Option("--access-denied-pct", help="403 AccessDenied error percentage.", min=0.0, max=100.0),
    ] = None,
    not_found_pct: Annotated[
        float | None,
        typer.Option("--not-found-pct", help="404 NoSuchKey error percentage.", min=0.0, max=100.0),
    ] = None,
    service_unavailable_pct: Annotated[
        float | None,
        typer.Option("--service-unavailable-pct", help="503 ServiceUnavailable error percentage.", min=0.0, max=100.0),
    ] = None,
    internal_error_pct: Annotated[
        float | None,
        typer.Option("--internal-error-pct", help="500 InternalError percentage.", min=0.0, max=100.0),
    ] = None,
    bad_gateway_pct: Annotated[
        float | None,
        typer.Option("--bad-gateway-pct", help="502 BadGateway percentage.", min=0.0, max=100.0),
    ] = None,
    gateway_timeout_pct: Annotated[
        float | None,
        typer.Option("--gateway-timeout-pct", help="504 GatewayTimeout percentage.", min=0.0, max=100.0),
    ] = None,
    timeout_pct: Annotated[
        float | None,
        typer.Option("--timeout-pct", help="Connection timeout percentage.", min=0.0, max=100.0),
    ] = None,
    connection_reset_pct: Annotated[
        float | None,
        typer.Option("--connection-reset-pct", help="Connection reset percentage.", min=0.0, max=100.0),
    ] = None,
    connection_stall_pct: Annotated[
        float | None,
        typer.Option("--connection-stall-pct", help="Connection stall percentage.", min=0.0, max=100.0),
    ] = None,
    slow_response_pct: Annotated[
        float | None,
        typer.Option("--slow-response-pct", help="Slow response percentage.", min=0.0, max=100.0),
    ] = None,
    truncated_body_pct: Annotated[
        float | None,
        typer.Option("--truncated-body-pct", help="Truncated object body percentage.", min=0.0, max=100.0),
    ] = None,
    wrong_content_length_pct: Annotated[
        float | None,
        typer.Option("--wrong-content-length-pct", help="Wrong Content-Length percentage.", min=0.0, max=100.0),
    ] = None,
    checksum_mismatch_pct: Annotated[
        float | None,
        typer.Option("--checksum-mismatch-pct", help="Checksum mismatch percentage.", min=0.0, max=100.0),
    ] = None,
    metadata_corruption_pct: Annotated[
        float | None,
        typer.Option("--metadata-corruption-pct", help="Metadata corruption percentage.", min=0.0, max=100.0),
    ] = None,
    stale_list_pct: Annotated[
        float | None,
        typer.Option("--stale-list-pct", help="Stale list response percentage.", min=0.0, max=100.0),
    ] = None,
    malformed_xml_pct: Annotated[
        float | None,
        typer.Option("--malformed-xml-pct", help="Malformed XML response percentage.", min=0.0, max=100.0),
    ] = None,
    selection_mode: Annotated[
        str | None,
        typer.Option("--selection-mode", help="Error selection: priority or weighted."),
    ] = None,
    base_ms: Annotated[
        int | None,
        typer.Option("--base-ms", help="Base latency in milliseconds.", min=0),
    ] = None,
    jitter_ms: Annotated[
        int | None,
        typer.Option("--jitter-ms", help="Latency jitter in milliseconds.", min=0),
    ] = None,
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
    max_object_bytes: Annotated[
        int | None,
        typer.Option("--max-object-bytes", help="Maximum stored object size in bytes.", min=1),
    ] = None,
    allow_external_bind: Annotated[
        bool,
        typer.Option("--allow-external-bind", help="Allow binding to all interfaces such as 0.0.0.0."),
    ] = False,
    version: Annotated[
        bool,
        typer.Option("--version", "-v", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    """Start the ChaosBlob fake object storage server."""
    cli_overrides = _build_cli_overrides(
        host=host,
        port=port,
        workers=workers,
        database=database,
        slow_down_pct=slow_down_pct,
        access_denied_pct=access_denied_pct,
        not_found_pct=not_found_pct,
        service_unavailable_pct=service_unavailable_pct,
        internal_error_pct=internal_error_pct,
        bad_gateway_pct=bad_gateway_pct,
        gateway_timeout_pct=gateway_timeout_pct,
        timeout_pct=timeout_pct,
        connection_reset_pct=connection_reset_pct,
        connection_stall_pct=connection_stall_pct,
        slow_response_pct=slow_response_pct,
        truncated_body_pct=truncated_body_pct,
        wrong_content_length_pct=wrong_content_length_pct,
        checksum_mismatch_pct=checksum_mismatch_pct,
        metadata_corruption_pct=metadata_corruption_pct,
        stale_list_pct=stale_list_pct,
        malformed_xml_pct=malformed_xml_pct,
        selection_mode=selection_mode,
        base_ms=base_ms,
        jitter_ms=jitter_ms,
        burst_enabled=burst_enabled,
        burst_interval_sec=burst_interval_sec,
        burst_duration_sec=burst_duration_sec,
        max_object_bytes=max_object_bytes,
        allow_external_bind=allow_external_bind,
    )

    try:
        config = load_config(preset=preset, config_file=config_file, cli_overrides=cli_overrides)
    except FileNotFoundError as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e
    except (pydantic.ValidationError, yaml.YAMLError, ValueError) as e:
        typer.secho(f"Configuration error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e

    typer.secho(f"Starting ChaosBlob server on {config.server.host}:{config.server.port}", fg=typer.colors.GREEN)
    if preset:
        typer.echo(f"  Preset: {preset}")
    if config_file:
        typer.echo(f"  Config: {config_file}")
    typer.echo(f"  Metrics DB: {config.metrics.database}")
    typer.echo(f"  Workers: {config.server.workers}")
    typer.echo(f"  Max object bytes: {config.storage.max_object_bytes}")

    error_cfg = config.error_injection
    active_errors = [
        f"{name.removesuffix('_pct')}:{getattr(error_cfg, name):.1f}%"
        for name in type(error_cfg).model_fields
        if name.endswith("_pct") and getattr(error_cfg, name) > 0
    ]
    if active_errors:
        typer.echo(f"  Error injection: {', '.join(active_errors)}")
    else:
        typer.echo("  Error injection: disabled")

    if error_cfg.burst.enabled:
        typer.echo(f"  Burst mode: every {error_cfg.burst.interval_sec}s for {error_cfg.burst.duration_sec}s")

    typer.echo()

    try:
        import uvicorn
    except ImportError as e:
        typer.secho("Error: uvicorn is not installed. Install with: uv pip install uvicorn", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e

    if config.server.workers > 1:
        import os
        import tempfile
        from contextlib import suppress

        fd, config_path = tempfile.mkstemp(prefix="errorworks-blob-", suffix=".json")
        os.close(fd)
        os.chmod(config_path, 0o600)
        Path(config_path).write_text(config.model_dump_json())
        os.environ[_CONFIG_FILE_ENV_VAR] = config_path
        try:
            uvicorn.run(
                "errorworks.blob.cli:_create_app_from_env",
                factory=True,
                host=config.server.host,
                port=config.server.port,
                workers=config.server.workers,
                log_level="info",
            )
        finally:
            os.environ.pop(_CONFIG_ENV_VAR, None)
            os.environ.pop(_CONFIG_FILE_ENV_VAR, None)
            with suppress(FileNotFoundError):
                Path(config_path).unlink()
    else:
        from errorworks.blob.server import create_app

        blob_app = create_app(config)
        uvicorn.run(blob_app, host=config.server.host, port=config.server.port, workers=1, log_level="info")


def _build_cli_overrides(**values: Any) -> dict[str, Any]:
    cli_overrides: dict[str, Any] = {}

    server_overrides = _non_none(values, "host", "port", "workers")
    if server_overrides:
        cli_overrides["server"] = server_overrides

    if values["database"] is not None:
        cli_overrides["metrics"] = {"database": values["database"]}

    error_overrides = _non_none(
        values,
        "slow_down_pct",
        "access_denied_pct",
        "not_found_pct",
        "service_unavailable_pct",
        "internal_error_pct",
        "bad_gateway_pct",
        "gateway_timeout_pct",
        "timeout_pct",
        "connection_reset_pct",
        "connection_stall_pct",
        "slow_response_pct",
        "truncated_body_pct",
        "wrong_content_length_pct",
        "checksum_mismatch_pct",
        "metadata_corruption_pct",
        "stale_list_pct",
        "malformed_xml_pct",
        "selection_mode",
    )
    burst_overrides = {key: values[key] for key in ("burst_enabled", "burst_interval_sec", "burst_duration_sec") if values[key] is not None}
    if burst_overrides:
        error_overrides["burst"] = {
            "enabled" if key == "burst_enabled" else key.removeprefix("burst_"): value for key, value in burst_overrides.items()
        }
    if error_overrides:
        cli_overrides["error_injection"] = error_overrides

    latency_overrides = _non_none(values, "base_ms", "jitter_ms")
    if latency_overrides:
        cli_overrides["latency"] = latency_overrides

    if values["max_object_bytes"] is not None:
        cli_overrides["storage"] = {"max_object_bytes": values["max_object_bytes"]}

    if values["allow_external_bind"]:
        cli_overrides["allow_external_bind"] = True

    return cli_overrides


def _non_none(values: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: values[key] for key in keys if values[key] is not None}


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
    typer.echo("Use with: chaosblob serve --preset=<name>")


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

    config_dict = config.model_dump(mode="json")
    if output_format == "json":
        typer.echo(json.dumps(config_dict, indent=2))
    elif output_format == "yaml":
        typer.echo(yaml.dump(config_dict, default_flow_style=False, sort_keys=False))
    else:
        typer.secho(f"Error: unsupported format '{output_format}'. Use 'json' or 'yaml'.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


def main() -> None:
    """Entry point for chaosblob CLI."""
    app()


if __name__ == "__main__":
    main()
