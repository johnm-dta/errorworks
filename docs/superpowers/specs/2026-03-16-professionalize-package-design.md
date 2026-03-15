# Professionalize Errorworks Package

**Date:** 2026-03-16
**Status:** Draft
**Author:** Claude (with John Morrissey)

## Context

Errorworks is a general-purpose composable chaos-testing service framework at v0.1.0 on PyPI. The engineering foundation is strong (583 tests, strict mypy, comprehensive CI/CD, proper src/ layout) but the public-facing presentation — README, docs, metadata, community files — reads as an early-stage hobby project. The goal is to make it look like a professionally maintained tool.

Errorworks is maintained by the Digital Transformation Agency (DTA). Its primary use case is as a dependency in a reference implementation for semantic data tracing, but it's a general-purpose tool that should stand on its own. DTA branding material doesn't exist yet but should be easy to slot in later.

The project will grow to include additional server types beyond ChaosLLM and ChaosWeb (e.g. email), so documentation and structure must be extensible.

## Deliverables

### 1. README.md (~150 lines)

Expand from current 3-line stub to a full professional README.

**Structure:**
- Title + one-line tagline + 1-2 sentence value proposition
- Badge row: CI status, PyPI version, Python versions, License
- **What is errorworks?** — 2-3 paragraphs explaining the problem it solves, who it's for
- **Features** — bullet list grouped by capability:
  - Error injection (HTTP errors, connection failures, malformed responses)
  - Latency simulation (base + jitter, clamped)
  - Response generation modes (random, template, echo, preset)
  - Metrics collection (SQLite-backed, timeseries aggregation)
  - OpenAI-compatible API server (ChaosLLM)
  - Web server for scraping resilience (ChaosWeb)
  - Pytest fixtures for in-process testing
- **Quick Start** — `pip install errorworks`, 3-4 line CLI example
- **Usage** — brief examples for: CLI server, pytest fixture, presets; each linking to docs
- **Documentation** — link to MkDocs site
- **Architecture** — brief composition-based design explanation
- Footer: *"An open-source project by the Digital Transformation Agency."* + MIT license

**Badges** (shields.io / GitHub Actions):
- `![CI](https://github.com/johnm-dta/errorworks/actions/workflows/ci.yml/badge.svg)`
- `![PyPI](https://img.shields.io/pypi/v/errorworks)`
- `![Python](https://img.shields.io/pypi/pyversions/errorworks)`
- `![License](https://img.shields.io/pypi/l/errorworks)`

### 2. PyPI Metadata (pyproject.toml)

Update `[project.urls]` from single Repository link to:

```toml
[project.urls]
Homepage = "https://github.com/johnm-dta/errorworks"
Documentation = "https://johnm-dta.github.io/errorworks"
Changelog = "https://github.com/johnm-dta/errorworks/blob/main/CHANGELOG.md"
"Bug Tracker" = "https://github.com/johnm-dta/errorworks/issues"
Repository = "https://github.com/johnm-dta/errorworks"
```

### 3. MkDocs-Material Documentation Site

Deployed to GitHub Pages at `https://johnm-dta.github.io/errorworks`.

**Directory structure:**
```
docs/
├── index.md                  # Landing page (value prop, links deeper)
├── getting-started/
│   ├── installation.md       # pip/uv install, prerequisites, verification
│   └── quickstart.md         # First server, first request, first chaos scenario
├── guide/
│   ├── chaosllm.md           # ChaosLLM — config, error categories, response modes
│   ├── chaosweb.md           # ChaosWeb — same pattern
│   ├── presets.md            # Available presets, creating custom ones
│   ├── configuration.md     # YAML config, CLI flags, precedence rules
│   ├── metrics.md           # MetricsStore, timeseries, querying stats
│   └── testing-fixtures.md  # Pytest markers, fixtures, in-process testing
├── reference/
│   ├── cli.md               # chaosengine / chaosllm / chaosweb CLI reference
│   ├── api.md               # HTTP API endpoints
│   └── configuration.md     # Full config model reference (all fields, defaults, types)
├── architecture.md           # Composition pattern, engine components, config snapshot
└── changelog.md              # Include or symlink of CHANGELOG.md
```

