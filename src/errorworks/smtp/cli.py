"""CLI for ChaosSMTP fake SMTP server."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

import pydantic
import typer
import uvicorn
import yaml

from errorworks.smtp.config import list_presets, load_config
from errorworks.smtp.server import ChaosSMTPServer

app = typer.Typer(
    name="chaossmtp",
    help="ChaosSMTP: Fake SMTP server for outbound email resilience testing.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        from importlib.metadata import PackageNotFoundError, version

        try:
            typer.echo(f"chaossmtp (errorworks {version('errorworks')})")
        except PackageNotFoundError:
            typer.echo("chaossmtp (version unknown)")
        raise typer.Exit()


@app.command()
def serve(
    preset: Annotated[
        str | None,
        typer.Option("--preset", "-p", help="Preset configuration to use. Use 'chaossmtp presets' to list available."),
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
        typer.Option("--host", "-h", help="SMTP host address to bind to."),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option("--port", "-P", help="SMTP port to listen on.", min=1, max=65535),
    ] = None,
    hostname: Annotated[
        str | None,
        typer.Option("--hostname", help="SMTP server hostname announced to clients."),
    ] = None,
    data_size_limit: Annotated[
        int | None,
        typer.Option("--data-size-limit", help="Maximum SMTP DATA size in bytes.", min=1),
    ] = None,
    enable_smtputf8: Annotated[
        bool | None,
        typer.Option("--enable-smtputf8/--disable-smtputf8", help="Enable SMTPUTF8 support."),
    ] = None,
    require_starttls: Annotated[
        bool | None,
        typer.Option("--require-starttls/--no-require-starttls", help="Require STARTTLS before mail commands."),
    ] = None,
    admin_enabled: Annotated[
        bool | None,
        typer.Option("--admin-enabled/--no-admin", help="Enable the HTTP admin sidecar."),
    ] = None,
    admin_host: Annotated[
        str | None,
        typer.Option("--admin-host", help="Admin sidecar host address to bind to."),
    ] = None,
    admin_port: Annotated[
        int | None,
        typer.Option("--admin-port", help="Admin sidecar port to listen on.", min=1, max=65535),
    ] = None,
    admin_token: Annotated[
        str | None,
        typer.Option("--admin-token", help="Bearer token for /admin/* endpoints."),
    ] = None,
    database: Annotated[
        str | None,
        typer.Option("--database", "-d", help="SQLite database path for metrics."),
    ] = None,
    timeseries_bucket_sec: Annotated[
        int | None,
        typer.Option("--timeseries-bucket-sec", help="Metrics time-series bucket size in seconds.", min=1),
    ] = None,
    rate_limit_pct: Annotated[
        float | None,
        typer.Option("--rate-limit-pct", help="SMTP rate limit error percentage.", min=0.0, max=100.0),
    ] = None,
    mail_from_tempfail_pct: Annotated[
        float | None,
        typer.Option("--mail-from-tempfail-pct", help="MAIL FROM temporary failure percentage.", min=0.0, max=100.0),
    ] = None,
    mail_from_reject_pct: Annotated[
        float | None,
        typer.Option("--mail-from-reject-pct", help="MAIL FROM permanent rejection percentage.", min=0.0, max=100.0),
    ] = None,
    rcpt_to_tempfail_pct: Annotated[
        float | None,
        typer.Option("--rcpt-to-tempfail-pct", help="RCPT TO temporary failure percentage.", min=0.0, max=100.0),
    ] = None,
    rcpt_to_reject_pct: Annotated[
        float | None,
        typer.Option("--rcpt-to-reject-pct", help="RCPT TO permanent rejection percentage.", min=0.0, max=100.0),
    ] = None,
    data_tempfail_pct: Annotated[
        float | None,
        typer.Option("--data-tempfail-pct", help="DATA temporary failure percentage.", min=0.0, max=100.0),
    ] = None,
    data_reject_pct: Annotated[
        float | None,
        typer.Option("--data-reject-pct", help="DATA permanent rejection percentage.", min=0.0, max=100.0),
    ] = None,
    accept_then_drop_pct: Annotated[
        float | None,
        typer.Option("--accept-then-drop-pct", help="Accept message then drop it without capture.", min=0.0, max=100.0),
    ] = None,
    banner_reject_pct: Annotated[
        float | None,
        typer.Option("--banner-reject-pct", help="Banner-stage rejection percentage.", min=0.0, max=100.0),
    ] = None,
    malformed_reply_pct: Annotated[
        float | None,
        typer.Option("--malformed-reply-pct", help="Malformed SMTP reply percentage.", min=0.0, max=100.0),
    ] = None,
    wrong_reply_code_pct: Annotated[
        float | None,
        typer.Option("--wrong-reply-code-pct", help="Unexpected SMTP reply code percentage.", min=0.0, max=100.0),
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
    selection_mode: Annotated[
        str | None,
        typer.Option("--selection-mode", help="Error selection strategy: priority or weighted."),
    ] = None,
    burst_enabled: Annotated[
        bool | None,
        typer.Option("--burst-enabled/--no-burst", help="Enable burst pattern injection."),
    ] = None,
    burst_interval_sec: Annotated[
        int | None,
        typer.Option("--burst-interval-sec", help="Time between burst starts in seconds.", min=1),
    ] = None,
    burst_duration_sec: Annotated[
        int | None,
        typer.Option("--burst-duration-sec", help="Burst duration in seconds.", min=1),
    ] = None,
    burst_tempfail_pct: Annotated[
        float | None,
        typer.Option("--burst-tempfail-pct", help="Temporary failure percentage during bursts.", min=0.0, max=100.0),
    ] = None,
    burst_rate_limit_pct: Annotated[
        float | None,
        typer.Option("--burst-rate-limit-pct", help="Rate limit percentage during bursts.", min=0.0, max=100.0),
    ] = None,
    base_ms: Annotated[
        int | None,
        typer.Option("--base-ms", help="Base latency in milliseconds.", min=0),
    ] = None,
    jitter_ms: Annotated[
        int | None,
        typer.Option("--jitter-ms", help="Latency jitter in milliseconds.", min=0),
    ] = None,
    capture_mode: Annotated[
        str | None,
        typer.Option("--capture-mode", help="Message capture mode: discard, metadata, or full."),
    ] = None,
    max_message_bytes: Annotated[
        int | None,
        typer.Option("--max-message-bytes", help="Maximum captured message bytes.", min=0),
    ] = None,
    allow_external_bind: Annotated[
        bool | None,
        typer.Option("--allow-external-bind/--no-allow-external-bind", help="Allow binding ChaosSMTP to non-loopback hosts."),
    ] = None,
    version: Annotated[
        bool,
        typer.Option("--version", "-v", callback=_version_callback, is_eager=True, help="Show version and exit."),
    ] = False,
) -> None:
    """Start the ChaosSMTP fake SMTP server."""
    cli_overrides = _build_cli_overrides(
        host=host,
        port=port,
        hostname=hostname,
        data_size_limit=data_size_limit,
        enable_smtputf8=enable_smtputf8,
        require_starttls=require_starttls,
        admin_enabled=admin_enabled,
        admin_host=admin_host,
        admin_port=admin_port,
        admin_token=admin_token,
        database=database,
        timeseries_bucket_sec=timeseries_bucket_sec,
        rate_limit_pct=rate_limit_pct,
        mail_from_tempfail_pct=mail_from_tempfail_pct,
        mail_from_reject_pct=mail_from_reject_pct,
        rcpt_to_tempfail_pct=rcpt_to_tempfail_pct,
        rcpt_to_reject_pct=rcpt_to_reject_pct,
        data_tempfail_pct=data_tempfail_pct,
        data_reject_pct=data_reject_pct,
        accept_then_drop_pct=accept_then_drop_pct,
        banner_reject_pct=banner_reject_pct,
        malformed_reply_pct=malformed_reply_pct,
        wrong_reply_code_pct=wrong_reply_code_pct,
        connection_reset_pct=connection_reset_pct,
        connection_stall_pct=connection_stall_pct,
        slow_response_pct=slow_response_pct,
        selection_mode=selection_mode,
        burst_enabled=burst_enabled,
        burst_interval_sec=burst_interval_sec,
        burst_duration_sec=burst_duration_sec,
        burst_tempfail_pct=burst_tempfail_pct,
        burst_rate_limit_pct=burst_rate_limit_pct,
        base_ms=base_ms,
        jitter_ms=jitter_ms,
        capture_mode=capture_mode,
        max_message_bytes=max_message_bytes,
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

    server = ChaosSMTPServer(config)
    try:
        server.start()
        typer.secho(f"Starting ChaosSMTP server on {server.smtp_host}:{server.smtp_port}", fg=typer.colors.GREEN)
        if preset:
            typer.echo(f"  Preset: {preset}")
        if config_file:
            typer.echo(f"  Config: {config_file}")
        typer.echo(f"  Metrics DB: {config.metrics.database}")
        typer.echo(f"  Capture mode: {config.capture.mode}")
        if config.admin.enabled:
            typer.echo(f"  Admin: http://{config.admin.host}:{config.admin.port}")
        else:
            typer.echo("  Admin: disabled")

        _echo_error_summary(config.error_injection)
        typer.echo()

        if config.admin.enabled:
            uvicorn.run(server.admin_app, host=config.admin.host, port=config.admin.port, workers=1, log_level="info")
        else:
            asyncio.run(_wait_forever())
    finally:
        server.stop()


def _build_cli_overrides(**values: Any) -> dict[str, Any]:
    cli_overrides: dict[str, Any] = {}

    smtp_overrides = _present(
        {
            "host": values["host"],
            "port": values["port"],
            "hostname": values["hostname"],
            "data_size_limit": values["data_size_limit"],
            "enable_smtputf8": values["enable_smtputf8"],
            "require_starttls": values["require_starttls"],
        }
    )
    if smtp_overrides:
        cli_overrides["smtp"] = smtp_overrides

    admin_overrides = _present(
        {
            "enabled": values["admin_enabled"],
            "host": values["admin_host"],
            "port": values["admin_port"],
            "admin_token": values["admin_token"],
        }
    )
    if admin_overrides:
        cli_overrides["admin"] = admin_overrides

    metrics_overrides = _present(
        {
            "database": values["database"],
            "timeseries_bucket_sec": values["timeseries_bucket_sec"],
        }
    )
    if metrics_overrides:
        cli_overrides["metrics"] = metrics_overrides

    error_overrides = _present(
        {
            "rate_limit_pct": values["rate_limit_pct"],
            "mail_from_tempfail_pct": values["mail_from_tempfail_pct"],
            "mail_from_reject_pct": values["mail_from_reject_pct"],
            "rcpt_to_tempfail_pct": values["rcpt_to_tempfail_pct"],
            "rcpt_to_reject_pct": values["rcpt_to_reject_pct"],
            "data_tempfail_pct": values["data_tempfail_pct"],
            "data_reject_pct": values["data_reject_pct"],
            "accept_then_drop_pct": values["accept_then_drop_pct"],
            "banner_reject_pct": values["banner_reject_pct"],
            "malformed_reply_pct": values["malformed_reply_pct"],
            "wrong_reply_code_pct": values["wrong_reply_code_pct"],
            "connection_reset_pct": values["connection_reset_pct"],
            "connection_stall_pct": values["connection_stall_pct"],
            "slow_response_pct": values["slow_response_pct"],
            "selection_mode": values["selection_mode"],
        }
    )
    burst_overrides = _present(
        {
            "enabled": values["burst_enabled"],
            "interval_sec": values["burst_interval_sec"],
            "duration_sec": values["burst_duration_sec"],
            "tempfail_pct": values["burst_tempfail_pct"],
            "rate_limit_pct": values["burst_rate_limit_pct"],
        }
    )
    if burst_overrides:
        error_overrides["burst"] = burst_overrides
    if error_overrides:
        cli_overrides["error_injection"] = error_overrides

    latency_overrides = _present(
        {
            "base_ms": values["base_ms"],
            "jitter_ms": values["jitter_ms"],
        }
    )
    if latency_overrides:
        cli_overrides["latency"] = latency_overrides

    capture_overrides = _present(
        {
            "mode": values["capture_mode"],
            "max_message_bytes": values["max_message_bytes"],
        }
    )
    if capture_overrides:
        cli_overrides["capture"] = capture_overrides

    if values["allow_external_bind"] is not None:
        cli_overrides["allow_external_bind"] = values["allow_external_bind"]

    return cli_overrides


def _present(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _echo_error_summary(error_cfg: Any) -> None:
    active_errors = []
    for name in type(error_cfg).model_fields:
        if name.endswith("_pct"):
            val = getattr(error_cfg, name)
            if val > 0:
                active_errors.append(f"{name.removesuffix('_pct')}:{val:.1f}%")

    if active_errors:
        typer.echo(f"  Error injection: {', '.join(active_errors)}")
    else:
        typer.echo("  Error injection: disabled")

    if error_cfg.burst.enabled:
        typer.echo(f"  Burst mode: every {error_cfg.burst.interval_sec}s for {error_cfg.burst.duration_sec}s")


async def _wait_forever() -> None:
    while True:
        await asyncio.sleep(3600)


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
    typer.echo("Use with: chaossmtp serve --preset=<name>")


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
    """Entry point for chaossmtp CLI."""
    app()


if __name__ == "__main__":
    main()
