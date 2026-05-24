"""Tests for ChaosSMTP CLI entry points."""

import json
from unittest.mock import patch

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from errorworks.engine.cli import app as engine_app
from errorworks.engine.types import MetricsConfig
from errorworks.smtp.cli import app
from errorworks.smtp.config import ChaosSMTPConfig, SMTPAdminConfig

runner = CliRunner()
SECRET_ADMIN_TOKEN = "review-secret-admin-token"


def test_chaossmtp_cli_has_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "ChaosSMTP" in result.stdout
    assert "serve" in result.stdout
    assert "presets" in result.stdout


def test_chaosengine_mounts_smtp_subcommand() -> None:
    result = runner.invoke(engine_app, ["--help"])
    assert result.exit_code == 0
    assert "smtp" in result.stdout


def _validation_error() -> ValidationError:
    try:
        ChaosSMTPConfig(smtp={"port": 70000})
    except ValidationError as exc:
        return exc
    raise AssertionError("expected invalid SMTP config to raise ValidationError")


def _combined_output(result: object) -> str:
    stdout = getattr(result, "stdout", "")
    try:
        stderr = getattr(result, "stderr", "")
    except ValueError:
        stderr = ""
    return f"{stdout}{stderr}"


def test_presets_lists_expected_names() -> None:
    result = runner.invoke(app, ["presets"])
    assert result.exit_code == 0
    assert "silent" in result.stdout
    assert "realistic" in result.stdout
    assert "stress_delivery" in result.stdout


def test_show_config_outputs_yaml() -> None:
    result = runner.invoke(app, ["show-config", "--preset", "silent"])
    assert result.exit_code == 0
    assert "smtp:" in result.stdout
    assert "error_injection:" in result.stdout


def test_show_config_yaml_excludes_admin_token(tmp_path) -> None:
    config_file = tmp_path / "smtp.yaml"
    config_file.write_text(yaml.dump({"admin": {"admin_token": SECRET_ADMIN_TOKEN}}))

    result = runner.invoke(app, ["show-config", "--config", str(config_file)])

    assert result.exit_code == 0
    assert SECRET_ADMIN_TOKEN not in result.stdout
    data = yaml.safe_load(result.stdout)
    assert "admin_token" not in data["admin"]


def test_show_config_json_excludes_admin_token(tmp_path) -> None:
    config_file = tmp_path / "smtp.yaml"
    config_file.write_text(yaml.dump({"admin": {"admin_token": SECRET_ADMIN_TOKEN}}))

    result = runner.invoke(app, ["show-config", "--config", str(config_file), "--format", "json"])

    assert result.exit_code == 0
    assert SECRET_ADMIN_TOKEN not in result.stdout
    data = json.loads(result.stdout)
    assert "admin_token" not in data["admin"]


def test_serve_builds_config_and_starts_server() -> None:
    with patch("errorworks.smtp.cli.ChaosSMTPServer") as server_cls:
        server = server_cls.return_value
        server.smtp_host = "127.0.0.1"
        server.smtp_port = 2525
        server.admin_app = object()
        with patch("errorworks.smtp.cli.uvicorn.run") as uvicorn_run:
            result = runner.invoke(app, ["serve", "--preset", "silent", "--port", "2526", "--admin-port", "8526"])

    assert result.exit_code == 0
    server.start.assert_called_once()
    uvicorn_run.assert_called_once()
    server.stop.assert_called_once()
    config = server_cls.call_args.args[0]
    assert config.smtp.port == 2526
    assert config.admin.port == 8526


def test_serve_stops_server_when_admin_sidecar_fails() -> None:
    config = ChaosSMTPConfig()

    with (
        patch("errorworks.smtp.cli.load_config", return_value=config),
        patch("errorworks.smtp.cli.ChaosSMTPServer") as server_cls,
        patch("errorworks.smtp.cli.uvicorn.run", side_effect=RuntimeError("admin failed")),
    ):
        server = server_cls.return_value
        server.smtp_host = "127.0.0.1"
        server.smtp_port = 2525
        server.admin_app = object()
        result = runner.invoke(app, ["serve", "--preset", "silent"])

    assert result.exit_code == 1
    assert isinstance(result.exception, RuntimeError)
    server.start.assert_called_once()
    server.stop.assert_called_once()


def test_serve_stops_server_when_admin_disabled_wait_fails() -> None:
    async def fail_wait() -> None:
        raise RuntimeError("wait failed")

    config = ChaosSMTPConfig(admin=SMTPAdminConfig(enabled=False))

    with (
        patch("errorworks.smtp.cli.load_config", return_value=config),
        patch("errorworks.smtp.cli.ChaosSMTPServer") as server_cls,
        patch("errorworks.smtp.cli.uvicorn.run") as uvicorn_run,
        patch("errorworks.smtp.cli._wait_forever", fail_wait),
    ):
        server = server_cls.return_value
        server.smtp_host = "127.0.0.1"
        server.smtp_port = 2525
        result = runner.invoke(app, ["serve", "--preset", "silent"])

    assert result.exit_code == 1
    assert isinstance(result.exception, RuntimeError)
    server.start.assert_called_once()
    uvicorn_run.assert_not_called()
    server.stop.assert_called_once()


