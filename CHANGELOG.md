# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-05-25

### Added

- **ChaosBlob**: S3-compatible-ish path-style object storage chaos server with
  PUT/GET/HEAD/DELETE/ListObjectsV2 support, blob-specific fault injection,
  metrics, CLI, presets, pytest fixture, and documentation.
- **ChaosSMTP**: SMTP receiving server for outbound email resilience tests.
  Stage-aware error injection across MAIL/RCPT/DATA, slow-reply latency,
  accepted-but-dropped messages, three capture modes (`metadata`, `discard`,
  `full`), admin app for runtime config/metrics, immutable captured-header
  policy, SQLite metrics, CLI (`chaossmtp`), presets, pytest fixture, and
  documentation. Mail is never relayed — all sessions stay local.

### Changed (breaking)

- **`server.workers` default is now 1** (was 4). Multi-worker mode is now
  opt-in and requires a file-backed `metrics.database`; the previous default
  combination silently fragmented metrics across worker processes (each
  uvicorn worker is a separate process and could not share an in-memory
  SQLite DB). All bundled presets now also default to `workers: 1`.
- **Top-level config validators (`ChaosLLMConfig`, `ChaosWebConfig`) reject
  `workers > 1` combined with an in-memory metrics database.** Set
  `metrics.database` to a file path (e.g. `metrics.db`) or keep `workers: 1`.

### Fixed (security / robustness)

- **LLM completions endpoint**: a JSON body that is not a JSON object (array,
  string, etc.) now returns `400 invalid_request_error` instead of `500`.
- **Admin `/admin/config` POST**: unknown top-level config sections and
  non-object section values are now rejected with `400 invalid_request_error`
  before reaching `deep_merge`. Previously, `{"typo_section": ...}` silently
  no-op'd (returning 200) and `{"error_injection": null}` raised an uncaught
  `AttributeError` (returning 500). Applies to both ChaosLLM and ChaosWeb.
- **LLM `X-Fake-Template` override hardening**: the runtime template now
  catches any exception (not just `jinja2.TemplateError`), so helper-raised
  errors such as `random_int(10, 1)` are reported as content rather than
  crashing the worker. `random_words(...)` output is hard-capped to
  `_MAX_RANDOM_WORDS = 10_000` words to defend against requests like
  `random_words(100000000)`.
- **MCP analyzer SQL `query()`**: the row cap is now enforced via
  `fetchmany(_MAX_QUERY_ROWS)` so that user-supplied `LIMIT -1` (or any other
  bypass of the keyword check) cannot return more than `_MAX_QUERY_ROWS` rows.
- **MCP analyzer is now truly read-only**: the SQLite connection is opened via
  a `file:...?mode=ro` URI and no longer executes `PRAGMA journal_mode=WAL`,
  so it does not create WAL/SHM side files or mutate the on-disk database.
- **Engine: malformed `Content-Length` now rejected explicitly.**
  `read_limited_body()` previously relied on `except ValueError` plus
  `isinstance` to distinguish a size-limit exception from an int-parse
  failure, but because `RequestBodyTooLarge` subclasses `ValueError`, a
  genuine parse failure was silently swallowed and the size guard was
  effectively disabled for any client sending `Content-Length: abc`, `1.5`,
  or `-1`. A new `MalformedContentLength(ValueError)` is now raised on bad
  input; blob maps it to `S3 InvalidRequest`/HTTP 400, and admin/LLM inherit
  the correct behaviour via their existing handlers.
- **Engine: graceful fallback when config-handoff temp file is missing.**
  Worker processes (uvicorn fork) previously died with a bare
  `FileNotFoundError` when the handoff temp file was absent (shutdown race,
  `/tmp` cleaner, mismatched cleanup). A shared `engine/config_handoff.py`
  helper now falls back to the env-var-only form when the temp file is gone,
  and raises a diagnostic `ConfigHandoffError` only when both mechanisms are
  missing or unreadable. Used by all three HTTP servers (blob/llm/web).
- **MCP `analyze_latency`: percentiles now computed over full population.**
  The previous implementation ran `ORDER BY latency_ms LIMIT 100` and then
  computed percentiles over the returned rows — the smallest-100 lower tail,
  producing wildly low p95/p99 values. Replaced with the
  `LIMIT 1 OFFSET k` per-percentile SQL pattern already used in
  `engine/metrics_store.py` — exact, single-row per query, consistent across
  the codebase.

### Removed (security)

- Removed an explicit `rm -rf $REPO/.git && git init` permission entry from
  `.claude/settings.local.json` — a destructive command that should never
  have been pre-authorized.

### Documentation

- README: removed the non-existent `chaos` Web preset and added the
  `stress_extreme` LLM preset, matching what ships in
  `src/errorworks/{llm,web}/presets/`.
- Quickstart: removed reference to a non-existent `--admin-token` CLI flag
  (use `server.admin_token` in YAML config instead).
- ChaosWeb guide: fixed the template helper list to match what is actually
  registered (`random_choice`, `random_int`, `random_words`, `timestamp` —
  no `random_float`).
- Added `docs/guide/chaosblob.md` and `docs/guide/chaossmtp.md`; updated
  `docs/index.md` and the MkDocs nav to surface both new plugins.

## [0.1.3] - 2026-05-24

### Changed

- **Dependency**: Loosen `starlette` cap from `<1` to `<2` to support Starlette 1.x.
  Starlette 1.0 removed deprecated APIs that errorworks does not use; the full test
  suite passes against starlette 1.1.0 with no source changes. This unblocks
  downstream consumers that need to pull starlette 1.x.

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
