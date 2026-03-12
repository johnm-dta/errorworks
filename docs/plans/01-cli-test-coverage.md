# Plan 01 — CLI Test Coverage

**Parent:** [00-test-remediation-overview.md](00-test-remediation-overview.md)
**Priority:** High
**Target files:**
- `tests/unit/llm/test_cli.py` (exists, 1 test → ~24 tests)
- `tests/unit/web/test_cli.py` (new file, ~18 tests)

## Context

Both CLI modules use Typer with identical structural patterns:
- `serve` command — config loading, override assembly, uvicorn launch
- `presets` command — list available presets
- `show-config` command — dump effective config as YAML/JSON (Typer converts the Python name `show_config` to `show-config` on the CLI)
- `--version` flag — eager callback
- LLM additionally has `mcp_app` with `mcp_main` callback (Web does NOT have MCP)

The CLI modules are the thinnest layer — they translate flags into config dicts,
call `load_config()`, and hand off to uvicorn. Testing should focus on the
flag→config wiring and error handling, NOT on uvicorn actually binding a socket.

## Approach

Use Typer's `CliRunner` (already imported in `test_cli.py`). Mock only `uvicorn.run`
to prevent actual server startup. All config loading and validation runs for real.

## Test Matrix — LLM CLI (`tests/unit/llm/test_cli.py`)

### `serve` command

| Test | What it validates |
|------|-------------------|
| `test_serve_defaults` | Invoke `serve` with no flags; verify `uvicorn.run` called with default host=`127.0.0.1`, port=`8000`, workers=`1` |
| `test_serve_with_preset` | `--preset=gentle`; verify config loaded from preset YAML |
| `test_serve_with_config_file` | `--config=<tmp_yaml>`; verify file config applied |
| `test_serve_preset_plus_overrides` | `--preset=gentle --rate-limit-pct=50`; verify CLI flag wins |
| `test_serve_all_error_flags` | Pass every error flag (see **Full Error Flag List** below); verify each reaches the config |
| `test_serve_burst_flags` | `--burst-enabled --burst-interval-sec=10 --burst-duration-sec=2` |
| `test_serve_latency_flags` | `--base-ms=100 --jitter-ms=20` |
| `test_serve_response_mode_flag` | `--response-mode=echo` |
| `test_serve_selection_mode_flag` | `--selection-mode=weighted`; verify reaches config |
| `test_serve_workers_flag` | `--workers=4`; verify uvicorn.run receives `workers=4` |
| `test_serve_custom_host_port` | `--host=0.0.0.0 --port=9999` |
| `test_serve_custom_database` | `--database=/tmp/test.db` |
| `test_serve_invalid_preset` | `--preset=nonexistent`; verify exit code 1 (uses `raise typer.Exit(1)`) |
| `test_serve_invalid_yaml_config` | `--config=<malformed_yaml>`; verify exit code 1 |
| `test_serve_validation_error` | `--rate-limit-pct=200`; verify exit code 1 — **NOTE:** Typer does NOT range-check this flag; validation happens downstream in Pydantic's `ChaosLLMConfig`. Expect a `ValidationError` caught by the CLI's error handler, not a Typer argument error |

#### Full Error Flag List (LLM)

All of these must be covered by `test_serve_all_error_flags`:

- `--rate-limit-pct`
- `--capacity-529-pct`
- `--service-unavailable-pct`
- `--internal-error-pct`
- `--timeout-pct`

### `presets` command

| Test | What it validates |
|------|-------------------|
| `test_presets_lists_all` | Output contains all 6 preset names: `chaos`, `gentle`, `realistic`, `silent`, `stress_aimd`, `stress_extreme` |
| `test_presets_sorted` | Output is alphabetically sorted |

### `show-config` command

