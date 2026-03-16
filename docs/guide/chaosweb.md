# ChaosWeb Guide

ChaosWeb is a fake web server that injects configurable faults into HTTP responses for testing web scraping pipeline resilience. It serves HTML pages on any URL path and randomly injects errors -- anti-scraping blocks, broken encoding, SSRF redirects, and more.

Point your scraper at ChaosWeb to verify it handles every real-world failure mode before scraping production sites.

## Quick Start

```bash
# Start with a realistic error profile
uv run chaosweb serve --preset=realistic

# Your scraper fetches from localhost:8200 instead of the real site
curl http://127.0.0.1:8200/articles/some-page
```

## Endpoints

### Content Serving

| Endpoint | Method | Description |
|---|---|---|
| `/{any-path}` | GET | Catch-all route -- serves HTML with error injection |
| `/redirect` | GET | Redirect loop handler (hop counter management) |

Any GET request to any path returns either a successful HTML page or an injected error. The path is available to templates and echo mode for generating path-specific content.

### Health and Admin

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/health` | GET | None | Server health check (includes `run_id`, `started_utc`, `in_burst`) |
| `/admin/config` | GET | Bearer token | View current configuration |
| `/admin/config` | POST | Bearer token | Update configuration at runtime |
| `/admin/stats` | GET | Bearer token | Request statistics summary |
| `/admin/export` | GET | Bearer token | Export raw metrics data |
| `/admin/reset` | POST | Bearer token | Reset metrics and start new run |

Admin endpoints require an `Authorization: Bearer <token>` header.

## Error Injection

ChaosWeb injects five categories of errors, each controlled by percentage fields (0-100).

### HTTP Errors

Standard HTTP error responses with HTML error pages:

| Error Type | Status Code | Config Field | Description |
|---|---|---|---|
| Rate Limit | 429 | `rate_limit_pct` | Anti-scraping throttle, includes `Retry-After` |
| Forbidden | 403 | `forbidden_pct` | Bot detection block |
| Not Found | 404 | `not_found_pct` | Deleted or missing page |
| Gone | 410 | `gone_pct` | Permanently removed resource |
| Payment Required | 402 | `payment_required_pct` | Paywall / quota exceeded |
| Unavailable for Legal | 451 | `unavailable_for_legal_pct` | Geo-blocking |
| Service Unavailable | 503 | `service_unavailable_pct` | Maintenance page |
| Bad Gateway | 502 | `bad_gateway_pct` | Upstream failure |
| Gateway Timeout | 504 | `gateway_timeout_pct` | Upstream timeout |
| Internal Error | 500 | `internal_error_pct` | Server-side failure |

### Connection Failures

Network-level problems your scraper must handle:

| Error Type | Config Field | Behavior |
|---|---|---|
| Timeout | `timeout_pct` | Hangs for `timeout_sec` range, then returns 504 |
| Connection Reset | `connection_reset_pct` | Sends headers then drops the connection |
| Connection Stall | `connection_stall_pct` | Delays, stalls, then disconnects |
| Slow Response | `slow_response_pct` | Delays `slow_response_sec` then returns successful HTML |
| Incomplete Response | `incomplete_response_pct` | Sends partial HTML body then disconnects |

!!! warning
    Incomplete responses are particularly tricky -- your scraper receives a 200 status code and partial HTML, then the connection drops. Always validate that your parsed HTML is structurally complete.

### Content Malformations

HTTP 200 responses with corrupted content -- the subtlest failures:

| Error Type | Config Field | What Goes Wrong |
|---|---|---|
| Wrong Content-Type | `wrong_content_type_pct` | Declares `application/pdf` or similar instead of `text/html` |
| Encoding Mismatch | `encoding_mismatch_pct` | Header says UTF-8, body is ISO-8859-1 |
| Truncated HTML | `truncated_html_pct` | HTML cut off mid-tag |
| Invalid Encoding | `invalid_encoding_pct` | Non-decodable bytes in the declared encoding |
| Charset Confusion | `charset_confusion_pct` | HTTP header says one charset, `<meta>` tag says another |
| Malformed Meta | `malformed_meta_pct` | Invalid `<meta http-equiv="refresh">` directives |

### Redirect Injection

Tests your scraper's redirect handling:

| Error Type | Config Field | Behavior |
|---|---|---|
| Redirect Loop | `redirect_loop_pct` | Chain of 301 redirects up to `max_redirect_loop_hops` (default 10) |
| SSRF Redirect | `ssrf_redirect_pct` | 301 redirect to private IPs (169.254.169.254, 10.x.x.x, etc.) |

!!! warning
    SSRF redirect testing verifies that your scraper blocks redirects to private/internal addresses. Real scrapers should never follow redirects to cloud metadata endpoints like `http://169.254.169.254/`.

