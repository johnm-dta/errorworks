# Testing Fixtures Guide

Errorworks provides pytest fixtures that run ChaosLLM and ChaosWeb servers in-process using Starlette's `TestClient`. No real network sockets are opened -- requests go directly through the ASGI stack, making tests fast, isolated, and safe to run in parallel.

## Setup

Import the fixtures in your `conftest.py`:

```python
# tests/conftest.py
from tests.fixtures.chaosllm import chaosllm_server  # noqa: F401
from tests.fixtures.chaosweb import chaosweb_server  # noqa: F401
```

Register the custom markers to avoid pytest warnings:

```python
# tests/conftest.py (or pyproject.toml)
def pytest_configure(config):
    config.addinivalue_line("markers", "chaosllm: ChaosLLM server configuration")
    config.addinivalue_line("markers", "chaosweb: ChaosWeb server configuration")
```

## ChaosLLM Fixture

### Basic Usage

```python
def test_successful_completion(chaosllm_server):
    """Test that completions work with no error injection."""
    response = chaosllm_server.post_completion(
        messages=[{"role": "user", "content": "Hello"}],
        model="gpt-4",
    )
    assert response.status_code == 200
    data = response.json()
    assert "choices" in data
    assert data["choices"][0]["message"]["content"]
```

### Marker-Based Configuration

Use `@pytest.mark.chaosllm(...)` to configure the server for a specific test:

```python
import pytest

@pytest.mark.chaosllm(preset="realistic", rate_limit_pct=25.0)
def test_rate_limit_handling(chaosllm_server):
    """Test that the pipeline handles rate limits."""
    errors = 0
    for _ in range(100):
        response = chaosllm_server.post_completion()
        if response.status_code == 429:
            errors += 1
    # With 25% rate limiting, expect roughly 25 errors out of 100
    assert errors > 10
```

### Available Marker Kwargs

The `chaosllm` marker accepts these keyword arguments:

| Kwarg | Type | Description |
|---|---|---|
| `preset` | str | Base preset name (`silent`, `gentle`, `realistic`, etc.) |
| `rate_limit_pct` | float | 429 Rate Limit percentage |
| `capacity_529_pct` | float | 529 Capacity error percentage |
| `service_unavailable_pct` | float | 503 Service Unavailable percentage |
| `bad_gateway_pct` | float | 502 Bad Gateway percentage |
| `gateway_timeout_pct` | float | 504 Gateway Timeout percentage |
| `internal_error_pct` | float | 500 Internal Server Error percentage |
| `timeout_pct` | float | Timeout (hang) percentage |
| `connection_reset_pct` | float | Connection reset percentage |
| `connection_failed_pct` | float | Connection failed percentage |
| `connection_stall_pct` | float | Connection stall percentage |
| `slow_response_pct` | float | Slow response percentage |
| `invalid_json_pct` | float | Invalid JSON response percentage |
| `truncated_pct` | float | Truncated response percentage |
| `empty_body_pct` | float | Empty body response percentage |
| `missing_fields_pct` | float | Missing fields response percentage |
| `wrong_content_type_pct` | float | Wrong Content-Type percentage |
| `forbidden_pct` | float | 403 Forbidden percentage |
| `not_found_pct` | float | 404 Not Found percentage |
| `selection_mode` | str | `priority` or `weighted` |
| `base_ms` | int | Base latency in milliseconds |
| `jitter_ms` | int | Latency jitter in milliseconds |
| `mode` | str | Response mode (`random`, `template`, `echo`, `preset`) |

!!! note
    The fixture sets `base_ms=0` and `jitter_ms=0` by default so tests run without artificial delays. If you need latency simulation, set these explicitly in the marker.

### Fixture Helpers

The `ChaosLLMFixture` object provides:

| Method/Property | Description |
|---|---|
| `post_completion(messages=..., model=..., **kwargs)` | POST to `/v1/chat/completions` |
| `post_azure_completion(deployment, messages=..., **kwargs)` | POST to Azure endpoint |
| `get_stats()` | Get metrics summary (same as `/admin/stats`) |
| `export_metrics()` | Export raw metrics data |
| `update_config(rate_limit_pct=..., ...)` | Update config at runtime |
| `reset()` | Reset metrics and start new run |
| `wait_for_requests(count, timeout=10.0)` | Block until N requests recorded |
| `run_id` | Current run ID |
| `url` | Base URL (`http://testserver`) |
| `admin_headers` | Dict with auth headers for admin endpoints |

