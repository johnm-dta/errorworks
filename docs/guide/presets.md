# Presets Guide

Presets are pre-built configuration profiles that set error rates, latency, burst patterns, and response generation for common testing scenarios. Instead of manually configuring dozens of fields, pick a preset that matches your testing goal.

## Using Presets

```bash
# CLI
uv run chaosllm serve --preset=realistic
uv run chaosweb serve --preset=stress_scraping
uv run chaosblob serve --preset=stress_storage

# Python
from errorworks.llm.config import load_config
config = load_config(preset="realistic")
```

## ChaosLLM Presets

### Comparison Table

| Preset | Rate Limit | Capacity 529 | Server Errors | Connection Failures | Malformed | Burst | Latency |
|---|---|---|---|---|---|---|---|
| `silent` | 0% | 0% | 0% | 0% | 0% | Off | 10 +/- 5ms |
| `gentle` | 1% | 0.5% | 0.5% svc unavail | 0% | 0% | Off | 50 +/- 20ms |
| `realistic` | 5% | 2% | 0.5% svc, 0.2% internal, 0.1% bad gw, 0.2% gw timeout | 0.2% timeout, 0.1% reset, 1% slow | 0.1% invalid JSON, 0.1% truncated, 0.1% missing fields | 60s/5s (50% rl, 30% cap) | 100 +/- 50ms |
| `stress_aimd` | 15% | 5% | 2% svc, 0.5% internal, 0.2% bad gw, 0.3% gw timeout | 0.5% slow | 0% | 30s/5s (80% rl, 50% cap) | 30 +/- 15ms |
| `stress_extreme` | 20% | 10% | 3% svc, 5% internal, 1% bad gw, 1% gw timeout | 0% | 3% invalid JSON, 2% truncated | 15s/5s (90% rl, 70% cap) | 10 +/- 5ms |
| `chaos` | 6.25% | 3.13% | 1.88% svc, 1.88% internal, 1.25% bad gw, 1.25% gw timeout | 1.25% timeout, 0.94% reset, 1.88% slow | 1.25% invalid JSON, 0.94% truncated, 0.63% empty, 0.94% missing, 0.31% wrong ct | 20s/8s (90% rl, 70% cap) | 100 +/- 100ms |

### When to Use Each

| Preset | Use When |
|---|---|
| `silent` | Measuring maximum pipeline throughput without noise |
| `gentle` | Verifying basic pipeline operation and debugging |
| `realistic` | Testing against production-like Azure OpenAI conditions |
| `stress_aimd` | Tuning AIMD throttle parameters and backoff behavior |
| `stress_extreme` | Verifying pipeline survives under harsh HTTP error rates |
| `chaos` | Achieving error handling coverage across every failure type |

## ChaosWeb Presets

### Comparison Table

| Preset | Rate Limit | Forbidden | Not Found | Connection Failures | Content Malform. | Redirects | Burst | Latency |
|---|---|---|---|---|---|---|---|---|
| `silent` | 0% | 0% | 0% | 0% | 0% | 0% | Off | 200 +/- 100ms |
| `gentle` | 1% | 0% | 1% | 0% | 0% | 0% | Off | 100 +/- 50ms |
| `realistic` | 5% | 3% | 2% | 0.5% timeout, 0.2% reset, 5% slow | 1% wrong ct, 1% encoding, 0.5% truncated | 0% | 60s/8s (40% rl, 30% forbid) | 300 +/- 150ms |
| `stress_scraping` | 15% | 10% | 3% | 5% timeout, 3% reset, 8% slow, 2% incomplete | 3% wrong ct, 2% encoding, 2% truncated, 1% charset | 1% SSRF | 60s/10s (80% rl, 50% forbid) | 500 +/- 200ms |
| `stress_extreme` | 25% | 15% | 5% | 10% timeout, 5% reset, 3% stall, 5% slow, 5% incomplete | 5% wrong ct, 3% encoding, 3% truncated, 2% invalid enc, 2% charset, 1% meta | 3% loop, 2% SSRF | 30s/8s (90% rl, 70% forbid) | 800 +/- 400ms |

### When to Use Each

| Preset | Use When |
|---|---|
| `silent` | Measuring scraping throughput without error injection overhead |
| `gentle` | Verifying basic scraping functionality works before adding stress |
| `realistic` | Testing against typical web scraping production conditions |
| `stress_scraping` | Verifying retry logic, backoff, and error routing under pressure |
| `stress_extreme` | Finding failure modes and verifying graceful degradation |

