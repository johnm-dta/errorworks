# errorworks

Composable chaos-testing services for LLM and web scraping pipelines.

[![CI](https://github.com/johnm-dta/errorworks/actions/workflows/ci.yml/badge.svg)](https://github.com/johnm-dta/errorworks/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/errorworks)](https://pypi.org/project/errorworks/)
[![Python](https://img.shields.io/pypi/pyversions/errorworks)](https://pypi.org/project/errorworks/)
[![License](https://img.shields.io/pypi/l/errorworks)](https://github.com/johnm-dta/errorworks/blob/main/LICENSE)

## What is errorworks?

Testing how your code handles API failures, malformed responses, rate limits, and
network issues is hard. Unit-testing a retry loop against a mock is easy; knowing
whether your pipeline actually degrades gracefully under realistic fault patterns
requires a server that behaves badly on purpose.

errorworks provides fake servers that inject configurable faults into your test
traffic. Point your LLM client at a ChaosLLM server to verify it retries on 429s
and surfaces clean errors on malformed JSON. Point your scraper at a ChaosWeb
server to confirm it handles truncated HTML, encoding mismatches, and SSRF
redirects. Fault rates, error distributions, and latency profiles are all
configurable via CLI flags, YAML files, or built-in presets.

Everything runs in-process during CI via pytest fixtures (no sockets, no
containers), records metrics to a thread-safe SQLite store, and supports live
reconfiguration through admin endpoints.

## Features

**Error injection**
- HTTP errors: 429, 529, 503, 502, 504, 500
- Connection failures: timeout, reset, stall
- Malformed responses: invalid JSON, truncated bodies, missing fields, wrong content-type
- Web-specific: SSRF redirects (private IPs, cloud metadata), encoding mismatches, truncated HTML, charset confusion

**Latency simulation**
- Configurable base delay with jitter
- Per-request latency injection, independent of error selection

**Response generation**
- Four content modes: `random` (vocabulary-based), `template` (Jinja2 sandbox), `echo` (reflect input), `preset` (JSONL bank)
- ChaosLLM returns OpenAI-compatible chat completion responses
- ChaosWeb returns HTML pages

**Presets**
- LLM: `silent`, `gentle`, `realistic`, `chaos`, `stress_aimd`
- Web: `silent`, `gentle`, `realistic`, `chaos`, `stress_scraping`, `stress_extreme`

**Metrics and admin**
- SQLite-backed metrics with timeseries aggregation
- Admin endpoints for stats, config, export, and reset (bearer-token auth)

**Testing support**
- In-process pytest fixtures with marker-based configuration
- No sockets or containers required in CI

## Quick start

```bash
pip install errorworks

# Start a fake OpenAI server with realistic fault injection
chaosllm serve --preset=realistic

# In another terminal
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4", "messages": [{"role": "user", "content": "Hello"}]}'
```

## Usage

### CLI servers

```bash
# LLM server
chaosllm serve --preset=realistic --port=8000

# Web server
chaosweb serve --preset=chaos --port=9000

# Unified CLI
chaosengine llm serve --preset=gentle
chaosengine web serve --preset=stress_scraping
```

### Pytest fixtures

```python
import pytest

@pytest.mark.chaosllm(preset="realistic", rate_limit_pct=25.0)
def test_retry_on_rate_limit(chaosllm):
    response = chaosllm.post_completion(
        model="gpt-4",
        messages=[{"role": "user", "content": "test"}],
    )
    assert response.status_code in (200, 429)
```

### Configuration

Presets provide sensible defaults. Override individual settings with a YAML config
file or CLI flags. Precedence: CLI flags > config file > preset > defaults.

```yaml
# config.yaml
error_rate_pct: 30.0
rate_limit_pct: 10.0
latency:
  base_ms: 50
  jitter_ms: 20
response:
  mode: random
  vocabulary: english
```

```bash
chaosllm serve --preset=gentle --config=config.yaml --port=8080
```

## Documentation

Full documentation is available at [johnm-dta.github.io/errorworks](https://johnm-dta.github.io/errorworks).

## Architecture

errorworks uses a composition-based design: each server type (ChaosLLM, ChaosWeb)
composes shared engine components rather than inheriting from base classes. The
core engine provides an `InjectionEngine` for fault selection, a `MetricsStore`
for recording, a `LatencySimulator` for delays, and a `ConfigLoader` for
YAML/preset merging. All configuration models are frozen Pydantic instances;
runtime updates create new model instances and atomically swap references under
lock, ensuring thread-safe request handling without mid-request inconsistency.

---

An open-source project by the [Digital Transformation Agency](https://www.dta.gov.au/).

Licensed under [MIT](LICENSE).
