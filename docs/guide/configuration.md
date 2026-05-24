# Configuration Guide

Errorworks servers are configured through three layered methods: presets, YAML config files, and CLI flags. Each layer overrides the one below it, giving you fine-grained control without rewriting entire configuration files.

## Configuration Precedence

From highest to lowest priority:

```
CLI flags  >  Config file  >  Preset  >  Built-in defaults
```

Each layer is deep-merged into the one below. You only need to specify the fields you want to change -- everything else inherits from the lower layer.

### Example: How Layers Combine

Given this preset (`realistic`):

```yaml
error_injection:
  rate_limit_pct: 5.0
  capacity_529_pct: 2.0
  burst:
    enabled: true
    interval_sec: 60
    duration_sec: 5
latency:
  base_ms: 100
  jitter_ms: 50
```

And this config file (`my-config.yaml`):

```yaml
error_injection:
  rate_limit_pct: 15.0
  burst:
    interval_sec: 30
```

And this CLI flag:

```bash
uv run chaosllm serve --preset=realistic --config=my-config.yaml --rate-limit-pct=25.0
```

The final configuration is:

```yaml
error_injection:
  rate_limit_pct: 25.0       # CLI flag wins
  capacity_529_pct: 2.0      # From preset (config file didn't touch it)
  burst:
    enabled: true             # From preset (preserved by deep merge)
    interval_sec: 30          # Config file overrode preset
    duration_sec: 5           # From preset (preserved by deep merge)
latency:
  base_ms: 100               # From preset
  jitter_ms: 50               # From preset
```

!!! note
    Deep merge is recursive. When the config file sets `burst.interval_sec`, it does not reset `burst.enabled` or `burst.duration_sec` to their defaults. Only the fields you explicitly set are changed.

## YAML Config File

Pass a YAML file with `--config=path/to/config.yaml`. The file structure mirrors the configuration models.

### ChaosLLM Full Example

```yaml
server:
  host: "127.0.0.1"
  port: 8000
  workers: 1
  admin_token: "my-secret-token"  # Auto-generated if omitted

metrics:
  database: "file:chaosllm-metrics?mode=memory&cache=shared"
  timeseries_bucket_sec: 1

response:
  mode: random                    # random | template | echo | preset
  allow_header_overrides: true
  max_template_length: 10000
  random:
    min_words: 20
    max_words: 100
    vocabulary: english           # english | lorem
  template:
    body: '{"result": "ok"}'
  preset:
    file: ./responses.jsonl
    selection: random             # random | sequential

latency:
  base_ms: 100
  jitter_ms: 50

error_injection:
  # Selection strategy
  selection_mode: priority        # priority | weighted

  # HTTP errors (0-100 percentage)
  rate_limit_pct: 5.0
  capacity_529_pct: 2.0
  service_unavailable_pct: 0.5
  bad_gateway_pct: 0.1
  gateway_timeout_pct: 0.2
  internal_error_pct: 0.2
  forbidden_pct: 0.0
  not_found_pct: 0.0

  # Retry-After header range for rate limit errors
  retry_after_sec: [1, 5]

  # Connection failures
  timeout_pct: 0.2
  timeout_sec: [30, 60]
  connection_reset_pct: 0.1
  connection_failed_pct: 0.0
  connection_failed_lead_sec: [2, 5]
  connection_stall_pct: 0.0
  connection_stall_start_sec: [0, 2]
  connection_stall_sec: [30, 60]
  slow_response_pct: 1.0
  slow_response_sec: [5, 15]

  # Malformed responses
  invalid_json_pct: 0.1
  truncated_pct: 0.1
  empty_body_pct: 0.0
  missing_fields_pct: 0.1
  wrong_content_type_pct: 0.0

  # Burst patterns
  burst:
    enabled: true
    interval_sec: 60
    duration_sec: 5
    rate_limit_pct: 50
    capacity_pct: 30
```

### ChaosWeb Full Example

