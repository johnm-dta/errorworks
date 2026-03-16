# Configuration Schema Reference

All configuration models use Pydantic with `frozen=True` (immutable) and `extra="forbid"` (no unknown fields). Runtime updates go through the admin API's `POST /admin/config` endpoint, which creates new model instances rather than mutating existing ones.

## Shared Configuration

These models are defined in `errorworks.engine.types` and used by both ChaosLLM and ChaosWeb.

### ServerConfig

Server binding and worker configuration.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | `str` | `"127.0.0.1"` | Host address to bind to. Must match pattern `^[a-zA-Z0-9.:\[\]-]+$`. |
| `port` | `int` | `8000` (LLM) / `8200` (Web) | Port to listen on. Range: 1-65535. |
| `workers` | `int` | `4` | Number of uvicorn workers. Must be > 0. |
| `admin_token` | `str` | Auto-generated | Bearer token for `/admin/*` endpoints. Auto-generated via `secrets.token_urlsafe(32)` if not set. |

**Safety constraint:** Binding to `0.0.0.0`, `::`, or `0:0:0:0:0:0:0:0` is blocked by default. Set `allow_external_bind: true` in the top-level config to override.

### MetricsConfig

Metrics storage configuration.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `database` | `str` | In-memory SQLite URI | SQLite database path. Use a file path for persistent storage or a `file:...?mode=memory&cache=shared` URI for in-memory. |
| `timeseries_bucket_sec` | `int` | `1` | Time-series aggregation bucket size in seconds. Must be > 0. |

Default database URIs:

- ChaosLLM: `file:chaosllm-metrics?mode=memory&cache=shared`
- ChaosWeb: `file:chaosweb-metrics?mode=memory&cache=shared`

### LatencyConfig

Latency simulation configuration. The simulated delay is `(base_ms + uniform(-jitter_ms, +jitter_ms)) / 1000` seconds, clamped to a minimum of 0.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `base_ms` | `int` | `50` | Base latency in milliseconds. Must be >= 0. |
| `jitter_ms` | `int` | `30` | Random jitter added to base latency (+/- ms). Must be >= 0. |

---

## ChaosLLM Configuration

### ChaosLLMConfig (top-level)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `server` | `ServerConfig` | See above | Server binding configuration. |
| `metrics` | `MetricsConfig` | See above | Metrics storage configuration. |
| `response` | `ResponseConfig` | See below | Response generation configuration. |
| `latency` | `LatencyConfig` | See above | Latency simulation configuration. |
| `error_injection` | `ErrorInjectionConfig` | See below | Error injection configuration. |
| `preset_name` | `str \| None` | `None` | Preset name used to build this config (set automatically). |
| `allow_external_bind` | `bool` | `false` | Allow binding to all interfaces (`0.0.0.0`). |

### ErrorInjectionConfig (ChaosLLM)

All percentage fields are floats in the range 0.0-100.0. A value of `5.0` means 5% of requests.

#### HTTP-Level Errors

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `rate_limit_pct` | `float` | `0.0` | 429 Rate Limit error percentage (primary AIMD trigger). |
| `capacity_529_pct` | `float` | `0.0` | 529 Model Overloaded error percentage (Azure-specific). |
| `service_unavailable_pct` | `float` | `0.0` | 503 Service Unavailable error percentage. |
| `bad_gateway_pct` | `float` | `0.0` | 502 Bad Gateway error percentage. |
| `gateway_timeout_pct` | `float` | `0.0` | 504 Gateway Timeout error percentage. |
| `internal_error_pct` | `float` | `0.0` | 500 Internal Server Error percentage. |
| `forbidden_pct` | `float` | `0.0` | 403 Forbidden error percentage. |
| `not_found_pct` | `float` | `0.0` | 404 Not Found error percentage. |

#### Retry-After Header

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `retry_after_sec` | `tuple[int, int]` | `(1, 5)` | Retry-After header value range [min, max] seconds. |

#### Connection-Level Failures

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `timeout_pct` | `float` | `0.0` | Percentage of requests that hang (trigger client timeout). |
| `timeout_sec` | `tuple[int, int]` | `(30, 60)` | How long to hang before responding [min, max] seconds. |
| `connection_failed_pct` | `float` | `0.0` | Percentage of requests that disconnect after a short lead time. |
| `connection_failed_lead_sec` | `tuple[int, int]` | `(2, 5)` | Lead time before disconnect [min, max] seconds. |
| `connection_stall_pct` | `float` | `0.0` | Percentage of requests that stall the connection then disconnect. |
| `connection_stall_start_sec` | `tuple[int, int]` | `(0, 2)` | Initial delay before stalling [min, max] seconds. |
| `connection_stall_sec` | `tuple[int, int]` | `(30, 60)` | How long to stall before disconnect [min, max] seconds. |
| `connection_reset_pct` | `float` | `0.0` | Percentage of requests that RST the TCP connection. |
| `slow_response_pct` | `float` | `0.0` | Percentage of requests with artificially slow responses. |
| `slow_response_sec` | `tuple[int, int]` | `(10, 30)` | Slow response delay range [min, max] seconds. |

