"""Tests for ChaosWeb CLI entry points."""

from __future__ import annotations

import json
from unittest.mock import patch

import yaml
from typer.testing import CliRunner

from errorworks.web.cli import app

runner = CliRunner()

# uvicorn is imported locally inside serve(), so we patch uvicorn.run directly.
_UVICORN_RUN = "uvicorn.run"


# ---------------------------------------------------------------------------
# serve command tests
# ---------------------------------------------------------------------------


@patch(_UVICORN_RUN)
def test_serve_defaults(mock_run):
    """Default serve uses Pydantic model defaults (not CLI defaults)."""
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 0, result.output
    mock_run.assert_called_once()
    call_kwargs = mock_run.call_args[1]
    assert call_kwargs["host"] == "127.0.0.1"
    assert call_kwargs["port"] == 8200
    assert call_kwargs["workers"] == 4  # ServerConfig default, not CLI default
    # Default workers=4 triggers multi-worker factory mode
    assert isinstance(mock_run.call_args.args[0], str)
    assert call_kwargs["factory"] is True


@patch(_UVICORN_RUN)
def test_serve_with_preset(mock_run):
    """Serve with --preset=gentle exits 0."""
    result = runner.invoke(app, ["serve", "--preset=gentle"])
    assert result.exit_code == 0, result.output


@patch(_UVICORN_RUN)
def test_serve_with_config_file(mock_run, tmp_path):
    """Serve with a valid YAML config file exits 0."""
    cfg = tmp_path / "chaos.yaml"
    cfg.write_text(yaml.dump({"server": {"host": "127.0.0.1", "port": 8200}}))
    result = runner.invoke(app, ["serve", "--config", str(cfg)])
    assert result.exit_code == 0, result.output


@patch(_UVICORN_RUN)
def test_serve_preset_plus_overrides(mock_run):
    """Preset combined with CLI overrides exits 0."""
    result = runner.invoke(app, ["serve", "--preset=gentle", "--rate-limit-pct=50"])
    assert result.exit_code == 0, result.output


@patch(_UVICORN_RUN)
def test_serve_all_error_flags(mock_run):
    """All 7 error flags are accepted without error."""
    result = runner.invoke(
        app,
        [
            "serve",
            "--rate-limit-pct=5",
            "--forbidden-pct=3",
            "--not-found-pct=2",
            "--service-unavailable-pct=4",
            "--internal-error-pct=1",
            "--timeout-pct=2",
            "--ssrf-redirect-pct=1",
        ],
    )
    assert result.exit_code == 0, result.output