```yaml
server:
  host: "127.0.0.1"
  port: 8200
  workers: 1
  admin_token: "my-secret-token"

metrics:
  database: "file:chaosweb-metrics?mode=memory&cache=shared"
  timeseries_bucket_sec: 1

content:
  mode: random                    # random | template | echo | preset
  allow_header_overrides: true
  max_template_length: 10000
  default_content_type: "text/html; charset=utf-8"
  random:
    min_words: 100
    max_words: 500
    vocabulary: english
  template:
    body: "<html><body><h1>{{ path }}</h1><p>{{ random_words(100, 300) }}</p></body></html>"
  preset:
    file: ./pages.jsonl
    selection: random

latency:
  base_ms: 300
  jitter_ms: 150

error_injection:
  selection_mode: priority

  # HTTP errors
  rate_limit_pct: 5.0
  forbidden_pct: 3.0
  not_found_pct: 2.0
  gone_pct: 0.0
  payment_required_pct: 0.0
  unavailable_for_legal_pct: 0.0
  service_unavailable_pct: 1.0
  bad_gateway_pct: 0.2
  gateway_timeout_pct: 0.3
  internal_error_pct: 0.5
  retry_after_sec: [5, 30]

  # Connection failures
  timeout_pct: 0.5
  timeout_sec: [10, 30]
  connection_reset_pct: 0.2
  connection_stall_pct: 0.0
  connection_stall_start_sec: [0, 2]
  connection_stall_sec: [30, 60]
  slow_response_pct: 5.0
  slow_response_sec: [3, 10]
  incomplete_response_pct: 0.0
  incomplete_response_bytes: [100, 1000]

  # Content malformations
  wrong_content_type_pct: 1.0
  encoding_mismatch_pct: 1.0
  truncated_html_pct: 0.5
  invalid_encoding_pct: 0.0
  charset_confusion_pct: 0.0
  malformed_meta_pct: 0.0

  # Redirects
  redirect_loop_pct: 0.0
  max_redirect_loop_hops: 10
  ssrf_redirect_pct: 0.0

  # Burst patterns
  burst:
    enabled: true
    interval_sec: 60
    duration_sec: 8
    rate_limit_pct: 40
    forbidden_pct: 30
```

### ChaosBlob Full Example

```yaml
server:
  host: "127.0.0.1"
  port: 8300
  workers: 1
  admin_token: "my-secret-token"

metrics:
  database: "file:chaosblob-metrics?mode=memory&cache=shared"
  timeseries_bucket_sec: 1

storage:
  max_object_bytes: 10485760
  default_content_type: "application/octet-stream"

latency:
  base_ms: 150
  jitter_ms: 75

error_injection:
  selection_mode: priority

  # S3 HTTP errors
  slow_down_pct: 4.0
  access_denied_pct: 0.5
  not_found_pct: 1.0
  service_unavailable_pct: 0.8
  internal_error_pct: 0.2
  bad_gateway_pct: 0.2
  gateway_timeout_pct: 0.3
  retry_after_sec: [2, 20]

  # Connection failures
  timeout_pct: 0.3
  timeout_sec: [10, 30]
  connection_reset_pct: 0.2
  connection_stall_pct: 0.0
  connection_stall_start_sec: [0, 2]
  connection_stall_sec: [30, 60]
  slow_response_pct: 3.0
  slow_response_sec: [2, 8]

  # Object and list corruption
  truncated_body_pct: 0.5
  wrong_content_length_pct: 0.3
  checksum_mismatch_pct: 0.5
  metadata_corruption_pct: 0.3
  stale_list_pct: 3.0
  malformed_xml_pct: 0.2

  # Burst patterns
  burst:
    enabled: true
    interval_sec: 90
    duration_sec: 10
    slow_down_pct: 35.0
    service_unavailable_pct: 10.0
```

### ChaosSMTP Full Example

```yaml
smtp:
  host: "127.0.0.1"
  port: 2525              # Use 0 in tests for an ephemeral loopback port
  hostname: "chaossmtp.local"
  data_size_limit: 10485760
  enable_smtputf8: true
  require_starttls: false       # true is reserved until TLS context support exists

admin:
  enabled: true
  host: "127.0.0.1"
  port: 8525
  admin_token: "my-secret-token"  # Auto-generated if omitted

metrics:
  database: "file:chaossmtp-metrics?mode=memory&cache=shared"
  timeseries_bucket_sec: 1

capture:
  mode: metadata          # discard | metadata | full
  max_message_bytes: 1048576
  max_messages: 1000

latency:
  base_ms: 120
  jitter_ms: 60

error_injection:
  selection_mode: priority

  # SMTP-stage failures
  rate_limit_pct: 3.0
  mail_from_tempfail_pct: 0.0
  mail_from_reject_pct: 0.0
  rcpt_to_tempfail_pct: 4.0
  rcpt_to_reject_pct: 0.0
  data_tempfail_pct: 3.0
  data_reject_pct: 1.0
  accept_then_drop_pct: 0.0
  malformed_reply_pct: 0.0
  wrong_reply_code_pct: 0.0
  connection_reset_pct: 0.0
  connection_stall_pct: 0.0
  slow_response_pct: 2.0

  # Delay ranges for selected SMTP behavior
  # retry_after_sec is validated config; current SMTP replies do not emit a Retry-After header.
  retry_after_sec: [1, 30]
  connection_stall_sec: [30, 60]
  slow_response_sec: [3, 15]

  # Burst patterns
  burst:
    enabled: true
    interval_sec: 60
    duration_sec: 8
    tempfail_pct: 50.0
    rate_limit_pct: 40.0
```

## Configuration Sections

### Server (ChaosLLM and ChaosWeb)

| Field | Type | Default (LLM/Web/Blob) | Description |
|---|---|---|---|
| `host` | string | `127.0.0.1` | Bind address |
| `port` | int | `8000` / `8200` / `8300` | Listen port |
| `workers` | int | `1` | Uvicorn worker count. Values > 1 require a file-backed metrics database. |
| `admin_token` | string | auto-generated | Bearer token for `/admin/*` endpoints |