| Test | What it validates |
|------|-------------------|
| `test_show_config_defaults_yaml` | Default output is valid YAML |
| `test_show_config_json_format` | `--format=json` produces valid JSON |
| `test_show_config_with_preset` | `--preset=gentle` shows preset values |
| `test_show_config_invalid_preset` | Exit code 1 with error message |

### `--version` flag

| Test | What it validates |
|------|-------------------|
| `test_version_flag` | `--version` prints version string and exits 0 |

### MCP CLI (existing + new)

| Test | What it validates |
|------|-------------------|
| `test_mcp_main_calls_run_server` | (existing) Regression for correct function name |
| `test_mcp_no_database_found` | No `--database`, no default file; verify exit 1 |
| `test_mcp_database_not_exists` | `--database=/nonexistent`; verify exit 1 |

### Additional tests to consider

| Test | What it validates |
|------|-------------------|
| `test_serve_no_burst` | `--no-burst`; verify burst disabled (Typer generates `--no-burst` as negation of `--burst-enabled`) |
| `test_serve_invalid_selection_mode` | `--selection-mode=bogus`; verify exit code 1 — Typer accepts any string, Pydantic rejects downstream |

## Test Matrix — Web CLI (`tests/unit/web/test_cli.py`)

The Web CLI mirrors LLM structurally but has **no MCP subcommand** and different
error/content flags. This yields ~17 tests (not mirroring the 3 MCP tests).

| Test | Web-specific difference |
|------|------------------------|
| `test_serve_defaults` | Default port is `8200` (not `8000`), default host `127.0.0.1`, workers `1` |
| `test_serve_with_preset` | `--preset=gentle` from `web/presets/` |
| `test_serve_all_error_flags` | Web error flags: `--rate-limit-pct`, `--forbidden-pct`, `--not-found-pct`, `--ssrf-redirect-pct`, `--service-unavailable-pct`, `--internal-error-pct`, `--timeout-pct` |
| `test_serve_content_mode_flag` | `--content-mode=echo` (not `--response-mode`) |
| `test_serve_selection_mode_flag` | Same as LLM: `--selection-mode=weighted` |
| `test_serve_workers_flag` | Same as LLM: `--workers=4` |
| `test_presets_lists_all` | Lists 5 web presets: `gentle`, `realistic`, `silent`, `stress_extreme`, `stress_scraping` |
| `test_serve_custom_database` | `--database=/tmp/test.db`; verify reaches config (mirrors LLM) |
| All others | Structurally identical to LLM (no MCP tests) |

Mock target for Web: `@patch("errorworks.web.cli.uvicorn")`.

## Implementation Notes

### Mocking Strategy

```python
# Only mock uvicorn.run to prevent actual server startup
@patch("errorworks.llm.cli.uvicorn")  # NOT uvicorn directly — mock where it's imported
def test_serve_defaults(mock_uvicorn):
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 0
    mock_uvicorn.run.assert_called_once()
    call_kwargs = mock_uvicorn.run.call_args
    assert call_kwargs.kwargs["host"] == "127.0.0.1"
    assert call_kwargs.kwargs["port"] == 8000
    assert call_kwargs.kwargs["workers"] == 1
```

### Error Handling

The CLI catches config errors and calls `raise typer.Exit(1)`. Tests should check
`result.exit_code == 1` and optionally verify the error message appears in
`result.output`. Do NOT assert on specific exception types — the CLI catches and
converts them.

### Config File Tests

Use `tmp_path` fixture to create temporary YAML files:

```python
def test_serve_with_config_file(tmp_path, mock_uvicorn):
    config = tmp_path / "test.yaml"
    config.write_text("error_injection:\n  rate_limit_pct: 42.0\n")
    result = runner.invoke(app, ["serve", "--config", str(config)])
    assert result.exit_code == 0
```

### What NOT to Test

- Uvicorn actually binding to a port (that's uvicorn's responsibility)
- Starlette app behavior (covered by `test_server.py`)
- Config validation rules (covered by `test_config.py`)
- Preset file contents (covered by `test_config.py`)