#### Malformed Response Errors

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `invalid_json_pct` | `float` | `0.0` | Percentage of responses with invalid JSON. |
| `truncated_pct` | `float` | `0.0` | Percentage of responses truncated mid-stream. |
| `empty_body_pct` | `float` | `0.0` | Percentage of responses with empty body. |
| `missing_fields_pct` | `float` | `0.0` | Percentage of responses missing required fields. |
| `wrong_content_type_pct` | `float` | `0.0` | Percentage of responses with wrong Content-Type header. |

#### Selection Mode

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `selection_mode` | `"priority" \| "weighted"` | `"priority"` | `priority`: errors evaluated in order, first triggered wins. `weighted`: errors selected proportionally by weight. |

**Validation:** In weighted mode, if total error percentages reach or exceed 100%, a warning is emitted (no successful responses will be generated).

#### LLMBurstConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `false` | Enable burst pattern injection. |
| `interval_sec` | `int` | `30` | Time between burst starts in seconds. Must be > 0. |
| `duration_sec` | `int` | `5` | How long each burst lasts in seconds. Must be > 0 and < `interval_sec` when enabled. |
| `rate_limit_pct` | `float` | `80.0` | Rate limit percentage during burst (0-100). |
| `capacity_pct` | `float` | `50.0` | Capacity error (529) percentage during burst (0-100). |

#### Range Field Constraints

All `tuple[int, int]` range fields must satisfy `min <= max`. They accept both tuples and lists in YAML/JSON input (e.g., `[1, 5]` or `(1, 5)`).

### ResponseConfig (ChaosLLM)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mode` | `"random" \| "template" \| "echo" \| "preset"` | `"random"` | Response generation mode. |
| `allow_header_overrides` | `bool` | `true` | Allow `X-Fake-Response-Mode` and `X-Fake-Template` headers to override response generation. |
| `max_template_length` | `int` | `10000` | Maximum length for template strings (config or header override). Must be > 0. |
| `random` | `RandomResponseConfig` | See below | Settings for random mode. |
| `template` | `TemplateResponseConfig` | See below | Settings for template mode. |
| `preset` | `PresetResponseConfig` | See below | Settings for preset mode. |

#### RandomResponseConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `min_words` | `int` | `10` | Minimum words in generated response. Must be > 0 and <= `max_words`. |
| `max_words` | `int` | `100` | Maximum words in generated response. Must be > 0. |
| `vocabulary` | `"english" \| "lorem"` | `"english"` | Word source: common English words or Lorem Ipsum. |

#### TemplateResponseConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `body` | `str` | `'{"result": "ok"}'` | Jinja2 template for response body. Rendered in a `SandboxedEnvironment`. |

#### PresetResponseConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `file` | `str` | `"./responses.jsonl"` | Path to JSONL file with canned responses. |
| `selection` | `"random" \| "sequential"` | `"random"` | How to select responses from the bank. |

---

## ChaosWeb Configuration

### ChaosWebConfig (top-level)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `server` | `ServerConfig` | Port defaults to `8200` | Server binding configuration. |
| `metrics` | `MetricsConfig` | See above | Metrics storage configuration. |
| `content` | `WebContentConfig` | See below | HTML content generation configuration. |
| `latency` | `LatencyConfig` | See above | Latency simulation configuration. |
| `error_injection` | `WebErrorInjectionConfig` | See below | Error injection configuration. |
| `allow_external_bind` | `bool` | `false` | Allow binding to all interfaces (`0.0.0.0`). |
| `preset_name` | `str \| None` | `None` | Preset name used to build this config (set automatically). |

### WebErrorInjectionConfig (ChaosWeb)

#### HTTP-Level Errors

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `rate_limit_pct` | `float` | `0.0` | 429 Rate Limit percentage (anti-scraping throttle). |
| `forbidden_pct` | `float` | `0.0` | 403 Forbidden percentage (bot detection). |
| `not_found_pct` | `float` | `0.0` | 404 Not Found percentage (deleted page). |
| `gone_pct` | `float` | `0.0` | 410 Gone percentage (permanent deletion). |
| `payment_required_pct` | `float` | `0.0` | 402 Payment Required percentage (quota exceeded). |
| `unavailable_for_legal_pct` | `float` | `0.0` | 451 Unavailable for Legal Reasons percentage (geo-blocking). |
| `service_unavailable_pct` | `float` | `0.0` | 503 Service Unavailable percentage (maintenance). |
| `bad_gateway_pct` | `float` | `0.0` | 502 Bad Gateway percentage. |
| `gateway_timeout_pct` | `float` | `0.0` | 504 Gateway Timeout percentage. |
| `internal_error_pct` | `float` | `0.0` | 500 Internal Server Error percentage. |

#### Retry-After Header

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `retry_after_sec` | `tuple[int, int]` | `(1, 30)` | Retry-After header value range [min, max] seconds. |