## ChaosBlob Presets

### Comparison Table

| Preset | SlowDown | HTTP Errors | Connection Failures | Object Corruption | List Corruption | Burst | Latency |
|---|---|---|---|---|---|---|---|
| `silent` | 0% | 0% | 0% | 0% | 0% | Off | 50 +/- 25ms |
| `gentle` | 1% | 0.5% not found | 0% | 0% | 0% | Off | 100 +/- 50ms |
| `realistic` | 4% | 0.5% access denied, 1% not found, 0.8% svc, 0.2% internal, 0.2% bad gw, 0.3% gw timeout | 0.3% timeout, 0.2% reset, 3% slow | 0.5% truncated, 0.3% wrong length, 0.5% checksum, 0.3% metadata | 3% stale, 0.2% malformed XML | 90s/10s (35% slow, 10% svc) | 150 +/- 75ms |
| `stress_storage` | 8% | 4% not found | 8% slow | 8% truncated, 6% wrong length, 8% checksum, 6% metadata | 12% stale, 4% malformed XML | 60s/12s (60% slow, 20% svc) | 250 +/- 150ms |
| `stress_extreme` | 20% | 5% access denied, 5% not found, 8% svc, 4% internal, 3% bad gw, 5% gw timeout | 8% timeout, 5% reset, 4% stall, 8% slow | 6% truncated, 5% wrong length, 6% checksum, 4% metadata | 8% stale, 4% malformed XML | 30s/8s (90% slow, 60% svc) | 600 +/- 300ms |

### When to Use Each

| Preset | Use When |
|---|---|
| `silent` | Measuring object workflow throughput without injected failures |
| `gentle` | Verifying happy-path PUT/GET/list behavior with light throttling |
| `realistic` | Testing common object-store throttling, stale list, and rare read faults |
| `stress_storage` | Exercising body integrity, metadata validation, and stale listing recovery |
| `stress_extreme` | Finding retry, timeout, and corruption handling breakpoints |

## Combining Presets with Overrides

Presets provide the base configuration, but you can override any setting on top. Configuration precedence (highest to lowest):

1. **CLI flags** -- Override individual settings
2. **Config file** -- `--config=my-config.yaml`
3. **Preset** -- `--preset=realistic`
4. **Defaults** -- Built-in Pydantic defaults

### Example: Preset with CLI Override

```bash
# Start with realistic, but increase rate limiting
uv run chaosllm serve --preset=realistic --rate-limit-pct=20.0
```

### Example: Preset with Config File Override

```yaml
# my-overrides.yaml
error_injection:
  rate_limit_pct: 20.0
  burst:
    interval_sec: 30  # More frequent bursts
```

```bash
uv run chaosllm serve --preset=realistic --config=my-overrides.yaml
```

The config file's `rate_limit_pct: 20.0` overrides the preset's `5.0`, and the burst `interval_sec: 30` overrides the preset's `60`. All other preset values are preserved.

### Example: Python with Overrides

```python
from errorworks.llm.config import load_config

config = load_config(
    preset="realistic",
    cli_overrides={
        "error_injection": {"rate_limit_pct": 20.0},
        "latency": {"base_ms": 200},
    },
)
```

!!! tip
    Deep merge means you only need to specify the fields you want to change. Nested objects are merged recursively -- you do not need to repeat the entire `burst` section just to change `interval_sec`.

## Listing Available Presets

```python
from errorworks.llm.config import list_presets as list_llm_presets
from errorworks.blob.config import list_presets as list_blob_presets
from errorworks.web.config import list_presets as list_web_presets

print(list_llm_presets())  # ['chaos', 'gentle', 'realistic', 'silent', 'stress_aimd', 'stress_extreme']
print(list_web_presets())  # ['gentle', 'realistic', 'silent', 'stress_extreme', 'stress_scraping']
print(list_blob_presets())  # ['gentle', 'realistic', 'silent', 'stress_extreme', 'stress_storage']
```

## Related Pages

- [ChaosLLM](chaosllm.md) -- Full ChaosLLM endpoint and error injection reference
- [ChaosWeb](chaosweb.md) -- Full ChaosWeb endpoint and error injection reference
- [ChaosBlob](chaosblob.md) -- Full ChaosBlob endpoint and error injection reference
- [Configuration](configuration.md) -- YAML config file structure and precedence details
