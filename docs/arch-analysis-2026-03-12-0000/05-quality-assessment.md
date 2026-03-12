# Architecture Quality Assessment: Errorworks

**Assessed:** 2026-03-12
**Scope:** Full codebase at `/home/john/errorworks/src/errorworks/`
**Assessor:** Architecture Critic Agent

---

## Overall Quality Score: 4 / 5

**Critical Issues:** 0
**High Issues:** 3
**Medium Issues:** 5
**Low Issues:** 3

---

## 1. Engine Subsystem (`engine/`)

**Quality Score:** 5 / 5
**Critical Issues:** 0
**High Issues:** 0

**Findings:**

1. **MetricsStore uses f-string SQL construction** - Medium
   - **Evidence:** `src/errorworks/engine/metrics_store.py:254` - `f"INSERT INTO requests ({col_str}) VALUES ({placeholders})"` and similar patterns at lines 288, 393.
   - **Impact:** Column names are injected via f-string into SQL. The column names come from the internal `MetricsSchema` definition (frozen dataclass, not user input), so this is NOT a SQL injection vulnerability. However, it creates a fragile pattern -- if the schema ever accepts external column names, this becomes exploitable.
   - **Recommendation:** The mitigation (schema is frozen, column names validated at init via `ColumnDef.__post_init__`) is adequate. No action required unless schema becomes dynamic.

2. **Thread-local connection cleanup relies on thread enumeration** - Low
   - **Evidence:** `src/errorworks/engine/metrics_store.py:186` - `_cleanup_stale_connections` iterates `threading.enumerate()`.
   - **Impact:** Thread IDs can be reused by the OS. A stale connection might be closed while a new thread with the same ID is mid-query. In practice, this is extremely unlikely in the ASGI context.
   - **Recommendation:** Accept the risk. The stale connection cleanup is opportunistic and the window for thread ID reuse collision is negligible.

**Strengths:**

- `InjectionEngine` is genuinely domain-agnostic. It operates on `ErrorSpec` tags and weights with zero knowledge of HTTP, LLM, or web concepts. This is textbook separation of concerns.
- `MetricsStore` achieves schema-driven DDL generation cleanly. The `MetricsSchema`/`ColumnDef` pattern lets each plugin define its own table structure without touching SQLite infrastructure code.
- `ConfigLoader` correctly implements config precedence (CLI > file > preset > defaults) with path traversal prevention on preset names.
- Dependency injection of `time_func`, `rng`, and `uuid_func` throughout the engine layer makes everything deterministically testable.
- Frozen dataclasses (`ErrorSpec`, `BurstConfig`, `ColumnDef`, `MetricsSchema`) with thorough `__post_init__` validation enforce invariants at construction time.

---

## 2. LLM Subsystem (`llm/`)

**Quality Score:** 4 / 5
**Critical Issues:** 0
**High Issues:** 1

**Findings:**

1. **Server file is 829 lines with deeply nested request handling** - High
   - **Evidence:** `src/errorworks/llm/server.py` -- `_handle_completion_request` dispatches to `_handle_error_injection`, which dispatches to `_handle_connection_error` (4 branches), `_handle_http_error`, or `_handle_malformed_response` (5 branches). Each handler receives 8-11 keyword arguments threaded through manually.
   - **Impact:** Adding a new error type requires touching 3+ methods and threading new parameters through multiple layers. The function signatures are getting unwieldy (e.g., `_handle_slow_response` takes 11 parameters). This is a growth bottleneck.
   - **Recommendation:** Extract error response rendering into a separate module (e.g., `llm/response_handlers.py`). The dispatch logic can use a registry pattern mapping `ErrorCategory` to handler callables, eliminating the cascading if-elif chains and parameter threading.

2. **Metrics recording catches bare `Exception`** - Medium
   - **Evidence:** `src/errorworks/llm/server.py:802` - `except Exception:` in `_record_request`.
   - **Impact:** The rationale is documented and sound (metrics side-effects must not replace intended chaos responses). However, catching bare `Exception` also swallows `KeyboardInterrupt`, `SystemExit`, and programming errors like `TypeError`. The web server (line 882) correctly catches only `sqlite3.Error`.
   - **Recommendation:** Change to `except (sqlite3.Error, ValueError):` to match the web server's more targeted approach.

