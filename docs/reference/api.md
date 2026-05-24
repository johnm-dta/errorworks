# HTTP and SMTP API Reference

ChaosLLM, ChaosWeb, and ChaosBlob are Starlette ASGI applications. ChaosSMTP exposes a real SMTP listener plus a Starlette HTTP admin sidecar. This page documents every HTTP endpoint exposed by each server and the SMTP listener behavior.

## Authentication

All `/admin/*` endpoints require a Bearer token in the `Authorization` header:

```
Authorization: Bearer <admin_token>
```

The `admin_token` is auto-generated if omitted, but generated tokens are not printed. Set `server.admin_token` explicitly in config when you need to call the web or LLM admin API. For ChaosSMTP, use `admin.admin_token` or `--admin-token` when you need a stable token; `chaossmtp show-config` redacts the token from CLI output. Requests without a valid token receive:

- **401** if the `Authorization: Bearer` header is missing
- **403** if the token does not match

---

## ChaosLLM Endpoints

### `POST /v1/chat/completions`

OpenAI-compatible chat completions endpoint. This is the primary endpoint for LLM chaos testing.

**Request body** (OpenAI format):

```json
{
  "model": "gpt-4",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello!"}
  ],
  "stream": false
}
```

**Optional request headers:**

| Header | Description |
|--------|-------------|
| `X-Fake-Response-Mode` | Override response generation mode (`random`, `template`, `echo`, `preset`). Only honored when `allow_header_overrides` is `true` in config. |
| `X-Fake-Template` | Override template string for template mode. |

**Success response** (200):

```json
{
  "id": "chatcmpl-<uuid>",
  "object": "chat.completion",
  "created": 1700000000,
  "model": "gpt-4",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Generated response text..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 25,
    "completion_tokens": 42,
    "total_tokens": 67
  }
}
```

**Error responses** vary by injection type:

| Injection | Status | Response |
|-----------|--------|----------|
| `rate_limit` | 429 | JSON error with `Retry-After` header |
| `capacity_529` | 529 | JSON error body |
| `service_unavailable` | 503 | JSON error body |
| `bad_gateway` | 502 | JSON error body |
| `gateway_timeout` | 504 | JSON error body |
| `internal_error` | 500 | JSON error body |
| `timeout` | 504 or connection drop | Delays, then responds or disconnects |
| `connection_reset` | N/A | TCP connection reset |
| `connection_stall` | N/A | Stalls, then connection reset |
| `invalid_json` | 200 | Unparseable JSON body |
| `truncated` | 200 | Truncated JSON mid-stream |
| `empty_body` | 200 | Empty response body |
| `missing_fields` | 200 | Valid JSON missing required fields |
| `wrong_content_type` | 200 | HTML body with `text/html` content type |

**Example curl:**

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

### `POST /openai/deployments/{deployment}/chat/completions`

Azure OpenAI-compatible endpoint. Same request/response format as `/v1/chat/completions` with an additional `api-version` query parameter.

**Example curl:**

```bash
curl -X POST "http://localhost:8000/openai/deployments/my-gpt4/chat/completions?api-version=2024-02-01" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

---

## ChaosWeb Endpoints

### `GET /{path}`

Catch-all content endpoint. Returns HTML pages with configurable error injection, content malformations, and redirect behavior.

**Optional request headers:**

| Header | Description |
|--------|-------------|
| `X-Fake-Content-Mode` | Override content generation mode (`random`, `template`, `echo`, `preset`). Only honored when `allow_header_overrides` is `true` in config. |

**Success response** (200): HTML page with `text/html; charset=utf-8` content type.

**Error responses** include all ChaosLLM categories plus:

| Injection | Status | Response |
|-----------|--------|----------|
| `forbidden` | 403 | HTML error page |
| `not_found` | 404 | HTML error page |
| `gone` | 410 | HTML error page |
| `payment_required` | 402 | HTML error page |
| `unavailable_for_legal` | 451 | HTML error page |
| `redirect_loop` | 301 | Chain of 301 redirects via `/redirect` |
| `ssrf_redirect` | 301 | Redirect to private IP / cloud metadata |
| `incomplete_response` | 200 | Partial body then connection drop |
| `encoding_mismatch` | 200 | UTF-8 header with ISO-8859-1 body |
| `truncated_html` | 200 | HTML cut off mid-tag |
| `invalid_encoding` | 200 | Non-decodable bytes in declared encoding |
| `charset_confusion` | 200 | Conflicting charset in header vs meta tag |
| `malformed_meta` | 200 | Invalid `<meta http-equiv='refresh'>` directives |

**Example curl:**

```bash
curl http://localhost:8200/some/page
```

### `GET /redirect`

Internal redirect hop handler used by redirect loop injection. Tracks hops via query parameters (`hop`, `max`, `target`). Not intended for direct use.

---

## ChaosBlob Endpoints

ChaosBlob exposes path-style S3-compatible-ish object operations. Object data is stored in memory.

### `PUT /{bucket}/{key:path}`

Store an object body under a bucket and key. `Content-Type` is preserved, and any `x-amz-meta-*` headers are returned on future `GET` and `HEAD` requests.

**Success response** (200): empty body with an `ETag` header.

```bash
curl -X PUT http://localhost:8300/my-bucket/data/1.json \
  -H "Content-Type: application/json" \
  -H "x-amz-meta-source: test" \
  -d '{"id": 1}'
