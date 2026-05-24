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

## Epic Creation Workflow

When creating a new epic (a major capability or theme of work), always follow this process:

1. **Create the epic** — `type: epic` with a clear description of the capability and its key sub-capabilities
2. **Draft requirements** — Create `type: requirement` issues as children of the epic (`parent_id`). Each requirement should have:
   - `req_type`: functional, non_functional, constraint, or interface
   - `rationale`: why this requirement exists
   - `acceptance_criteria`: testable conditions
   - `stakeholder`: who needs it
3. **Add acceptance criteria** — For non-trivial requirements, create `type: acceptance_criterion` children with Given/When/Then fields
4. **Label the epic** — Add `future` label for backlog epics, or appropriate labels for active work

Requirements start in `drafted` state. As epics move out of backlog:
- Requirements go through `reviewing → approved` during scope refinement
- Tasks/features created during implementation link back to their requirements via dependencies
- Requirements move to `implementing → verified` as work completes (verification requires `verification_method`: test, inspection, analysis, or demonstration)

This ensures traceability from "why does this exist" through to "how was it verified."

<!-- filigree:instructions:v2.1.0:d454f2c2 -->
## Filigree Issue Tracker

`filigree` tracks tasks for this project. Data lives in `.filigree/`. Prefer
the MCP tools (`mcp__filigree__*`) when available; fall back to the `filigree`
CLI otherwise.

### Workflow

```bash
# At session start
filigree session-context                            # ready / in-progress / critical path

# Pick up the next ready issue (atomic claim + transition to in_progress)
filigree start-next-work --assignee <name>
# ...or claim a specific issue
filigree start-work <id> --assignee <name>

# Do the work, commit, then
filigree close <id>
```

Use the atomic claim+transition verbs — `start_work` / `start_next_work`
(MCP) or `start-work` / `start-next-work` (CLI). Do **not** chain
`claim_issue` (MCP) or `filigree claim` (CLI) with a subsequent status
update — the two-step form races against other agents; the combined verb is
atomic.

### Observations: when (and when not) to use them

`observe` is a fire-and-forget scratchpad for *incidental* defects — things
you notice *outside the scope of your current task* (a code smell in a
neighbouring file, a stale TODO, a missing test for an edge case you happened
to spot). Notes expire after 14 days unless promoted. Include `file_path` and
`line` when relevant. At session end, skim `list_observations` and either
`dismiss_observation` or `promote_observation` for what has accumulated.

**You fix bugs in your currently defined scope. You do NOT use observations
to finish work prematurely.** If a defect, gap, or follow-up belongs to your
current task, you own it — handle it as part of that task: fix it now, expand
the task's scope, file a proper issue with a dependency, or surface it to the
user. Filing it as an observation and closing the task is *not* completing
the task; it is shipping known-broken work and hiding the debt in a 14-day
expiring scratchpad. The test is "would I have noticed this even if I weren't
working on this task?" If no, it's task scope, not an observation.

### Priority scale

- P0: Critical (drop everything)
- P1: High (do next)
- P2: Medium (default)
- P3: Low
- P4: Backlog

### Reaching for tools

MCP tool schemas describe each tool; `filigree --help` and `filigree <verb>
--help` are the authoritative CLI reference. You do not need to memorise
either catalogue. The verbs you will reach for most:

- **Find work:** `get_ready`, `get_blocked`, `list_issues`, `search_issues`
- **Claim work:** `start_work`, `start_next_work`
- **Update:** `add_comment`, `add_label`, `update_issue`, `close_issue`
- **Scratchpad:** `observe`, `list_observations`, `promote_observation`, `dismiss_observation`
- **Cross-product entity bindings (ADR-029):** `add_entity_association`,
  `remove_entity_association`, `list_entity_associations`,
  `list_associations_by_entity`. Used when a sibling tool (e.g.
  Clarion) needs to bind a Filigree issue to a function, class, or
  module identifier it owns. The `entity_id` is an opaque string
  from Filigree's perspective; the consumer (the sibling tool's read
  path) does drift detection against the stored
  `content_hash_at_attach`. `list_associations_by_entity` is the
  reverse-lookup surface — given a Clarion entity ID, return every
  Filigree issue bound to it (project isolation is by DB file). Also
  reachable over HTTP as
  `GET/POST /api/issue/{issue_id}/entity-associations`,
  `DELETE /api/issue/{issue_id}/entity-associations?entity_id=…`,
  and `GET /api/entity-associations?entity_id=…`.
- **Health:** `get_stats`, `get_metrics`, `get_mcp_status`

Pass `--actor <name>` (CLI) so events attribute to your agent identity.

### Error handling

Errors return `{error: str, code: ErrorCode, details?: dict}`. Switch on
`code`, not on message text. Codes: `VALIDATION`, `NOT_FOUND`, `CONFLICT`,
`INVALID_TRANSITION`, `PERMISSION`, `NOT_INITIALIZED`, `IO`,
`INVALID_API_URL`, `STOP_FAILED`, `SCHEMA_MISMATCH`, `INTERNAL`.

On `INVALID_TRANSITION`, call `get_valid_transitions` (MCP) or
`filigree transitions <id>` to see what the workflow allows from here.

Two failure modes deserve a specific response:

- **`SCHEMA_MISMATCH`** — the installed `filigree` is older than the project
  database. The error message contains upgrade guidance. Surface it to the
  user; do not retry.
- **`ForeignDatabaseError`** — filigree found a parent project's database
  but no local `.filigree.conf`. Run `filigree init` in the current
  directory. Do **not** `cd` upward to a different project unless that was
  the actual intent.
<!-- /filigree:instructions -->