@patch(_UVICORN_RUN)
def test_serve_error_summary_shows_all_pct_fields(mock_run):
    """Startup summary includes all non-zero _pct fields, not just a hardcoded subset."""
    result = runner.invoke(
        app,
        [
            "serve",
            "--rate-limit-pct=10",
            "--timeout-pct=25",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "rate_limit:10.0%" in result.output
    assert "timeout:25.0%" in result.output


@patch(_UVICORN_RUN)
def test_serve_burst_flags(mock_run):
    """Burst flags are accepted."""
    result = runner.invoke(
        app,
        [
            "serve",
            "--burst-enabled",
            "--burst-interval-sec=10",
            "--burst-duration-sec=2",
        ],
    )
    assert result.exit_code == 0, result.output


@patch(_UVICORN_RUN)
def test_serve_latency_flags(mock_run):
    """Latency flags are accepted."""
    result = runner.invoke(app, ["serve", "--base-ms=100", "--jitter-ms=20"])
    assert result.exit_code == 0, result.output


@patch(_UVICORN_RUN)
def test_serve_content_mode_flag(mock_run):
    """--content-mode flag (not --response-mode) is accepted."""
    result = runner.invoke(app, ["serve", "--content-mode=echo"])
    assert result.exit_code == 0, result.output


@patch(_UVICORN_RUN)
def test_serve_selection_mode_flag(mock_run):
    """--selection-mode=weighted is accepted."""
    result = runner.invoke(app, ["serve", "--selection-mode=weighted"])
    assert result.exit_code == 0, result.output


@patch(_UVICORN_RUN)
def test_serve_workers_flag(mock_run):
    """--workers=4 is passed through to uvicorn."""
    result = runner.invoke(app, ["serve", "--workers=4"])
    assert result.exit_code == 0, result.output
    call_kwargs = mock_run.call_args[1]
    assert call_kwargs["workers"] == 4


# ---------------------------------------------------------------------------
# Multi-worker factory tests
# ---------------------------------------------------------------------------


@patch(_UVICORN_RUN)
def test_serve_multi_worker_uses_import_string(mock_run):
    """When workers > 1, uvicorn.run receives an import string, not an app object."""
    result = runner.invoke(app, ["serve", "--workers=4"])
    assert result.exit_code == 0, result.output
    first_arg = mock_run.call_args.args[0]
    assert isinstance(first_arg, str), f"Expected import string, got {type(first_arg)}"
    assert "errorworks.web.server" in first_arg


@patch(_UVICORN_RUN)
def test_serve_multi_worker_uses_factory_flag(mock_run):
    """When workers > 1, factory=True is passed to uvicorn.run."""
    result = runner.invoke(app, ["serve", "--workers=4"])
    assert result.exit_code == 0, result.output
    assert mock_run.call_args.kwargs.get("factory") is True


@patch(_UVICORN_RUN)
def test_serve_single_worker_uses_app_object(mock_run):
    """When workers == 1, uvicorn.run receives the app object directly."""
    result = runner.invoke(app, ["serve", "--workers=1"])
    assert result.exit_code == 0, result.output
    first_arg = mock_run.call_args.args[0]
    assert not isinstance(first_arg, str), f"Expected app object, got string: {first_arg}"


@patch(_UVICORN_RUN)
def test_serve_custom_host_port(mock_run):
    """Custom host and port are forwarded to uvicorn."""
    result = runner.invoke(app, ["serve", "--host=127.0.0.2", "--port=9999"])
    assert result.exit_code == 0, result.output
    call_kwargs = mock_run.call_args[1]
    assert call_kwargs["host"] == "127.0.0.2"
    assert call_kwargs["port"] == 9999


@patch(_UVICORN_RUN)
def test_serve_custom_database(mock_run):
    """--database flag is accepted."""
    result = runner.invoke(app, ["serve", "--database=/tmp/test.db"])
    assert result.exit_code == 0, result.output


def test_serve_invalid_preset():
    """Non-existent preset exits with code 1."""
    result = runner.invoke(app, ["serve", "--preset=nonexistent"])
    assert result.exit_code == 1


def test_serve_invalid_yaml_config(tmp_path):
    """Malformed config file exits with code 1."""
    cfg = tmp_path / "bad.yaml"
    cfg.write_text('error_injection: "not a dict"')
    result = runner.invoke(app, ["serve", "--config", str(cfg)])
    assert result.exit_code == 1


def test_serve_validation_error():
    """Error percentage out of range exits with code 1."""
    result = runner.invoke(app, ["serve", "--rate-limit-pct=200"])
    assert result.exit_code != 0


@patch(_UVICORN_RUN)
def test_serve_no_burst(mock_run):
    """--no-burst flag is accepted."""
    result = runner.invoke(app, ["serve", "--no-burst"])
    assert result.exit_code == 0, result.output


def test_serve_invalid_selection_mode():
    """Invalid selection mode exits with code 1."""
    result = runner.invoke(app, ["serve", "--selection-mode=bogus"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# presets command tests
# ---------------------------------------------------------------------------


def test_presets_lists_all():
    """Presets command output contains all 5 web preset names."""
    result = runner.invoke(app, ["presets"])
    assert result.exit_code == 0, result.output
    expected = ["gentle", "realistic", "silent", "stress_extreme", "stress_scraping"]
    for name in expected:
        assert name in result.output, f"Missing preset: {name}"


def test_presets_sorted():
    """Preset names appear in alphabetical order."""
    result = runner.invoke(app, ["presets"])
    assert result.exit_code == 0, result.output
    lines = [line.strip().lstrip("- ") for line in result.output.splitlines() if line.strip().startswith("-")]
    assert lines == sorted(lines)


# ---------------------------------------------------------------------------
# show-config command tests
# ---------------------------------------------------------------------------


def test_show_config_defaults_yaml():
    """show-config with defaults produces YAML parseable by safe_load (no !!python tags)."""
    result = runner.invoke(app, ["show-config"])
    assert result.exit_code == 0, result.output
    parsed = yaml.safe_load(result.output)
    assert isinstance(parsed, dict)
    assert "!!python" not in result.output


def test_show_config_json_format():
    """--format=json produces valid JSON output."""
    result = runner.invoke(app, ["show-config", "--format=json"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert isinstance(parsed, dict)


def test_show_config_with_preset():
    """show-config with --preset=gentle exits 0."""
    result = runner.invoke(app, ["show-config", "--preset=gentle"])
    assert result.exit_code == 0, result.output


def test_show_config_invalid_preset():
    """show-config with non-existent preset exits 1."""
    result = runner.invoke(app, ["show-config", "--preset=nonexistent"])
    assert result.exit_code == 1


def test_show_config_invalid_format():
    """show-config --format=xml should exit non-zero, not silently fall through."""
    result = runner.invoke(app, ["show-config", "--format=xml"])
    assert result.exit_code != 0


@patch(_UVICORN_RUN)
def test_serve_multi_worker_cleans_up_env_var(mock_run):
    """Env var _ERRORWORKS_WEB_CONFIG is cleaned up after uvicorn.run returns."""
    import os

    result = runner.invoke(app, ["serve", "--workers=2"])
    assert result.exit_code == 0, result.output
    assert "_ERRORWORKS_WEB_CONFIG" not in os.environ


# ---------------------------------------------------------------------------
# version flag
# ---------------------------------------------------------------------------


def test_version_flag():
    """--version on serve exits 0 and output contains 'chaosweb'."""
    result = runner.invoke(app, ["serve", "--version"])
    assert result.exit_code == 0, result.output
    assert "chaosweb" in result.output


# ---------------------------------------------------------------------------
# Factory function tests
# ---------------------------------------------------------------------------


def test_create_app_from_env_builds_valid_app(monkeypatch):
    """_create_app_from_env reads config from env var and returns a Starlette app."""
    from starlette.applications import Starlette

    from errorworks.web.config import ChaosWebConfig
    from errorworks.web.server import _create_app_from_env

    config = ChaosWebConfig()
    monkeypatch.setenv("_ERRORWORKS_WEB_CONFIG", config.model_dump_json())

    result_app = _create_app_from_env()
    assert isinstance(result_app, Starlette)
