# HTTP API Reference

Both ChaosLLM and ChaosWeb are Starlette ASGI applications. This page documents every HTTP endpoint exposed by each server.

## Authentication

All `/admin/*` endpoints require a Bearer token in the `Authorization` header:

```
Authorization: Bearer <admin_token>
```

The `admin_token` is auto-generated at startup (printed to the console) or set explicitly via config. Requests without a valid token receive:

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

## Shared Endpoints

These endpoints are available on both ChaosLLM and ChaosWeb servers.

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

Returns the current runtime configuration (error injection, response/content, and latency settings).

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
    "server": { "host": "127.0.0.1", "port": 8000, "workers": 4 },
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