### Burst Patterns

Bursts simulate coordinated anti-scraping escalation -- a site suddenly blocks most requests, then backs off:

```yaml
error_injection:
  burst:
    enabled: true
    interval_sec: 60    # Burst every 60 seconds
    duration_sec: 8     # Lasts 8 seconds
    rate_limit_pct: 40  # During burst: 40% rate limits
    forbidden_pct: 30   # During burst: 30% forbidden
```

### Selection Mode

- **`priority`** (default): Errors evaluated in category order (connection > redirect > HTTP > malformed). First match wins.
- **`weighted`**: All percentages treated as proportional weights for uniform distribution.

## Content Modes

When a request is not selected for error injection, ChaosWeb generates HTML content using one of four modes:

### Random (default)

Generates syntactically valid HTML pages with random content:

```yaml
content:
  mode: random
  random:
    min_words: 100
    max_words: 500
    vocabulary: english  # or "lorem"
```

### Template

Renders HTML through a Jinja2 `SandboxedEnvironment`:

```yaml
content:
  mode: template
  template:
    body: >
      <html><head><title>{{ path }}</title></head>
      <body><h1>{{ path }}</h1>
      <p>{{ random_words(100, 300) }}</p></body></html>
```

Template helpers include `random_words`, `random_choice`, `random_float`, `timestamp`, and more. The `path` variable contains the requested URL path.

### Echo

Reflects request information as HTML. Content is HTML-escaped to prevent XSS when rendering in a browser:

```yaml
content:
  mode: echo
```

### Preset

Loads HTML page snapshots from a JSONL file:

```yaml
content:
  mode: preset
  preset:
    file: ./pages.jsonl
    selection: random  # or "sequential"
```

### Per-Request Overrides

When `allow_header_overrides` is `true` (the default), use the `X-Fake-Content-Mode` header:

```bash
curl -H "X-Fake-Content-Mode: echo" http://localhost:8200/articles/test
```

## Available Presets

ChaosWeb ships with five presets. Use them with `--preset=<name>`:

| Preset | Error Rate | Latency | Burst | Best For |
|---|---|---|---|---|
| `silent` | 0% | 200ms +/- 100ms | Off | Baseline throughput measurement |
| `gentle` | ~2% | 100ms +/- 50ms | Off | Basic scraping functionality testing |
| `realistic` | ~19% | 300ms +/- 150ms | 60s/8s | Production-like scraping conditions |
| `stress_scraping` | ~57% | 500ms +/- 200ms | 60s/10s | Heavy anti-scraping resilience testing |
| `stress_extreme` | ~98% | 800ms +/- 400ms | 30s/8s | Breaking-point stress testing |

### Preset Details

**`silent`** -- Zero errors. Every request returns HTML. Use this to establish baseline scraping throughput.

**`gentle`** -- Minimal error injection: 1% rate limits and 1% not-found errors. No connection failures, malformations, or bursts. Verifies your scraper handles basic error paths.

**`realistic`** -- Mimics typical web scraping conditions. Moderate rate limiting (5%), bot detection (3% forbidden), occasional slow responses (5%), and rare encoding issues. Bursts every 60 seconds simulate coordinated anti-scraping responses.

**`stress_scraping`** -- Heavy anti-scraping simulation. 15% rate limits, 10% forbidden, connection failures (5% timeout, 3% reset), content malformations (3% wrong content-type, 2% encoding mismatch), and SSRF redirect testing (1%). Aggressive burst escalation with 80% rate limiting.

**`stress_extreme`** -- Every error type is active at high rates. 25% rate limits, 15% forbidden, 10% timeout, 5% connection reset, heavy content malformations, redirect loops (3%), and SSRF redirects (2%). Very aggressive 30-second burst cycles. Use for finding failure modes and verifying graceful degradation.

## Usage Examples

### CLI

```bash
# Start with a preset
uv run chaosweb serve --preset=realistic

# Start with a custom config file
uv run chaosweb serve --config=my-config.yaml

# Via the unified CLI
uv run chaosengine web serve --preset=realistic
```

### Python

```python
from errorworks.web.config import ChaosWebConfig, load_config
from errorworks.web.server import ChaosWebServer, create_app

# Quick start
config = load_config(preset="realistic")
app = create_app(config)

# With full control
server = ChaosWebServer(config)
server.update_config({"error_injection": {"rate_limit_pct": 25.0}})
stats = server.get_stats()
```

## Related Pages

- [Presets](presets.md) -- Full preset comparison and customization
- [Configuration](configuration.md) -- YAML config file structure and precedence rules
- [Metrics](metrics.md) -- Querying request statistics
- [Testing Fixtures](testing-fixtures.md) -- In-process testing with pytest
