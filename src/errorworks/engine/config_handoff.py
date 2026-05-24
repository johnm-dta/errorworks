"""Config handoff loader for uvicorn multi-worker mode.

Parent CLI processes serialize config to a private temp file and pass the path
via an env var; uvicorn forks worker processes which call back into a factory
function that loads the config. The env-var-only form (whole JSON serialized
into an env var) is supported as a fallback for compatibility and for cases
where the temp file is gone (race during shutdown, /tmp cleaner, mismatched
cleanup).

The bug this module exists to fix: workers reading the file would die with a
bare ``FileNotFoundError`` if the temp file was missing — no diagnostic
context, no fallback, no hint about the handoff mechanism.
"""

from __future__ import annotations

import os
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


class ConfigHandoffError(RuntimeError):
    """Raised when the config handoff between parent CLI and worker fails.

    Carries diagnostic context about which env vars were inspected and which
    file paths (if any) were attempted, so operators can map the symptom back
    to the parent CLI's handoff lifecycle.
    """


def load_handoff_config_json(
    *,
    file_env_var: str,
    config_env_var: str,
) -> str:
    """Load serialized config JSON for a uvicorn worker process.

    Precedence:

    1. If ``file_env_var`` is set, read the file at that path. If the file is
       missing (the race this loader was built to handle) or otherwise
       unreadable, log a warning and fall through to step 2.
    2. If ``config_env_var`` is set, return its value.
    3. Raise :class:`ConfigHandoffError` with diagnostic context naming both
       env vars and (if attempted) the file path and underlying OSError.

    Parameters
    ----------
    file_env_var:
        Name of the env var that holds the path to a JSON config file.
    config_env_var:
        Name of the env var that holds the JSON config directly (fallback
        and legacy mechanism).

    Returns
    -------
    str
        The serialized config JSON, ready to feed into ``model_validate_json``.

    Raises
    ------
    ConfigHandoffError
        If neither mechanism yields a usable config payload.
    """
    config_file = os.environ.get(file_env_var)
    file_error: OSError | None = None

    if config_file:
        try:
            return Path(config_file).read_text()
        except OSError as exc:
            file_error = exc
            logger.warning(
                "config_handoff_file_unreadable",
                file_env_var=file_env_var,
                config_file=config_file,
                error=str(exc),
                fallback_env_var=config_env_var,
            )
            # Fall through to env-var fallback.

    fallback = os.environ.get(config_env_var)
    if fallback is not None:
        if file_error is not None:
            logger.info(
                "config_handoff_using_env_fallback",
                file_env_var=file_env_var,
                config_env_var=config_env_var,
            )
        return fallback

    # Both mechanisms failed. Construct a diagnostic message that points the
    # operator at the parent CLI's handoff lifecycle.
    if config_file and file_error is not None:
        raise ConfigHandoffError(
            f"Worker process could not load handoff config. "
            f"File env var {file_env_var}={config_file!r} pointed at a file "
            f"that could not be read ({file_error.__class__.__name__}: {file_error}), "
            f"and fallback env var {config_env_var} is not set. "
            f"This typically means the parent CLI's temp-file lifecycle was "
            f"interrupted (early shutdown, mismatched cleanup, or /tmp cleaner) "
            f"before workers could read it."
        ) from file_error

    if config_file:
        # Pathologically: file env var set, file read succeeded but returned
        # empty AND fallback missing. Treat as not-set.
        raise ConfigHandoffError(
            f"Worker process could not load handoff config. "
            f"File env var {file_env_var}={config_file!r} did not yield config, "
            f"and fallback env var {config_env_var} is not set."
        )

    raise ConfigHandoffError(
        f"Worker process could not load handoff config. "
        f"Neither {file_env_var} (preferred, temp file path) nor "
        f"{config_env_var} (legacy/fallback, inline JSON) is set in the "
        f"environment. Workers must be spawned by a parent CLI that prepares "
        f"the handoff."
    )


__all__ = ["ConfigHandoffError", "load_handoff_config_json"]
