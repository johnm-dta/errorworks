"""Tests for ChaosBlob CLI entry points."""

from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from errorworks.blob.cli import _create_app_from_env, app
from errorworks.engine.cli import app as engine_app

runner = CliRunner()

_UVICORN_RUN = "uvicorn.run"


def test_presets_lists_all_blob_profiles() -> None:
    result = runner.invoke(app, ["presets"])

    assert result.exit_code == 0, result.output
    expected = ["gentle", "realistic", "silent", "stress_extreme", "stress_storage"]
    for name in expected:
        assert name in result.output


def test_show_config_realistic_json_emits_json() -> None:
    result = runner.invoke(app, ["show-config", "--preset=realistic", "--format=json"])

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert parsed["preset_name"] == "realistic"
    assert "error_injection" in parsed
    assert "!!python" not in result.output


@patch(_UVICORN_RUN)
def test_serve_preset_and_port_pass_config_to_uvicorn(mock_run) -> None:
    result = runner.invoke(app, ["serve", "--preset=silent", "--port=9300"])

    assert result.exit_code == 0, result.output
    mock_run.assert_called_once()
    assert mock_run.call_args.kwargs["port"] == 9300
    assert mock_run.call_args.kwargs["workers"] == 1
    uvicorn_app = mock_run.call_args.args[0]
    server = uvicorn_app.state.server
    assert server._config.preset_name == "silent"
    assert server._config.server.port == 9300


def test_serve_workers_with_in_memory_database_exits_with_error() -> None:
    result = runner.invoke(app, ["serve", "--workers=2"])

    assert result.exit_code != 0
    assert "file-backed metrics database" in result.output


@patch(_UVICORN_RUN)
def test_serve_workers_with_file_database_preserves_blob_default_port(mock_run, tmp_path) -> None:
    db = tmp_path / "blob-cli-review.db"

    result = runner.invoke(app, ["serve", "--workers=2", f"--database={db}"])

    assert result.exit_code == 0, result.output
    assert mock_run.call_args.kwargs["port"] == 8300


@patch(_UVICORN_RUN)
def test_serve_host_without_port_preserves_blob_default_port(mock_run) -> None:
    result = runner.invoke(app, ["serve", "--host=127.0.0.2"])

    assert result.exit_code == 0, result.output
    assert mock_run.call_args.kwargs["host"] == "127.0.0.2"
    assert mock_run.call_args.kwargs["port"] == 8300


@patch(_UVICORN_RUN)
def test_serve_blob_specific_flags_reach_server_config(mock_run) -> None:
    result = runner.invoke(
        app,
        [
            "serve",
            "--slow-down-pct=0.1",
            "--access-denied-pct=0.2",
            "--not-found-pct=0.3",
            "--service-unavailable-pct=0.4",
            "--internal-error-pct=0.5",
            "--bad-gateway-pct=0.6",
            "--gateway-timeout-pct=0.7",
            "--timeout-pct=0.8",
            "--connection-reset-pct=0.9",
            "--connection-stall-pct=1.0",
            "--slow-response-pct=1.1",
            "--truncated-body-pct=1.2",
            "--wrong-content-length-pct=1.3",
            "--checksum-mismatch-pct=1.4",
            "--metadata-corruption-pct=1.5",
            "--stale-list-pct=1.6",
            "--malformed-xml-pct=1.7",
            "--selection-mode=weighted",
            "--base-ms=13",
            "--jitter-ms=14",
            "--burst-enabled",
            "--burst-interval-sec=30",
            "--burst-duration-sec=5",
            "--max-object-bytes=1024",
        ],
    )

    assert result.exit_code == 0, result.output
    server = mock_run.call_args.args[0].state.server
    error_config = server._error_injector.config
    assert error_config.slow_down_pct == 0.1
    assert error_config.access_denied_pct == 0.2
    assert error_config.not_found_pct == 0.3
    assert error_config.service_unavailable_pct == 0.4
    assert error_config.internal_error_pct == 0.5
    assert error_config.bad_gateway_pct == 0.6
    assert error_config.gateway_timeout_pct == 0.7
    assert error_config.timeout_pct == 0.8
    assert error_config.connection_reset_pct == 0.9
    assert error_config.connection_stall_pct == 1.0
    assert error_config.slow_response_pct == 1.1
    assert error_config.truncated_body_pct == 1.2
    assert error_config.wrong_content_length_pct == 1.3
    assert error_config.checksum_mismatch_pct == 1.4
    assert error_config.metadata_corruption_pct == 1.5
    assert error_config.stale_list_pct == 1.6
    assert error_config.malformed_xml_pct == 1.7
    assert error_config.selection_mode == "weighted"
    assert error_config.burst.enabled is True
    assert error_config.burst.interval_sec == 30
    assert error_config.burst.duration_sec == 5

    latency_config = server._latency_simulator.config
    assert latency_config.base_ms == 13
    assert latency_config.jitter_ms == 14
    assert server._storage_config.max_object_bytes == 1024


