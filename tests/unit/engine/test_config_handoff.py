"""Unit tests for the config handoff loader.

Worker processes spawned by uvicorn re-enter the CLI via a factory function
that must reload config from env-vars set by the parent CLI. The loader needs
to be resilient to:

- The temp file being missing (race during shutdown, /tmp cleaner, mismatched
  cleanup) — falls back to the legacy inline env-var form.
- Both mechanisms being missing — raises a diagnostic error naming both env
  vars and the parent CLI's handoff lifecycle as the likely cause.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from errorworks.engine.config_handoff import (
    ConfigHandoffError,
    load_handoff_config_json,
)

FILE_ENV = "_TEST_HANDOFF_FILE"
CONFIG_ENV = "_TEST_HANDOFF_CONFIG"


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the test env vars are clean for every test."""
    monkeypatch.delenv(FILE_ENV, raising=False)
    monkeypatch.delenv(CONFIG_ENV, raising=False)


# =============================================================================
# Happy path
# =============================================================================


class TestHappyPath:
    """Loader returns the expected payload under normal conditions."""

    def test_file_env_var_returns_file_contents(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text('{"hello": "world"}')
        monkeypatch.setenv(FILE_ENV, str(config_file))

        result = load_handoff_config_json(file_env_var=FILE_ENV, config_env_var=CONFIG_ENV)

        assert result == '{"hello": "world"}'

    def test_env_var_only_returns_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CONFIG_ENV, '{"legacy": true}')

        result = load_handoff_config_json(file_env_var=FILE_ENV, config_env_var=CONFIG_ENV)

        assert result == '{"legacy": true}'

    def test_file_takes_precedence_over_env_var(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text('{"from": "file"}')
        monkeypatch.setenv(FILE_ENV, str(config_file))
        monkeypatch.setenv(CONFIG_ENV, '{"from": "env"}')

        result = load_handoff_config_json(file_env_var=FILE_ENV, config_env_var=CONFIG_ENV)

        assert result == '{"from": "file"}'


# =============================================================================
# Fallback when file is missing (the bug this loader was built to fix)
# =============================================================================


class TestFileMissingFallback:
    """When the file env var points at a missing file, fall back to env var."""

    def test_missing_file_falls_back_to_env_var(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.json"
        monkeypatch.setenv(FILE_ENV, str(missing))
        monkeypatch.setenv(CONFIG_ENV, '{"fallback": "used"}')

        result = load_handoff_config_json(file_env_var=FILE_ENV, config_env_var=CONFIG_ENV)

        assert result == '{"fallback": "used"}'

    def test_missing_file_no_fallback_raises_diagnostic(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.json"
        monkeypatch.setenv(FILE_ENV, str(missing))
        # CONFIG_ENV intentionally not set.

        with pytest.raises(ConfigHandoffError) as excinfo:
            load_handoff_config_json(file_env_var=FILE_ENV, config_env_var=CONFIG_ENV)

        message = str(excinfo.value)
        assert FILE_ENV in message
        assert CONFIG_ENV in message
        assert str(missing) in message
        # Should hint at parent CLI lifecycle as the cause.
        assert "parent" in message.lower() or "handoff" in message.lower()

    def test_missing_file_no_fallback_chains_oserror(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """The underlying OSError must be chained for debugging."""
        missing = tmp_path / "does-not-exist.json"
        monkeypatch.setenv(FILE_ENV, str(missing))

        with pytest.raises(ConfigHandoffError) as excinfo:
            load_handoff_config_json(file_env_var=FILE_ENV, config_env_var=CONFIG_ENV)

        assert isinstance(excinfo.value.__cause__, OSError)


# =============================================================================
# Nothing set
# =============================================================================


class TestNeitherSet:
    """Both env vars absent — diagnostic error naming both."""

    def test_neither_env_var_set_raises_diagnostic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # _clear_env autouse fixture already cleared both.
        with pytest.raises(ConfigHandoffError) as excinfo:
            load_handoff_config_json(file_env_var=FILE_ENV, config_env_var=CONFIG_ENV)

        message = str(excinfo.value)
        assert FILE_ENV in message
        assert CONFIG_ENV in message


# =============================================================================
# Integration with the three production call sites
# =============================================================================


class TestLLMSiteUsesHandoff:
    """The LLM server factory uses the shared handoff loader."""

    def test_llm_missing_file_falls_back_to_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from starlette.applications import Starlette

        from errorworks.llm.config import ChaosLLMConfig
        from errorworks.llm.server import _create_app_from_env

        missing = tmp_path / "missing.json"
        monkeypatch.setenv("_ERRORWORKS_LLM_CONFIG_FILE", str(missing))
        monkeypatch.setenv("_ERRORWORKS_LLM_CONFIG", ChaosLLMConfig().model_dump_json())

        app = _create_app_from_env()

        assert isinstance(app, Starlette)

    def test_llm_missing_both_raises_diagnostic(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from errorworks.llm.server import _create_app_from_env

        missing = tmp_path / "missing.json"
        monkeypatch.setenv("_ERRORWORKS_LLM_CONFIG_FILE", str(missing))
        monkeypatch.delenv("_ERRORWORKS_LLM_CONFIG", raising=False)

        with pytest.raises(ConfigHandoffError):
            _create_app_from_env()


class TestWebSiteUsesHandoff:
    """The Web server factory uses the shared handoff loader."""

    def test_web_missing_file_falls_back_to_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from starlette.applications import Starlette

        from errorworks.web.config import ChaosWebConfig
        from errorworks.web.server import _create_app_from_env

        missing = tmp_path / "missing.json"
        monkeypatch.setenv("_ERRORWORKS_WEB_CONFIG_FILE", str(missing))
        monkeypatch.setenv("_ERRORWORKS_WEB_CONFIG", ChaosWebConfig().model_dump_json())

        app = _create_app_from_env()

        assert isinstance(app, Starlette)

    def test_web_missing_both_raises_diagnostic(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from errorworks.web.server import _create_app_from_env

        missing = tmp_path / "missing.json"
        monkeypatch.setenv("_ERRORWORKS_WEB_CONFIG_FILE", str(missing))
        monkeypatch.delenv("_ERRORWORKS_WEB_CONFIG", raising=False)

        with pytest.raises(ConfigHandoffError):
            _create_app_from_env()


class TestBlobSiteUsesHandoff:
    """The Blob CLI factory uses the shared handoff loader."""

    def test_blob_missing_file_falls_back_to_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from starlette.applications import Starlette

        from errorworks.blob.cli import _create_app_from_env
        from errorworks.blob.config import ChaosBlobConfig

        missing = tmp_path / "missing.json"
        monkeypatch.setenv("_ERRORWORKS_BLOB_CONFIG_FILE", str(missing))
        monkeypatch.setenv("_ERRORWORKS_BLOB_CONFIG", ChaosBlobConfig().model_dump_json())

        app = _create_app_from_env()

        assert isinstance(app, Starlette)

    def test_blob_missing_both_raises_diagnostic(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from errorworks.blob.cli import _create_app_from_env

        missing = tmp_path / "missing.json"
        monkeypatch.setenv("_ERRORWORKS_BLOB_CONFIG_FILE", str(missing))
        monkeypatch.delenv("_ERRORWORKS_BLOB_CONFIG", raising=False)

        with pytest.raises(ConfigHandoffError):
            _create_app_from_env()