```

### `GET /{bucket}/{key:path}`

Return object bytes and metadata.

**Success response** (200): object body with `Content-Type`, `Content-Length`, `ETag`, and stored `x-amz-meta-*` headers.

### `HEAD /{bucket}/{key:path}`

Return object metadata without the object body.

### `DELETE /{bucket}/{key:path}`

Delete an object. Returns `204 No Content` whether or not the object existed.

### `GET /{bucket}?list-type=2`

List objects using a `ListObjectsV2` style XML response.

**Query parameters:**

| Parameter | Description |
|-----------|-------------|
| `list-type=2` | Required. Other values return `InvalidRequest`. |
| `prefix` | Optional key prefix filter. |
| `max-keys` | Optional maximum number of keys to return. Defaults to `1000`; must be at least `1`; values above `1000` are capped. |
| `continuation-token` | Optional opaque token from `NextContinuationToken`. |

**Success response** (200): XML `ListBucketResult` with `Contents`, `IsTruncated`, and optional `NextContinuationToken` elements.

```bash
curl "http://localhost:8300/my-bucket?list-type=2&prefix=data/&max-keys=10"
```

**Error responses** include:

| Injection | Status | Response |
|-----------|--------|----------|
| `slow_down` | 503 | S3 XML error with `Retry-After` header |
| `access_denied` | 403 | S3 XML `AccessDenied` error |
| `not_found` | 404 | S3 XML `NoSuchKey` error |
| `service_unavailable` | 503 | S3 XML `ServiceUnavailable` error |
| `internal_error` | 500 | S3 XML `InternalError` error |
| `bad_gateway` | 502 | S3 XML `BadGateway` error |
| `gateway_timeout` | 504 | S3 XML `GatewayTimeout` error |
| `timeout` | 504 | S3 XML `RequestTimeout` error after delay |
| `connection_reset` | N/A | Response starts, then disconnects |
| `connection_stall` | N/A | Delays and disconnects |
| `truncated_body` | 200 | Partial object body |
| `wrong_content_length` | 200 | Declares full length, sends partial body, then disconnects |
| `checksum_mismatch` | 200 | Corrupted ETag |
| `metadata_corruption` | 200 | Missing stored metadata header |
| `stale_list` | 200 | List omits the newest object |
| `malformed_xml` | 200 | Broken list XML |

---

## ChaosSMTP Listener and Admin Sidecar

ChaosSMTP has two network surfaces:

- SMTP listener: default `127.0.0.1:2525`, accepts real SMTP clients such as `smtplib`.
- HTTP admin sidecar: default `127.0.0.1:8525`, exposes health, metrics, export, reset, and runtime config endpoints.

ChaosSMTP never relays mail. Messages are accepted, rejected, dropped, or captured locally according to configuration.

### SMTP Listener

The SMTP listener supports normal SMTP transactions with `MAIL FROM`, `RCPT TO`, and `DATA`. The server announces `smtp.hostname` (default `chaossmtp.local`) and enforces `smtp.data_size_limit` (default `10485760` bytes). `smtp.port` may be `0` in YAML or Python config for ephemeral test binding.

**Success behavior:** successful messages receive normal `250` replies and are captured according to `capture.mode`.

**Injected SMTP outcomes:** current server handling invokes MAIL, RCPT, DATA, and ACCEPT stage decisions. CONNECT-stage config fields are accepted but are not currently called by the listener.

| Injection | Stage | Reply or Behavior |
|-----------|-------|-------------------|
| `rate_limit` | MAIL/RCPT | `450 4.7.0 Mailbox temporarily unavailable due to rate limiting` |
| `mail_from_tempfail` | MAIL | `451 4.3.0 Temporary sender failure` |
| `mail_from_reject` | MAIL | `550 5.1.0 Sender rejected` |
| `rcpt_to_tempfail` | RCPT | `451 4.3.0 Temporary recipient failure` |
| `rcpt_to_reject` | RCPT | `550 5.1.1 Recipient rejected` |
| `data_tempfail` | DATA | `451 4.3.0 Temporary message failure` |
| `data_reject` | DATA | `554 5.6.0 Message rejected` |
| `accept_then_drop` | ACCEPT | Returns `250` but records `accepted_then_dropped` and skips capture |
| `banner_reject` | CONNECT | Schema/CLI field exists; current listener does not invoke CONNECT-stage injection |
| `malformed_reply` | DATA | Writes a malformed SMTP reply and closes the transport |
| `wrong_reply_code` | DATA | Returns `252 2.5.2 Cannot VRFY user, accepting chaos path` |
| `connection_reset` | MAIL/RCPT/DATA | Closes the SMTP transport |
| `connection_stall` | MAIL/RCPT/DATA | Delays for `connection_stall_sec`, then closes the transport |
| `slow_response` | MAIL/RCPT/DATA | Delays for `slow_response_sec`, then continues the normal path |

**Example smtplib client:**

```python
from email.message import EmailMessage
import smtplib

