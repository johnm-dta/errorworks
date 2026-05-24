"""Tests for the public errorworks.testing fixture surface."""

from __future__ import annotations


def test_testing_exports_documented_fixtures() -> None:
    from errorworks import testing

    assert hasattr(testing, "ChaosLLMFixture")
    assert hasattr(testing, "ChaosWebFixture")
    assert hasattr(testing, "chaosllm_server")
    assert hasattr(testing, "chaosweb_server")


def test_package_version_matches_metadata() -> None:
    from importlib.metadata import version

    import errorworks

    assert errorworks.__version__ == version("errorworks")
