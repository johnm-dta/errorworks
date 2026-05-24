# Metrics Guide

Every request or SMTP transaction that passes through an Errorworks server is recorded in a SQLite database. You can query these metrics to understand error rates, latency distributions, and how your pipeline responds to injected faults.

## What Gets Recorded

Each request produces a row in the `requests` table with fields including:

| Field | Description |
|---|---|
| `request_id` | Unique ID for this request |
| `timestamp_utc` | ISO-8601 timestamp |
| `endpoint` / `path` | The requested URL path |
| `outcome` | `success`, `error_injected`, `error_malformed`, `error_redirect`, etc. |
| `status_code` | HTTP status code returned (NULL for connection-level errors) |
| `error_type` | Specific error injected (e.g., `rate_limit`, `timeout`, `malformed_truncated`) |
| `injection_type` | Category of injection applied |
| `latency_ms` | Total request duration in milliseconds |
| `injected_delay_ms` | Artificial delay added (latency simulation + slow response) |

ChaosLLM additionally records:

| Field | Description |
|---|---|
| `model` | Requested model name (as sent by client, not fabricated) |
| `deployment` | Azure deployment name (if using Azure endpoint) |
| `message_count` | Number of messages in the chat request |
| `prompt_tokens_approx` | Approximate prompt token count |
| `response_tokens` | Response token count |
| `response_mode` | Content generation mode used (`random`, `template`, `echo`, `preset`) |

ChaosWeb additionally records:

| Field | Description |
|---|---|
| `content_type_served` | Content-Type header returned |
| `encoding_served` | Actual encoding used (for encoding mismatch errors) |
| `redirect_target` | SSRF redirect destination URL |
| `redirect_hops` | Number of hops in redirect chain |

ChaosSMTP additionally records:

| Field | Description |
|---|---|
| `transaction_id` | Unique ID for the SMTP transaction |
| `session_id` | Server-side SMTP session identifier |
| `client_addr` | Remote SMTP client address |
| `mail_from` | Envelope sender |
| `rcpt_count` | Number of recipients |
| `rcpt_domains` | JSON list of recipient domains |
| `message_size_bytes` | SMTP DATA size in bytes |
| `subject` | Captured Subject header when capture mode records metadata |
| `smtp_stage` | Stage where the outcome happened: `mail`, `rcpt`, `data`, or `accept` |
| `reply_code` | SMTP reply code, when one was sent |
| `enhanced_status_code` | Enhanced status code parsed from the reply text, such as `4.3.0` |
| `error_type` | Specific SMTP fault injected |
| `capture_mode` | `discard`, `metadata`, or `full` |
| `tls_used` | Whether the SMTP session used TLS |
| `auth_username` | Authenticated username when supplied by the SMTP session |

SMTP outcomes include:

| Outcome | Meaning |
|---|---|
| `success` | Message was accepted and captured according to `capture.mode` |
| `tempfailed` | A 4xx SMTP reply was injected |
| `permfailed` | A 5xx SMTP reply was injected |
| `connection_error` | The SMTP transport was closed or stalled |
| `malformed_protocol` | A malformed reply or unexpected code was injected |
| `accepted_then_dropped` | The server returned success but intentionally did not capture the message |

## Querying via Admin API

All admin endpoints require authentication with `Authorization: Bearer <token>`.

### GET /admin/stats -- Summary Statistics

Returns aggregated statistics for the current run:

```bash
curl http://localhost:8000/admin/stats \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

For ChaosSMTP, use the admin sidecar port:

```bash
curl http://localhost:8525/admin/stats \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Example response:

```json
{
  "run_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "started_utc": "2025-03-15T14:30:00.123456+00:00",
  "total_requests": 1500,
  "requests_by_outcome": {
    "success": 1275,
    "error_injected": 195,
    "error_malformed": 30
  },
  "error_rate": 15.0,
  "requests_by_status_code": {
    "200": 1305,
    "429": 120,
    "529": 45,
    "503": 15,
    "500": 15
  },
  "latency_stats": {
    "avg_ms": 125.4,
    "p50_ms": 108.2,
    "p95_ms": 215.6,
    "p99_ms": 485.3,
    "max_ms": 15234.1
  }
}
```

The `latency_stats` object provides percentile-based latency distribution:

| Field | Description |
|---|---|
| `avg_ms` | Mean latency across all requests |
| `p50_ms` | Median latency (50th percentile) |
| `p95_ms` | 95th percentile latency |
| `p99_ms` | 99th percentile latency |
| `max_ms` | Maximum observed latency |

### GET /admin/export -- Raw Data Export

Returns all raw request records and time-series data for external analysis:

