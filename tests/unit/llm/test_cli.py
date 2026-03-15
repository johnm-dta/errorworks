"""Tests for ChaosLLM CLI entry points."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import yaml
from typer.testing import CliRunner

from errorworks.llm.cli import app, mcp_app

runner = CliRunner()

# uvicorn is imported inside the serve() function body via `import uvicorn`.
# We patch uvicorn.run directly since the module is installed and importable.
_patch_uvicorn_run = patch("uvicorn.run")


# ---------------------------------------------------------------------------
# serve command tests
# ---------------------------------------------------------------------------


@_patch_uvicorn_run
def test_serve_defaults(mock_run):
    """serve with no flags uses Pydantic model defaults (not CLI defaults)."""
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 0, result.output
    mock_run.assert_called_once()
    call_kwargs = mock_run.call_args
    assert call_kwargs.kwargs["host"] == "127.0.0.1"
    assert call_kwargs.kwargs["port"] == 8000
    assert call_kwargs.kwargs["workers"] == 4  # ServerConfig default, not CLI default


@_patch_uvicorn_run
def test_serve_with_preset(mock_run):
    """serve --preset=gentle exits 0."""
    result = runner.invoke(app, ["serve", "--preset=gentle"])
    assert result.exit_code == 0, result.output


@_patch_uvicorn_run
def test_serve_with_config_file(mock_run, tmp_path):
    """serve --config with a valid yaml file exits 0."""
    cfg = tmp_path / "test.yaml"
    cfg.write_text(yaml.dump({"error_injection": {"rate_limit_pct": 42.0}}))
    result = runner.invoke(app, ["serve", "--config", str(cfg)])
    assert result.exit_code == 0, result.output


@_patch_uvicorn_run
def test_serve_preset_plus_overrides(mock_run):
    """serve --preset=gentle --rate-limit-pct=50 exits 0."""
    result = runner.invoke(app, ["serve", "--preset=gentle", "--rate-limit-pct=50"])
    assert result.exit_code == 0, result.output


@_patch_uvicorn_run
def test_serve_all_error_flags(mock_run):
    """serve with all 5 error percentage flags exits 0."""
    result = runner.invoke(
        app,
        [
            "serve",
            "--rate-limit-pct=5",
            "--capacity-529-pct=3",
            "--service-unavailable-pct=2",
            "--internal-error-pct=1",
            "--timeout-pct=4",
        ],
    )
    assert result.exit_code == 0, result.output


@_patch_uvicorn_run
def test_serve_error_summary_shows_all_pct_fields(mock_run):
    """Startup summary includes all non-zero _pct fields, not just a hardcoded subset."""
    result = runner.invoke(
        app,
        [
            "serve",
            "--rate-limit-pct=10",
            "--timeout-pct=50",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "rate_limit:10.0%" in result.output
    assert "timeout:50.0%" in result.output


@_patch_uvicorn_run
def test_serve_burst_flags(mock_run):
    """serve with burst flags exits 0."""
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


@_patch_uvicorn_run
def test_serve_latency_flags(mock_run):
    """serve with latency flags exits 0."""
    result = runner.invoke(app, ["serve", "--base-ms=100", "--jitter-ms=20"])
    assert result.exit_code == 0, result.output


@_patch_uvicorn_run
def test_serve_response_mode_flag(mock_run):
    """serve --response-mode=echo exits 0."""
    result = runner.invoke(app, ["serve", "--response-mode=echo"])
    assert result.exit_code == 0, result.output


@_patch_uvicorn_run
def test_serve_selection_mode_flag(mock_run):
    """serve --selection-mode=weighted exits 0."""
    result = runner.invoke(app, ["serve", "--selection-mode=weighted"])
    assert result.exit_code == 0, result.output


@_patch_uvicorn_run
def test_serve_workers_flag(mock_run):
    """serve --workers=4 passes workers=4 to uvicorn."""
    result = runner.invoke(app, ["serve", "--workers=4"])
    assert result.exit_code == 0, result.output
    mock_run.assert_called_once()
    assert mock_run.call_args.kwargs["workers"] == 4


@_patch_uvicorn_run
def test_serve_custom_host_port(mock_run):
    """serve --host=10.0.0.1 --port=9999 passes through to uvicorn."""
    result = runner.invoke(app, ["serve", "--host=10.0.0.1", "--port=9999"])
    assert result.exit_code == 0, result.output
    mock_run.assert_called_once()
    assert mock_run.call_args.kwargs["host"] == "10.0.0.1"
    assert mock_run.call_args.kwargs["port"] == 9999


@_patch_uvicorn_run
def test_serve_custom_database(mock_run, tmp_path):
    """serve --database with a custom path exits 0."""
    db_path = str(tmp_path / "custom-metrics.db")
    result = runner.invoke(app, ["serve", f"--database={db_path}"])
    assert result.exit_code == 0, result.output


def test_serve_invalid_preset():
    """serve --preset=nonexistent exits 1."""
    result = runner.invoke(app, ["serve", "--preset=nonexistent"])
    assert result.exit_code == 1


def test_serve_invalid_yaml_config(tmp_path):
    """serve with a file containing valid YAML but invalid config exits 1."""
    cfg = tmp_path / "bad.yaml"
    cfg.write_text(yaml.dump({"error_injection": "not a dict"}))
    result = runner.invoke(app, ["serve", "--config", str(cfg)])
    assert result.exit_code == 1


def test_serve_validation_error():
    """serve --rate-limit-pct=200 fails validation, exits non-zero.

    Typer enforces max=100.0 on the option, so this is rejected at the CLI
    argument parsing level rather than Pydantic. Either way, it should not
    succeed.
    """
    result = runner.invoke(app, ["serve", "--rate-limit-pct=200"])
    assert result.exit_code != 0


@_patch_uvicorn_run
def test_serve_no_burst(mock_run):
    """serve --no-burst exits 0."""
    result = runner.invoke(app, ["serve", "--no-burst"])
    assert result.exit_code == 0, result.output


def test_serve_invalid_selection_mode():
    """serve --selection-mode=bogus exits 1 (Pydantic rejects the value)."""
    result = runner.invoke(app, ["serve", "--selection-mode=bogus"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# CLI flag propagation tests (verify flags reach the server config)
# ---------------------------------------------------------------------------


@_patch_uvicorn_run
def test_cli_flags_propagate_to_server_config(mock_run):
    """CLI flags actually modify the server config, not just exit 0."""
    result = runner.invoke(
        app,
        [
            "serve",
            "--rate-limit-pct=42",
            "--timeout-pct=7",
            "--selection-mode=weighted",
            "--base-ms=200",
            "--jitter-ms=50",
            "--response-mode=echo",
        ],
    )
    assert result.exit_code == 0, result.output

    # Extract the app passed to uvicorn.run and get the server from app.state
    uvicorn_app = mock_run.call_args.args[0]
    server = uvicorn_app.state.server
    ei = server._error_injector.config
    assert ei.rate_limit_pct == 42.0
    assert ei.timeout_pct == 7.0
    assert ei.selection_mode == "weighted"

    lat = server._latency_simulator.config
    assert lat.base_ms == 200
    assert lat.jitter_ms == 50

    assert server._response_generator.config.mode == "echo"


@_patch_uvicorn_run
def test_preset_values_not_overridden_by_cli_defaults(mock_run):
    """Preset workers=4 is preserved when no --workers flag is given."""
    result = runner.invoke(app, ["serve", "--preset=gentle"])
    assert result.exit_code == 0, result.output

    uvicorn_app = mock_run.call_args.args[0]
    server = uvicorn_app.state.server
    # gentle preset sets workers=4 — CLI should NOT override to 1
    assert mock_run.call_args.kwargs["workers"] == 4


# ---------------------------------------------------------------------------
# presets command tests
# ---------------------------------------------------------------------------


def test_presets_lists_all():
    """presets command output contains all 6 expected preset names."""
    result = runner.invoke(app, ["presets"])
    assert result.exit_code == 0, result.output
    expected = {"chaos", "gentle", "realistic", "silent", "stress_aimd", "stress_extreme"}
    for name in expected:
        assert name in result.output, f"Missing preset: {name}"


def test_presets_sorted():
    """presets command lists names in alphabetical order."""
    result = runner.invoke(app, ["presets"])
    assert result.exit_code == 0, result.output
    # Extract preset names from lines like "  - name"
    names = [line.strip().lstrip("- ") for line in result.output.splitlines() if line.strip().startswith("- ")]
    assert names == sorted(names), f"Presets not sorted: {names}"


# ---------------------------------------------------------------------------
# show-config command tests
# ---------------------------------------------------------------------------


def test_show_config_defaults_yaml():
    """show-config with defaults produces parseable YAML output."""
    result = runner.invoke(app, ["show-config"])
    assert result.exit_code == 0, result.output
    # The YAML output may contain Python-tagged tuples that safe_load rejects,
    # so use yaml.full_load which handles !!python/tuple tags.
    parsed = yaml.full_load(result.output)
    assert isinstance(parsed, dict)


def test_show_config_json_format():
    """show-config --format=json produces valid JSON."""
    result = runner.invoke(app, ["show-config", "--format=json"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert isinstance(parsed, dict)


def test_show_config_with_preset():
    """show-config --preset=gentle exits 0."""
    result = runner.invoke(app, ["show-config", "--preset=gentle"])
    assert result.exit_code == 0, result.output


def test_show_config_invalid_preset():
    """show-config --preset=nonexistent exits 1."""
    result = runner.invoke(app, ["show-config", "--preset=nonexistent"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# version flag
# ---------------------------------------------------------------------------


def test_version_flag():
    """serve --version exits 0 and output contains 'chaosllm'."""
    result = runner.invoke(app, ["serve", "--version"])
    assert result.exit_code == 0, result.output
    assert "chaosllm" in result.output.lower()


# ---------------------------------------------------------------------------
# MCP CLI tests
# ---------------------------------------------------------------------------


def test_mcp_main_calls_run_server(tmp_path):
    """MCP CLI must call run_server(), not the nonexistent serve().

    Regression test for T27: the CLI was calling mcp_server.serve(database)
    which raises AttributeError because the function is run_server().
    """
    db_file = tmp_path / "test-metrics.db"
    db_file.write_bytes(b"")  # Create empty file so path validation passes

    mock_run_server = AsyncMock()

    with patch(
        "errorworks.llm_mcp.server.run_server",
        mock_run_server,
    ):
        result = runner.invoke(mcp_app, ["--database", str(db_file)])

    assert result.exit_code == 0, f"CLI exited with error: {result.output}"
    mock_run_server.assert_called_once_with(str(db_file))


def test_mcp_no_database_found(tmp_path, monkeypatch):
    """MCP CLI with no --database and no default files exits 1."""
    # Change to a temp dir where no default db files exist
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(mcp_app, [])
    assert result.exit_code == 1


def test_mcp_database_not_exists():
    """MCP CLI with --database pointing to nonexistent file exits 1."""
    result = runner.invoke(mcp_app, ["--database=/nonexistent/path.db"])
    assert result.exit_code == 1
