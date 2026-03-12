# Plan 02 — Integration Test Layer

**Parent:** [00-test-remediation-overview.md](00-test-remediation-overview.md)
**Priority:** Medium
**Target directory:** `tests/integration/` (new)

## Context

The existing unit tests exercise components in isolation. The `test_server.py` files
come closest to integration testing — they use Starlette's `TestClient` to send real
HTTP requests — but they construct configs programmatically, skipping the
preset-loading and config-merging pipeline.

The gap: no test validates the full path from a YAML preset file through
`load_config()` → server construction → HTTP request → chaos response.

## Goal

Validate that the **composition seams** work: config loading feeds valid config
to servers, servers produce the expected chaos behavior, and metrics are recorded.

## Directory Structure

```
tests/
├── integration/
│   ├── __init__.py
│   ├── conftest.py            # shared helpers (assert_rate_near, etc.)
│   ├── test_llm_pipeline.py   # ~8 tests
│   ├── test_web_pipeline.py   # ~8 tests
│   └── test_mcp_pipeline.py   # ~4 tests
├── unit/
│   └── ...  (existing)
└── ...
```

Add a pytest marker in `pyproject.toml`:

```toml
markers = [
    ...
    "integration: marks tests as integration tests",
]
```

**Default run behavior:** Integration tests run in the default `pytest` invocation.
They should be fast enough (<5s total) to not need exclusion. If statistical tests
prove too slow, move them behind `@pytest.mark.slow` rather than excluding all
integration tests.

## Test Matrix — LLM Pipeline (`test_llm_pipeline.py`)

These tests load real presets, build real servers, and make real HTTP requests
via `TestClient`. No mocks.

| Test | Pipeline coverage |
|------|-------------------|
| `test_silent_preset_returns_200` | Load `silent` preset → server → POST `/v1/chat/completions` → always 200 |
| `test_gentle_preset_injects_errors` | Load `gentle` preset → 500 requests → total error rate ≈ 2% (±3%). The `gentle.yaml` sums to 2%: `rate_limit_pct=1.0` + `capacity_529_pct=0.5` + `service_unavailable_pct=0.5` |
| `test_stress_extreme_injects_heavily` | Load `stress_extreme` → 100 requests → majority are errors |
| `test_preset_plus_config_file_merge` | Preset + YAML overlay → verify merged config takes effect |
| `test_streaming_response_format` | Preset → streaming request → SSE format with `data:` lines |
| `test_metrics_recorded_after_requests` | 10 requests → GET `/admin/stats` → counts match |
| `test_config_reload_endpoint` | POST new config to `/admin/config` → subsequent requests use new rates |
| `test_azure_endpoint_compatibility` | Same preset → POST to `/openai/deployments/{deployment}/chat/completions` → valid response |

## Test Matrix — Web Pipeline (`test_web_pipeline.py`)

| Test | Pipeline coverage |
|------|-------------------|
| `test_silent_preset_returns_html` | `silent` preset → GET `/` → 200 with valid HTML |
| `test_gentle_preset_injects_errors` | `gentle` → 500 requests → total error rate ≈ 2% (±3%). Web `gentle.yaml` sums to 2%: `rate_limit_pct=1.0` + `not_found_pct=1.0` |
| `test_stress_scraping_anti_bot` | `stress_scraping` → high error rates, redirects present |
| `test_preset_plus_config_file_merge` | Preset + YAML overlay → merged config |
| `test_content_structure` | Request → HTML has `<html>`, `<head>`, `<body>`, links |
| `test_metrics_recorded` | 10 requests → GET `/admin/stats` → counts reflect requests |
| `test_redirect_deterministic` | Config with `ssrf_redirect_pct=100` → every request gets redirect response |
| `test_malformed_html_injection` | Config with malformed HTML enabled → response has broken tags |

## Test Matrix — MCP Pipeline (`test_mcp_pipeline.py`)

| Test | Pipeline coverage |
|------|-------------------|
| `test_analyze_with_real_metrics_db` | Populate DB → create MCP analyzer → call tool → valid analysis |
| `test_error_rate_tool_matches_recorded` | Record known requests → query error rate → matches expectations |
| `test_empty_database_returns_no_data` | Empty DB → tool returns appropriate "no data" response |
| `test_time_series_tool` | Record requests over time → query series → buckets present |

## Implementation Patterns

### Basic Pipeline Test