**Design decisions:**
- Each server type (chaosllm, chaosweb, future email etc.) follows the same guide page template, making it easy to add new ones
- `guide/` is the extensibility point — new server types = new pages, no restructuring
- `reference/` separates "how to use" from "what every field means"
- MkDocs-Material theme with search plugin
- DTA attribution in footer; `logo` field commented out in mkdocs.yml, ready for DTA branding
- No `mike` versioning yet — structured so it can be added later without restructuring

**mkdocs.yml key settings:**
- `site_name: errorworks`
- `site_description: Composable chaos-testing services for LLM and web scraping pipelines`
- `site_url: https://johnm-dta.github.io/errorworks`
- `repo_url: https://github.com/johnm-dta/errorworks`
- `theme: material` with appropriate palette
- `copyright: "An open-source project by the Digital Transformation Agency"`
- Navigation structure matching directory layout above

### 4. GitHub Actions Docs Workflow

New `.github/workflows/docs.yml`:
- Triggers on push to `main` (paths: `docs/**`, `mkdocs.yml`)
- Builds MkDocs site
- Deploys to `gh-pages` branch using `peaceiris/actions-gh-pages` or equivalent
- Requires `mkdocs-material` as build dependency

### 5. Community Files

**CONTRIBUTING.md** (~30 lines):
- Prerequisites: Python 3.12+, uv
- Setup: `uv sync --all-extras`
- Running tests: `uv run pytest`
- Linting: `uv run ruff check src tests` + `uv run ruff format src tests`
- Type checking: `uv run mypy src`
- PR expectations: tests pass, ruff clean, mypy clean, changelog entry for user-facing changes
- Attribution: "This project is maintained by the Digital Transformation Agency"

**SECURITY.md** (~15 lines):
- Responsible disclosure instructions (GitHub security advisories preferred)
- Scope clarification: errorworks intentionally generates error responses, malformed data, and simulated faults — these are features, not vulnerabilities. Security issues are things like: arbitrary code execution outside sandbox, unintended data exposure, dependency vulnerabilities.

**CODE_OF_CONDUCT.md**:
- Adopt Contributor Covenant v2.1 verbatim
- Contact: maintainer email or GitHub discussions

### 6. GitHub Templates

**.github/ISSUE_TEMPLATE/bug_report.md:**
- Frontmatter: name, about, labels
- Sections: Describe the bug, Steps to reproduce, Expected behavior, Actual behavior, Environment (OS, Python version, errorworks version)

**.github/ISSUE_TEMPLATE/feature_request.md:**
- Frontmatter: name, about, labels
- Sections: Use case, Proposed solution, Alternatives considered

**.github/PULL_REQUEST_TEMPLATE.md:**
- Checklist: tests pass, ruff clean, mypy clean, changelog entry, docs updated (if applicable)
- Description section
- Related issues section

### 7. Pre-commit Config

`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.9.10  # pin to current version used in CI
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.15.0  # pin to current version
    hooks:
      - id: mypy
        additional_dependencies: [pydantic]
        args: [src]
```

Matches CI enforcement exactly.

### 8. DTA Branding Hooks

- README footer: `An open-source project by the [Digital Transformation Agency](https://www.dta.gov.au/).`
- MkDocs `copyright` field: same text
- MkDocs `theme.logo`: commented out placeholder, ready for PNG drop-in
- MkDocs `theme.favicon`: commented out placeholder
- No logo files committed — just configuration wired for future use

## Out of Scope (for now)

- Dynamic versioning from git tags (Approach 2 cherry-pick — deferred)
- Codecov integration
- CODEOWNERS file
- Dependabot config
- Full C-level docs (tutorials, integration guides, auto-generated API docs)
- DTA branding assets (logo, colour palette)

## Dependencies

- `mkdocs-material` added as a dev/docs dependency
- GitHub Pages enabled on the repository (Settings > Pages > Source: gh-pages branch)
- No other external service accounts needed

## Success Criteria

- Someone visiting the GitHub repo immediately understands what errorworks does and how to use it
- The PyPI page has functional sidebar links (Docs, Changelog, Issues, Homepage)
- The docs site is live and navigable at `johnm-dta.github.io/errorworks`
- `pre-commit install` works and catches lint/format/type issues locally
- Adding a new server type (e.g. email) requires adding one guide page and one nav entry — no restructuring
