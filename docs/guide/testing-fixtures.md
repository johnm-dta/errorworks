# Testing Fixtures Guide

Errorworks provides pytest fixtures for ChaosLLM, ChaosWeb, ChaosBlob, and ChaosSMTP. ChaosLLM, ChaosWeb, and ChaosBlob run in-process using Starlette's `TestClient`, so no real network sockets are opened for HTTP tests. ChaosSMTP uses an ephemeral loopback TCP socket because normal SMTP clients require a real socket and protocol session.

## Setup

Import the fixtures in your `conftest.py`:

```python
# tests/conftest.py
from tests.fixtures.chaosllm import chaosllm_server  # noqa: F401
from tests.fixtures.chaossmtp import chaossmtp_server  # noqa: F401
from tests.fixtures.chaosweb import chaosweb_server  # noqa: F401
from tests.fixtures.chaosblob import chaosblob  # noqa: F401
```

Register the custom markers to avoid pytest warnings:

```python
# tests/conftest.py (or pyproject.toml)
def pytest_configure(config):
    config.addinivalue_line("markers", "chaosllm: ChaosLLM server configuration")
    config.addinivalue_line("markers", "chaossmtp: ChaosSMTP server configuration")
    config.addinivalue_line("markers", "chaosweb: ChaosWeb server configuration")
    config.addinivalue_line("markers", "chaosblob: ChaosBlob server configuration")
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

## ChaosBlob Fixture

### Basic Usage

```python
def test_object_round_trip(chaosblob):
    """Test a simple object-storage round trip."""
    put = chaosblob.put_object(
        "bucket",
        "incoming/item.json",
        b'{"id": 1}',
        headers={"content-type": "application/json"},
    )
    assert put.status_code == 200

    get = chaosblob.get_object("bucket", "incoming/item.json")
    assert get.status_code == 200
    assert get.json() == {"id": 1}
    assert get.headers["etag"] == put.headers["etag"]
```

### Marker-Based Configuration

```python
import pytest

@pytest.mark.chaosblob(preset="silent", slow_down_pct=100.0)
def test_blob_retry_on_slow_down(chaosblob):
    """Test that the pipeline handles object-store throttling."""
    response = chaosblob.put_object("bucket", "key", b"data")
    assert response.status_code == 503
    assert "retry-after" in response.headers

    chaosblob.update_config(slow_down_pct=0.0)
    assert chaosblob.put_object("bucket", "key", b"data").status_code == 200
```

### Available Marker Kwargs

The `chaosblob` marker accepts these keyword arguments:

| Kwarg | Type | Description |
|---|---|---|
| `preset` | str | Base preset name (`silent`, `gentle`, `realistic`, etc.) |
| `slow_down_pct` | float | S3 SlowDown percentage |
| `access_denied_pct` | float | 403 AccessDenied percentage |
| `not_found_pct` | float | 404 NoSuchKey percentage |
| `service_unavailable_pct` | float | 503 ServiceUnavailable percentage |
| `internal_error_pct` | float | 500 InternalError percentage |
| `bad_gateway_pct` | float | 502 BadGateway percentage |
| `gateway_timeout_pct` | float | 504 GatewayTimeout percentage |
| `timeout_pct` | float | Timeout percentage |
| `connection_reset_pct` | float | Connection reset percentage |
| `connection_stall_pct` | float | Connection stall percentage |
| `slow_response_pct` | float | Slow response percentage |
| `truncated_body_pct` | float | Truncated object body percentage |
| `wrong_content_length_pct` | float | Wrong Content-Length percentage |
| `checksum_mismatch_pct` | float | ETag/checksum mismatch percentage |
| `metadata_corruption_pct` | float | Metadata corruption percentage |
| `stale_list_pct` | float | Stale list response percentage |
| `malformed_xml_pct` | float | Malformed XML response percentage |
| `selection_mode` | str | `priority` or `weighted` |
| `base_ms` | int | Base latency in milliseconds |
| `jitter_ms` | int | Latency jitter in milliseconds |
| `max_object_bytes` | int | Maximum stored object size |

Unknown marker kwargs fail fast so misspelled settings do not silently turn into happy-path tests.

!!! note
    The fixture sets `base_ms=0` and `jitter_ms=0` by default so tests run without artificial delays. If you need latency simulation, set these explicitly in the marker.

### Fixture Helpers

The `ChaosBlobFixture` object provides:

| Method/Property | Description |
|---|---|
| `put_object(bucket, key, body, headers=...)` | PUT object bytes |
| `get_object(bucket, key, headers=...)` | GET object bytes |
| `head_object(bucket, key, headers=...)` | HEAD object metadata |
| `delete_object(bucket, key)` | DELETE an object |
| `list_objects(bucket, prefix="", max_keys=1000)` | List objects through `ListObjectsV2` |
| `get_stats()` | Get metrics summary |
| `export_metrics()` | Export raw metrics data |
| `update_config(slow_down_pct=..., updates=..., ...)` | Update config at runtime |
| `reset()` | Reset metrics, stored objects, and start a new run |
| `wait_for_requests(count, timeout=10.0)` | Block until N requests recorded |
| `run_id` | Current run ID |
| `base_url` | Base URL (`http://testserver`) |
| `admin_headers` | Dict with auth headers for admin endpoints |