3. **ErrorInjectionConfig has 17 percentage fields with repetitive validation** - Medium
   - **Evidence:** `src/errorworks/llm/config.py:182-387` -- each field follows the same `float = Field(default=0.0, ge=0.0, le=100.0)` pattern, and `validate_ranges` manually checks each range tuple.
   - **Impact:** Adding a new error type requires touching 5 files: config (add field), error_injector (add to `_build_specs` and `_build_decision`), server (add handler branch), metrics (add timeseries column), and the fixture (add to `update_config`). This is manageable but the config validation is needlessly verbose.
   - **Recommendation:** Consider a `dict[str, float]` for percentage configs with a shared validator, or at minimum consolidate the range validation into a loop (as the web config already does at line 417-428).

**Strengths:**

- `ErrorDecision` dataclass with factory classmethods (`success()`, `http_error()`, `connection_error()`, `malformed_response()`) is a clean domain model. Cross-field validation in `__post_init__` catches invalid states early.
- `ResponseGenerator` handles 4 generation modes cleanly, with proper Jinja2 sandboxing via `SandboxedEnvironment`.
- Template override error handling is thoughtful: config templates crash (config bug = fast failure), header-override templates return error content (external data = graceful degradation).
- Best-effort metrics recording is a correct design choice for a chaos testing tool.

---

## 3. Web Subsystem (`web/`)

**Quality Score:** 4 / 5
**Critical Issues:** 0
**High Issues:** 1

**Findings:**

1. **Structural duplication with LLM server** - High
   - **Evidence:** Comparing `llm/server.py` and `web/server.py`:
     - `_check_admin_auth`: 18 lines, identical in both files.
     - `_admin_config_endpoint`, `_admin_stats_endpoint`, `_admin_reset_endpoint`, `_admin_export_endpoint`: functionally identical, ~40 lines total.
     - `_health_endpoint`: identical structure.
     - `update_config`: same deep-merge-then-atomic-swap pattern, ~30 lines.
     - `_record_run_info`: identical pattern.
     - `_get_current_config`: same pattern.
   - Comparing `llm/metrics.py` and `web/metrics.py`:
     - `MetricsRecorder` and `WebMetricsRecorder` are structurally identical. Every method (`reset`, `get_stats`, `export_data`, `save_run_info`, `get_requests`, `get_timeseries`, `close`) is a 1-line delegation to `self._store`. The only difference is `record_request` parameter names and the classification function.
   - Comparing `llm/error_injector.py` and `web/error_injector.py`:
     - `ErrorDecision` and `WebErrorDecision` share ~80% of their validation logic and factory methods.
     - `ErrorInjector` and `WebErrorInjector` share identical `__init__`, `decide()`, `reset()`, `is_in_burst()` patterns, and similar `_pick_*` helper methods.
   - **Impact:** Every cross-cutting change to admin auth, config update, or metrics recording must be made twice. Bug fixes can be applied to one server but forgotten in the other. This has already happened: `llm/server.py:802` catches bare `Exception` while `web/server.py:882` correctly catches `sqlite3.Error`.
   - **Recommendation:** Extract shared server infrastructure:
     - Admin auth and admin endpoint handlers into a mixin or shared router.
     - `MetricsRecorder` into a generic base that domain-specific recorders extend with only `record_request` and classification logic.
     - `ErrorDecision` base dataclass shared between LLM and web, with web adding redirect-specific fields.

2. **`_StreamingDisconnect` accesses Starlette internals** - Low
   - **Evidence:** `src/errorworks/web/server.py:892-924` -- directly constructs ASGI response dicts and iterates `body_iterator`.
   - **Impact:** Coupled to Starlette's internal ASGI protocol. A Starlette upgrade could break this. However, the ASGI spec itself is stable, so the actual risk is low.
   - **Recommendation:** Accept. This is necessary for simulating mid-transfer disconnects and the ASGI interface it uses is a specification, not an implementation detail.

