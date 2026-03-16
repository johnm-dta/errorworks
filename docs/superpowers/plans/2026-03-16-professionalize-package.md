# Professionalize Errorworks Package — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform errorworks from a well-engineered but poorly-presented 0.1.0 package into one that looks professionally maintained — README, docs site, PyPI metadata, community files, GitHub templates, pre-commit config.

**Architecture:** No code changes. Eight independent deliverables that each produce a committable unit. The MkDocs site depends on having docs content written first, and the docs workflow depends on mkdocs.yml existing.

**Tech Stack:** MkDocs-Material, GitHub Actions, GitHub Pages, shields.io badges, pre-commit

**Spec:** `docs/superpowers/specs/2026-03-16-professionalize-package-design.md`

---

## Chunk 1: Package Metadata, Community Files, and GitHub Templates

These are small, independent files that establish the project's professional baseline.

### Task 1: Update PyPI metadata in pyproject.toml

**Files:**
- Modify: `pyproject.toml:66-67` (project.urls section)
- Modify: `pyproject.toml:47-58` (optional-dependencies — add docs group)
- Modify: `pyproject.toml:76-83` (sdist exclusions — add docs/)

- [ ] **Step 1: Add project URLs**

Replace the existing `[project.urls]` section:

```toml
[project.urls]
Homepage = "https://github.com/johnm-dta/errorworks"
Documentation = "https://johnm-dta.github.io/errorworks"
Changelog = "https://github.com/johnm-dta/errorworks/blob/main/CHANGELOG.md"
"Bug Tracker" = "https://github.com/johnm-dta/errorworks/issues"
Repository = "https://github.com/johnm-dta/errorworks"
```

- [ ] **Step 2: Add docs dependency group**

Add after the existing `dev` group in `[project.optional-dependencies]`:

```toml
docs = [
    "mkdocs-material>=9,<10",
]
```

- [ ] **Step 3: Add docs/ to sdist exclusions**

Add `"docs/"` to the `[tool.hatch.build.targets.sdist] exclude` list (after the existing `"docs/plans/"` entry). Remove the now-redundant `"docs/plans/"` and `"docs/arch-analysis-*"` entries since `"docs/"` covers them.

- [ ] **Step 4: Run uv sync to verify**

Run: `uv sync --all-extras`
Expected: Installs mkdocs-material and its dependencies without errors.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add PyPI project URLs, docs dependency group, sdist exclusions"
```

---

### Task 2: Add community files — CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md

**Files:**
- Create: `CONTRIBUTING.md`
- Create: `SECURITY.md`
- Create: `CODE_OF_CONDUCT.md`

- [ ] **Step 1: Create CONTRIBUTING.md**

```markdown
# Contributing to errorworks

Thank you for your interest in contributing to errorworks.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager

## Setup

```bash
git clone https://github.com/johnm-dta/errorworks.git
cd errorworks
uv sync --all-extras
```

## Development workflow

```bash
# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov

# Lint and format
uv run ruff check src tests
uv run ruff format src tests

# Type check
uv run mypy src
```

## Pull request expectations

- All tests pass (`uv run pytest`)
- No lint issues (`uv run ruff check src tests`)
- No format issues (`uv run ruff format --check src tests`)
- No type errors (`uv run mypy src`)
- Add a changelog entry for user-facing changes

## Project

