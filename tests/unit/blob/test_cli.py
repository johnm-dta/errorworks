"""Tests for ChaosBlob CLI entry points."""

from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from errorworks.blob.cli import app
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
def test_serve_blob_specific_flags_reach_server_config(mock_run) -> None:
    result = runner.invoke(
        app,
        [
            "serve",
            "--slow-down-pct=1",
            "--access-denied-pct=2",
            "--not-found-pct=3",
            "--service-unavailable-pct=4",
            "--internal-error-pct=5",
            "--timeout-pct=6",
            "--truncated-body-pct=7",
            "--wrong-content-length-pct=8",
            "--checksum-mismatch-pct=9",
            "--metadata-corruption-pct=10",
            "--stale-list-pct=11",
            "--malformed-xml-pct=12",
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
    assert error_config.slow_down_pct == 1
    assert error_config.access_denied_pct == 2
    assert error_config.not_found_pct == 3
    assert error_config.service_unavailable_pct == 4
    assert error_config.internal_error_pct == 5
    assert error_config.timeout_pct == 6
    assert error_config.truncated_body_pct == 7
    assert error_config.wrong_content_length_pct == 8
    assert error_config.checksum_mismatch_pct == 9
    assert error_config.metadata_corruption_pct == 10
    assert error_config.stale_list_pct == 11
    assert error_config.malformed_xml_pct == 12
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
