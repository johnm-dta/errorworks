# Errorworks Subsystem Catalog

Generated: 2026-03-12

## Engine (Shared Core)

**Location:** `src/errorworks/engine/`

**Responsibility:** Provides composition-based building blocks (injection engine, metrics storage, latency simulation, config loading, vocabulary) shared by all chaos plugins without base-class inheritance.

**Key Components:**
- `types.py` (197 lines) - Frozen Pydantic models (ServerConfig, MetricsConfig, LatencyConfig) and frozen dataclasses (ErrorSpec, BurstConfig, ColumnDef, MetricsSchema). All config models use `frozen=True, extra="forbid"`. ErrorSpec carries an opaque `tag` + `weight`; the engine never interprets the tag.
- `injection_engine.py` (173 lines) - Burst state machine (periodic windows via modular arithmetic on elapsed time) + two selection algorithms: "priority" (first-triggered-wins) and "weighted" (proportional with implicit success weight of `max(0, 100 - total_weight)`). Thread-safe via `threading.Lock` on start time. Injectable `time_func` and `rng` for deterministic testing.
- `metrics_store.py` (585 lines) - Thread-safe SQLite storage with thread-local connections, WAL mode for file DBs, schema-driven DDL generation from MetricsSchema. Handles connection pooling, stale connection cleanup, run info tracking, UPSERT-based timeseries aggregation, percentile computation, data export, and full timeseries rebuild via caller-supplied classifier callback.
- `config_loader.py` (154 lines) - YAML preset loading with path-traversal prevention (regex on preset names), `deep_merge` for dict layering, generic `load_config[ConfigT: BaseModel]` with precedence: CLI > config file > preset > defaults.
- `latency.py` (77 lines) - Configurable artificial delays: `simulate()` returns `(base_ms + uniform(-jitter, +jitter)) / 1000` seconds, clamped to 0. Also provides `simulate_slow_response(min_sec, max_sec)` for error injection.
- `vocabulary.py` (206 lines) - Two word banks: `ENGLISH_VOCABULARY` (108 common English words including tech terms) and `LOREM_VOCABULARY` (sorted, deduplicated Lorem Ipsum). Both are frozen tuples.
- `cli.py` (38 lines) - Unified `chaosengine` Typer CLI that mounts LLM and Web sub-apps: `chaosengine llm serve`, `chaosengine web serve`.
- `__init__.py` (50 lines) - Public API re-exports all key types and functions.

**Dependencies:**
- Inbound: `llm`, `web`, `llm_mcp` (all chaos plugins compose engine utilities)
- Outbound: `pydantic`, `pyyaml` (no internal errorworks dependencies)

**Patterns Observed:**
- Composition over inheritance: engine provides utilities that plugins instantiate, not base classes they extend. This avoids covariant return type friction.
- Immutable configuration: all Pydantic models are `frozen=True` with `extra="forbid"`. Runtime updates create new instances via `deep_merge` + reconstruction.
- Dependency injection for testability: `time_func`, `rng`, `uuid_func` parameters on InjectionEngine and LatencySimulator enable deterministic testing.
- Schema-driven DDL: MetricsStore generates CREATE TABLE statements from MetricsSchema dataclasses, keeping schema definitions co-located with domain code.
- Thread safety via thread-local storage and locks for SQLite connections and burst state.

**Concerns:**
- `metrics_store.py` at 585 lines contains substantial logic (DDL generation, UPSERT, timeseries rebuild, stats computation, data export). The `rebuild_timeseries` method duplicates some logic from `update_timeseries` and `update_bucket_latency`.
- `_get_bucket_utc` only considers hour/minute/second for bucketing, ignoring the date boundary. A bucket that spans midnight would be computed incorrectly for bucket sizes that are not exact divisors of 86400.
- The `_cleanup_stale_connections` method in MetricsStore runs on every new connection creation, which adds overhead proportional to the number of tracked threads.
- `load_config` unconditionally sets `preset_name` in `config_dict` (line 151), meaning downstream Pydantic models must accept this field even if not explicitly documented.

