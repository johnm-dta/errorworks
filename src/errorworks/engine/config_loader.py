"""Shared configuration loading utilities for chaos testing servers.

Provides YAML preset loading and deep merge for configuration precedence
(CLI > config file > preset > defaults). Each chaos plugin calls these
utilities from its own `load_config()` function.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

# Preset names must be alphanumeric with hyphens/underscores only.
# This prevents path traversal via names like "../../etc/passwd".
_VALID_PRESET_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two dicts, with override taking precedence.

    Args:
        base: Base configuration dict.
        override: Override values (takes precedence).

    Returns:
        Merged configuration dict (new dict, does not mutate inputs).
    """
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def list_presets(presets_dir: Path) -> list[str]:
    """List available preset names from a directory.

    Args:
        presets_dir: Path to the directory containing preset YAML files.

    Returns:
        Sorted list of preset names (without .yaml extension).
    """
    if not presets_dir.exists():
        return []
    return sorted(p.stem for p in presets_dir.glob("*.yaml"))


def load_preset(presets_dir: Path, preset_name: str) -> dict[str, Any]:
    """Load a preset configuration by name.

    Args:
        presets_dir: Path to the directory containing preset YAML files.
        preset_name: Name of the preset (e.g., 'gentle', 'stress_aimd').

    Returns:
        Raw configuration dict from the preset YAML.

    Raises:
        FileNotFoundError: If preset does not exist.
        yaml.YAMLError: If preset YAML is malformed.
        ValueError: If preset is not a YAML mapping.
    """
    if not _VALID_PRESET_NAME.match(preset_name):
        raise ValueError(
            f"Invalid preset name '{preset_name}': must contain only alphanumeric characters, hyphens, and underscores"
        )

    preset_path = presets_dir / f"{preset_name}.yaml"

    if not preset_path.exists():
        available = list_presets(presets_dir)
        raise FileNotFoundError(f"Preset '{preset_name}' not found. Available presets: {available}")

    with preset_path.open() as f:
        loaded = yaml.safe_load(f)
        if not isinstance(loaded, dict):
            raise ValueError(f"Preset '{preset_name}' must be a YAML mapping, got {type(loaded).__name__}")
        return loaded


def load_config[ConfigT: BaseModel](
    config_cls: type[ConfigT],
    presets_dir: Path,
    *,
    preset: str | None = None,
    config_file: Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> ConfigT:
    """Load a chaos server configuration with precedence handling.

    Generic implementation shared by all chaos plugins. Layers config
    from preset, YAML file, and CLI overrides, then validates through
    the given Pydantic model class.

    Precedence (highest to lowest):
    1. cli_overrides - Direct overrides from CLI flags
    2. config_file - User's YAML configuration file
    3. preset - Named preset configuration
    4. defaults - Built-in Pydantic defaults

    Args:
        config_cls: The Pydantic model class to validate into.
        presets_dir: Path to the plugin's presets directory.
        preset: Optional preset name to use as base.
        config_file: Optional path to YAML config file.
        cli_overrides: Optional dict of CLI flag overrides.

    Returns:
        Validated config instance of type ``config_cls``.

    Raises:
        FileNotFoundError: If preset or config_file not found.
        yaml.YAMLError: If YAML is malformed.
        pydantic.ValidationError: If final config fails validation.
    """
    config_dict: dict[str, Any] = {}

    # Layer 1: Preset (lowest precedence of explicit config)
    if preset is not None:
        config_dict = load_preset(presets_dir, preset)

    # Layer 2: Config file
    if config_file is not None:
        if not config_file.exists():
            raise FileNotFoundError(f"Config file not found: {config_file}")
        with config_file.open() as f:
            file_config = yaml.safe_load(f)
        if file_config is None:
            warnings.warn(
                f"Config file '{config_file}' is empty or contains only comments; all settings will use defaults",
                UserWarning,
                stacklevel=2,
            )
            file_config = {}
        elif not isinstance(file_config, dict):
            raise ValueError(
                f"Config file '{config_file}' must be a YAML mapping, got {type(file_config).__name__}"
            )
        config_dict = deep_merge(config_dict, file_config)

    # Layer 3: CLI overrides (highest precedence)
    if cli_overrides is not None:
        config_dict = deep_merge(config_dict, cli_overrides)

    # Record preset name used for this config (if any)
    config_dict["preset_name"] = preset

    # Validate and return
    return config_cls(**config_dict)