#### Connection-Level Failures

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `timeout_pct` | `float` | `0.0` | Percentage of requests that hang (trigger client timeout). |
| `timeout_sec` | `tuple[int, int]` | `(30, 60)` | How long to hang before responding [min, max] seconds. |
| `connection_reset_pct` | `float` | `0.0` | Percentage of requests that RST the TCP connection. |
| `connection_stall_pct` | `float` | `0.0` | Percentage of requests that stall then disconnect. |
| `connection_stall_start_sec` | `tuple[int, int]` | `(0, 2)` | Initial delay before stalling [min, max] seconds. |
| `connection_stall_sec` | `tuple[int, int]` | `(30, 60)` | How long to stall before disconnect [min, max] seconds. |
| `slow_response_pct` | `float` | `0.0` | Percentage of requests with artificially slow responses. |
| `slow_response_sec` | `tuple[int, int]` | `(3, 15)` | Slow response delay range [min, max] seconds. |
| `incomplete_response_pct` | `float` | `0.0` | Percentage of responses that disconnect mid-body. |
| `incomplete_response_bytes` | `tuple[int, int]` | `(100, 1000)` | How many bytes to send before disconnecting [min, max]. |

#### Content Malformations

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `wrong_content_type_pct` | `float` | `0.0` | Percentage of responses with wrong Content-Type (e.g., `application/pdf`). |
| `encoding_mismatch_pct` | `float` | `0.0` | Percentage with UTF-8 header but ISO-8859-1 body. |
| `truncated_html_pct` | `float` | `0.0` | Percentage with HTML cut off mid-tag. |
| `invalid_encoding_pct` | `float` | `0.0` | Percentage with non-decodable bytes in declared encoding. |
| `charset_confusion_pct` | `float` | `0.0` | Percentage with conflicting charset declarations (header vs meta). |
| `malformed_meta_pct` | `float` | `0.0` | Percentage with invalid `<meta http-equiv='refresh'>` directives. |

#### Redirect Injection

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `redirect_loop_pct` | `float` | `0.0` | Percentage of requests that enter redirect loops. |
| `max_redirect_loop_hops` | `int` | `10` | Maximum hops in a redirect loop before terminating. Minimum: 3. |
| `ssrf_redirect_pct` | `float` | `0.0` | Percentage of requests redirected to private IPs (SSRF testing). |

#### Selection Mode

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `selection_mode` | `"priority" \| "weighted"` | `"priority"` | Error selection strategy. Same semantics as ChaosLLM. |

#### WebBurstConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `false` | Enable burst pattern injection. |
| `interval_sec` | `int` | `30` | Time between burst starts in seconds. Must be > 0. |
| `duration_sec` | `int` | `5` | How long each burst lasts in seconds. Must be > 0 and < `interval_sec` when enabled. |
| `rate_limit_pct` | `float` | `80.0` | Rate limit (429) percentage during burst (0-100). |
| `forbidden_pct` | `float` | `50.0` | Forbidden (403) percentage during burst (0-100). |

### WebContentConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mode` | `"random" \| "template" \| "echo" \| "preset"` | `"random"` | Content generation mode. |
| `allow_header_overrides` | `bool` | `true` | Allow `X-Fake-Content-Mode` header to override content generation. |
| `max_template_length` | `int` | `10000` | Maximum length for template strings. Must be > 0. |
| `default_content_type` | `str` | `"text/html; charset=utf-8"` | Default Content-Type header for successful responses. |
| `random` | `RandomContentConfig` | See below | Settings for random mode. |
| `template` | `TemplateContentConfig` | See below | Settings for template mode. |
| `preset` | `PresetContentConfig` | See below | Settings for preset mode. |

#### RandomContentConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `min_words` | `int` | `50` | Minimum words in generated HTML body. Must be > 0 and <= `max_words`. |
| `max_words` | `int` | `500` | Maximum words in generated HTML body. Must be > 0. |
| `vocabulary` | `"english" \| "lorem"` | `"english"` | Word source: common English words or Lorem Ipsum. |

#### TemplateContentConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `body` | `str` | HTML template with `{{ path }}` and `{{ random_words() }}` | Jinja2 template for HTML response body. Rendered in a `SandboxedEnvironment`. |

#### PresetContentConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `file` | `str` | `"./pages.jsonl"` | Path to JSONL file with HTML page snapshots. |
| `selection` | `"random" \| "sequential"` | `"random"` | How to select pages from the bank. |

---

## YAML Configuration Example

```yaml
server:
  host: 127.0.0.1
  port: 8000
  workers: 4
  admin_token: my-secret-token

metrics:
  database: ./chaosllm-metrics.db
  timeseries_bucket_sec: 1

error_injection:
  rate_limit_pct: 5.0
  service_unavailable_pct: 2.0
  timeout_pct: 1.0
  selection_mode: priority
  burst:
    enabled: true
    interval_sec: 60
    duration_sec: 10
    rate_limit_pct: 80.0
    capacity_pct: 50.0

latency:
  base_ms: 50
  jitter_ms: 30

response:
  mode: random
  random:
    min_words: 20
    max_words: 200
    vocabulary: english
```
