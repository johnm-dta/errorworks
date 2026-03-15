"""Unit tests for the config_loader shared utilities.

Tests deep_merge, list_presets, and load_preset behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st

from errorworks.engine.config_loader import deep_merge, list_presets, load_config, load_preset

# =============================================================================
# deep_merge
# =============================================================================


class TestDeepMerge:
    """Tests for deep_merge utility."""

    def test_empty_override(self) -> None:
        """Empty override returns base unchanged."""
        base = {"a": 1, "b": 2}
        result = deep_merge(base, {})
        assert result == {"a": 1, "b": 2}

    def test_empty_base(self) -> None:
        """Empty base returns override."""
        result = deep_merge({}, {"a": 1})
        assert result == {"a": 1}

    def test_flat_override(self) -> None:
        """Override replaces flat values."""
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self) -> None:
        """Nested dicts are merged recursively."""
        base = {"top": {"a": 1, "b": 2}, "flat": "value"}
        override = {"top": {"b": 3, "c": 4}}
        result = deep_merge(base, override)
        assert result == {"top": {"a": 1, "b": 3, "c": 4}, "flat": "value"}

    def test_deep_nested_merge(self) -> None:
        """Three levels deep merges correctly."""
        base = {"l1": {"l2": {"l3": "base"}}}
        override = {"l1": {"l2": {"l4": "new"}}}
        result = deep_merge(base, override)
        assert result == {"l1": {"l2": {"l3": "base", "l4": "new"}}}

    def test_override_replaces_dict_with_scalar(self) -> None:
        """Override can replace a dict with a scalar."""
        base = {"a": {"nested": True}}
        override = {"a": "flat"}
        result = deep_merge(base, override)
        assert result == {"a": "flat"}

    def test_does_not_mutate_inputs(self) -> None:
        """deep_merge does not mutate base or override."""
        base = {"a": {"b": 1}}
        override = {"a": {"c": 2}}
        base_copy = {"a": {"b": 1}}
        override_copy = {"a": {"c": 2}}
        deep_merge(base, override)
        assert base == base_copy
        assert override == override_copy

    def test_result_does_not_alias_base_nested_dicts(self) -> None:
        """Nested dicts in result must not be shared references to base."""
        base = {"a": {"nested": 1}}
        override = {"b": 2}
        result = deep_merge(base, override)
        result["a"]["nested"] = 99
        assert base["a"]["nested"] == 1, "Mutating result must not affect base"


# =============================================================================
# list_presets
# =============================================================================


class TestListPresets:
    """Tests for list_presets utility."""

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Empty directory returns empty list."""
        assert list_presets(tmp_path) == []

    def test_nonexistent_directory(self, tmp_path: Path) -> None:
        """Non-existent directory returns empty list."""
        assert list_presets(tmp_path / "no_such_dir") == []

    def test_lists_yaml_files(self, tmp_path: Path) -> None:
        """Lists .yaml files without extension, sorted."""
        (tmp_path / "stress.yaml").write_text("key: value")
        (tmp_path / "gentle.yaml").write_text("key: value")
        (tmp_path / "not_yaml.txt").write_text("key: value")
        result = list_presets(tmp_path)
        assert result == ["gentle", "stress"]

    def test_ignores_subdirectories(self, tmp_path: Path) -> None:
        """Subdirectories with .yaml suffix are not listed as presets."""
        (tmp_path / "subdir.yaml").mkdir()
        (tmp_path / "real.yaml").write_text("key: value")
        result = list_presets(tmp_path)
        assert result == ["real"]


# =============================================================================
# load_preset
# =============================================================================