def test_serve_stops_server_when_start_fails() -> None:
    config = ChaosSMTPConfig()

    with (
        patch("errorworks.smtp.cli.load_config", return_value=config),
        patch("errorworks.smtp.cli.ChaosSMTPServer") as server_cls,
        patch("errorworks.smtp.cli.uvicorn.run") as uvicorn_run,
    ):
        server = server_cls.return_value
        server.start.side_effect = RuntimeError("start failed")
        result = runner.invoke(app, ["serve", "--preset", "silent"])

    assert result.exit_code == 1
    assert isinstance(result.exception, RuntimeError)
    server.start.assert_called_once()
    uvicorn_run.assert_not_called()
    server.stop.assert_called_once()


def test_serve_builds_cli_overrides_for_config_sections() -> None:
    config = ChaosSMTPConfig(
        admin=SMTPAdminConfig(port=8626),
        metrics=MetricsConfig(database="file:chaossmtp-cli-test?mode=memory&cache=shared"),
    )

    with (
        patch("errorworks.smtp.cli.load_config", return_value=config) as load_config,
        patch("errorworks.smtp.cli.ChaosSMTPServer") as server_cls,
        patch("errorworks.smtp.cli.uvicorn.run"),
    ):
        server = server_cls.return_value
        server.smtp_host = "127.0.0.1"
        server.smtp_port = 2525
        server.admin_app = object()
        result = runner.invoke(
            app,
            [
                "serve",
                "--preset",
                "silent",
                "--host",
                "127.0.0.2",
                "--port",
                "2527",
                "--admin-host",
                "127.0.0.3",
                "--admin-port",
                "8527",
                "--database",
                "smtp-cli.db",
                "--rate-limit-pct",
                "5",
                "--rcpt-to-tempfail-pct",
                "6",
                "--rcpt-to-reject-pct",
                "7",
                "--data-tempfail-pct",
                "8",
                "--data-reject-pct",
                "9",
                "--base-ms",
                "10",
                "--jitter-ms",
                "11",
                "--capture-mode",
                "full",
            ],
        )

    assert result.exit_code == 0
    assert load_config.call_args.kwargs["preset"] == "silent"
    assert load_config.call_args.kwargs["cli_overrides"] == {
        "smtp": {"host": "127.0.0.2", "port": 2527},
        "admin": {"host": "127.0.0.3", "port": 8527},
        "metrics": {"database": "smtp-cli.db"},
        "error_injection": {
            "rate_limit_pct": 5.0,
            "rcpt_to_tempfail_pct": 6.0,
            "rcpt_to_reject_pct": 7.0,
            "data_tempfail_pct": 8.0,
            "data_reject_pct": 9.0,
        },
        "latency": {"base_ms": 10, "jitter_ms": 11},
        "capture": {"mode": "full"},
    }


def test_serve_waits_without_admin_and_stops_server() -> None:
    async def wait_once() -> None:
        return None

    config = ChaosSMTPConfig(admin=SMTPAdminConfig(enabled=False))

    with (
        patch("errorworks.smtp.cli.load_config", return_value=config),
        patch("errorworks.smtp.cli.ChaosSMTPServer") as server_cls,
        patch("errorworks.smtp.cli.uvicorn.run") as uvicorn_run,
        patch("errorworks.smtp.cli._wait_forever", wait_once),
    ):
        server = server_cls.return_value
        server.smtp_host = "127.0.0.1"
        server.smtp_port = 2525
        result = runner.invoke(app, ["serve", "--preset", "silent"])

    assert result.exit_code == 0
    server.start.assert_called_once()
    uvicorn_run.assert_not_called()
    server.stop.assert_called_once()


@pytest.mark.parametrize("exc", [ValueError("bad preset"), yaml.YAMLError("bad yaml"), _validation_error()])
def test_serve_reports_config_errors(exc: Exception) -> None:
    with patch("errorworks.smtp.cli.load_config", side_effect=exc):
        result = runner.invoke(app, ["serve", "--preset", "silent"])

    assert result.exit_code == 1
    output = _combined_output(result)
    assert "Configuration error:" in output
    assert "bad" in output or "port" in output


def test_serve_redacts_admin_token_from_validation_errors(tmp_path) -> None:
    config_file = tmp_path / "unsafe.yaml"
    config_file.write_text(yaml.dump({"smtp": {"host": "0.0.0.0"}, "admin": {"admin_token": SECRET_ADMIN_TOKEN}}))

    result = runner.invoke(app, ["serve", "--config", str(config_file)])

    assert result.exit_code == 1
    output = _combined_output(result)
    assert "Configuration error:" in output
    assert "exposes ChaosSMTP" in output
    assert SECRET_ADMIN_TOKEN not in output
    assert "admin_token" not in output
