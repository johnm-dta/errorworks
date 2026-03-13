"""Tests for ChaosWeb configuration module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from errorworks.web.config import (
    ChaosWebConfig,
    RandomContentConfig,
    WebBurstConfig,
    WebContentConfig,
    WebErrorInjectionConfig,
    list_presets,
    load_config,
    load_preset,
)


class TestListPresets:
    """Tests for list_presets()."""

    def test_returns_list(self) -> None:
        """list_presets returns a list of strings."""
        presets = list_presets()
        assert isinstance(presets, list)
        for name in presets:
            assert isinstance(name, str)

    def test_returns_sorted(self) -> None:
        """Presets are returned in sorted order."""
        presets = list_presets()
        assert presets == sorted(presets)

    def test_known_presets_present(self) -> None:
        """Known presets exist in the list."""
        presets = list_presets()
        assert "gentle" in presets
        assert "realistic" in presets
        assert "stress_scraping" in presets
        assert "silent" in presets


class TestLoadPreset:
    """Tests for load_preset()."""

    def test_loads_known_preset(self) -> None:
        """Known preset loads as a dict."""
        data = load_preset("gentle")
        assert isinstance(data, dict)

    def test_all_presets_load_and_validate(self) -> None:
        """Every available preset produces a valid ChaosWebConfig."""
        for preset_name in list_presets():
            config = load_config(preset=preset_name)
            assert isinstance(config, ChaosWebConfig)
            assert config.preset_name == preset_name

    def test_missing_preset_raises(self) -> None:
        """Non-existent preset raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="not_a_real_preset"):
            load_preset("not_a_real_preset")