```bash
curl http://localhost:8000/admin/export \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Example response:

```json
{
  "run_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "started_utc": "2025-03-15T14:30:00.123456+00:00",
  "requests": [
    {
      "request_id": "req-001",
      "timestamp_utc": "2025-03-15T14:30:01.000000+00:00",
      "endpoint": "/v1/chat/completions",
      "outcome": "success",
      "status_code": 200,
      "latency_ms": 112.5,
      "model": "gpt-4",
      "message_count": 3,
      "response_mode": "random"
    },
    {
      "request_id": "req-002",
      "timestamp_utc": "2025-03-15T14:30:01.500000+00:00",
      "endpoint": "/v1/chat/completions",
      "outcome": "error_injected",
      "status_code": 429,
      "error_type": "rate_limit",
      "latency_ms": 2.1,
      "model": "gpt-4",
      "message_count": 1
    }
  ],
  "timeseries": [
    {
      "bucket_utc": "2025-03-15T14:30:01+00:00",
      "requests_total": 42,
      "requests_success": 36,
      "requests_rate_limited": 4,
      "requests_error": 2,
      "avg_latency_ms": 118.7,
      "p99_latency_ms": 312.4
    }
  ],
  "config": {
    "server": {"host": "127.0.0.1", "port": 8000, "workers": 1},
    "metrics": {"database": "file:chaosllm-metrics?mode=memory&cache=shared", "timeseries_bucket_sec": 1},
    "error_injection": {"rate_limit_pct": 5.0, "...": "..."},
    "response": {"mode": "random", "...": "..."},
    "latency": {"base_ms": 100, "jitter_ms": 50}
  }
}
```

The export includes the full server configuration used for this run, making it self-documenting for later analysis.

ChaosSMTP exports also include a `messages` array. In `metadata` mode each item contains envelope sender, recipients, size, subject, and safe headers. In `full` mode each item also includes base64-encoded message bytes up to `capture.max_message_bytes`.

### POST /admin/reset -- Reset Metrics

Clears all request and timeseries data and starts a new run:

```bash
curl -X POST http://localhost:8000/admin/reset \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Response:

```json
{
  "status": "reset",
  "new_run_id": "new-uuid-here"
}
```

!!! tip
    Reset between test scenarios so metrics from one test do not contaminate the next. Each reset generates a new `run_id`.

## Time-Series Aggregation

Metrics are aggregated into time-series buckets using SQLite UPSERT. The bucket size is configurable via `timeseries_bucket_sec` (default: 1 second).

Each bucket tracks:

- `requests_total` -- Total requests in this time window
- Per-outcome counters (e.g., `requests_success`, `requests_rate_limited`)
- `avg_latency_ms` -- Average latency for the bucket
- `p99_latency_ms` -- Approximate 99th percentile latency

ChaosSMTP buckets use SMTP-specific counters:

- `messages_accepted`
- `messages_tempfailed`
- `messages_permfailed`
- `messages_connection_error`
- `messages_malformed_protocol`
- `messages_accepted_then_dropped`

Time-series data is included in the `/admin/export` response and is useful for observing how error rates and latency change over time, especially around burst windows.

## Storage Options

### In-Memory (Default)

By default, metrics are stored in a shared in-memory SQLite database:

```yaml
metrics:
  database: "file:chaosllm-metrics?mode=memory&cache=shared"
```

This is fast and requires no cleanup, but data is lost when the server stops. The `cache=shared` URI parameter allows multiple threads to access the same in-memory database.

Default in-memory database URIs are service-specific:

- ChaosLLM: `file:chaosllm-metrics?mode=memory&cache=shared`
- ChaosWeb: `file:chaosweb-metrics?mode=memory&cache=shared`
- ChaosSMTP: `file:chaossmtp-metrics?mode=memory&cache=shared`

### File-Backed

For persistent storage, specify a file path:

```bash
uv run chaosllm serve --preset=realistic --database=/tmp/metrics.db
```

Or in YAML:

```yaml
metrics:
  database: /tmp/metrics.db
```

File-backed databases use WAL (Write-Ahead Logging) mode and `synchronous=NORMAL` for good write performance without sacrificing durability. The directory is created automatically if it does not exist.

!!! note
    In-memory databases use `journal_mode=MEMORY` and `synchronous=OFF` for maximum speed, since durability is not a concern.

## Thread Safety

The MetricsStore uses thread-local SQLite connections. Each worker thread gets its own connection, avoiding contention. Connections are tracked and cleaned up when threads exit.

Metrics recording is best-effort: if a SQLite write fails, the error is logged but the chaos response is still returned to the client. A metrics side-effect should never replace an intended chaos response with an unintended real 500.

## Python API

When using the server programmatically, you have direct access to metrics:

```python
from errorworks.llm.server import ChaosLLMServer
from errorworks.llm.config import load_config

config = load_config(preset="realistic")
server = ChaosLLMServer(config)

# After running some requests...
stats = server.get_stats()
print(f"Total: {stats['total_requests']}, Error rate: {stats['error_rate']:.1f}%")

# Export everything
data = server.export_metrics()

# Reset for next test
new_run_id = server.reset()
```

## Related Pages

- [Configuration](configuration.md) -- Metrics storage configuration options
- [ChaosLLM](chaosllm.md) -- LLM-specific metrics fields
- [ChaosWeb](chaosweb.md) -- Web-specific metrics fields
- [ChaosSMTP](chaossmtp.md) -- SMTP-specific metrics and capture modes
- [Testing Fixtures](testing-fixtures.md) -- Accessing metrics in pytest