def test_unified_cli_blob_presets_works() -> None:
    result = runner.invoke(engine_app, ["blob", "presets"])

    assert result.exit_code == 0, result.output
    assert "stress_storage" in result.output


@patch(_UVICORN_RUN)
def test_serve_multi_worker_uses_import_string(mock_run, tmp_path) -> None:
    db = tmp_path / "blob-metrics.db"

    result = runner.invoke(app, ["serve", "--workers=2", f"--database={db}"])

    assert result.exit_code == 0, result.output
    assert isinstance(mock_run.call_args.args[0], str)
    assert "errorworks.blob.cli" in mock_run.call_args.args[0]


@patch(_UVICORN_RUN)
def test_serve_multi_worker_uses_factory_flag(mock_run, tmp_path) -> None:
    db = tmp_path / "blob-metrics.db"

    result = runner.invoke(app, ["serve", "--workers=2", f"--database={db}"])

    assert result.exit_code == 0, result.output
    assert mock_run.call_args.kwargs["factory"] is True


@patch(_UVICORN_RUN)
def test_serve_multi_worker_cleans_up_env_var(mock_run, tmp_path) -> None:
    import os

    db = tmp_path / "blob-metrics.db"

    result = runner.invoke(app, ["serve", "--workers=2", f"--database={db}"])

    assert result.exit_code == 0, result.output
    assert "_ERRORWORKS_BLOB_CONFIG" not in os.environ
    assert "_ERRORWORKS_BLOB_CONFIG_FILE" not in os.environ


@patch(_UVICORN_RUN)
def test_serve_multi_worker_uses_config_file_not_secret_bearing_env(mock_run, tmp_path) -> None:
    import os
    from pathlib import Path

    db = tmp_path / "blob-metrics.db"
    observed_config_path: str | None = None

    def inspect_env(*_args, **_kwargs) -> None:
        nonlocal observed_config_path
        assert "_ERRORWORKS_BLOB_CONFIG" not in os.environ
        observed_config_path = os.environ["_ERRORWORKS_BLOB_CONFIG_FILE"]
        config_path = Path(observed_config_path)
        assert config_path.exists()
        assert config_path.stat().st_mode & 0o777 == 0o600

    mock_run.side_effect = inspect_env

    result = runner.invoke(app, ["serve", "--workers=2", f"--database={db}"])

    assert result.exit_code == 0, result.output
    assert observed_config_path is not None
    assert not Path(observed_config_path).exists()


def test_create_app_from_env_builds_valid_app(monkeypatch) -> None:
    from starlette.applications import Starlette

    from errorworks.blob.config import ChaosBlobConfig

    monkeypatch.setenv("_ERRORWORKS_BLOB_CONFIG", ChaosBlobConfig().model_dump_json())

    result_app = _create_app_from_env()

    assert isinstance(result_app, Starlette)


def test_create_app_from_env_reads_private_config_file(monkeypatch, tmp_path) -> None:
    from starlette.applications import Starlette

    from errorworks.blob.config import ChaosBlobConfig

    config_file = tmp_path / "blob-config.json"
    config_file.write_text(ChaosBlobConfig().model_dump_json())
    monkeypatch.setenv("_ERRORWORKS_BLOB_CONFIG_FILE", str(config_file))

    result_app = _create_app_from_env()

    assert isinstance(result_app, Starlette)