### Azure Endpoint Testing

```python
def test_azure_deployment(chaosllm_server):
    """Test Azure OpenAI endpoint compatibility."""
    response = chaosllm_server.post_azure_completion(
        deployment="my-gpt4-deployment",
        messages=[{"role": "user", "content": "Hello"}],
        api_version="2024-02-01",
    )
    assert response.status_code == 200
```

## ChaosWeb Fixture

### Basic Usage

```python
def test_page_fetch(chaosweb_server):
    """Test that pages load successfully."""
    response = chaosweb_server.fetch_page("/articles/test")
    assert response.status_code == 200
    assert "html" in response.text.lower()
```

### Marker-Based Configuration

```python
import pytest

@pytest.mark.chaosweb(preset="stress_scraping", rate_limit_pct=25.0)
def test_scraper_resilience(chaosweb_server):
    """Test scraper handles rate limiting under stress."""
    success = 0
    for _ in range(50):
        response = chaosweb_server.fetch_page("/articles/test")
        if response.status_code == 200:
            success += 1
    assert success > 0  # At least some succeed
```

### Available Marker Kwargs

The `chaosweb` marker accepts these keyword arguments:

| Kwarg | Type | Description |
|---|---|---|
| `preset` | str | Base preset name |
| `rate_limit_pct` | float | 429 Rate Limit percentage |
| `forbidden_pct` | float | 403 Forbidden percentage |
| `not_found_pct` | float | 404 Not Found percentage |
| `gone_pct` | float | 410 Gone percentage |
| `payment_required_pct` | float | 402 Payment Required percentage |
| `unavailable_for_legal_pct` | float | 451 Unavailable for Legal Reasons percentage |
| `service_unavailable_pct` | float | 503 Service Unavailable percentage |
| `bad_gateway_pct` | float | 502 Bad Gateway percentage |
| `gateway_timeout_pct` | float | 504 Gateway Timeout percentage |
| `internal_error_pct` | float | 500 Internal Server Error percentage |
| `timeout_pct` | float | Timeout percentage |
| `connection_reset_pct` | float | Connection reset percentage |
| `connection_stall_pct` | float | Connection stall percentage |
| `slow_response_pct` | float | Slow response percentage |
| `incomplete_response_pct` | float | Incomplete response percentage |
| `wrong_content_type_pct` | float | Wrong Content-Type percentage |
| `encoding_mismatch_pct` | float | Encoding mismatch percentage |
| `truncated_html_pct` | float | Truncated HTML percentage |
| `invalid_encoding_pct` | float | Invalid encoding percentage |
| `charset_confusion_pct` | float | Charset confusion percentage |
| `malformed_meta_pct` | float | Malformed meta tag percentage |
| `redirect_loop_pct` | float | Redirect loop percentage |
| `ssrf_redirect_pct` | float | SSRF redirect percentage |
| `selection_mode` | str | `priority` or `weighted` |
| `base_ms` | int | Base latency in milliseconds |
| `jitter_ms` | int | Latency jitter in milliseconds |
| `content_mode` | str | Content mode (`random`, `template`, `echo`, `preset`) |

### Fixture Helpers

The `ChaosWebFixture` object provides:

| Method/Property | Description |
|---|---|
| `fetch_page(path="/", headers=..., follow_redirects=False)` | GET a page |
| `get_stats()` | Get metrics summary |
| `export_metrics()` | Export raw metrics data |
| `update_config(rate_limit_pct=..., ...)` | Update config at runtime |
| `reset()` | Reset metrics and start new run |
| `wait_for_requests(count, timeout=10.0)` | Block until N requests recorded |
| `run_id` | Current run ID |
| `base_url` | Base URL (`http://testserver`) |
| `admin_headers` | Dict with auth headers for admin endpoints |

## Complete Working Examples

### ChaosLLM: Testing Error Recovery

