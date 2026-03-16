# Architecture Overview

Errorworks is a composable chaos-testing service framework. Each server type (LLM, Web) is built from shared engine components rather than inheriting from a base class. This document explains the design rationale, key components, and extension points.

## Composition Over Inheritance

The central design principle is that **HTTP concerns stay out of domain logic**. Each chaos plugin (ChaosLLM, ChaosWeb) creates instances of shared engine utilities and delegates specific responsibilities to them:

- **InjectionEngine** handles burst state and error selection algorithms
- **MetricsStore** handles SQLite persistence and timeseries aggregation
- **LatencySimulator** handles delay calculation
- **ConfigLoader** handles YAML loading and config precedence

The server classes (`ChaosLLMServer`, `ChaosWebServer`) own the HTTP routing, request parsing, and response formatting. They compose engine components but never extend them. This means a new server type (e.g., email, gRPC) can reuse the same engine components without inheriting HTTP-specific behavior it does not need.

## Package Structure

```
src/errorworks/
├── engine/                  # Shared core utilities
│   ├── types.py             # ServerConfig, MetricsConfig, LatencyConfig,
│   │                        # BurstConfig, ErrorSpec, SelectionMode,
│   │                        # MetricsSchema, ColumnDef
│   ├── injection_engine.py  # Burst state machine + selection algorithms
│   ├── metrics_store.py     # Thread-safe SQLite with schema-driven DDL
│   ├── latency.py           # Latency simulation (base +/- jitter)
│   ├── config_loader.py     # YAML preset loading + deep merge
│   ├── admin.py             # Shared admin endpoint handlers
│   ├── validators.py        # Shared Pydantic validators (range parsing)
│   └── cli.py               # Unified chaosengine CLI
│
├── llm/                     # ChaosLLM: Fake OpenAI-compatible server
│   ├── config.py            # ChaosLLMConfig, ErrorInjectionConfig, ResponseConfig
│   ├── server.py            # ChaosLLMServer (Starlette ASGI app)
│   ├── error_injector.py    # LLM-specific error decision logic
│   ├── response_generator.py# OpenAI-format response generation
│   ├── metrics.py           # LLM-specific MetricsRecorder wrapper
│   ├── cli.py               # chaosllm CLI
│   └── presets/             # YAML preset files
│
├── web/                     # ChaosWeb: Fake web server for scraping tests
│   ├── config.py            # ChaosWebConfig, WebErrorInjectionConfig, WebContentConfig
│   ├── server.py            # ChaosWebServer (Starlette ASGI app)
│   ├── error_injector.py    # Web-specific error decision logic
│   ├── content_generator.py # HTML content generation + corruption functions
│   ├── metrics.py           # Web-specific MetricsRecorder wrapper
│   ├── cli.py               # chaosweb CLI
│   └── presets/             # YAML preset files
│
├── llm_mcp/                 # MCP server for ChaosLLM metrics analysis
│   └── server.py            # Claude-optimized metrics tools via MCP protocol
│
└── testing/                 # Pytest fixture support
    └── ...                  # In-process test fixtures using Starlette TestClient
```

## Key Engine Components

### InjectionEngine

**File:** `engine/injection_engine.py`

The InjectionEngine is the decision-making core for error injection. It handles two concerns:

1. **Burst state machine** -- Periodic burst windows where error rates are elevated. Bursts occur every `interval_sec` seconds and last for `duration_sec` seconds. The state is computed from elapsed time using modular arithmetic (`elapsed % interval < duration`), making it stateless beyond the start timestamp.

2. **Error selection** -- Two algorithms:
   - **Priority mode:** Specs are evaluated in order. The first one that triggers (based on a random roll against its weight) wins. This gives deterministic precedence to high-priority errors.
   - **Weighted mode:** A single error is selected proportionally from all active specs. Success probability is implicitly `max(0, 100 - total_weight)`.

The engine is deliberately domain-agnostic. It works with `ErrorSpec(tag, weight)` objects where `tag` is an opaque string. The calling plugin builds the spec list (with domain-specific tags like `"rate_limit"` or `"ssrf_redirect"`) and interprets the selected tag to produce a response.

**Thread safety:** The burst start time is protected by a lock. The RNG is not thread-safe, but this is handled by the config snapshot pattern (each request snapshots the engine reference, so concurrent requests use different engine instances after a config update).

**Testability:** Both `time_func` and `rng` are injectable. Tests pass `time.monotonic` replacements and seeded `random.Random` instances for deterministic behavior.

### MetricsStore

**File:** `engine/metrics_store.py`

Thread-safe SQLite storage with several notable design choices:

- **Thread-local connections:** Each thread gets its own `sqlite3.Connection` via `threading.local()`. This avoids SQLite's thread-safety limitations while allowing concurrent access from uvicorn workers.

- **WAL mode for file databases:** File-backed databases use Write-Ahead Logging (`PRAGMA journal_mode=WAL`) with `PRAGMA synchronous=NORMAL` for better concurrent read/write performance. In-memory databases use `PRAGMA journal_mode=MEMORY` with `PRAGMA synchronous=OFF` for maximum speed.

- **Schema-driven DDL:** Table structures are defined declaratively via `MetricsSchema` dataclasses containing `ColumnDef` tuples. The store generates `CREATE TABLE IF NOT EXISTS` statements from the schema at initialization. This means each plugin defines its own schema (LLM requests have `model` and `deployment` columns; Web requests have `path` and `redirect_hops` columns) without modifying the store.

- **Timeseries UPSERT:** The `update_timeseries()` method uses SQLite's `INSERT ... ON CONFLICT(bucket_utc) DO UPDATE SET` to atomically increment counters per time bucket. Latency statistics (avg, p99) are computed via SQL aggregation rather than loading all values into Python.

