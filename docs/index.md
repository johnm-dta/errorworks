# errorworks

**Composable chaos-testing services for LLM and web scraping pipelines.**

errorworks gives you drop-in fake servers that inject faults, simulate latency,
generate realistic responses, and record metrics -- so you can test how your
client code behaves when things go wrong, before they go wrong in production.

## Get started in 60 seconds

```bash
# Install
pip install errorworks

# Start a fake OpenAI-compatible server
chaosllm serve --preset=realistic

# In another terminal, make a request
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test-key" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

Some requests return `200 OK` with generated content. Others return `429`,
`503`, or malformed responses -- exactly what happens in the real world.

## What's included

### ChaosLLM

A fake OpenAI-compatible API server. Point your OpenAI client at it and test how
your code handles rate limits (429), server errors (503/500), connection
timeouts, truncated streams, invalid JSON, and more.

### ChaosWeb

A fake web server for scraping resilience tests. Serves HTML pages that
intermittently break with encoding mismatches, truncated content, SSRF redirects,
and other real-world failure modes that trip up web scrapers.

## Next steps

<div class="grid cards" markdown>

-   **Installation**

    Set up errorworks with pip or uv, including development installs.

    [:octicons-arrow-right-24: Installation](getting-started/installation.md)

-   **Quick Start**

    Walk through a complete scenario with ChaosLLM, ChaosWeb, and pytest fixtures.

    [:octicons-arrow-right-24: Quick Start](getting-started/quickstart.md)

-   **Guide**

    Deep dives into presets, configuration, metrics, and testing fixtures.

    [:octicons-arrow-right-24: Guide](guide/chaosllm.md)

-   **Reference**

    CLI commands, HTTP API endpoints, and configuration schema.

    [:octicons-arrow-right-24: Reference](reference/cli.md)

</div>