!!! warning
    Binding to `0.0.0.0` or `::` is blocked by default. Errorworks servers are testing tools and should not be exposed to the network. Set `allow_external_bind: true` at the top level to override this safety check.

### SMTP Listener and Admin Sidecar (ChaosSMTP)

ChaosSMTP separates the SMTP listener from the HTTP admin sidecar:

| Field | Type | Default | Description |
|---|---|---|---|
| `smtp.host` | string | `127.0.0.1` | SMTP listener bind address |
| `smtp.port` | int | `2525` | SMTP listener port. Config accepts `0` for an ephemeral test port. |
| `smtp.hostname` | string | `chaossmtp.local` | Hostname announced to SMTP clients |
| `smtp.data_size_limit` | int | `10485760` | Maximum SMTP DATA size in bytes |
| `smtp.enable_smtputf8` | bool | `true` | Enable SMTPUTF8 extension support |
| `smtp.require_starttls` | bool | `false` | Reserved for future TLS context support. `true` is rejected. |
| `admin.enabled` | bool | `true` | Run the HTTP admin sidecar |
| `admin.host` | string | `127.0.0.1` | Admin sidecar bind address |
| `admin.port` | int | `8525` | Admin sidecar port |
| `admin.admin_token` | string | auto-generated | Bearer token for `/admin/*` endpoints |

`chaossmtp show-config` redacts `admin.admin_token`, but admin endpoints still require the bearer token at runtime.

### Metrics

| Field | Type | Default | Description |
|---|---|---|---|
| `database` | string | in-memory (shared) | SQLite database path or URI |
| `timeseries_bucket_sec` | int | `1` | Time-series aggregation bucket size in seconds |

Use `--database=/path/to/metrics.db` for persistent file-backed storage. See the [Metrics Guide](metrics.md) for details.

Default in-memory database URIs are service-specific:

- ChaosLLM: `file:chaosllm-metrics?mode=memory&cache=shared`
- ChaosWeb: `file:chaosweb-metrics?mode=memory&cache=shared`
- ChaosSMTP: `file:chaossmtp-metrics?mode=memory&cache=shared`

### Latency

| Field | Type | Default | Description |
|---|---|---|---|
| `base_ms` | int | `50` | Base latency added to every response (milliseconds) |
| `jitter_ms` | int | `30` | Random jitter range (+/- milliseconds) |

The actual delay per request is `(base_ms + random(-jitter_ms, +jitter_ms)) / 1000` seconds, clamped to zero.

### SMTP Capture

| Field | Type | Default | Description |
|---|---|---|---|
| `capture.mode` | `discard \| metadata \| full` | `metadata` | How accepted SMTP messages are stored |
| `capture.max_message_bytes` | int | `1048576` | Maximum bytes stored in `full` capture mode |
| `capture.max_messages` | int | `1000` | Maximum captured messages kept in memory |

`discard` records metrics only. `metadata` stores the envelope, subject, and safe headers. `full` stores base64-encoded message bytes up to `max_message_bytes`. Metadata and full capture keep at most `max_messages` records and drop the oldest first.

## Runtime Config Updates

You can update the configuration while the server is running via `POST /admin/config`:

```bash
# Increase rate limiting at runtime
curl -X POST http://localhost:8000/admin/config \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "error_injection": {
      "rate_limit_pct": 25.0
    }
  }'
```

```bash
# View current config
curl http://localhost:8000/admin/config \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Runtime updates use the same deep-merge behavior as config file layering. You only send the fields you want to change -- everything else is preserved.

ChaosSMTP runtime updates cover `error_injection`, `capture`, and `latency`. Listener binding, admin binding, metrics database, and admin token changes require restarting the server with a new config.

### How Runtime Updates Work

The server uses immutable Pydantic models (`frozen=True`) for all configuration. When you POST an update:

1. The current config is serialized to a dict
2. Your update is deep-merged into it
3. New immutable model instances are created and validated
4. The new components (error injector, response/content/capture component, latency simulator) are built
5. References are atomically swapped under a lock

Requests that are already in-flight continue using the old configuration. This guarantees each request sees a consistent configuration throughout its lifetime.

### Validation

If your update contains invalid values, the server returns 422 with a validation error and the configuration is unchanged:

```json
{
  "error": {
    "type": "validation_error",
    "message": "1 validation error for ErrorInjectionConfig\nrate_limit_pct\n  Input should be less than or equal to 100 [type=less_than_equal, ...]"
  }
}
```

## Related Pages

- [Presets](presets.md) -- Pre-built configuration profiles
- [ChaosLLM](chaosllm.md) -- LLM-specific error types and endpoints
- [ChaosWeb](chaosweb.md) -- Web-specific error types and endpoints
- [ChaosBlob](chaosblob.md) -- Blob-specific error types and endpoints
- [ChaosSMTP](chaossmtp.md) -- SMTP-specific listener, capture, and error injection behavior
- [Metrics](metrics.md) -- Metrics storage configuration