```python
import pytest

@pytest.mark.chaosllm(rate_limit_pct=100.0)
def test_all_requests_rate_limited(chaosllm_server):
    """Verify behavior when every request is rate limited."""
    response = chaosllm_server.post_completion()
    assert response.status_code == 429
    assert "Retry-After" in response.headers
    data = response.json()
    assert data["error"]["type"] == "rate_limit_error"


@pytest.mark.chaosllm(invalid_json_pct=100.0)
def test_malformed_json_handling(chaosllm_server):
    """Verify the client can detect invalid JSON responses."""
    response = chaosllm_server.post_completion()
    assert response.status_code == 200  # Malformed responses return 200
    # The body is not valid JSON
    try:
        response.json()
        assert False, "Expected JSON decode error"
    except Exception:
        pass  # Expected


def test_runtime_config_update(chaosllm_server):
    """Verify runtime config updates take effect."""
    # Start with no errors
    response = chaosllm_server.post_completion()
    assert response.status_code == 200

    # Enable 100% rate limiting
    chaosllm_server.update_config(rate_limit_pct=100.0)

    response = chaosllm_server.post_completion()
    assert response.status_code == 429

    # Check metrics
    stats = chaosllm_server.get_stats()
    assert stats["total_requests"] == 2


def test_metrics_tracking(chaosllm_server):
    """Verify metrics are recorded for each request."""
    for _ in range(10):
        chaosllm_server.post_completion()

    chaosllm_server.wait_for_requests(10)
    stats = chaosllm_server.get_stats()
    assert stats["total_requests"] == 10
    assert "latency_stats" in stats
```

### ChaosWeb: Testing Scraper Resilience

```python
import pytest

@pytest.mark.chaosweb(forbidden_pct=100.0)
def test_all_requests_blocked(chaosweb_server):
    """Verify behavior when bot detection blocks everything."""
    response = chaosweb_server.fetch_page("/articles/test")
    assert response.status_code == 403


@pytest.mark.chaosweb(encoding_mismatch_pct=100.0)
def test_encoding_mismatch_detection(chaosweb_server):
    """Verify the scraper detects encoding mismatches."""
    response = chaosweb_server.fetch_page("/articles/test")
    assert response.status_code == 200
    # Header says UTF-8 but body is ISO-8859-1
    assert "utf-8" in response.headers.get("content-type", "").lower()


@pytest.mark.chaosweb(redirect_loop_pct=100.0)
def test_redirect_loop_handling(chaosweb_server):
    """Verify the scraper detects redirect loops."""
    response = chaosweb_server.fetch_page("/articles/test")
    assert response.status_code == 301
    assert "Location" in response.headers
    # Without follow_redirects, you get the first redirect
    assert "/redirect?" in response.headers["Location"]


@pytest.mark.chaosweb(preset="realistic")
def test_realistic_scraping(chaosweb_server):
    """Test with realistic error distribution."""
    results = {"success": 0, "error": 0}
    for _ in range(100):
        response = chaosweb_server.fetch_page("/articles/test")
        if response.status_code == 200:
            results["success"] += 1
        else:
            results["error"] += 1
    # Realistic preset: ~80% success rate
    assert results["success"] > 50
```

## How It Works

The fixtures use Starlette's `TestClient`, which wraps the ASGI application and routes HTTP calls through the stack without opening a network socket. This means:

- **No port conflicts** -- multiple tests can run in parallel
- **No startup delay** -- the server is ready immediately
- **Full fidelity** -- the same request handling code runs as in production
- **Isolated state** -- each test gets a fresh server instance via `tmp_path`

The `_build_config_from_marker()` function translates marker kwargs into a `ChaosLLMConfig` or `ChaosWebConfig` object. It applies the same precedence rules as the CLI: marker kwargs override the preset, and the fixture always forces latency to zero and sets a deterministic admin token for test convenience.

## Related Pages

- [ChaosLLM](chaosllm.md) -- Error types and response modes
- [ChaosWeb](chaosweb.md) -- Error types and content modes
- [Metrics](metrics.md) -- Understanding metrics data in tests
- [Configuration](configuration.md) -- How configuration precedence works
