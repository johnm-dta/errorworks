from __future__ import annotations

import tomllib
from pathlib import Path

import errorworks

ROOT = Path(__file__).resolve().parents[2]


def test_package_version_matches_pyproject() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert errorworks.__version__ == pyproject["project"]["version"]
