# Configuration Schema Reference

All configuration models use Pydantic with `frozen=True` (immutable) and `extra="forbid"` (no unknown fields). Runtime updates go through the admin API's `POST /admin/config` endpoint, which creates new model instances rather than mutating existing ones.

## Shared Configuration

These models are defined in `errorworks.engine.types`. `MetricsConfig` and `LatencyConfig` are shared by all server types; `ServerConfig` is used by the HTTP-native ChaosLLM, ChaosWeb, and ChaosBlob servers.

### ServerConfig

Server binding and worker configuration.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | `str` | `"127.0.0.1"` | Host address to bind to. Must match pattern `^[a-zA-Z0-9.:\[\]-]+$`. |
| `port` | `int` | `8000` (LLM) / `8200` (Web) / `8300` (Blob) | Port to listen on. Range: 1-65535. |
| `workers` | `int` | `1` | Number of uvicorn workers. Must be > 0. Workers > 1 require a file-backed metrics database. |
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
- ChaosBlob: `file:chaosblob-metrics?mode=memory&cache=shared`
- ChaosSMTP: `file:chaossmtp-metrics?mode=memory&cache=shared`

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

## ChaosBlob Configuration

### ChaosBlobConfig (top-level)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `server` | `BlobServerConfig` | Port defaults to `8300` | Server binding configuration. |
| `metrics` | `MetricsConfig` | See above | Metrics storage configuration. |
| `storage` | `BlobStorageConfig` | See below | Object storage limits and response defaults. |
| `latency` | `LatencyConfig` | See above | Latency simulation configuration. |
| `error_injection` | `BlobErrorInjectionConfig` | See below | Error injection configuration. |
| `allow_external_bind` | `bool` | `false` | Allow binding to all interfaces (`0.0.0.0`). |
| `preset_name` | `str \| None` | `None` | Preset name used to build this config (set automatically). |

### BlobErrorInjectionConfig

All percentage fields are floats in the range 0.0-100.0.

#### S3 HTTP Errors

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `slow_down_pct` | `float` | `0.0` | S3 SlowDown percentage. Includes `Retry-After`. |
| `access_denied_pct` | `float` | `0.0` | 403 AccessDenied percentage. |
| `not_found_pct` | `float` | `0.0` | 404 NoSuchKey percentage. |
| `service_unavailable_pct` | `float` | `0.0` | 503 ServiceUnavailable percentage. |
| `internal_error_pct` | `float` | `0.0` | 500 InternalError percentage. |
| `bad_gateway_pct` | `float` | `0.0` | 502 BadGateway percentage. |
| `gateway_timeout_pct` | `float` | `0.0` | 504 GatewayTimeout percentage. |
| `retry_after_sec` | `tuple[int, int]` | `(1, 30)` | Retry-After header value range [min, max] seconds. |

#### Connection Failures

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `timeout_pct` | `float` | `0.0` | Percentage of requests that hang before a timeout response. |
| `timeout_sec` | `tuple[int, int]` | `(30, 60)` | How long to hang [min, max] seconds. |
| `connection_reset_pct` | `float` | `0.0` | Percentage of requests that disconnect mid-response. |
| `connection_stall_pct` | `float` | `0.0` | Percentage of requests that stall then disconnect. |
| `connection_stall_start_sec` | `tuple[int, int]` | `(0, 2)` | Initial delay before stalling [min, max]. |
| `connection_stall_sec` | `tuple[int, int]` | `(30, 60)` | Stall duration [min, max] seconds. |
| `slow_response_pct` | `float` | `0.0` | Percentage of artificially slow responses. |
| `slow_response_sec` | `tuple[int, int]` | `(3, 15)` | Slow response delay range [min, max] seconds. |

