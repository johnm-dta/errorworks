# Errorworks Deep Dive — Final Report

**Date:** 2026-03-12
**Scope:** Full codebase analysis (~9,350 LOC, 6 subsystems, 665 tests)

---

## Executive Summary

Errorworks is a well-engineered codebase. Static analysis is completely clean (ruff, mypy), all 665 tests pass, and the architecture follows its stated principles (composition over inheritance, frozen configs, thread-safe metrics). The overall architecture quality is **4/5**.

However, the deep analysis revealed **2 critical security issues**, **3 high-severity architecture concerns**, and **12 significant test coverage gaps** that should be addressed.

---

## Health Check Results

| Tool | Result |
|------|--------|
| Ruff lint | Clean — 0 violations |
| Mypy types | Clean — 0 issues in 26 files |
| Test suite | 665/665 passing (42s) |

---

## Critical Findings (Fix Immediately)

### SEC-1: Admin Token Leaked to Metrics Database (CRITICAL)

**Files:** `llm/server.py:217-228`, `web/server.py`, `engine/metrics_store.py:505-509`

The `admin_token` is persisted in plaintext in `run_info.config_json` via `model_dump()`. Any MCP client can extract it:
```sql
SELECT config_json FROM run_info
```
This completely bypasses admin authentication.

**Fix:** Use `model_dump(exclude={"admin_token"})` when serializing config for storage and export.

### SEC-2: Timing Side-Channel in Token Comparison (HIGH)

**Files:** `llm/server.py:268`, `web/server.py:226`

`auth_header[7:] != token` uses Python's short-circuit string comparison, enabling byte-by-byte token recovery via timing analysis.

**Fix:** Replace with `hmac.compare_digest(auth_header[7:], token)`.

---

## Architecture Issues

### ARCH-1: Structural Duplication Between LLM and Web Servers (HIGH)

Admin auth, admin endpoints, config update, health check, run info recording, and `MetricsRecorder` are copy-pasted between the two servers. This has **already caused a bug**: `llm/server.py:802` catches bare `Exception` while `web/server.py:882` correctly catches only `sqlite3.Error`.

**Recommendation:** Extract shared server infrastructure into a mixin or shared router module.

### ARCH-2: Server Files Are Too Large (HIGH)

- `llm_mcp/server.py` — 1,102 lines
- `web/server.py` — 934 lines
- `llm/server.py` — 829 lines

Error handlers take 8-11 keyword arguments threaded through cascading if-elif chains. Adding a new error type requires touching 3+ methods.

**Recommendation:** Extract error response rendering into separate modules. Use a registry pattern for error category dispatch.

### ARCH-3: MCP Server Missing WAL Mode (HIGH)

`llm_mcp/server.py:68-71` connects to SQLite without WAL pragma or timeout. Reads block when ChaosLLM is writing.

**Fix:** Add `conn.execute("PRAGMA journal_mode=WAL")` and `timeout=30.0`.

### ARCH-4: `except Exception` vs `except sqlite3.Error` Inconsistency (MEDIUM)

`llm/server.py:802` catches bare `Exception` (swallowing `KeyboardInterrupt`, `SystemExit`, and programming errors). `web/server.py:882` correctly catches only `sqlite3.Error`.

**Fix:** Align LLM server to catch `(sqlite3.Error, ValueError)` like the web server.

### ARCH-5: MCP `describe_schema()` Hardcoded (MEDIUM)

Schema description is hardcoded and can drift from actual `LLM_METRICS_SCHEMA`. No validation ensures they stay in sync.

### ARCH-6: Empty `testing/__init__.py` (MEDIUM)

Declares `ChaosLLMFixture` and `ChaosWebFixture` in docstring but doesn't export them. Consumers must import from `tests/fixtures/` directly.

---

## Test Coverage Gaps (Priority Order)

### Critical

| ID | Gap | Impact |
|----|-----|--------|
| GAP-C1 | Admin auth rejection paths (401/403) — zero negative tests | Security regression undetectable |
| GAP-C2 | MCP `_readonly_authorizer` — no direct tests, defense-in-depth unverified | SQL injection defense untested |

### High

| ID | Gap | Impact |
|----|-----|--------|
| GAP-H1 | `MetricsStore.rebuild_timeseries` — most complex method, zero tests | Silent data corruption |
| GAP-H2 | LLM connection-error handlers — not exercised through HTTP | Metrics recording untested end-to-end |
| GAP-H3 | `_StreamingDisconnect` ASGI class — completely untested | Mid-transfer disconnect simulation broken silently |
| GAP-H4 | `load_config` empty YAML warning path — untested | Config loading regression |

### Medium

| ID | Gap | Impact |
|----|-----|--------|
| GAP-M1 | `simulate_slow_response` — no direct test | Low |
| GAP-M2 | Midnight bucket boundary — not tested | Cross-day metrics corruption |
| GAP-M3 | `ResponseGenerator` mode fallback messages — not covered | Low |
| GAP-M4 | `chaosengine` unified CLI — no tests at all | Routing regression |
| GAP-M5 | MCP `_find_metrics_databases` autodiscovery — not tested | Wrong DB selected silently |

---

## Security Threat Summary (STRIDE)

| ID | Threat | Risk | Fix Complexity |
|----|--------|------|----------------|
| THREAT-006/003 | Admin token in SQLite `run_info` table | **Critical** | Low — exclude from `model_dump()` |
| THREAT-002 | Admin token in `export_metrics()` output | **High** | Low — same fix as above |
| THREAT-007 | DoS via expensive MCP SQL queries | **High** | Medium — add `set_progress_handler()` timeout |
| THREAT-009 | Jinja2 SSTI via header (sandboxed) | **High** | Low — consider `allow_header_overrides=false` default |
| THREAT-001 | Timing side-channel in token comparison | **High** | Low — `hmac.compare_digest()` |

---

## What's Done Well

- **Composition over inheritance** genuinely executed — `InjectionEngine` has zero HTTP knowledge
- **Schema-driven DDL** via `MetricsSchema`/`ColumnDef` is clean and extensible
- **Dependency injection** (`time_func`, `rng`, `uuid_func`) enables fully deterministic tests
- **Frozen Pydantic models** with `extra="forbid"` enforce invariants at construction
- **Error handling philosophy** is correct — chaos responses over metrics accuracy
- **Security fundamentals** — bearer auth, path traversal prevention, Jinja2 sandboxing, SQLite authorizer, HTML escaping, SSRF target coverage
- **Test infrastructure** — marker-based fixtures, in-process TestClient, zero-latency defaults

---

## Recommended Action Plan

### This Week (Critical)
1. Fix admin token leakage (SEC-1) — exclude from `model_dump()` serialization
2. Fix timing side-channel (SEC-2) — use `hmac.compare_digest()`
3. Add admin auth negative tests (GAP-C1)
4. Add MCP authorizer tests (GAP-C2)

### Next Sprint
5. Fix `except Exception` inconsistency (ARCH-4)
6. Add WAL mode to MCP server (ARCH-3)
7. Add `rebuild_timeseries` tests (GAP-H1)
8. Add MCP query timeout (THREAT-007)
9. Add connection-error server tests (GAP-H2, GAP-H3)

### Future
10. Extract shared server infrastructure (ARCH-1) to eliminate duplication
11. Extract error handlers into separate modules (ARCH-2)
12. Fill remaining test gaps (GAP-M1 through GAP-M5)
13. Make MCP schema self-describing (ARCH-5)