**Confidence:** High - Read 100% of all 8 files (1480 total lines). Cross-verified imports: all outbound dependencies confirmed in pyproject.toml. Inbound usage verified by reading all consumer __init__.py and server files.

---

## LLM (ChaosLLM - Fake OpenAI Server)

**Location:** `src/errorworks/llm/`

**Responsibility:** Provides a fake OpenAI and Azure OpenAI compatible HTTP server with configurable error injection (HTTP errors, connection failures, malformed responses), response generation (random, template, echo, preset), burst simulation for AIMD testing, and SQLite metrics recording.

**Key Components:**
- `server.py` (828 lines) - Starlette ASGI app via `ChaosLLMServer` class. Routes: `/health`, `/v1/chat/completions`, `/openai/deployments/{deployment}/chat/completions`, `/admin/{config,stats,reset,export}`. Admin endpoints require Bearer token auth. Request flow: snapshot components under lock, parse body, check error injection, dispatch to connection/HTTP/malformed/success handler. Metrics recording is best-effort (exceptions logged, not propagated). Runtime config updates use deep_merge + atomic swap under `_config_lock`.
- `config.py` (486 lines) - Pydantic config hierarchy: `ChaosLLMConfig` contains `ServerConfig`, `MetricsConfig`, `ResponseConfig`, `LatencyConfig`, `ErrorInjectionConfig`. ErrorInjectionConfig defines 17 error percentage fields, 6 range tuple fields (retry_after, timeout, stall, etc.), BurstConfig, and selection_mode. All models frozen. `load_config` wraps engine's generic `load_config` with ChaosLLM-specific presets directory.
- `error_injector.py` (374 lines) - `ErrorInjector` composes InjectionEngine. Builds 17-element ErrorSpec list with burst-adjusted weights for rate_limit and capacity_529. Maps selected tags to `ErrorDecision` dataclass (3 categories: HTTP, CONNECTION, MALFORMED). Timeout decisions use 50/50 mix of 504 response vs connection drop.
- `response_generator.py` (459 lines) - `ResponseGenerator` supports 4 modes: random (vocabulary-based text), template (Jinja2 SandboxedEnvironment with helpers: random_choice, random_float, random_int, random_words, timestamp), echo (last user message reflection), preset (JSONL bank with random/sequential selection). Produces `OpenAIResponse` dataclass that serializes to OpenAI API format. Token estimation: `len(text) // 4`. Template override from headers is Tier 3 (errors caught, not crashed).
- `metrics.py` (288 lines) - `MetricsRecorder` composes MetricsStore with `LLM_METRICS_SCHEMA` (15 request columns, 11 timeseries columns, 3 indexes). Classifies outcomes into 7 categories (success, rate_limited, capacity_error, server_error, client_error, connection_error, malformed). Atomic commit of record + timeseries upsert + latency update.
- `cli.py` (558 lines) - Typer CLI with `serve`, `presets`, `show-config` commands. 20+ CLI flags map to config overrides. Also hosts `chaosllm-mcp` entry point that delegates to `llm_mcp.server`.
- `__init__.py` (70 lines) - Public API re-exports.
- `presets/` - 6 YAML presets: chaos, gentle, realistic, silent, stress_aimd, stress_extreme.

**Dependencies:**
- Inbound: `engine.cli` (mounts llm.cli as sub-command), `llm_mcp` (imports LLM metrics schema), test fixtures
- Outbound: `engine` (InjectionEngine, MetricsStore, LatencySimulator, config_loader, types, vocabulary), `starlette`, `jinja2`, `structlog`, `typer`, `uvicorn`

**Patterns Observed:**
- Server composes 4 domain components (ErrorInjector, ResponseGenerator, LatencySimulator, MetricsRecorder) rather than inheriting from a base server class.
- Config snapshot pattern: request handlers snapshot component references under `_config_lock` at the start, so concurrent `update_config()` cannot produce a half-updated view.
- Best-effort metrics: `_record_request` wraps all metrics operations in try/except to prevent metrics failures from affecting chaos responses.
- Error categorization uses a 3-tier priority system: connection > HTTP > malformed, with burst mode dynamically elevating rate_limit and capacity_529 weights.
- Frozen config with reconstruction: runtime updates merge dicts, create new Pydantic model, create new component, then swap atomically.