3. **`ContentGenerator` and `ResponseGenerator` duplicate `PresetBank`** - Medium
   - **Evidence:** `llm/response_generator.py:102-194` and `web/content_generator.py:71-153` both implement `PresetBank` classes with identical structure: `__init__`, `next()`, `reset()`, `from_jsonl()`. The LLM version works with strings, the web version with dicts. Both have identical JSONL parsing, validation, and selection logic.
   - **Impact:** Bug in JSONL parsing logic must be fixed in both places.
   - **Recommendation:** Extract a generic `PresetBank[T]` into `engine/` that handles file loading, selection mode, and thread-safety, with a transform function for domain-specific value extraction.

**Strengths:**

- SSRF target list in `web/error_injector.py:71-91` is comprehensive: covers AWS/GCP/Azure metadata, RFC 1918, RFC 6598, loopback (v4 and v6), IPv4-mapped IPv6, and decimal IP encoding. This is genuinely useful for security testing.
- Content corruption helpers (`truncate_html`, `inject_encoding_mismatch`, `inject_charset_confusion`, `inject_invalid_encoding`, `inject_malformed_meta`) are well-isolated pure functions with no side effects.
- HTML echo mode uses `html.escape()` throughout, preventing XSS in reflected content. Template mode uses `SandboxedEnvironment` with `autoescape=True`.
- Redirect loop uses stateless query-parameter approach with configurable hop limits and server-side cap, avoiding infinite loops.

---

## 4. MCP Subsystem (`llm_mcp/`)

**Quality Score:** 3 / 5
**Critical Issues:** 0
**High Issues:** 1

**Findings:**

1. **Single-threaded connection without WAL mode** - High
   - **Evidence:** `src/errorworks/llm_mcp/server.py:68-71` -- `self._conn = sqlite3.connect(self._db_path)` with no WAL pragma, no timeout, no error handling on connection failure. Compare to `MetricsStore._get_connection()` which sets WAL mode, 30-second timeout, and handles thread-local connections.
   - **Impact:** If the MCP server connects to a file database that the ChaosLLM server is actively writing to, reads will block on write locks. The MCP server is explicitly read-only, so WAL mode would allow concurrent reads without blocking.
   - **Recommendation:** Add `conn.execute("PRAGMA journal_mode=WAL")` after connection and set `timeout=30.0`.

2. **SQL query safety relies on keyword blocklist** - Medium
   - **Evidence:** `src/errorworks/llm_mcp/server.py:742-774` -- `query()` method uses regex word-boundary matching against a blocklist of SQL keywords. Defense-in-depth via `_readonly_authorizer` is present.
   - **Impact:** The authorizer provides genuine protection (line 765), making the keyword blocklist defense-in-depth rather than the primary safeguard. The authorizer correctly denies all non-SELECT, non-READ, non-FUNCTION operations at the SQLite engine level. This is adequate.
   - **Recommendation:** No change needed. The authorizer-based approach is the correct one, and the keyword blocklist provides useful user-facing error messages.

3. **MCP server is LLM-only; no equivalent for ChaosWeb** - Medium
   - **Evidence:** `src/errorworks/llm_mcp/` exists, no `web_mcp/` directory. `ChaosLLMAnalyzer` hardcodes timeseries columns like `requests_rate_limited`, `requests_capacity_error` which do not exist in the web schema.
   - **Impact:** Web pipeline users get no MCP analysis tools. The analyzer logic is heavily coupled to LLM-specific schema column names.
   - **Recommendation:** Factor out schema-aware analysis into a base analyzer, then create `web_mcp/` using the same pattern. Alternatively, make the MCP server schema-introspecting (read column names from sqlite_master).

**Strengths:**

- Tool design is well-suited for LLM consumption: `diagnose()` returns ~100 tokens, `analyze_errors()` ~120 tokens, `analyze_latency()` ~80 tokens. Pre-computed insights avoid the need for multiple roundtrips.
- Read-only authorizer at the SQLite engine level is defense-in-depth done correctly.

---

## 5. Testing Subsystem (`testing/`, `tests/fixtures/`)

**Quality Score:** 4 / 5
**Critical Issues:** 0
**High Issues:** 0

**Findings:**