message = EmailMessage()
message["From"] = "sender@example.com"
message["To"] = "recipient@example.com"
message["Subject"] = "SMTP API test"
message.set_content("hello")

with smtplib.SMTP("127.0.0.1", 2525, timeout=5) as client:
    client.send_message(message)
```

### HTTP Admin Sidecar

The admin sidecar uses the shared admin endpoint set documented below. Use the sidecar port, not the SMTP port:

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://127.0.0.1:8525/admin/stats
```

Admin endpoints require the bearer token even though `chaossmtp show-config` redacts `admin_token` from CLI output. Set the token with `admin.admin_token` or `--admin-token` when tests need a stable value.

`GET /health` includes `smtp_running` in addition to the shared health fields:

```json
{
  "status": "healthy",
  "smtp_running": true,
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "started_utc": "2025-01-15T10:30:00+00:00",
  "in_burst": false
}
```

`GET /admin/config` and `POST /admin/config` expose runtime-updatable SMTP sections: `error_injection`, `capture`, and `latency`. Listener binding, admin binding, metrics database, and admin token changes require restart.

`GET /admin/export` returns raw SMTP transaction metrics plus captured messages:

```json
{
  "requests": [
    {
      "transaction_id": "abc-123",
      "mail_from": "sender@example.com",
      "rcpt_count": 1,
      "outcome": "success",
      "smtp_stage": "data",
      "reply_code": 250,
      "capture_mode": "metadata"
    }
  ],
  "messages": [
    {
      "transaction_id": "abc-123",
      "mail_from": "sender@example.com",
      "rcpt_tos": ["recipient@example.com"],
      "message_size_bytes": 184,
      "subject": "SMTP API test",
      "headers": {"from": "sender@example.com", "to": "recipient@example.com", "subject": "SMTP API test"},
      "body": null,
      "body_encoding": null,
      "truncated": false
    }
  ]
}
```

---

## Shared Endpoints

These endpoints are available on ChaosLLM, ChaosWeb, and ChaosBlob servers, and on the ChaosSMTP HTTP admin sidecar.

### `GET /health`

Health check endpoint. No authentication required.

**Response** (200):

```json
{
  "status": "healthy",
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "started_utc": "2025-01-15T10:30:00+00:00",
  "in_burst": false
}
```

ChaosSMTP also includes `smtp_running`.

**Example curl:**

```bash
curl http://localhost:8000/health
```

---

### `GET /admin/stats`

Returns summary statistics for the current run.

**Response** (200):

```json
{
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "started_utc": "2025-01-15T10:30:00+00:00",
  "total_requests": 1500,
  "requests_by_outcome": {
    "success": 1200,
    "error_injected": 280,
    "error_malformed": 20
  },
  "error_rate": 20.0,
  "requests_by_status_code": {
    "200": 1220,
    "429": 150,
    "503": 80,
    "500": 50
  },
  "latency_stats": {
    "avg_ms": 65.3,
    "p50_ms": 52.1,
    "p95_ms": 112.7,
    "p99_ms": 198.4,
    "max_ms": 350.2
  }
}
```