- **Stale connection cleanup:** When a new connection is created, connections from dead threads are detected and closed. Thread ID reuse is an acknowledged edge case that is acceptable for a testing tool.

### LatencySimulator

**File:** `engine/latency.py`

Adds artificial delays to simulate real service latency. The formula is:

```
delay_seconds = max(0, (base_ms + uniform(-jitter_ms, +jitter_ms))) / 1000
```

The result is always non-negative (clamped to 0). The simulator also provides `simulate_slow_response(min_sec, max_sec)` for slow response error injection where delays are specified as second-level ranges.

Like the InjectionEngine, the RNG is injectable for deterministic testing.

### ConfigLoader

**File:** `engine/config_loader.py`

Handles configuration loading with a four-layer precedence model:

1. **CLI flags** (highest) -- Only explicitly provided values; `None` values are excluded so they do not override lower layers.
2. **Config file** -- YAML file specified by `--config`.
3. **Preset** -- Named YAML file from the plugin's `presets/` directory.
4. **Built-in defaults** (lowest) -- Pydantic field defaults.

The `deep_merge(base, override)` function recursively merges dicts so that nested updates (e.g., changing only `burst.enabled` within `error_injection`) preserve sibling fields rather than resetting them to defaults. The function returns a new dict and never mutates its inputs.

**Preset safety:** Preset names are validated against `^[a-zA-Z0-9][a-zA-Z0-9_-]*$` to prevent path traversal attacks.

## Config Snapshot Pattern

Request handlers in both `ChaosLLMServer` and `ChaosWebServer` snapshot component references at the start of each request:

```python
with self._config_lock:
    error_injector = self._error_injector
    response_generator = self._response_generator
    latency_simulator = self._latency_simulator
```

This snapshot is taken under `_config_lock` and produces local references that the handler uses for the remainder of the request. If a concurrent `update_config()` call swaps in new components while the request is in progress, the request continues using the old components, guaranteeing a consistent configuration view throughout its lifetime.

This pattern is critical because the alternative -- reading `self._error_injector` at error check time and `self._response_generator` later at response time -- could produce a half-updated view where the error rates come from the new config but the response settings come from the old one.

## Immutable Config Update Flow

All Pydantic config models use `frozen=True` and `extra="forbid"`. This means fields cannot be mutated after construction and unknown fields cause validation errors.

Runtime configuration updates through `POST /admin/config` follow this sequence:

1. **Receive** the partial update dict from the HTTP request body.
2. **Deep-merge** the update with the current config (preserving unspecified nested fields).
3. **Construct** new Pydantic model instances from the merged dict (validation happens here).
4. **Create** new component instances (e.g., new `ErrorInjector`, new `ResponseGenerator`) from the new config. This happens outside the lock because construction and validation may be expensive.
5. **Swap** the new components atomically under `_config_lock`.

If validation fails at step 3, no changes are applied and a 422 error is returned. If construction succeeds, the swap in step 5 is an atomic pointer replacement -- there is no intermediate state where some components are updated and others are not.

## Thread Safety Model

Errorworks is designed for multi-worker uvicorn deployments. The thread safety strategy has several layers:

- **`_config_lock`** (per-server instance): Protects reads and writes of component references (`_error_injector`, `_response_generator`, etc.). The lock is held briefly for pointer reads (snapshot) and pointer swaps (update), never for request processing.

- **InjectionEngine lock**: Protects the burst start timestamp. Held only for the time calculation.

- **MetricsStore thread-local connections**: Each thread gets its own SQLite connection, avoiding cross-thread connection sharing entirely.

- **Immutable config models**: Frozen Pydantic models cannot be accidentally mutated by concurrent readers.

- **Best-effort metrics recording**: Metrics writes that fail (SQLite errors) are logged but never propagated to the caller. A metrics side-effect must not replace an intended chaos response with an unintended real 500 error.

## Adding a New Server Type

To add a new chaos server type (e.g., email, gRPC, GraphQL), follow this pattern:

1. **Create a new package** under `src/errorworks/` (e.g., `src/errorworks/email/`).

2. **Define config models** in `config.py`:
   - Create an error injection config with domain-specific `_pct` fields
   - Create a content/response config appropriate to the protocol
   - Create a top-level config composing `ServerConfig`, `MetricsConfig`, `LatencyConfig`, and your domain configs
   - Wire up `load_config()` using the shared `config_loader.load_config()` generic function

3. **Define a metrics schema** using `MetricsSchema` and `ColumnDef` with domain-specific columns for the requests and timeseries tables.

4. **Create an error injector** that:
   - Composes an `InjectionEngine` instance
   - Builds `ErrorSpec` lists from your config (with burst-aware adjustments)
   - Calls `engine.select(specs)` and maps the selected tag to a domain-specific decision dataclass

5. **Create a server class** that:
   - Composes all components (error injector, content generator, latency simulator, metrics recorder)
   - Implements the `ChaosServer` protocol from `engine/admin.py` (`get_admin_token`, `get_current_config`, `update_config`, `reset`, `export_metrics`, `get_stats`)
   - Uses the config snapshot pattern in request handlers
   - Uses the immutable config update flow in `update_config()`

6. **Register routes** including `/health`, `/admin/*` (delegating to `engine.admin` handlers), and your domain-specific endpoints.

7. **Add a CLI** using Typer, with a `serve` command and a `presets` command. Register it as a console script in `pyproject.toml` and add it as a subcommand to `chaosengine`.

8. **Add presets** as YAML files in a `presets/` directory within your package.

The shared engine layer handles all the infrastructure: burst timing, selection algorithms, SQLite management, config loading, admin authentication, and deep merge. Your plugin only needs to define what errors look like in your domain and how to render responses.