This project is maintained by the [Digital Transformation Agency](https://www.dta.gov.au/).
```

- [ ] **Step 2: Create SECURITY.md**

```markdown
# Security Policy

## Scope

Errorworks intentionally generates error responses, malformed data, and simulated faults — these are features, not vulnerabilities.

Security issues include:
- Arbitrary code execution outside the Jinja2 sandbox
- Unintended data exposure from the metrics store
- Dependency vulnerabilities with exploitable impact

## Reporting a vulnerability

Please report security vulnerabilities through [GitHub Security Advisories](https://github.com/johnm-dta/errorworks/security/advisories/new).

Do not open a public issue for security vulnerabilities.
```

- [ ] **Step 3: Create CODE_OF_CONDUCT.md**

Fetch the full markdown text from `https://www.contributor-covenant.org/version/2/1/code_of_conduct/code_of_conduct.md` and use it verbatim. Set the `[INSERT CONTACT METHOD]` placeholder to: `john.morrissey@dta.gov.au`.

- [ ] **Step 4: Commit**

```bash
git add CONTRIBUTING.md SECURITY.md CODE_OF_CONDUCT.md
git commit -m "docs: add CONTRIBUTING, SECURITY, and CODE_OF_CONDUCT"
```

---

### Task 3: Add GitHub issue and PR templates

**Files:**
- Create: `.github/ISSUE_TEMPLATE/bug_report.md`
- Create: `.github/ISSUE_TEMPLATE/feature_request.md`
- Create: `.github/PULL_REQUEST_TEMPLATE.md`

- [ ] **Step 1: Create bug report template**

Create `.github/ISSUE_TEMPLATE/bug_report.md`:

```markdown
---
name: Bug report
about: Report a bug in errorworks
labels: bug
---

## Description

A clear description of the bug.

## Steps to reproduce

1.
2.
3.

## Expected behavior

What you expected to happen.

## Actual behavior

What actually happened. Include error messages or tracebacks if applicable.

## Environment

- OS:
- Python version:
- errorworks version:
- Installation method (pip/uv):
```

- [ ] **Step 2: Create feature request template**

Create `.github/ISSUE_TEMPLATE/feature_request.md`:

```markdown
---
name: Feature request
about: Suggest a new feature or enhancement
labels: enhancement
---

## Use case

Describe the problem or need this feature would address.

## Proposed solution

How you think this could work.

## Alternatives considered

Any other approaches you've thought about.
```

- [ ] **Step 3: Create PR template**

Create `.github/PULL_REQUEST_TEMPLATE.md`:

```markdown
## Description

What does this PR do?

## Related issues

Closes #

## Checklist

- [ ] Tests pass (`uv run pytest`)
- [ ] Lint clean (`uv run ruff check src tests`)
- [ ] Format clean (`uv run ruff format --check src tests`)
- [ ] Types clean (`uv run mypy src`)
- [ ] Changelog entry added (if user-facing change)
- [ ] Docs updated (if applicable)
```

- [ ] **Step 4: Commit**

```bash
git add .github/ISSUE_TEMPLATE/ .github/PULL_REQUEST_TEMPLATE.md
git commit -m "docs: add GitHub issue and PR templates"
```

---

### Task 4: Add pre-commit configuration

**Files:**
- Create: `.pre-commit-config.yaml`

- [ ] **Step 1: Check current ruff version**

Run: `uv run ruff --version`
Note the version number — you'll pin to this in the config.

- [ ] **Step 2: Create .pre-commit-config.yaml**

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v<RUFF_VERSION_FROM_STEP_1>
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: local
    hooks:
      - id: mypy
        name: mypy
        entry: uv run mypy src
        language: system
        types: [python]
        pass_filenames: false
```

- [ ] **Step 3: Verify pre-commit works**

Run: `uv run pre-commit run --all-files`
Expected: All hooks pass (ruff check, ruff format, mypy).

- [ ] **Step 4: Commit**

```bash
git add .pre-commit-config.yaml
git commit -m "chore: add pre-commit config for ruff and mypy"
```

---

## Chunk 2: README

The single highest-impact deliverable — what everyone sees first on GitHub and PyPI.

### Task 5: Write the full README

**Files:**
- Modify: `README.md` (replace the existing 3-line stub)

**Important context for the implementer:**
- errorworks is a general-purpose chaos testing framework, maintained by the Digital Transformation Agency (DTA)
- Two server types exist today: ChaosLLM (OpenAI-compatible) and ChaosWeb (scraping resilience). More will come (e.g. email).
- CLI entry points: `chaosllm serve`, `chaosweb serve`, `chaosengine llm serve` / `chaosengine web serve`
- Presets: silent, gentle, realistic, chaos/stress variants
- The completions endpoint is `POST /v1/chat/completions` with standard OpenAI request format
- The web endpoint is `GET /{any-path}` returning HTML
- Admin endpoints (`/admin/stats`, `/admin/config`, `/admin/export`, `/admin/reset`) require `Authorization: Bearer {admin_token}`
- Pytest fixtures use marker-based config: `@pytest.mark.chaosllm(preset="realistic")`
- Python 3.12+, install via pip or uv

- [ ] **Step 1: Write README.md**

Replace the entire file. The README should follow this structure (refer to the spec for the full outline):

**Header:**
```markdown
# errorworks

Composable chaos-testing services for LLM and web scraping pipelines.

[![CI](https://github.com/johnm-dta/errorworks/actions/workflows/ci.yml/badge.svg)](https://github.com/johnm-dta/errorworks/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/errorworks)](https://pypi.org/project/errorworks/)
[![Python](https://img.shields.io/pypi/pyversions/errorworks)](https://pypi.org/project/errorworks/)
[![License](https://img.shields.io/pypi/l/errorworks)](https://github.com/johnm-dta/errorworks/blob/main/LICENSE)
```

**What is errorworks?** (2-3 paragraphs):
- Explain the problem: testing how your code handles API failures, malformed responses, rate limits, and network issues is hard. You need a server that reproducibly generates these faults.
- Explain the solution: errorworks provides fake servers that inject configurable faults into HTTP responses. Use them to verify your LLM client retries on 429s, your scraper handles malformed HTML, your pipeline degrades gracefully under load.
- Mention: composable, configurable via CLI/YAML/presets, in-process pytest fixtures for CI, SQLite-backed metrics.

**Features** — grouped bullet list:
- Error injection categories (HTTP errors, connection failures, malformed responses)
- Latency simulation
- Response generation modes (random, template, echo, preset)
- Built-in presets (silent → stress)
- Metrics & observability (SQLite, timeseries, admin API)
- Testing support (pytest fixtures, markers, in-process — no sockets)

**Quick Start:**
```bash
pip install errorworks

# Start a fake OpenAI server with realistic fault injection
chaosllm serve --preset=realistic

# In another terminal, make a request
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4", "messages": [{"role": "user", "content": "Hello"}]}'
```

**Usage** — three subsections with brief examples:
1. CLI server (`chaosllm serve`, `chaosweb serve`, preset flags)
2. Pytest fixture (marker example, `post_completion()` / `fetch_page()` helpers)
3. Configuration (YAML file example, precedence: CLI > file > preset > defaults)

**Documentation** — link to `https://johnm-dta.github.io/errorworks`

**Architecture** — 3-4 sentences about composition-based design, engine components, the config snapshot pattern. Link to docs for full detail.

**Footer:**
```markdown
---

An open-source project by the [Digital Transformation Agency](https://www.dta.gov.au/).

Licensed under [MIT](LICENSE).
```

Target: ~120-160 lines. Don't pad it — every line should earn its place.

- [ ] **Step 2: Verify rendering**

Run: `uv run python -m markdown README.md > /dev/null 2>&1 || echo "check markdown syntax"`
Or just visually inspect the structure makes sense.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: expand README with badges, quickstart, features, and architecture"
```

---

## Chunk 3: MkDocs Site and Docs Workflow

### Task 6: Create mkdocs.yml and docs site structure

**Files:**
- Create: `mkdocs.yml`
- Create: `docs/index.md`
- Create: `docs/getting-started/installation.md`
- Create: `docs/getting-started/quickstart.md`
- Create: `docs/guide/chaosllm.md`
- Create: `docs/guide/chaosweb.md`
- Create: `docs/guide/presets.md`
- Create: `docs/guide/configuration.md`
- Create: `docs/guide/metrics.md`
- Create: `docs/guide/testing-fixtures.md`
- Create: `docs/reference/cli.md`
- Create: `docs/reference/api.md`
- Create: `docs/reference/config-schema.md`
- Create: `docs/architecture.md`

**Important context for the implementer:**
- The `docs/` directory already contains `superpowers/`, `plans/`, `arch-analysis-*`, and `file_breakdown.md` — these are internal files. They must NOT appear in the MkDocs nav. Use explicit nav entries in mkdocs.yml (no auto-discovery).
- `docs/changelog.md` is NOT committed — it's copied from `CHANGELOG.md` at build time by the docs workflow (Task 7). Add it to `.gitignore`.
- All content should be written from the perspective of a developer who has never seen errorworks before. Don't assume they've read the README.

- [ ] **Step 1: Create mkdocs.yml**

```yaml
site_name: errorworks
site_description: Composable chaos-testing services for LLM and web scraping pipelines
site_url: https://johnm-dta.github.io/errorworks
repo_url: https://github.com/johnm-dta/errorworks
repo_name: johnm-dta/errorworks

copyright: An open-source project by the <a href="https://www.dta.gov.au/">Digital Transformation Agency</a>.

theme:
  name: material
  palette:
    - scheme: default
      primary: deep purple
      accent: amber
      toggle:
        icon: material/brightness-7
        name: Switch to dark mode
    - scheme: slate
      primary: deep purple
      accent: amber
      toggle:
        icon: material/brightness-4
        name: Switch to light mode
  features:
    - navigation.sections
    - navigation.expand
    - navigation.top
    - content.code.copy
    - search.suggest
    - search.highlight
  # logo: assets/logo.png  # Uncomment when DTA branding is available
  # favicon: assets/favicon.png  # Uncomment when DTA branding is available

nav:
  - Home: index.md
  - Getting Started:
    - Installation: getting-started/installation.md
    - Quick Start: getting-started/quickstart.md
  - Guide:
    - ChaosLLM: guide/chaosllm.md
    - ChaosWeb: guide/chaosweb.md
    - Presets: guide/presets.md
    - Configuration: guide/configuration.md
    - Metrics: guide/metrics.md
    - Testing Fixtures: guide/testing-fixtures.md
  - Reference:
    - CLI: reference/cli.md
    - HTTP API: reference/api.md
    - Configuration Schema: reference/config-schema.md
  - Architecture: architecture.md
  - Changelog: changelog.md

markdown_extensions:
  - admonition
  - pymdownx.details
  - pymdownx.superfences
  - pymdownx.highlight:
      anchor_linenums: true
  - pymdownx.inlinehilite
  - pymdownx.tabbed:
      alternate_style: true
  - toc:
      permalink: true
```

- [ ] **Step 2: Add docs/changelog.md to .gitignore**

Append to `.gitignore`:
```
docs/changelog.md
```

- [ ] **Step 3: Create docs/index.md**

Landing page. Should:
- Restate the value proposition (don't just link to README)
- Have a "Get started in 60 seconds" code block (install + start server + make request)
- Link to Getting Started, Guide, and Reference sections
- Mention both ChaosLLM and ChaosWeb with one-line descriptions

- [ ] **Step 4: Create docs/getting-started/installation.md**

Cover:
- Prerequisites (Python 3.12+)
- Install from PyPI: `pip install errorworks`
- Install with uv: `uv add errorworks`
- Verify: `chaosllm --help`
- Development install: `git clone ... && uv sync --all-extras`

- [ ] **Step 5: Create docs/getting-started/quickstart.md**

Walk through a complete scenario:
1. Start ChaosLLM with `realistic` preset
2. Make a curl request to `/v1/chat/completions`
3. Observe: sometimes you get a 200, sometimes a 429 or 503
4. Check metrics via `/admin/stats` (with admin token)
5. Try ChaosWeb: `chaosweb serve --preset=realistic`, fetch a page
6. Use the pytest fixture in a test file (complete working example)

- [ ] **Step 6: Create docs/guide/chaosllm.md**

Cover:
- What ChaosLLM is (fake OpenAI-compatible server)
- Supported endpoints (`/v1/chat/completions`, `/health`, admin endpoints)
- Error injection categories: HTTP errors (429, 529, 503, 502, 504, 500), connection failures (timeout, reset, stall), malformed responses (invalid JSON, truncated, missing fields, wrong content-type)
- Response modes (random, template, echo, preset) with examples
- Streaming vs non-streaming
- Burst patterns
- Available presets with what each simulates

- [ ] **Step 7: Create docs/guide/chaosweb.md**

Same structure as chaosllm.md, covering:
- What ChaosWeb is (fake web server for scraping resilience)
- Supported endpoints (`/{any-path}`, `/health`, `/redirect`, admin endpoints)
- Error categories: all LLM categories plus SSRF redirects, content malformations (encoding mismatch, truncated HTML, charset confusion)
- Content modes
- Anti-scraping simulation features
- Available presets

- [ ] **Step 8: Create docs/guide/presets.md**

Cover:
- What presets are (pre-built configuration profiles)
- Table of all presets for each server type with key settings
- How to use: `--preset=realistic`
- How to create custom presets (YAML file structure)
- Precedence: CLI flags > config file > preset > defaults

- [ ] **Step 9: Create docs/guide/configuration.md**

Cover:
- Configuration methods: CLI flags, YAML file (`--config`), presets
- Precedence rules with example
- YAML file structure (complete example)
- Runtime config updates via `POST /admin/config` with deep merge
- The immutable config pattern (frozen Pydantic models, atomic swap under lock)

- [ ] **Step 10: Create docs/guide/metrics.md**

Cover:
- What's recorded (per-request: endpoint, outcome, status, latency, model/path)
- SQLite storage (WAL mode, thread-safe, thread-local connections)
- Timeseries aggregation (UPSERT bucketing)
- Querying via admin API (`/admin/stats`, `/admin/export`)
- Database persistence (`--database` flag)
- Reset (`/admin/reset`)

- [ ] **Step 11: Create docs/guide/testing-fixtures.md**

Cover:
- In-process testing (Starlette TestClient, no real sockets)
- Marker-based configuration: `@pytest.mark.chaosllm(preset="realistic", rate_limit_pct=25.0)`
- Available marker kwargs (map to CLI flags)
- Fixture helpers: `post_completion()`, `fetch_page()`, `update_config()`, `get_stats()`, `wait_for_requests()`
- Complete working test example for both ChaosLLM and ChaosWeb
- How to register the fixtures (plugin or conftest import)

- [ ] **Step 12: Create docs/reference/cli.md**

Full CLI reference for:
- `chaosengine` (with `llm` and `web` subcommands)
- `chaosllm serve` — all flags with defaults and descriptions
- `chaosweb serve` — all flags with defaults and descriptions
- `chaosllm-mcp` — brief description

Format as tables: Flag | Default | Description

- [ ] **Step 13: Create docs/reference/api.md**

Full HTTP API reference for both servers:
- `POST /v1/chat/completions` (ChaosLLM) — request/response format, streaming
- `GET /{path}` (ChaosWeb) — response format
- `GET /health` — both servers
- `GET /admin/stats` — response schema
- `GET /admin/config` — response schema
- `POST /admin/config` — request/response schema, deep merge behavior
- `GET /admin/export` — response schema
- `POST /admin/reset` — response schema
- Authentication: `Authorization: Bearer {admin_token}` for admin endpoints

- [ ] **Step 14: Create docs/reference/config-schema.md**

Document all Pydantic config model fields:
- `ServerConfig` (host, port, workers, admin_token, database)
- `ErrorInjectionConfig` (all percentage fields, selection_mode)
- `BurstConfig` (enabled, interval_sec, duration_sec)
- `LatencyConfig` (base_ms, jitter_ms)
- `ResponseConfig` / content mode configs
- ChaosLLM-specific and ChaosWeb-specific fields

Format as tables: Field | Type | Default | Description

Source these from the actual Pydantic models in:
- `src/errorworks/engine/config.py`
- `src/errorworks/llm/config.py`
- `src/errorworks/web/config.py`

- [ ] **Step 15: Create docs/architecture.md**

Cover:
- Composition over inheritance (engine utilities composed, not inherited)
- Package structure diagram (engine, llm, web, llm_mcp, testing)
- Key engine components: InjectionEngine, MetricsStore, LatencySimulator, ConfigLoader
- Config snapshot pattern (why and how)
- Immutable config update flow
- Thread safety model
- How to add a new server type (extensibility path)

- [ ] **Step 16: Add site/ to .gitignore**

Append to `.gitignore`:
```
site/
```

- [ ] **Step 17: Verify docs build locally**

Run: `cp CHANGELOG.md docs/changelog.md && uv run mkdocs build --strict && rm docs/changelog.md`
Expected: Builds without warnings or errors. Output in `site/` directory. The `docs/changelog.md` copy is temporary (it's gitignored — the docs workflow handles this at build time).

- [ ] **Step 18: Commit**

```bash
git add mkdocs.yml docs/ .gitignore
git commit -m "docs: add MkDocs-Material site with getting started, guides, reference, and architecture"
```

---

### Task 7: Add GitHub Actions docs workflow

**Files:**
- Create: `.github/workflows/docs.yml`

- [ ] **Step 1: Create the docs workflow**

```yaml
name: Docs

on:
  push:
    branches: [main]
    paths:
      - "docs/**"
      - "mkdocs.yml"
      - "CHANGELOG.md"

permissions:
  contents: write

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --extra docs
      - run: cp CHANGELOG.md docs/changelog.md
      - run: uv run mkdocs gh-deploy --force
```

Note: `mkdocs gh-deploy` handles pushing to the `gh-pages` branch directly — no need for a separate GitHub Pages action.

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/docs.yml
git commit -m "ci: add docs workflow for GitHub Pages deployment"
```

---

## Chunk 4: Final Verification

### Task 8: End-to-end verification

- [ ] **Step 1: Run full lint/typecheck/test suite**

Run: `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src && uv run pytest`
Expected: All pass. No existing functionality broken.

- [ ] **Step 2: Verify pre-commit**

Run: `uv run pre-commit run --all-files`
Expected: All hooks pass.

- [ ] **Step 3: Verify docs build**

Run: `cp CHANGELOG.md docs/changelog.md && uv run mkdocs build --strict`
Expected: Builds cleanly.

- [ ] **Step 4: Verify package build**

Run: `uv build`
Expected: Builds wheel and sdist. The `docs/` directory should NOT be in the sdist.

- [ ] **Step 5: Spot-check sdist contents**

Run: `tar tzf dist/errorworks-*.tar.gz | grep docs/ | head -5`
Expected: No docs/ files listed (excluded by sdist config).

- [ ] **Step 6: Clean up build artifacts**

Run: `rm -rf site/ dist/ docs/changelog.md`
