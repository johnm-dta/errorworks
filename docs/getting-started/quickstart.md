# Quick Start

This walkthrough takes you from zero to chaos-testing in a few minutes. You will
start fake servers, observe fault injection in action, check metrics, and write
your first test using the pytest fixture.

## 1. Start ChaosLLM

Launch a fake OpenAI-compatible server with the `realistic` preset, which
configures a mix of successful responses, rate limits, and server errors:

```bash
chaosllm serve --preset=realistic
```

The server starts on `http://localhost:8000` by default.

## 2. Make a request

In another terminal, send a standard chat completion request:

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test-key" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "What is chaos testing?"}]
  }'
```

## 3. Observe the chaos

Run the curl command several times. You will see a mix of:

- **200 OK** -- a generated chat completion response
- **429 Too Many Requests** -- simulated rate limiting
- **503 Service Unavailable** -- simulated server overload
- Occasional malformed responses (truncated JSON, wrong content types)

This is exactly the kind of unreliability your client code needs to handle.

## 4. Check metrics

ChaosLLM records every request. Query the admin stats endpoint to see what
happened:

```bash
curl http://localhost:8000/admin/stats \
  -H "Authorization: Bearer <admin_token>"
```

!!! note
    The admin token is randomly generated at startup and printed to the server
    log. You can also set it explicitly via the `server.admin_token` config
    field or the `--admin-token` CLI flag.

The response includes counts of each status code returned, latency percentiles,
and error category breakdowns.

## 5. Try ChaosWeb

ChaosWeb works the same way, but serves HTML pages for scraping resilience tests:

```bash
chaosweb serve --preset=realistic
```

The web server starts on `http://localhost:8200` by default. Fetch a page:

```bash
curl http://localhost:8200/articles/test
```

You will see a mix of valid HTML, encoding mismatches, truncated content, and
other failure modes that commonly break web scrapers.

## 6. Use the pytest fixture

The real power of errorworks is in automated testing. The built-in pytest fixtures
let you spin up an in-process fake server with no real network socket:

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

The `@pytest.mark.chaosllm` marker configures the server for that test. The
`chaosllm` fixture provides helper methods like `post_completion()`,
`get_stats()`, and `update_config()`.

To run this test, make sure errorworks is installed with test extras and invoke
pytest:

```bash
uv run pytest -m chaosllm
```

## Next steps

- Learn about all the fault types ChaosLLM can inject: [ChaosLLM Guide](../guide/chaosllm.md)
- Explore ChaosWeb's scraping-specific faults: [ChaosWeb Guide](../guide/chaosweb.md)
- See available presets and how to customize them: [Presets](../guide/presets.md)
- Dive into the testing fixture API: [Testing Fixtures](../guide/testing-fixtures.md)