class TestLoadConfig:
    """Tests for load_config() with merge precedence."""

    def test_defaults_only(self) -> None:
        """No arguments produces sensible defaults."""
        config = load_config()
        assert isinstance(config, ChaosWebConfig)
        assert config.preset_name is None

    def test_preset_sets_preset_name(self) -> None:
        """Preset name is recorded on the config."""
        config = load_config(preset="gentle")
        assert config.preset_name == "gentle"

    def test_cli_overrides_preset(self) -> None:
        """CLI overrides take precedence over preset values."""
        config = load_config(
            preset="gentle",
            cli_overrides={"error_injection": {"rate_limit_pct": 99.0}},
        )
        assert config.error_injection.rate_limit_pct == 99.0

    def test_three_layer_merge(self, tmp_path: Path) -> None:
        """Defaults < preset < cli_overrides — each layer wins over the one below."""
        # Write a config file that overrides the gentle preset's rate_limit_pct
        config_file = tmp_path / "mid.yaml"
        config_file.write_text("error_injection:\n  rate_limit_pct: 42.0\n")

        config = load_config(
            preset="gentle",
            config_file=config_file,
            cli_overrides={"error_injection": {"forbidden_pct": 7.0}},
        )

        # config_file overrides the gentle preset's rate_limit_pct
        assert config.error_injection.rate_limit_pct == 42.0
        # cli_overrides add forbidden_pct
        assert config.error_injection.forbidden_pct == 7.0

    def test_config_file_not_found(self, tmp_path: Path) -> None:
        """Missing config_file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_config(config_file=tmp_path / "nonexistent.yaml")


class TestChaosWebConfigDefaults:
    """Tests for ChaosWebConfig default values."""

    def test_default_port(self) -> None:
        """Default port is 8200."""
        config = ChaosWebConfig()
        assert config.server.port == 8200

    def test_default_content_mode(self) -> None:
        """Default content mode is random."""
        config = ChaosWebConfig()
        assert config.content.mode == "random"

    def test_default_error_rates_zero(self) -> None:
        """All error rates default to 0."""
        config = ChaosWebConfig()
        ei = config.error_injection
        assert ei.rate_limit_pct == 0.0
        assert ei.forbidden_pct == 0.0
        assert ei.not_found_pct == 0.0
        assert ei.timeout_pct == 0.0
        assert ei.redirect_loop_pct == 0.0
        assert ei.ssrf_redirect_pct == 0.0

    def test_frozen_model_prevents_mutation(self) -> None:
        """ChaosWebConfig is immutable."""
        config = ChaosWebConfig()
        with pytest.raises(ValidationError):
            config.preset_name = "mutated"  # type: ignore[misc]

    def test_blocks_external_bind_by_default(self) -> None:
        """Binding to 0.0.0.0 is blocked unless explicitly allowed."""
        with pytest.raises(ValidationError, match="exposes ChaosWeb"):
            ChaosWebConfig(server={"host": "0.0.0.0", "port": 8200})

    def test_allows_external_bind_when_enabled(self) -> None:
        """allow_external_bind=True permits 0.0.0.0."""
        config = ChaosWebConfig(
            server={"host": "0.0.0.0", "port": 8200},
            allow_external_bind=True,
        )
        assert config.server.host == "0.0.0.0"


class TestWebErrorInjectionConfig:
    """Tests for WebErrorInjectionConfig validation."""

    def test_negative_percentage_rejected(self) -> None:
        """Negative percentage raises ValidationError."""
        with pytest.raises(ValidationError):
            WebErrorInjectionConfig(rate_limit_pct=-1.0)

    def test_over_100_percentage_rejected(self) -> None:
        """Percentage > 100 raises ValidationError."""
        with pytest.raises(ValidationError):
            WebErrorInjectionConfig(rate_limit_pct=101.0)

    def test_boundary_zero_accepted(self) -> None:
        """0% is valid."""
        config = WebErrorInjectionConfig(rate_limit_pct=0.0)
        assert config.rate_limit_pct == 0.0

    def test_boundary_100_accepted(self) -> None:
        """100% is valid."""
        config = WebErrorInjectionConfig(rate_limit_pct=100.0)
        assert config.rate_limit_pct == 100.0

    def test_retry_after_range_validated(self) -> None:
        """retry_after_sec min must be <= max."""
        with pytest.raises(ValidationError, match="retry_after_sec"):
            WebErrorInjectionConfig(retry_after_sec=[10, 1])

    def test_timeout_sec_range_validated(self) -> None:
        """timeout_sec min must be <= max."""
        with pytest.raises(ValidationError, match="timeout_sec"):
            WebErrorInjectionConfig(timeout_sec=[60, 10])

    def test_slow_response_sec_range_validated(self) -> None:
        """slow_response_sec min must be <= max."""
        with pytest.raises(ValidationError, match="slow_response_sec"):
            WebErrorInjectionConfig(slow_response_sec=[20, 5])

    def test_incomplete_response_bytes_range_validated(self) -> None:
        """incomplete_response_bytes min must be <= max."""
        with pytest.raises(ValidationError, match="incomplete_response_bytes"):
            WebErrorInjectionConfig(incomplete_response_bytes=[1000, 100])

    def test_connection_stall_sec_range_validated(self) -> None:
        """connection_stall_sec min must be <= max."""
        with pytest.raises(ValidationError, match="connection_stall_sec"):
            WebErrorInjectionConfig(connection_stall_sec=[60, 10])

    def test_connection_stall_start_sec_range_validated(self) -> None:
        """connection_stall_start_sec min must be <= max."""
        with pytest.raises(ValidationError, match="connection_stall_start_sec"):
            WebErrorInjectionConfig(connection_stall_start_sec=[10, 1])

    def test_selection_mode_default(self) -> None:
        """Default selection mode is priority."""
        config = WebErrorInjectionConfig()
        assert config.selection_mode == "priority"

    def test_selection_mode_weighted(self) -> None:
        """Weighted selection mode is accepted."""
        config = WebErrorInjectionConfig(selection_mode="weighted")
        assert config.selection_mode == "weighted"

    def test_selection_mode_invalid(self) -> None:
        """Invalid selection mode raises ValidationError."""
        with pytest.raises(ValidationError):
            WebErrorInjectionConfig(selection_mode="invalid_mode")

    def test_range_parses_from_list(self) -> None:
        """Range fields parse from list input."""
        config = WebErrorInjectionConfig(retry_after_sec=[5, 15])
        assert config.retry_after_sec == (5, 15)

    def test_frozen(self) -> None:
        """Model is frozen (immutable)."""
        config = WebErrorInjectionConfig()
        with pytest.raises(ValidationError):
            config.rate_limit_pct = 50.0  # type: ignore[misc]


class TestWebBurstConfig:
    """Tests for WebBurstConfig defaults and validation."""

    def test_defaults(self) -> None:
        """Burst is disabled by default."""
        config = WebBurstConfig()
        assert config.enabled is False
        assert config.interval_sec == 30
        assert config.duration_sec == 5
        assert config.rate_limit_pct == 80.0
        assert config.forbidden_pct == 50.0

    def test_negative_burst_pct_rejected(self) -> None:
        """Negative burst percentage is rejected."""
        with pytest.raises(ValidationError):
            WebBurstConfig(rate_limit_pct=-1.0)

    def test_over_100_burst_pct_rejected(self) -> None:
        """Burst percentage > 100 is rejected."""
        with pytest.raises(ValidationError):
            WebBurstConfig(forbidden_pct=101.0)

    def test_frozen(self) -> None:
        """WebBurstConfig is frozen."""
        config = WebBurstConfig()
        with pytest.raises(ValidationError):
            config.enabled = True  # type: ignore[misc]


class TestWebContentConfig:
    """Tests for WebContentConfig."""

    def test_default_mode(self) -> None:
        """Default mode is random."""
        config = WebContentConfig()
        assert config.mode == "random"

    def test_valid_modes(self) -> None:
        """All declared modes are accepted."""
        for mode in ("random", "template", "echo", "preset"):
            config = WebContentConfig(mode=mode)
            assert config.mode == mode

    def test_invalid_mode_rejected(self) -> None:
        """Invalid mode raises ValidationError."""
        with pytest.raises(ValidationError):
            WebContentConfig(mode="nonexistent")

    def test_frozen(self) -> None:
        """WebContentConfig is frozen."""
        config = WebContentConfig()
        with pytest.raises(ValidationError):
            config.mode = "echo"  # type: ignore[misc]


class TestRandomContentConfig:
    """Tests for RandomContentConfig."""

    def test_min_greater_than_max_rejected(self) -> None:
        """min_words > max_words raises ValidationError."""
        with pytest.raises(ValidationError, match="min_words"):
            RandomContentConfig(min_words=500, max_words=50)

    def test_zero_words_rejected(self) -> None:
        """Zero words is rejected (gt=0 constraint)."""
        with pytest.raises(ValidationError):
            RandomContentConfig(min_words=0)

    def test_equal_min_max_accepted(self) -> None:
        """min_words == max_words is valid."""
        config = RandomContentConfig(min_words=100, max_words=100)
        assert config.min_words == config.max_words == 100

    def test_vocabulary_options(self) -> None:
        """Both vocabulary options are accepted."""
        config_en = RandomContentConfig(vocabulary="english")
        assert config_en.vocabulary == "english"
        config_lorem = RandomContentConfig(vocabulary="lorem")
        assert config_lorem.vocabulary == "lorem"


# ---------------------------------------------------------------------------
# Config roundtrip property tests
# ---------------------------------------------------------------------------


def test_config_roundtrip() -> None:
    """Default config survives dump/reload roundtrip."""
    config = ChaosWebConfig()
    dumped = config.model_dump()
    restored = ChaosWebConfig(**dumped)
    assert restored == config


def test_config_json_serializable() -> None:
    """Config model_dump produces JSON-serializable output."""
    config = ChaosWebConfig()
    dumped = config.model_dump()
    # Should not raise
    json.dumps(dumped, default=str)


class TestWebErrorInjectionPercentageWarning:
    """Tests for total percentage warning in weighted mode."""

    def test_weighted_mode_warns_when_total_exceeds_100(self) -> None:
        """Weighted mode warns when total error percentages exceed 100%."""
        import warnings

        from errorworks.web.config import WebErrorInjectionConfig

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            WebErrorInjectionConfig(
                selection_mode="weighted",
                rate_limit_pct=60.0,
                forbidden_pct=60.0,
            )
            assert len(w) == 1
            assert "exceed 100%" in str(w[0].message)

    def test_priority_mode_no_warning_even_above_100(self) -> None:
        """Priority mode never warns about total percentages."""
        import warnings

        from errorworks.web.config import WebErrorInjectionConfig

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            WebErrorInjectionConfig(
                selection_mode="priority",
                rate_limit_pct=60.0,
                forbidden_pct=60.0,
            )
            assert len(w) == 0