1. **Test fixture accesses private attribute** - Low
   - **Evidence:** `tests/fixtures/chaosllm.py:61` - `self.server._config.server.admin_token`. The fixture reaches into the server's private `_config` to get the admin token.
   - **Impact:** Brittle coupling to internal attribute name. If the server renames `_config`, the fixture breaks.
   - **Recommendation:** Expose `admin_token` via a public property on `ChaosLLMServer`, or pass the token through the fixture constructor (the fixture already knows the token since it constructs the config).

2. **Fixture `update_config` method duplicates config field enumeration** - Medium
   - **Evidence:** `tests/fixtures/chaosllm.py:73-134` -- manually lists every configurable parameter as keyword arguments, mirroring the config model fields.
   - **Impact:** Every new error type requires updating the fixture in addition to the config. This is the fifth file that must be touched when adding an error type.
   - **Recommendation:** Accept `**kwargs` and build the updates dict dynamically, or accept a partial config dict directly.

**Strengths:**

- In-process test fixtures using `TestClient` provide fast, isolated test execution without network overhead.
- Marker-based configuration (`@pytest.mark.chaosllm(preset="...")`) is clean and declarative.
- Deterministic metrics database path via `tmp_path` ensures test isolation.

---

## 6. Cross-Cutting Concerns

### Separation of Concerns

The composition-over-inheritance approach is executed correctly. Each subsystem (LLM, Web) owns its domain logic and delegates infrastructure to the engine layer. The engine has zero knowledge of HTTP, LLM APIs, or web scraping.

The separation breaks down at the server layer, where admin endpoints, auth, config update, health checks, and run info recording are duplicated verbatim between the two servers. These are infrastructure concerns that should be extracted.

### Dependency Management

Dependencies flow in one direction: `llm/` and `web/` depend on `engine/`, never the reverse. `llm/` and `web/` do not depend on each other. This is clean.

The `llm_mcp/` subsystem has a hard dependency on `mcp` package but correctly isolates it in its own package.

### Error Handling

Error handling is generally thoughtful:
- Chaos responses prioritized over metrics accuracy (best-effort recording).
- Config errors fail fast via Pydantic validation.
- Template errors in config crash (correct); template errors from headers degrade gracefully (correct).
- Connection errors raise `ConnectionResetError` (ASGI-appropriate).

The inconsistency between `except Exception:` (LLM) and `except sqlite3.Error:` (Web) in metrics recording is the only error handling defect.

### Security

- Admin endpoints protected by bearer token auth.
- External bind blocked by default with explicit opt-in.
- Preset names validated against path traversal.
- Jinja2 uses `SandboxedEnvironment`.
- MCP query tool uses SQLite authorizer for read-only enforcement.
- SSRF targets are comprehensive for security testing.
- HTML echo mode uses proper escaping.

No security vulnerabilities found.

### Scalability

- SQLite is the right choice for a testing tool. The schema-driven approach means each plugin gets custom tables without schema migration complexity.
- Thread-local connections with WAL mode handle concurrent access correctly for file-backed databases.
- The in-memory default (`file:*?mode=memory&cache=shared`) is correct for ephemeral test runs.
- No scalability concerns for the intended use case (chaos testing, not production traffic).

---

## Confidence Assessment

**Confidence Level:** High (85%)

I read every Python source file in `src/errorworks/` and key test fixtures. The assessment is based on direct code evidence, not documentation or assumptions.

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Divergent bug fixes between LLM/Web servers | High | Medium | Extract shared infrastructure |
| New error type requires 5-file changes | Certain (by design) | Low | Accept; config-driven approach is explicit |
| MCP server blocks on writes without WAL | Medium | Low | Add WAL pragma |

## Information Gaps

- I did not run the test suite. Test coverage and passing status are unknown.
- I did not review YAML preset files for correctness.
- The `src/errorworks/llm/cli.py` and `src/errorworks/web/cli.py` were not deeply assessed (Typer boilerplate).

## Caveats

- This assessment evaluates architecture quality for a **testing tool**, not a production service. Design choices appropriate for testing tools (SQLite, in-memory defaults, single-process architecture) would be problems in a different context.
- The duplication between `llm/` and `web/` is rated High because it actively causes maintenance divergence (proven by the `except Exception` vs `except sqlite3.Error` discrepancy), not because duplication is inherently bad. If the two servers were expected to diverge significantly in the future, controlled duplication would be acceptable.
