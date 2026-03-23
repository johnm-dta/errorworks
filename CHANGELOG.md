# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.2] - 2026-03-23

### Fixed

- **Multi-worker startup crash**: All presets and default config set `workers=4`, but uvicorn
  requires an import string (not a Python object) when `workers > 1`. Implemented factory pattern
  with environment variable config serialization. Env var is cleaned up after uvicorn exits.
- **Metrics misclassification** (7 bugs): Both LLM and Web metrics classifiers gated
  `connection_error` on `status_code is None`, but servers record some connection errors with
  non-None status codes (timeout→504, incomplete_response→200). Classifiers now check `error_type`
  first. Also removed `slow_response` from Web connection error set (it's a successful response
  with extra delay) and added `redirect_loop_terminated` to the redirect category.
- **OpenAI API fidelity** (3 bugs): Added missing `param` field to all error responses, fixed
  timeout 504 body to use standard format (`type: server_error`, `code: timeout`), and fixed echo
  mode to extract text from multi-modal message content instead of dumping raw list representation.
- **CLI bugs** (6 bugs, 3 in each CLI): `show-config` YAML output no longer contains
  `!!python/tuple` tags (uses `model_dump(mode="json")`), `--format` flag now validates input
  and rejects unsupported formats, multi-worker env var cleaned up via `try/finally`.
- **MCP analysis logic** (4 bugs): Percentile calculation off-by-one (`int(n*p)` → `ceil(n*p)-1`),
  trailing burst no longer silently dropped from `get_burst_events`, unfinished bursts excluded
  from recovery time in `analyze_aimd_behavior`, `find_anomalies` now checks all 6 error columns
  instead of only `rate_limited` and `capacity_error`.
- **Thread safety**: Added double-checked locking to `ContentGenerator._get_preset_bank()`,
  porting the pattern already used in the LLM `ResponseGenerator`.
- **Memory scalability** (2 bugs): `get_stats()` loaded all latency values into Python memory
  for percentile computation — replaced with SQL `LIMIT 1 OFFSET` queries (O(1) memory).
  `export_data()` loaded entire database unbounded — added `limit`/`offset` parameters.

### Changed

- `InjectionEngine` docstring updated to accurately explain why RNG thread safety is acceptable
  in the current ASGI architecture (single-threaded event loop per worker, multi-worker forks).

## [0.1.1] - 2026-03-17

### Added

- Professional README with badges, value proposition, quickstart, and architecture overview
- MkDocs-Material documentation site with DTA brand theme (Getting Started, Guides, Reference, Architecture)
- GitHub Actions workflow for automatic docs deployment to GitHub Pages
- Community files: CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md
- GitHub issue templates (bug report, feature request) and PR template
- Pre-commit configuration (ruff lint/format, mypy)
- PyPI project URLs (Documentation, Changelog, Bug Tracker, Homepage)

### Changed

- Docs directory excluded from sdist distribution

### Fixed

- Unused `DEFAULT_MEMORY_DB` imports in CLI modules
- Minor lint issues (unsorted `__all__`, raw regex strings, trailing whitespace)

## [0.1.0] - 2026-03-12

Initial release of Errorworks — composable chaos-testing services for various pipelines.

### Added

#### Core Engine (`errorworks.engine`)
- **InjectionEngine**: Burst state machine with priority and weighted error selection modes
- **MetricsStore**: Thread-safe SQLite metrics storage with schema-driven DDL and time-series bucketing
- **LatencySimulator**: Configurable artificial latency injection with jitter support
- **Config loader**: YAML preset system with deep-merge precedence (CLI > file > preset > defaults)
- Shared vocabulary banks for content generation (English and Lorem Ipsum)
- Frozen Pydantic models for immutable, validated configuration throughout

#### ChaosLLM (`errorworks.llm`)
- OpenAI-compatible fake LLM server (chat completions API) with Starlette/ASGI
- Streaming and non-streaming response modes
- Error injection: rate limiting (429), server errors (500/502/503), connection errors, malformed JSON
- Burst pattern simulation for provider stress testing
- Response generation with gibberish, lorem, and template modes
- SQLite-backed metrics recording per endpoint/deployment/model
- Six built-in presets: `silent`, `gentle`, `realistic`, `chaos`, `stress_aimd`, `stress_extreme`
- `chaosllm` CLI with full configuration via flags, YAML files, or presets

#### ChaosLLM MCP (`errorworks.llm_mcp`)
- Model Context Protocol server for ChaosLLM metrics analysis
- Tools for querying error rates, latency distributions, and time-series trends
- `chaosllm-mcp` CLI entry point

#### ChaosWeb (`errorworks.web`)
- Fake web server for scraping pipeline resilience testing
- Error injection: rate limiting (429), forbidden (403), redirects, connection errors, malformed HTML
- Anti-scraping simulation: SSRF injection, redirect chains, content corruption
- HTML content generation with configurable structure and link density
- Five built-in presets: `silent`, `gentle`, `realistic`, `stress_scraping`, `stress_extreme`
- `chaosweb` CLI with full configuration via flags, YAML files, or presets

#### Unified CLI
- `chaosengine` command that mounts `chaosllm` and `chaosweb` as subcommands

#### Testing Support
- `ChaosLLMFixture`: In-process pytest fixture with marker-based configuration
- `ChaosWebFixture`: In-process pytest fixture with 23 configurable parameters
- 583 unit tests with 72% overall code coverage
