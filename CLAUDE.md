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

<!-- filigree:instructions:v1.5.1:63b4188e -->
## Filigree Issue Tracker

Use `filigree` for all task tracking in this project. Data lives in `.filigree/`.

### MCP Tools (Preferred)

When MCP is configured, prefer `mcp__filigree__*` tools over CLI commands — they're
faster and return structured data. Key tools:

- `get_ready` / `get_blocked` — find available work
- `get_issue` / `list_issues` / `search_issues` — read issues
- `create_issue` / `update_issue` / `close_issue` — manage issues
- `claim_issue` / `claim_next` — atomic claiming
- `add_comment` / `add_label` — metadata
- `list_labels` / `get_label_taxonomy` — discover labels and reserved namespaces
- `create_plan` / `get_plan` — milestone planning
- `get_stats` / `get_metrics` — project health
- `get_valid_transitions` — workflow navigation
- `observe` / `list_observations` / `dismiss_observation` / `promote_observation` — agent scratchpad
- `trigger_scan` / `trigger_scan_batch` / `get_scan_status` / `preview_scan` / `list_scanners` — automated code scanning
- `get_finding` / `list_findings` / `update_finding` / `batch_update_findings` — scan finding triage
- `promote_finding` / `dismiss_finding` — finding lifecycle (promote to issue or dismiss)

Observations are fire-and-forget notes that expire after 14 days. Use `list_issues --label=from-observation` to find promoted observations.

**Observations are ambient.** While doing other work, use `observe` whenever you
notice something worth noting — a code smell, a potential bug, a missing test, a
design concern. Don't stop what you're doing; just fire off the observation and
carry on. They're ideal for "I don't have time to investigate this right now, but
I want to come back to it." Include `file_path` and `line` when relevant so the
observation is anchored to code. At session end, skim `list_observations` and
either `dismiss_observation` (not worth tracking) or `promote_observation`
(deserves an issue) for anything that's accumulated.

Fall back to CLI (`filigree <command>`) when MCP is unavailable.

### CLI Quick Reference

```bash
# Finding work
filigree ready                              # Show issues ready to work (no blockers)
filigree list --status=open                 # All open issues
filigree list --status=in_progress          # Active work
filigree list --label=bug --label=P1        # Filter by multiple labels (AND)
filigree list --label-prefix=cluster/       # Filter by label namespace prefix
filigree list --not-label=wontfix           # Exclude issues with label
filigree show <id>                          # Detailed issue view

# Creating & updating
filigree create "Title" --type=task --priority=2          # New issue
filigree update <id> --status=in_progress                # Claim work
filigree close <id>                                      # Mark complete
filigree close <id> --reason="explanation"               # Close with reason

# Dependencies
filigree add-dep <issue> <depends-on>       # Add dependency
filigree remove-dep <issue> <depends-on>    # Remove dependency
filigree blocked                            # Show blocked issues

# Comments & labels
filigree add-comment <id> "text"            # Add comment
filigree get-comments <id>                  # List comments
filigree add-label <id> <label>             # Add label
filigree remove-label <id> <label>          # Remove label
filigree labels                             # List all labels by namespace
filigree taxonomy                           # Show reserved namespaces and vocabulary

# Workflow templates
filigree types                              # List registered types with state flows
filigree type-info <type>                   # Full workflow definition for a type
filigree transitions <id>                   # Valid next states for an issue
filigree packs                              # List enabled workflow packs
filigree validate <id>                      # Validate issue against template
filigree guide <pack>                       # Display workflow guide for a pack

# Atomic claiming
filigree claim <id> --assignee <name>            # Claim issue (optimistic lock)
filigree claim-next --assignee <name>            # Claim highest-priority ready issue

# Batch operations
filigree batch-update <ids...> --priority=0      # Update multiple issues
filigree batch-close <ids...>                    # Close multiple with error reporting

# Planning
filigree create-plan --file plan.json            # Create milestone/phase/step hierarchy

# Event history
filigree changes --since 2026-01-01T00:00:00    # Events since timestamp
filigree events <id>                             # Event history for issue
filigree explain-state <type> <state>            # Explain a workflow state

# All commands support --json and --actor flags
filigree --actor bot-1 create "Title"            # Specify actor identity
filigree list --json                             # Machine-readable output

# Project health
filigree stats                              # Project statistics
filigree search "query"                     # Search issues
filigree doctor                             # Health check
```

### File Records & Scan Findings (API)

The dashboard exposes REST endpoints for file tracking and scan result ingestion.
Use `GET /api/files/_schema` for available endpoints and valid field values.

Key endpoints:
- `GET /api/files/_schema` — Discovery: valid enums, endpoint catalog
- `POST /api/v1/scan-results` — Ingest scan results (SARIF-lite format)
- `GET /api/files` — List tracked files with filtering and sorting
- `GET /api/files/{file_id}` — File detail with associations and findings summary
- `GET /api/files/{file_id}/findings` — Findings for a specific file

### Workflow
1. `filigree ready` to find available work
2. `filigree show <id>` to review details
3. `filigree transitions <id>` to see valid state changes
4. `filigree update <id> --status=in_progress` to claim it
5. Do the work, commit code
6. `filigree close <id>` when done

### Session Start
When beginning a new session, run `filigree session-context` to load the project
snapshot (ready work, in-progress items, critical path). This provides the
context needed to pick up where the previous session left off.

### Priority Scale
- P0: Critical (drop everything)
- P1: High (do next)
- P2: Medium (default)
- P3: Low
- P4: Backlog
<!-- /filigree:instructions -->