## ChaosSMTP Fixture

The `chaossmtp_server` fixture starts a real SMTP listener on `127.0.0.1` with `smtp.port=0`, so the operating system assigns an ephemeral port. This keeps tests isolated while still exercising standard clients like `smtplib`.

### Basic Usage

```python
from email.message import EmailMessage

def test_sends_message(chaossmtp_server):
    message = EmailMessage()
    message["From"] = "sender@example.com"
    message["To"] = "recipient@example.com"
    message["Subject"] = "Fixture test"
    message.set_content("hello")

    assert chaossmtp_server.send_message(message) == {}
    assert chaossmtp_server.wait_for_messages(1)
    assert chaossmtp_server.get_stats()["total_requests"] == 1
```

### Marker-Based Configuration

```python
from email.message import EmailMessage
import pytest
import smtplib

@pytest.mark.chaossmtp(rcpt_to_reject_pct=100.0)
def test_recipient_rejection(chaossmtp_server):
    message = EmailMessage()
    message["From"] = "sender@example.com"
    message["To"] = "recipient@example.com"
    message["Subject"] = "Rejected"
    message.set_content("hello")

    with pytest.raises(smtplib.SMTPRecipientsRefused):
        chaossmtp_server.send_message(message)
```

### Available Marker Kwargs

The `chaossmtp` marker accepts these keyword arguments:

| Kwarg | Type | Description |
|---|---|---|
| `preset` | str | Base preset name (`silent`, `gentle`, `realistic`, `stress_delivery`, `stress_extreme`) |
| `rate_limit_pct` | float | SMTP rate limit percentage |
| `mail_from_tempfail_pct` | float | MAIL FROM temporary failure percentage |
| `mail_from_reject_pct` | float | MAIL FROM permanent rejection percentage |
| `rcpt_to_tempfail_pct` | float | RCPT TO temporary failure percentage |
| `rcpt_to_reject_pct` | float | RCPT TO permanent rejection percentage |
| `data_tempfail_pct` | float | DATA temporary failure percentage |
| `data_reject_pct` | float | DATA permanent rejection percentage |
| `accept_then_drop_pct` | float | Accept message and drop without capture percentage |
| `banner_reject_pct` | float | Banner-stage rejection config field; current listener does not invoke CONNECT-stage injection |
| `malformed_reply_pct` | float | Malformed SMTP reply percentage |
| `wrong_reply_code_pct` | float | Unexpected SMTP reply code percentage |
| `connection_reset_pct` | float | SMTP transport close percentage |
| `connection_stall_pct` | float | Stall then close percentage |
| `slow_response_pct` | float | Slow response percentage |
| `retry_after_sec` | tuple[int, int] | Validated retry range config; current SMTP replies do not emit a Retry-After header |
| `connection_stall_sec` | tuple[int, int] | Stall duration range |
| `slow_response_sec` | tuple[int, int] | Slow response delay range |
| `selection_mode` | str | `priority` or `weighted` |
| `base_ms` | int | Base latency in milliseconds |
| `jitter_ms` | int | Latency jitter in milliseconds |
| `capture_mode` | str | Capture mode (`discard`, `metadata`, `full`) |
| `max_message_bytes` | int | Maximum bytes stored in `full` capture mode |

