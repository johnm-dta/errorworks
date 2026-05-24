# errorworks

Composable chaos-testing services for LLM, web scraping, object storage, and outbound email pipelines.

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
redirects. Point your blob pipeline at a ChaosBlob server to exercise
S3-style throttling, stale listings, corrupted object reads, and metadata
surprises. Point your mail client at ChaosSMTP to test temporary recipient
failures, DATA rejections, rate limits, slow replies, and accepted-but-dropped
messages without relaying mail. Fault rates, error distributions, and latency
profiles are all configurable via CLI flags, YAML files, or built-in presets.

The HTTP servers run in-process during CI via pytest fixtures with no sockets or
containers. ChaosSMTP uses an ephemeral loopback TCP socket so standard SMTP
clients such as `smtplib` can exercise the real protocol. All servers record
metrics to a thread-safe SQLite store and support live reconfiguration through
bearer-token admin endpoints.

## Features

**Error injection**
- HTTP errors: 429, 529, 503, 502, 504, 500
- Connection failures: timeout, reset, stall
- Malformed responses: invalid JSON, truncated bodies, missing fields, wrong content-type
- Web-specific: SSRF redirects (private IPs, cloud metadata), encoding mismatches, truncated HTML, charset confusion
- Blob-specific: S3 `SlowDown`, `AccessDenied`, stale listings, malformed XML, truncated object bodies, ETag mismatch, metadata corruption
- SMTP-specific: temporary and permanent MAIL/RCPT/DATA failures, malformed DATA replies, slow responses, accepted-but-dropped messages

**Latency simulation**
- Configurable base delay with jitter
- Per-request latency injection, independent of error selection

**Response generation**
- Four content modes: `random` (vocabulary-based), `template` (Jinja2 sandbox), `echo` (reflect input), `preset` (JSONL bank)
- ChaosLLM returns OpenAI-compatible chat completion responses
- ChaosWeb returns HTML pages
- ChaosBlob stores and serves object bytes with S3-shaped XML list/error responses
- ChaosSMTP captures mail as metadata by default, with discard and full-message capture modes

**Presets**
- LLM: `silent`, `gentle`, `realistic`, `chaos`, `stress_aimd`, `stress_extreme`
- Web: `silent`, `gentle`, `realistic`, `stress_scraping`, `stress_extreme`
- Blob: `silent`, `gentle`, `realistic`, `stress_storage`, `stress_extreme`
- SMTP: `silent`, `gentle`, `realistic`, `stress_delivery`, `stress_extreme`

**Metrics and admin**
- SQLite-backed metrics with timeseries aggregation
- Admin endpoints for stats, config, export, and reset (bearer-token auth)

**Testing support**
- In-process pytest fixtures with marker-based configuration
- No containers required in CI; SMTP fixture binds an ephemeral loopback port

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
chaosweb serve --preset=stress_scraping --port=9000

# Blob server
chaosblob serve --preset=realistic --port=8300

# SMTP server
chaossmtp serve --preset=realistic --port=2525

# Unified CLI
chaosengine llm serve --preset=gentle
chaosengine web serve --preset=stress_scraping
chaosengine blob serve --preset=stress_storage
chaosengine smtp serve --preset=stress_delivery
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
error_injection:
  rate_limit_pct: 10.0
  service_unavailable_pct: 2.0
latency:
  base_ms: 50
  jitter_ms: 20
response:
  mode: random
  random:
    vocabulary: english
```

```bash
chaosllm serve --preset=gentle --config=config.yaml --port=8080
```

## Documentation

Full documentation is available at [johnm-dta.github.io/errorworks](https://johnm-dta.github.io/errorworks).

## Architecture

errorworks uses a composition-based design: each server type (ChaosLLM,
ChaosWeb, ChaosBlob, ChaosSMTP) composes shared engine components rather than
inheriting from base classes. The core engine provides an `InjectionEngine` for
fault selection, a `MetricsStore` for recording, a `LatencySimulator` for
delays, and a `ConfigLoader` for YAML/preset merging. All configuration models
are frozen Pydantic instances; runtime updates create new model instances and
atomically swap references under lock, ensuring thread-safe request handling
without mid-request inconsistency.

---

An open-source project by the [Digital Transformation Agency](https://www.dta.gov.au/).

Licensed under [MIT](LICENSE).