**Example curl:**

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://localhost:8000/admin/stats
```

---

### `GET /admin/config`

Returns the current runtime configuration (error injection, response/content/storage or capture settings, and latency settings).

**Response** (200):

ChaosLLM example:

```json
{
  "error_injection": {
    "rate_limit_pct": 5.0,
    "capacity_529_pct": 0.0,
    "service_unavailable_pct": 2.0,
    "selection_mode": "priority",
    "burst": {
      "enabled": false,
      "interval_sec": 30,
      "duration_sec": 5
    }
  },
  "response": {
    "mode": "random",
    "allow_header_overrides": true,
    "random": {
      "min_words": 10,
      "max_words": 100,
      "vocabulary": "english"
    }
  },
  "latency": {
    "base_ms": 50,
    "jitter_ms": 30
  }
}
```

**Example curl:**

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://localhost:8000/admin/config
```

---

### `POST /admin/config`

Update runtime configuration. Accepts a partial JSON body that is deep-merged with the current configuration. Only the sections you include are modified; omitted sections retain their current values.

Nested fields within a section are also deep-merged. For example, sending `{"error_injection": {"burst": {"enabled": true}}}` enables burst mode without resetting `interval_sec` or `duration_sec` to defaults.

After merging, the new configuration is validated through the Pydantic model. If validation fails, a 422 response is returned and no changes are applied.

**Request body:**

```json
{
  "error_injection": {
    "rate_limit_pct": 25.0,
    "burst": {
      "enabled": true
    }
  },
  "latency": {
    "base_ms": 100
  }
}
```

**Response** (200):

```json
{
  "status": "updated",
  "config": {
    "error_injection": { "..." : "full merged config" },
    "response": { "..." : "unchanged" },
    "latency": { "base_ms": 100, "jitter_ms": 30 }
  }
}
```

**Error responses:**

| Status | Condition |
|--------|-----------|
| 400 | Request body is not valid JSON or not a JSON object |
| 401 | Missing `Authorization: Bearer` header |
| 403 | Invalid admin token |
| 422 | Merged config fails Pydantic validation |

**Example curl:**

```bash
curl -X POST http://localhost:8000/admin/config \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"error_injection": {"rate_limit_pct": 25.0}}'
```

---

### `POST /admin/reset`

Reset all metrics and start a new run. Clears the `requests` and `timeseries` tables and generates a new `run_id`. The error injection engine's burst state is also reset.

**Response** (200):

```json
{
  "status": "reset",
  "new_run_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**Example curl:**

```bash
curl -X POST http://localhost:8000/admin/reset \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

### `GET /admin/export`

Export all raw metrics data for external analysis or archival. Returns the complete request log, timeseries data, and the configuration used for this run.

**Response** (200):

```json
{
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "started_utc": "2025-01-15T10:30:00+00:00",
  "requests": [
    {
      "request_id": "abc-123",
      "timestamp_utc": "2025-01-15T10:30:01+00:00",
      "endpoint": "/v1/chat/completions",
      "outcome": "success",
      "status_code": 200,
      "latency_ms": 52.3
    }
  ],
  "timeseries": [
    {
      "bucket_utc": "2025-01-15T10:30:00+00:00",
      "requests_total": 45,
      "avg_latency_ms": 65.3,
      "p99_latency_ms": 198.4
    }
  ],
  "config": {
    "server": { "host": "127.0.0.1", "port": 8000, "workers": 1 },
    "metrics": { "database": "file:chaosllm-metrics?mode=memory&cache=shared" },
    "error_injection": { "..." : "..." },
    "response": { "..." : "..." },
    "latency": { "base_ms": 50, "jitter_ms": 30 }
  }
}
```

**Example curl:**

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://localhost:8000/admin/export
```

For ChaosSMTP, use `http://localhost:8525/...` for these admin endpoints.

---

## Error Response Format

### ChaosLLM Error Bodies

All HTTP-level error injections return OpenAI-compatible error JSON:

```json
{
  "error": {
    "type": "rate_limit_error",
    "message": "Rate limit exceeded. Please retry after the specified time.",
    "code": "rate_limit"
  }
}
```

The `type` field maps to OpenAI error types: `rate_limit_error`, `capacity_error`, `server_error`, `permission_error`, `not_found_error`.

### ChaosWeb Error Bodies

HTTP-level errors return HTML error pages:

```html
<html><body><h1>429 Too Many Requests -- You are being rate limited.</h1></body></html>
```

### ChaosBlob Error Bodies

HTTP-level errors return S3-shaped XML:

```xml
<Error>
  <Code>SlowDown</Code>
  <Message>Please reduce your request rate.</Message>
  <Resource>/bucket/key</Resource>
  <RequestId>...</RequestId>
</Error>
```

### Admin Error Bodies

Authentication and validation errors from admin endpoints use a consistent format:

```json
{
  "error": {
    "type": "authentication_error",
    "message": "Missing Authorization: Bearer <token> header"
  }
}
```