!!! note
    The fixture sets `smtp.port=0`, `base_ms=0`, `jitter_ms=0`, and a deterministic admin token by default. If you need latency simulation, set latency explicitly in the marker.

### Fixture Helpers

The `ChaosSMTPFixture` object provides:

| Method/Property | Description |
|---|---|
| `send_message(message)` | Send an `EmailMessage` with `smtplib.SMTP` |
| `get_stats()` | Get metrics summary |
| `export_metrics()` | Export raw metrics data and captured messages |
| `update_config(rcpt_to_tempfail_pct=..., capture_mode=..., ...)` | Update runtime config |
| `reset()` | Reset metrics and captured messages |
| `wait_for_requests(count, timeout=10.0)` | Block until N SMTP transactions are recorded |
| `wait_for_messages(count, timeout=10.0)` | Block until N messages are captured |
| `host` | Bound SMTP host |
| `port` | Ephemeral SMTP port |
| `metrics_db` | File-backed SQLite metrics path for this test |
| `run_id` | Current run ID |

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

### ChaosBlob: Testing Blob Pipeline Recovery

```python
import pytest

@pytest.mark.chaosblob(preset="silent")
def test_blob_pipeline_handles_slow_down(chaosblob):
    """Verify a blob pipeline can retry after object-store throttling."""
    chaosblob.put_object("bucket", "incoming/1.json", b'{"id": 1}')
    chaosblob.update_config(slow_down_pct=100.0, updates={"error_injection": {"retry_after_sec": [0, 0]}})

    response = chaosblob.get_object("bucket", "incoming/1.json")
    assert response.status_code == 503
    assert response.headers["retry-after"] == "0"

    chaosblob.update_config(slow_down_pct=0.0)
    response = chaosblob.get_object("bucket", "incoming/1.json")
    assert response.status_code == 200
    assert response.json() == {"id": 1}

    stats = chaosblob.get_stats()
    assert stats["total_requests"] == 3
```

### ChaosSMTP: Testing Delivery Failures

```python
from email.message import EmailMessage
import pytest
import smtplib

def _message():
    message = EmailMessage()
    message["From"] = "sender@example.com"
    message["To"] = "recipient@example.com"
    message["Subject"] = "Delivery test"
    message.set_content("hello")
    return message

@pytest.mark.chaossmtp(data_reject_pct=100.0)
def test_data_rejection(chaossmtp_server):
    """Verify behavior when every DATA command is rejected."""
    with pytest.raises(smtplib.SMTPDataError) as exc_info:
        chaossmtp_server.send_message(_message())
    assert exc_info.value.smtp_code == 554

def test_capture_metadata(chaossmtp_server):
    """Verify accepted messages are captured as metadata by default."""
    assert chaossmtp_server.send_message(_message()) == {}
    assert chaossmtp_server.wait_for_messages(1)
    exported = chaossmtp_server.export_metrics()
    assert exported["messages"][0]["subject"] == "Delivery test"
```

## How It Works

The ChaosLLM and ChaosWeb fixtures use Starlette's `TestClient`, which wraps the ASGI application and routes HTTP calls through the stack without opening a network socket. This means:

- **No port conflicts** -- multiple tests can run in parallel
- **No startup delay** -- the server is ready immediately
- **Full fidelity** -- the same request handling code runs as in production
- **Isolated state** -- each test gets a fresh server instance via `tmp_path`

The ChaosSMTP fixture uses the same configuration pattern, but it starts a real `aiosmtpd` listener on an ephemeral loopback port. That keeps tests close to production SMTP client behavior while avoiding fixed-port conflicts.

The `_build_config_from_marker()` function translates marker kwargs into a `ChaosLLMConfig`, `ChaosWebConfig`, `ChaosBlobConfig`, or `ChaosSMTPConfig` object. It applies the same precedence rules as the CLI: marker kwargs override the preset, and the fixture always forces latency to zero and sets a deterministic admin token for test convenience.

## Related Pages

- [ChaosLLM](chaosllm.md) -- Error types and response modes
- [ChaosWeb](chaosweb.md) -- Error types and content modes
- [ChaosBlob](chaosblob.md) -- Object-storage error types and fixture helpers
- [ChaosSMTP](chaossmtp.md) -- SMTP listener, error types, and capture modes
- [Metrics](metrics.md) -- Understanding metrics data in tests
- [Configuration](configuration.md) -- How configuration precedence works