#### Object and List Corruption

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `truncated_body_pct` | `float` | `0.0` | Percentage of GET responses with truncated object bodies. |
| `wrong_content_length_pct` | `float` | `0.0` | Percentage of GET responses that declare the full length and disconnect early. |
| `checksum_mismatch_pct` | `float` | `0.0` | Percentage of GET responses with corrupted ETags. |
| `metadata_corruption_pct` | `float` | `0.0` | Percentage of GET/HEAD responses with missing metadata. |
| `stale_list_pct` | `float` | `0.0` | Percentage of list responses that omit the newest object. |
| `malformed_xml_pct` | `float` | `0.0` | Percentage of list responses with malformed XML. |

#### Selection and Burst

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `selection_mode` | `"priority" \| "weighted"` | `"priority"` | Error selection strategy. Same semantics as ChaosLLM. |
| `burst` | `BlobBurstConfig` | See below | Burst pattern configuration. |

#### BlobBurstConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `false` | Enable burst pattern injection. |
| `interval_sec` | `int` | `60` | Time between burst starts in seconds. Must be > 0. |
| `duration_sec` | `int` | `10` | How long each burst lasts in seconds. Must be > 0 and < `interval_sec` when enabled. |
| `slow_down_pct` | `float` | `80.0` | SlowDown percentage during burst. |
| `service_unavailable_pct` | `float` | `40.0` | ServiceUnavailable percentage during burst. |

### BlobStorageConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_object_bytes` | `int` | `10485760` | Maximum accepted object body size. Must be > 0. |
| `default_content_type` | `str` | `"application/octet-stream"` | Content-Type used when a PUT has no content-type header. |

---

## ChaosSMTP Configuration

### ChaosSMTPConfig (top-level)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `smtp` | `SMTPServerConfig` | See below | SMTP listener binding and protocol configuration. |
| `admin` | `SMTPAdminConfig` | See below | HTTP admin sidecar configuration. |
| `metrics` | `MetricsConfig` | `database="file:chaossmtp-metrics?mode=memory&cache=shared"` | Metrics storage configuration. |
| `latency` | `LatencyConfig` | See above | Latency simulation configuration. |
| `capture` | `SMTPCaptureConfig` | See below | Message capture configuration. |
| `error_injection` | `SMTPErrorInjectionConfig` | See below | SMTP-stage error injection configuration. |
| `preset_name` | `str \| None` | `None` | Preset name used to build this config (set automatically). |
| `allow_external_bind` | `bool` | `false` | Allow SMTP or admin binding to all interfaces (`0.0.0.0`, `::`, or equivalent). |

**Safety constraint:** Binding either `smtp.host` or `admin.host` to an unspecified/all-interface address is blocked by default. Set `allow_external_bind: true` to override for controlled local test environments.

### SMTPServerConfig

SMTP listener binding and protocol settings.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | `str` | `"127.0.0.1"` | SMTP listener bind address. Must match pattern `^[a-zA-Z0-9.:\[\]-]+$`. |
| `port` | `int` | `2525` | SMTP listener port. Range: 0-65535. Use `0` for ephemeral test binding. |
| `hostname` | `str` | `"chaossmtp.local"` | Hostname announced to SMTP clients. |
| `data_size_limit` | `int` | `10485760` | Maximum SMTP DATA size in bytes. Must be > 0. |
| `enable_smtputf8` | `bool` | `true` | Enable SMTPUTF8 support. |
| `require_starttls` | `bool` | `false` | Require STARTTLS before mail commands. |

### SMTPAdminConfig

HTTP admin sidecar configuration.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `true` | Enable the HTTP admin sidecar. |
| `host` | `str` | `"127.0.0.1"` | Admin sidecar bind address. Must match pattern `^[a-zA-Z0-9.:\[\]-]+$`. |
| `port` | `int` | `8525` | Admin sidecar port. Range: 1-65535. |
| `admin_token` | `str` | Auto-generated | Bearer token for `/admin/*` endpoints. Auto-generated via `secrets.token_urlsafe(32)` if not set. |

`chaossmtp show-config` removes `admin_token` from JSON/YAML output. The running admin sidecar still requires `Authorization: Bearer <admin_token>`.

### SMTPCaptureConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mode` | `"discard" \| "metadata" \| "full"` | `"metadata"` | Message capture mode. `discard` records metrics only; `metadata` stores envelope and safe headers; `full` stores message bytes. |
| `max_message_bytes` | `int` | `1048576` | Maximum bytes stored in `full` mode. Must be >= 0. |

### SMTPErrorInjectionConfig

All percentage fields are floats in the range 0.0-100.0. A value of `5.0` means 5% for the SMTP stage where the field applies.

#### SMTP Command and Delivery Errors

Current server handling invokes MAIL, RCPT, DATA, and ACCEPT stage decisions. CONNECT-stage fields such as `banner_reject_pct` are part of the schema and CLI surface, but the listener does not currently call CONNECT-stage injection.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `rate_limit_pct` | `float` | `0.0` | 450 rate-limit temporary failure percentage on MAIL/RCPT stages. |
| `mail_from_tempfail_pct` | `float` | `0.0` | MAIL FROM temporary failure percentage. |
| `mail_from_reject_pct` | `float` | `0.0` | MAIL FROM permanent rejection percentage. |
| `rcpt_to_tempfail_pct` | `float` | `0.0` | RCPT TO temporary failure percentage. |
| `rcpt_to_reject_pct` | `float` | `0.0` | RCPT TO permanent rejection percentage. |
| `data_tempfail_pct` | `float` | `0.0` | DATA temporary failure percentage. |
| `data_reject_pct` | `float` | `0.0` | DATA permanent rejection percentage. |
| `accept_then_drop_pct` | `float` | `0.0` | Accept message with `250` then drop it without capture. |
| `banner_reject_pct` | `float` | `0.0` | Connection/banner-stage `421` rejection percentage field. Current listener does not invoke CONNECT-stage injection. |

#### Protocol and Connection Failures

Protocol and connection percentage fields are evaluated on MAIL, RCPT, or DATA stages depending on the injector stage list. `malformed_reply_pct` and `wrong_reply_code_pct` are currently reached through DATA handling.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `malformed_reply_pct` | `float` | `0.0` | Malformed SMTP reply percentage on CONNECT/DATA stages. |
| `wrong_reply_code_pct` | `float` | `0.0` | Unexpected SMTP reply code percentage on CONNECT/DATA stages. |
| `connection_reset_pct` | `float` | `0.0` | Close the SMTP transport percentage. |
| `connection_stall_pct` | `float` | `0.0` | Stall then close percentage. |
| `slow_response_pct` | `float` | `0.0` | Slow response percentage. Slow response delays but does not otherwise fail the transaction. |

#### Range Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `retry_after_sec` | `tuple[int, int]` | `(1, 30)` | Validated retry delay range config. Current SMTP replies do not emit a Retry-After header. |
| `connection_stall_sec` | `tuple[int, int]` | `(30, 60)` | Stall duration range [min, max] seconds. |
| `slow_response_sec` | `tuple[int, int]` | `(3, 15)` | Slow response delay range [min, max] seconds. |

Range fields must satisfy `min <= max`. They accept both tuples and lists in YAML/JSON input.

#### Selection Mode

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `selection_mode` | `"priority" \| "weighted"` | `"priority"` | `priority`: errors evaluated in stage order. `weighted`: errors selected proportionally by weight. |

**Validation:** In weighted mode, if total SMTP error percentages reach or exceed 100%, a warning is emitted because no successful messages will be generated.

#### SMTPBurstConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `false` | Enable burst pattern injection. |
| `interval_sec` | `int` | `30` | Time between burst starts in seconds. Must be > 0. |
| `duration_sec` | `int` | `5` | How long each burst lasts in seconds. Must be > 0 and < `interval_sec` when enabled. |
| `tempfail_pct` | `float` | `80.0` | RCPT temporary failure percentage during burst windows. |
| `rate_limit_pct` | `float` | `50.0` | Rate-limit percentage during burst windows. |

---

## YAML Configuration Example

```yaml
server:
  host: 127.0.0.1
  port: 8000
  workers: 1
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
