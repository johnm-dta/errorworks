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