class TestLoadPreset:
    """Tests for load_preset utility."""

    def test_loads_valid_preset(self, tmp_path: Path) -> None:
        """Loads a valid YAML mapping."""
        preset_data = {"error_injection": {"rate_limit_pct": 5.0}}
        (tmp_path / "gentle.yaml").write_text(yaml.dump(preset_data))
        result = load_preset(tmp_path, "gentle")
        assert result == preset_data

    def test_missing_preset_raises(self, tmp_path: Path) -> None:
        """Missing preset raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="not found"):
            load_preset(tmp_path, "missing")

    def test_non_mapping_raises(self, tmp_path: Path) -> None:
        """Non-dict YAML raises ValueError."""
        (tmp_path / "bad.yaml").write_text("- item1\n- item2\n")
        with pytest.raises(ValueError, match="must be a YAML mapping"):
            load_preset(tmp_path, "bad")

    def test_empty_yaml_raises(self, tmp_path: Path) -> None:
        """Empty YAML file (None) raises ValueError."""
        (tmp_path / "empty.yaml").write_text("")
        with pytest.raises(ValueError, match="must be a YAML mapping"):
            load_preset(tmp_path, "empty")

    @pytest.mark.parametrize(
        "name",
        [
            "../../etc/passwd",
            "../secret",
            "foo/bar",
            ".hidden",
            " leading_space",
        ],
    )
    def test_path_traversal_names_rejected(self, tmp_path: Path, name: str) -> None:
        """Preset names with path traversal characters are rejected."""
        with pytest.raises(ValueError, match="Invalid preset name"):
            load_preset(tmp_path, name)


# =============================================================================
# load_config — config file validation
# =============================================================================


class TestLoadConfigFileValidation:
    """Tests for load_config config file type validation."""

    def test_non_dict_config_file_raises(self, tmp_path: Path) -> None:
        """Config file containing a YAML list raises ValueError."""
        from errorworks.llm.config import ChaosLLMConfig

        config_file = tmp_path / "bad_config.yaml"
        config_file.write_text("- item1\n- item2\n")
        presets_dir = tmp_path / "presets"
        presets_dir.mkdir()
        with pytest.raises(ValueError, match="must be a YAML mapping"):
            load_config(
                ChaosLLMConfig,
                presets_dir,
                config_file=config_file,
            )

    def test_scalar_config_file_raises(self, tmp_path: Path) -> None:
        """Config file containing just a string raises ValueError."""
        from errorworks.llm.config import ChaosLLMConfig

        config_file = tmp_path / "scalar_config.yaml"
        config_file.write_text('"just a string"')
        presets_dir = tmp_path / "presets"
        presets_dir.mkdir()
        with pytest.raises(ValueError, match="must be a YAML mapping"):
            load_config(
                ChaosLLMConfig,
                presets_dir,
                config_file=config_file,
            )


# ---------------------------------------------------------------------------
# Property-based tests for deep_merge
# ---------------------------------------------------------------------------

# Strategy for config-like nested dicts (2 levels deep)
_config_values = st.one_of(st.integers(), st.floats(allow_nan=False), st.text(max_size=20), st.booleans())
_flat_dicts = st.dictionaries(st.text(min_size=1, max_size=10), _config_values, max_size=5)
_nested_dicts = st.dictionaries(
    st.text(min_size=1, max_size=10),
    st.one_of(_config_values, _flat_dicts),
    max_size=5,
)


@given(d=_nested_dicts)
def test_deep_merge_identity(d: dict) -> None:
    """Merging with empty dict returns equivalent dict."""
    assert deep_merge(d, {}) == d
    assert deep_merge({}, d) == d


@given(d1=_nested_dicts, d2=_nested_dicts)
def test_deep_merge_no_key_loss(d1: dict, d2: dict) -> None:
    """Merge result contains all keys from both inputs."""
    result = deep_merge(d1, d2)
    assert set(result.keys()) == set(d1.keys()) | set(d2.keys())


@given(d1=_nested_dicts, d2=_nested_dicts)
def test_deep_merge_override_wins(d1: dict, d2: dict) -> None:
    """For flat (non-dict) keys in d2, d2's value wins."""
    result = deep_merge(d1, d2)
    for key, value in d2.items():
        if not isinstance(value, dict):
            assert result[key] == value
