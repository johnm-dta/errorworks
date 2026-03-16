# ChaosLLM Guide

ChaosLLM is a fake OpenAI-compatible chat completions server that injects configurable faults into LLM API responses. Point your LLM client at ChaosLLM instead of the real API, and it will return a mix of successful responses and realistic failures -- rate limits, timeouts, malformed JSON, and more.

Use ChaosLLM to verify that your LLM pipeline handles every failure mode before it hits production.

## Quick Start

```bash
# Start with a realistic error profile
uv run chaosllm serve --preset=realistic

# Your client talks to localhost:8000 instead of api.openai.com
export OPENAI_BASE_URL=http://127.0.0.1:8000/v1
```

## Endpoints

### Chat Completions

| Endpoint | Method | Description |
|---|---|---|
| `/v1/chat/completions` | POST | OpenAI-compatible chat completions |
| `/openai/deployments/{deployment}/chat/completions` | POST | Azure OpenAI-compatible chat completions |

Both endpoints accept the standard OpenAI request body:

```json
{
  "model": "gpt-4",
  "messages": [
    {"role": "user", "content": "Hello"}
  ]
}
```

### Health and Admin

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/health` | GET | None | Server health check (includes `run_id`, `started_utc`, `in_burst`) |
| `/admin/config` | GET | Bearer token | View current configuration |
| `/admin/config` | POST | Bearer token | Update configuration at runtime |
| `/admin/stats` | GET | Bearer token | Request statistics summary |
| `/admin/export` | GET | Bearer token | Export raw metrics data |
| `/admin/reset` | POST | Bearer token | Reset metrics and start new run |

Admin endpoints require an `Authorization: Bearer <token>` header. The token is auto-generated at startup and printed to the console, or you can set it in your config file.

## Error Injection

ChaosLLM injects three categories of errors, each controlled by percentage fields (0-100) in the configuration.

### HTTP Errors

These return proper HTTP error responses with OpenAI-formatted error bodies:

| Error Type | Status Code | Config Field | Description |
|---|---|---|---|
| Rate Limit | 429 | `rate_limit_pct` | Includes `Retry-After` header |
| Capacity | 529 | `capacity_529_pct` | Azure-specific "model overloaded" |
| Service Unavailable | 503 | `service_unavailable_pct` | Temporary outage |
| Bad Gateway | 502 | `bad_gateway_pct` | Upstream failure |
| Gateway Timeout | 504 | `gateway_timeout_pct` | Upstream timeout |
| Internal Error | 500 | `internal_error_pct` | Server-side failure |
| Forbidden | 403 | `forbidden_pct` | Permission denied |
| Not Found | 404 | `not_found_pct` | Resource missing |

Rate limit and capacity errors include a `Retry-After` header with a random value in the configured range (default `[1, 5]` seconds).

### Connection Failures

These simulate network-level problems that your HTTP client must handle:

| Error Type | Config Field | Behavior |
|---|---|---|
| Timeout | `timeout_pct` | Hangs for `timeout_sec` range, then returns 504 or drops |
| Connection Reset | `connection_reset_pct` | Immediately drops the TCP connection |
| Connection Failed | `connection_failed_pct` | Short delay (`connection_failed_lead_sec`), then drops |
| Connection Stall | `connection_stall_pct` | Optional start delay, then stalls for `connection_stall_sec`, then drops |
| Slow Response | `slow_response_pct` | Delays `slow_response_sec` then returns a successful response |

### Malformed Responses

These return HTTP 200 with corrupted content -- the hardest failures to detect:

| Error Type | Config Field | What Goes Wrong |
|---|---|---|
| Invalid JSON | `invalid_json_pct` | Response body is not parseable JSON |
| Truncated | `truncated_pct` | JSON cuts off mid-stream |
| Empty Body | `empty_body_pct` | 200 OK with zero-length body |
| Missing Fields | `missing_fields_pct` | Valid JSON but missing `choices`, `message`, etc. |
| Wrong Content-Type | `wrong_content_type_pct` | Returns `text/html` instead of `application/json` |

### Selection Mode

The `selection_mode` field controls how errors are chosen when multiple types are configured:

- **`priority`** (default): Errors are evaluated in a fixed order. The first one whose random check passes wins. This gives predictable behavior -- higher-priority errors (connection failures) fire before lower-priority ones (malformed responses).
- **`weighted`**: All configured error percentages are treated as proportional weights. A single random roll selects the error type. This gives a more uniform distribution.

## Response Modes

When a request is not selected for error injection, ChaosLLM generates a successful response using one of four modes:

### Random (default)

Generates responses with random words from a configurable vocabulary:

```yaml
response:
  mode: random
  random:
    min_words: 20
    max_words: 100
    vocabulary: english  # or "lorem" for Lorem Ipsum