**Concerns:**
- `server.py` at 828 lines is the largest source file. The connection error handler (`_handle_connection_error`) has 5 branches with significant code duplication (elapsed_ms calculation, _record_request calls with similar kwargs).
- The `_handle_completion_request` method passes `response_generator` and `latency_simulator` explicitly to sub-handlers but reads `_error_injector` indirectly via the snapshot. This asymmetry could cause confusion.
- Token estimation (`len(text) // 4`) is very rough -- fine for a fake server but could mislead tests that validate token counts.
- `cli.py` has a `_version_callback` function duplicated identically in `web/cli.py`.

**Confidence:** High - Read 100% of all 7 source files (3063 total lines) plus all 6 preset filenames verified. Cross-verified imports against engine subsystem. Verified admin auth flow, error injection priority, and metrics recording path.

---

## Web (ChaosWeb - Fake Web Server)

**Location:** `src/errorworks/web/`

**Responsibility:** Provides a fake multi-path web server for testing web scraping pipeline resilience, with error injection (HTTP errors, connection failures, content malformations, redirect loops, SSRF redirects), HTML content generation, and SQLite metrics recording.

**Key Components:**
- `server.py` (934 lines) - Starlette ASGI app via `ChaosWebServer`. Routes: `/health`, `/admin/*`, `/redirect` (redirect loop handler), `/{path:path}` (catch-all content route). Handles 6 malformed content types (wrong_content_type, encoding_mismatch, truncated_html, invalid_encoding, charset_confusion, malformed_meta) by generating valid HTML then corrupting it. `_StreamingDisconnect` class enables incomplete response injection by streaming partial body then raising ConnectionResetError.
- `config.py` (533 lines) - `ChaosWebConfig` with web-specific types: `WebContentConfig` (4 modes), `WebErrorInjectionConfig` (23 error percentage fields including web-specific: gone_pct, payment_required_pct, unavailable_for_legal_pct, encoding_mismatch_pct, truncated_html_pct, invalid_encoding_pct, charset_confusion_pct, malformed_meta_pct, redirect_loop_pct, ssrf_redirect_pct, incomplete_response_pct). `WebBurstConfig` elevates rate_limit_pct and forbidden_pct during bursts.
- `error_injector.py` (450 lines) - `WebErrorInjector` composes InjectionEngine. 4 error categories (HTTP, CONNECTION, MALFORMED, REDIRECT) with 22-element ErrorSpec list. SSRF targets include AWS/GCP/Azure metadata endpoints, private networks, loopback, CGNAT, IPv6 variants, and decimal IP encoding tricks. `WebErrorDecision` extends LLM's pattern with redirect_target, redirect_hops, incomplete_bytes, encoding_actual fields.
- `content_generator.py` (521 lines) - `ContentGenerator` generates syntactically valid HTML5 with random structural elements (headings, paragraphs, blockquotes, lists). Uses `html.escape` for XSS-safe echo mode. Jinja2 `SandboxedEnvironment` with `autoescape=True` for template mode. Content corruption helpers are module-level functions: `truncate_html`, `inject_encoding_mismatch`, `inject_charset_confusion`, `inject_invalid_encoding`, `inject_malformed_meta`, `generate_wrong_content_type`.
- `metrics.py` (264 lines) - `WebMetricsRecorder` composes MetricsStore with `WEB_METRICS_SCHEMA` (13 request columns including path, content_type_served, encoding_served, redirect_target, redirect_hops; 12 timeseries columns including requests_forbidden, requests_not_found, requests_redirect).
- `cli.py` (363 lines) - Typer CLI with `serve`, `presets`, `show-config` commands. Default port 8200 (vs LLM's 8000).
- `__init__.py` (65 lines) - Public API re-exports.
- `presets/` - 5 YAML presets: gentle, realistic, silent, stress_extreme, stress_scraping.

**Dependencies:**
- Inbound: `engine.cli` (mounts web.cli as sub-command), test fixtures
- Outbound: `engine` (InjectionEngine, MetricsStore, LatencySimulator, config_loader, types, vocabulary), `starlette`, `jinja2`, `structlog`, `typer`, `uvicorn`

**Patterns Observed:**
- Mirrors LLM subsystem's composition pattern: ChaosWebServer composes WebErrorInjector, ContentGenerator, LatencySimulator, WebMetricsRecorder.
- Same config snapshot + atomic swap pattern for runtime updates.
- Content corruption is separated into pure functions (module-level helpers) rather than methods on the server class, improving testability.
- Redirect loops use stateless query parameters (`/redirect?hop=N&max=M&target=T`) rather than server-side state, enabling proper redirect chain behavior through any HTTP client.
- SSRF target list is comprehensive and domain-specific, covering real attack vectors including IPv4-mapped IPv6 and decimal IP bypasses.

**Concerns:**
- `server.py` at 934 lines is the largest file in the codebase. The `_handle_malformed_content` method (lines 628-767) has 6 branches with repetitive record + response construction patterns.
- `_StreamingDisconnect` class (lines 892-923) directly sets `self.background = None` and bypasses normal Response initialization, which is fragile against Starlette version changes.
- The `_handle_connection_error` method catches `sqlite3.Error` in `_record_request` (line 882) but the LLM equivalent catches broad `Exception` (line 802). This inconsistency could miss non-SQLite metrics failures in the web server.
- Web and LLM subsystems have significant structural duplication (server.py, cli.py, metrics.py all follow the same patterns with domain-specific differences). This is a deliberate design choice (composition over inheritance) but increases maintenance surface.

**Confidence:** High - Read 100% of all 7 source files (3130 total lines) plus verified 5 preset filenames. Cross-verified imports against engine subsystem. Confirmed architectural symmetry with LLM subsystem.

---

## LLM MCP (Metrics Analysis Server)

**Location:** `src/errorworks/llm_mcp/`

**Responsibility:** Provides an MCP (Model Context Protocol) server for Claude-optimized analysis of ChaosLLM metrics databases, with pre-computed insights for diagnostics, AIMD behavior analysis, error distribution, latency analysis, anomaly detection, and raw SQL access.

**Key Components:**
- `server.py` (1102 lines) - `ChaosLLMAnalyzer` class with 10 analysis methods: `diagnose()` (one-paragraph summary with AIMD assessment), `analyze_aimd_behavior()` (burst detection, recovery times, throughput degradation), `analyze_errors()` (error breakdown by type and status code with sample timestamps), `analyze_latency()` (percentiles, slow request detection, error-latency correlation), `find_anomalies()` (unexpected status codes, throughput cliffs, error clustering, zero-success periods), `get_burst_events()` (before/during/after burst stats), `get_error_samples()`, `get_time_window()`, `query()` (read-only SQL with keyword blocklist + SQLite `set_authorizer` defense-in-depth), `describe_schema()`. MCP Server created via `create_server()` with tool registration. Also includes `_find_metrics_databases()` for auto-discovery and argparse-based CLI.
- `__init__.py` (26 lines) - Re-exports ChaosLLMAnalyzer, create_server, main, run_server.

**Dependencies:**
- Inbound: `llm.cli` (invokes `run_server` from MCP entry point)
- Outbound: `mcp` (MCP SDK -- optional dependency), `sqlite3` (stdlib, direct database access -- does NOT compose MetricsStore)

**Patterns Observed:**
- Direct SQLite access rather than composing MetricsStore -- the analyzer is read-only and needs custom aggregation queries that MetricsStore's API doesn't support.
- Defense-in-depth for SQL injection: keyword blocklist (regex word-boundary matching) + SQLite `set_authorizer` callback that only permits SELECT, READ, and FUNCTION operations.
- Pre-computed insights: each tool returns a `summary` field with a concise text string designed for LLM consumption (~80-150 tokens), plus structured data for detailed exploration.
- Burst detection uses a simple threshold: >30% error rate in a bucket starts a burst, <10% ends it.
- Auto LIMIT 100 on raw queries to prevent excessive output.

**Concerns:**
- At 1102 lines, this is the single largest file in the codebase. The ChaosLLMAnalyzer class has 10 methods with substantial SQL query logic that could be decomposed.
- The `_readonly_authorizer` resets to `None` after each `query()` call (line 772), meaning concurrent calls to `query()` could race on the authorizer state. However, the MCP server is async single-threaded, so this is unlikely to be an issue in practice.
- Schema description in `describe_schema()` (lines 776-827) is hardcoded and could drift from the actual LLM_METRICS_SCHEMA in `llm/metrics.py`. No validation ensures they stay in sync.
- The analyzer only works with ChaosLLM metrics schema (requests table columns like `endpoint`, `deployment`, `model`). It cannot analyze ChaosWeb metrics databases, despite the metrics store being schema-driven.
- `_find_metrics_databases` skips directories starting with `.` but does not handle symlink loops.

**Confidence:** High - Read 100% of both files (1128 total lines). Verified MCP tool registration matches analyzer methods. Confirmed SQL safety mechanisms. Noted the direct SQLite usage vs. MetricsStore composition.

---

## Testing (Pytest Fixture Support)

**Location:** `src/errorworks/testing/` and `tests/fixtures/`

**Responsibility:** Provides in-process test fixtures using Starlette's TestClient for both ChaosLLM and ChaosWeb, enabling tests to run without real network sockets. The `testing/` package is the public API; `tests/fixtures/` contains the actual fixture implementations.

**Key Components:**
- `src/errorworks/testing/__init__.py` (6 lines) - Docstring-only package. Declares intent to provide ChaosLLMFixture and ChaosWebFixture for consumers but does not actually export them (the fixtures live in tests/fixtures/).
- `tests/fixtures/chaosllm.py` (243 lines) - `ChaosLLMFixture` dataclass wrapping TestClient + ChaosLLMServer. Provides convenience methods: `post_completion()`, `post_azure_completion()`, `update_config()`, `get_stats()`, `export_metrics()`, `reset()`, `wait_for_requests()`. `_build_config_from_marker()` constructs config from `@pytest.mark.chaosllm(...)` kwargs. Tests use zero latency by default (`base_ms=0, jitter_ms=0`). Fixed admin token for deterministic test auth.
- `tests/fixtures/chaosweb.py` (313 lines) - `ChaosWebFixture` dataclass with `fetch_page()`, `update_config()` (24 error injection parameters), `wait_for_requests()`. Same marker-based config pattern as ChaosLLM. `_ERROR_INJECTION_KEYS` list (23 entries) mirrors WebErrorInjectionConfig fields.
- `tests/fixtures/__init__.py` (0 lines) - Empty package marker.

**Dependencies:**
- Inbound: All test files (via conftest.py imports)
- Outbound: `llm.config`, `llm.server`, `web.config`, `web.server`, `starlette.testclient`, `pytest`

**Patterns Observed:**
- Marker-based configuration: `@pytest.mark.chaosllm(preset="stress_aimd", rate_limit_pct=50)` allows per-test server configuration without fixture duplication.
- Zero-latency defaults: test fixtures set `base_ms=0, jitter_ms=0` to avoid test timing sensitivity.
- Fixed admin token: `TEST_ADMIN_TOKEN = "test-admin-token"` provides deterministic auth for admin endpoint testing.
- In-process testing: TestClient wraps the Starlette app directly, avoiding network socket allocation and enabling safe parallel test execution.

**Concerns:**
- `src/errorworks/testing/__init__.py` is essentially empty (docstring only). It declares ChaosLLMFixture and ChaosWebFixture as public API in its docstring but does not import or re-export them. Consumers must import from `tests/fixtures/` directly, which is not a standard package distribution pattern.
- Both fixture files access `server._config.server.admin_token` via the private `_config` attribute (e.g., line 61 in chaosllm.py), coupling tests to internal implementation.
- `wait_for_requests()` uses a polling loop with `time.sleep(0.01)`, which could be slow for CI environments. An event-based approach would be more efficient.
- The `_build_config_from_marker` functions in both fixtures duplicate significant config-building logic that could be shared.

**Confidence:** High - Read 100% of all 4 files (562 total lines). Verified marker handling and config construction paths. Confirmed TestClient pattern and admin auth mechanism.

---

## Test Suite

**Location:** `tests/`

**Responsibility:** Unit and integration tests covering all subsystems, using pytest markers (`chaosllm`, `chaosweb`, `integration`, `slow`, `stress`) and the in-process fixture system.

**Key Components:**
- `tests/unit/engine/` - 3 test files: `test_config_loader.py`, `test_injection_engine.py`, `test_metrics_store.py` testing core engine components.
- `tests/unit/llm/` - 8 test files: `test_server.py`, `test_error_injector.py`, `test_response_generator.py`, `test_metrics.py`, `test_config.py`, `test_cli.py`, `test_fixture.py`, `test_latency_simulator.py`. Uses `conftest.py` for shared LLM fixtures.
- `tests/unit/web/` - 6 test files: `test_server.py`, `test_error_injector.py`, `test_content_generator.py`, `test_metrics.py`, `test_config.py`, `test_cli.py`. Uses `conftest.py` for shared web fixtures.
- `tests/unit/llm_mcp/` - 1 test file: `test_server.py` for MCP server analysis tools.
- `tests/integration/` - 3 test files: `test_llm_pipeline.py`, `test_web_pipeline.py`, `test_mcp_pipeline.py`. Uses `conftest.py` for integration test setup.

**Dependencies:**
- Inbound: None (test-only code)
- Outbound: All `src/errorworks/` subsystems, `pytest`, `starlette.testclient`, `hypothesis` (property-based testing)

**Patterns Observed:**
- Marker-based test categorization: `@pytest.mark.chaosllm`, `@pytest.mark.chaosweb`, `@pytest.mark.integration` enable selective test execution.
- Strict marker configuration: `--strict-markers` and `--strict-config` in pyproject.toml prevents undefined markers.
- conftest.py files at unit/llm and unit/web levels import fixtures from `tests/fixtures/`.
- Integration tests exercise full request pipelines including error injection, metrics recording, and admin endpoints.

**Concerns:**
- Test file structure observed but individual test files not read in full (this entry is based on file listing and fixture analysis).
- Several test files appear in git status as modified (`test_llm_pipeline.py`, `test_web_pipeline.py`, `test_server.py` for both llm and web) -- uncommitted changes may affect test coverage.

**Confidence:** Medium - Read fixtures in full and verified test structure. Did not read individual test file implementations to verify coverage or correctness. Confidence is based on fixture analysis, file naming patterns, and pyproject.toml test configuration.

---

## Confidence Assessment

All subsystem entries above are supported by direct source file reading. The engine, LLM, web, LLM MCP, and testing subsystems were read at 100% coverage of their source files. The test suite entry is at medium confidence because individual test implementations were not read.

## Risk Assessment

- **Low risk:** Engine subsystem is well-factored with clear boundaries and comprehensive type safety (frozen models, dataclass validation).
- **Low risk:** Config precedence system (CLI > file > preset > defaults) is well-tested by design and uses Pydantic validation.
- **Medium risk:** server.py files in both LLM (828 lines) and Web (934 lines) are large and contain repetitive error handling branches that could benefit from extraction.
- **Medium risk:** MCP server's `describe_schema()` is hardcoded and could drift from the actual schema definitions.
- **Low risk:** SSRF target list in web error injector is comprehensive and covers real attack vectors.

## Information Gaps

1. **Preset YAML content** - Preset files were identified but their contents (specific error rates, burst patterns) were not read.
2. **Individual test implementations** - Test file structure and naming verified but test logic not read.
3. **CI workflow** - `.github/workflows/ci.yml` is modified but not read.
4. **chaos_services directory** - `src/chaos_services` is listed as an additional working directory but not explored (may be a separate service or deployment concern).

## Caveats

- This analysis reflects the codebase as of 2026-03-12 with uncommitted changes in 14 files (per git status).
- The `src/errorworks/testing/__init__.py` package appears to be a planned but incomplete public API for test fixtures.
- Line counts are approximate (from `wc -l`) and include blank lines and comments.
