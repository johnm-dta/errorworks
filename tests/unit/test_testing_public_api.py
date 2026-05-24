"""Tests for the public errorworks.testing fixture surface."""

from __future__ import annotations

from importlib.metadata import version

import errorworks
import errorworks.testing as testing


def test_testing_exports_documented_fixtures() -> None:
    assert hasattr(testing, "ChaosLLMFixture")
    assert hasattr(testing, "ChaosWebFixture")
    assert hasattr(testing, "ChaosBlobFixture")
    assert hasattr(testing, "chaosllm_server")
    assert hasattr(testing, "chaosweb_server")
    assert hasattr(testing, "chaosblob")


def test_package_version_matches_metadata() -> None:
    assert errorworks.__version__ == version("errorworks")