```

### Template

Renders responses through a Jinja2 `SandboxedEnvironment` with built-in helpers:

```yaml
response:
  mode: template
  template:
    body: '{"result": "processed at {{ timestamp() }}"}'
```

Available template helpers include `random_choice`, `random_float`, `timestamp`, and others.

### Echo

Reflects the user's input back in the response. Useful for verifying your client sends the right data:

```yaml
response:
  mode: echo
```

### Preset

Loads canned responses from a JSONL file:

```yaml
response:
  mode: preset
  preset:
    file: ./responses.jsonl
    selection: random  # or "sequential"
```

### Per-Request Overrides

When `allow_header_overrides` is `true` (the default), clients can override the response mode per-request:

```bash
curl -H "X-Fake-Response-Mode: echo" \
     -H "X-Fake-Template: {\"echo\": \"{{ messages[-1].content }}\"}" \
     http://localhost:8000/v1/chat/completions \
     -d '{"model": "gpt-4", "messages": [{"role": "user", "content": "test"}]}'
```

## Burst Patterns

Bursts simulate periodic provider stress -- a wave of rate limits and capacity errors that comes and goes:

```yaml
error_injection:
  burst:
    enabled: true
    interval_sec: 60    # A burst starts every 60 seconds
    duration_sec: 5     # Each burst lasts 5 seconds
    rate_limit_pct: 50  # During burst: 50% rate limits
    capacity_pct: 30    # During burst: 30% capacity errors
```

Outside burst windows, normal error percentages apply. During a burst, the burst percentages temporarily override the baseline rates for rate limits and capacity errors.

!!! tip
    The `/health` endpoint includes an `in_burst` field so you can observe burst timing from your test harness.

## Available Presets

ChaosLLM ships with six presets. Use them with `--preset=<name>`:

| Preset | Error Rate | Latency | Burst | Best For |
|---|---|---|---|---|
| `silent` | 0% | 10ms +/- 5ms | Off | Baseline measurements, throughput testing |
| `gentle` | ~2% | 50ms +/- 20ms | Off | Basic functionality testing, debugging |
| `realistic` | ~10% | 100ms +/- 50ms | 60s/5s | Production-like conditions |
| `stress_aimd` | ~23% | 30ms +/- 15ms | 30s/5s | AIMD throttle and backoff testing |
| `stress_extreme` | ~45% | 10ms +/- 5ms | 15s/5s | Survival under harsh conditions |
| `chaos` | ~25% | 100ms +/- 100ms | 20s/8s | Error handling coverage, every failure type |

### Preset Details

**`silent`** -- Zero errors. Every request succeeds. Use this to establish baseline throughput before adding chaos.

**`gentle`** -- Minimal error injection (1% rate limit, 0.5% capacity, 0.5% service unavailable). No connection failures or malformed responses. Good for verifying your pipeline works at all.

**`realistic`** -- Mimics typical Azure OpenAI behavior. Moderate rate limiting (5%), occasional capacity errors (2%), rare connection issues, and very rare malformed responses. Bursts every 60 seconds elevate rate limits to 50%.

**`stress_aimd`** -- Specifically targets AIMD throttle testing. High rate limits (15%) and capacity errors (5%) with frequent 30-second burst cycles. Connection failures are disabled to focus on HTTP-level retry behavior.

**`stress_extreme`** -- Maximum HTTP stress. 20% rate limits, 10% capacity errors, 5% internal errors. Aggressive 15-second burst cycles with 90% rate limiting during bursts. Includes malformed responses (3% invalid JSON, 2% truncated).

**`chaos`** -- Every error type is active. HTTP errors, connection failures, malformed responses, and aggressive bursts. Not suitable for performance measurements due to the wide variance, but excellent for error handling coverage.

## Usage Examples

### CLI

```bash
# Start with a preset
uv run chaosllm serve --preset=realistic

# Start with a custom config file
uv run chaosllm serve --config=my-config.yaml

# Preset + overrides
uv run chaosllm serve --preset=gentle --rate-limit-pct=10.0

# Via the unified CLI
uv run chaosengine llm serve --preset=realistic
```

### Python

```python
from errorworks.llm.config import ChaosLLMConfig, load_config
from errorworks.llm.server import ChaosLLMServer, create_app

# Quick start
config = load_config(preset="realistic")
app = create_app(config)

# With full control
server = ChaosLLMServer(config)
server.update_config({"error_injection": {"rate_limit_pct": 25.0}})
stats = server.get_stats()
```

## Related Pages

- [Presets](presets.md) -- Full preset comparison and customization
- [Configuration](configuration.md) -- YAML config file structure and precedence rules
- [Metrics](metrics.md) -- Querying request statistics
- [Testing Fixtures](testing-fixtures.md) -- In-process testing with pytest
