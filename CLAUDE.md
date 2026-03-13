# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Errorworks is a composable chaos-testing service framework for LLM and web scraping pipelines. It provides fake servers that inject faults, simulate latency, generate responses, and record metrics to test client resilience.

## Commands

```bash
# Install (uses uv)
uv sync --all-extras

# Run all tests
uv run pytest

# Run a single test file or test
uv run pytest tests/unit/llm/test_server.py
uv run pytest tests/unit/llm/test_server.py::test_name -k "pattern"

# Run tests with coverage
uv run pytest --cov

# Run by marker
uv run pytest -m chaosllm
uv run pytest -m chaosweb

# Lint and format
uv run ruff check src tests
uv run ruff check --fix src tests
uv run ruff format src tests

# Type check
uv run mypy src

# Run servers
uv run chaosllm serve --preset=realistic
uv run chaosweb serve --preset=realistic
uv run chaosengine llm serve  # unified CLI
```

## Architecture

### Composition-based design

Each chaos plugin (ChaosLLM, ChaosWeb) **composes** shared engine utilities rather than inheriting from base classes. This keeps HTTP concerns out of domain logic.

```
src/errorworks/
├── engine/          # Shared core: InjectionEngine, MetricsStore, LatencySimulator, ConfigLoader
├── llm/             # Fake OpenAI-compatible server (Starlette ASGI)
├── web/             # Fake web server for scraping resilience tests (Starlette ASGI)
├── llm_mcp/         # MCP server for ChaosLLM metrics analysis
└── testing/         # Pytest fixture support
```

### Key engine components

- **InjectionEngine** (`engine/injection_engine.py`): Burst state machine + weighted/priority error selection. Thread-safe; selection is deterministic per-call (no cross-request coupling beyond burst timing). Accepts injectable `time_func` and `rng` for deterministic testing.
- **MetricsStore** (`engine/metrics_store.py`): Thread-safe SQLite with thread-local connections, WAL mode for file DBs, schema-driven DDL from `MetricsSchema` dataclass. Timeseries aggregation via UPSERT.
- **ConfigLoader** (`engine/config_loader.py`): YAML preset loading with deep merge. Precedence: CLI flags > config file > preset > defaults.
- **LatencySimulator** (`engine/latency.py`): Artificial delays — `(base_ms ± jitter_ms) / 1000` seconds, clamped to 0.

### Config snapshot pattern

Request handlers snapshot component references under `_config_lock` at the start of each request. This prevents concurrent `update_config()` calls from producing half-updated views mid-request. When modifying server code, always follow this pattern.

### Immutable config update flow

All Pydantic config models use `frozen=True, extra="forbid"`. Runtime updates go through `server.update_config()` which merges the update dict, creates new immutable model instances, recreates affected components, and atomically swaps references under lock.

### Error injection categories

- **LLM**: HTTP errors (429/529/503/502/504/500), connection failures (timeout/reset/stall), malformed responses (invalid JSON, truncated, missing fields, wrong content-type)
- **Web**: All LLM categories plus SSRF redirects (private IPs, cloud metadata), content malformations (encoding mismatch, truncated HTML, charset confusion)

### Response generation modes

Both LLM and Web plugins support four content modes:
- `random`: Vocabulary-based text generation (English or Lorem Ipsum)
- `template`: Jinja2 `SandboxedEnvironment` with helpers (random_choice, random_float, timestamp, etc.)
- `echo`: Reflect user input (HTML-escaped in web for XSS safety)
- `preset`: JSONL bank with random/sequential selection

### Test fixtures

`tests/fixtures/chaosllm.py` and `tests/fixtures/chaosweb.py` provide in-process test fixtures using Starlette's `TestClient` (no real socket). Tests use `@pytest.mark.chaosllm(preset="...", rate_limit_pct=25.0)` / `@pytest.mark.chaosweb(preset="...")` markers to configure servers. The fixture's `_build_config_from_marker()` translates marker kwargs into config objects.

Key fixture helpers: `post_completion()`, `fetch_page()`, `update_config()`, `get_stats()`, `wait_for_requests()`.

## Style

- Python 3.12+, strict mypy, ruff for linting/formatting
- Line length: 140
- Ruff rules: E, F, W, I, UP, B, SIM, C4, DTZ, T20, RUF (print statements forbidden in src, allowed in tests)
- `SIM108` (ternary) is ignored — prefer explicit if/else
- First-party import: `errorworks`