```python
import pytest
from starlette.testclient import TestClient

from errorworks.llm.config import load_config
from errorworks.llm.server import create_app


class TestLLMPipeline:
    """Integration tests: preset → config → server → HTTP."""

    @pytest.mark.integration
    def test_silent_preset_returns_200(self):
        """Silent preset should never inject errors."""
        config = load_config(preset="silent")
        app = create_app(config)
        client = TestClient(app)

        for _ in range(50):
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "model": "test",
                    "messages": [{"role": "user", "content": "hello"}],
                },
            )
            assert resp.status_code == 200
```

### Config Reload Test

The config reload endpoint is `POST /admin/config` with a JSON body. The server
calls `update_config(body)` which creates a new frozen Pydantic config instance.

```python
@pytest.mark.integration
def test_config_reload_endpoint(self):
    """POST to /admin/config should update behavior for subsequent requests."""
    config = load_config(preset="silent")
    app = create_app(config)
    client = TestClient(app)

    # Verify initially silent (no errors)
    resp = client.post("/v1/chat/completions", json=CHAT_BODY)
    assert resp.status_code == 200

    # Reload with 100% rate limiting
    client.post("/admin/config", json={
        "error_injection": {"rate_limit_pct": 100.0}
    })

    # Now every request should be rate-limited
    resp = client.post("/v1/chat/completions", json=CHAT_BODY)
    assert resp.status_code == 429
```

### Redirect Test (Web — Deterministic)

To test redirects deterministically, set `ssrf_redirect_pct=100` via config
overlay rather than relying on probabilistic injection:

```python
@pytest.mark.integration
def test_redirect_deterministic(self):
    """With ssrf_redirect_pct=100, every request should redirect."""
    config = load_config(
        preset="silent",
        cli_overrides={"error_injection": {"ssrf_redirect_pct": 100.0}},
    )
    app = create_app(config)
    client = TestClient(app, follow_redirects=False)

    resp = client.get("/")
    assert resp.status_code in (301, 302, 307, 308)
```

### MCP Database Setup

The MCP server reads from a SQLite database. Use `MetricsStore` to populate a
real database file, then pass it to the MCP analyzer:

```python
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from errorworks.llm.metrics import MetricsRecorder
from errorworks.llm_mcp.server import create_server


@pytest.mark.integration
def test_analyze_with_real_metrics_db(tmp_path):
    """MCP analyzer should return valid analysis from a real metrics DB."""
    db_path = tmp_path / "metrics.db"
    recorder = MetricsRecorder(str(db_path))

    # Record known requests via the domain-specific recorder
    for i in range(20):
        recorder.record_request(
            request_id=str(uuid4()),
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            endpoint="/v1/chat/completions",
            outcome="success" if i < 18 else "error",
            status_code=200 if i < 18 else 429,
            error_type=None if i < 18 else "rate_limit",
            latency_ms=50.0,
        )

    # Create MCP server pointing at this DB and call the analysis tool
    mcp = create_server(database_path=str(db_path))
    # ... invoke tool and assert results
```

**Note:** `MetricsStore` only exposes a generic `record(**kwargs)` method.
Use the domain-specific `MetricsRecorder` (LLM) or `WebMetricsRecorder` (Web)
wrappers for the `record_request()` API. The `create_server()` function lives
in `errorworks.llm_mcp.server` (not `create_mcp_server`).

### Shared Fixtures (`conftest.py`)

Define reusable constants and helpers in `tests/integration/conftest.py`:

```python
# Standard chat completion body for LLM tests
CHAT_BODY = {
    "model": "test",
    "messages": [{"role": "user", "content": "hello"}],
}
```

This constant is referenced by multiple test patterns above.

## Statistical Tests

For tests that validate error rates, use tolerant assertions. Place this helper
in `tests/integration/conftest.py`:

```python
def assert_rate_near(actual_count: int, total: int, expected_pct: float, tolerance_pct: float = 3.0) -> None:
    """Assert observed rate is within tolerance of expected."""
    actual_pct = (actual_count / total) * 100
    assert abs(actual_pct - expected_pct) <= tolerance_pct, (
        f"Expected ~{expected_pct}%, got {actual_pct}% "
        f"({actual_count}/{total})"
    )
```

Use 500 requests for statistical tests (not 1000) to stay within the speed budget.
At 500 requests with a 2% expected rate, the 95% CI is roughly ±1.2%, so a ±3%
tolerance gives ample headroom while keeping runtime reasonable.

## What NOT to Test

- Individual error type behavior (covered by unit tests)
- Config validation rules (covered by `test_config.py`)
- Response content details (covered by `test_response_generator.py` / `test_content_generator.py`)
- Thread safety (covered by unit tests)
