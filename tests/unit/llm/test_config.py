"""Tests for ChaosLLM configuration module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from errorworks.llm.config import (
    ChaosLLMConfig,
    ErrorInjectionConfig,
    RandomResponseConfig,
    ResponseConfig,
    list_presets,
    load_config,
    load_preset,
)
from errorworks.llm.config import (
    LLMBurstConfig as BurstConfig,
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
        assert "chaos" in presets
        assert "silent" in presets


class TestLoadPreset:
    """Tests for load_preset()."""

    def test_loads_known_preset(self) -> None:
        """Known preset loads as a dict."""
        data = load_preset("gentle")
        assert isinstance(data, dict)

    def test_all_presets_load_and_validate(self) -> None:
        """Every available preset produces a valid ChaosLLMConfig."""
        for preset_name in list_presets():
            config = load_config(preset=preset_name)
            assert isinstance(config, ChaosLLMConfig)
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
        assert isinstance(config, ChaosLLMConfig)
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
        config_file = tmp_path / "mid.yaml"
        config_file.write_text("error_injection:\n  rate_limit_pct: 42.0\n")

        config = load_config(
            preset="gentle",
            config_file=config_file,
            cli_overrides={"error_injection": {"forbidden_pct": 7.0}},
        )

        assert config.error_injection.rate_limit_pct == 42.0
        assert config.error_injection.forbidden_pct == 7.0

    def test_config_file_not_found(self, tmp_path: Path) -> None:
        """Missing config_file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_config(config_file=tmp_path / "nonexistent.yaml")


class TestConfigRoundtrip:
    """Tests for config serialization roundtrip."""

    def test_config_roundtrip(self) -> None:
        """Default config survives dump/reload roundtrip."""
        config = ChaosLLMConfig()
        dumped = config.model_dump()
        restored = ChaosLLMConfig(**dumped)
        assert restored == config

    def test_config_json_serializable(self) -> None:
        """Config model_dump produces JSON-serializable output."""
        config = ChaosLLMConfig()
        dumped = config.model_dump()
        json.dumps(dumped, default=str)


class TestChaosLLMConfigDefaults:
    """Tests for ChaosLLMConfig default values."""

    def test_default_port(self) -> None:
        """Default port is 8000."""
        config = ChaosLLMConfig()
        assert config.server.port == 8000

    def test_default_response_mode(self) -> None:
        """Default response mode is random."""
        config = ChaosLLMConfig()
        assert config.response.mode == "random"

    def test_default_error_rates_zero(self) -> None:
        """All error rates default to 0."""
        config = ChaosLLMConfig()
        ei = config.error_injection
        assert ei.rate_limit_pct == 0.0
        assert ei.capacity_529_pct == 0.0
        assert ei.service_unavailable_pct == 0.0
        assert ei.bad_gateway_pct == 0.0
        assert ei.gateway_timeout_pct == 0.0
        assert ei.internal_error_pct == 0.0
        assert ei.forbidden_pct == 0.0
        assert ei.not_found_pct == 0.0
        assert ei.timeout_pct == 0.0
        assert ei.connection_failed_pct == 0.0
        assert ei.connection_stall_pct == 0.0
        assert ei.connection_reset_pct == 0.0
        assert ei.slow_response_pct == 0.0
        assert ei.invalid_json_pct == 0.0
        assert ei.truncated_pct == 0.0
        assert ei.empty_body_pct == 0.0
        assert ei.missing_fields_pct == 0.0
        assert ei.wrong_content_type_pct == 0.0

    def test_frozen_model_prevents_mutation(self) -> None:
        """ChaosLLMConfig is immutable."""
        config = ChaosLLMConfig()
        with pytest.raises(ValidationError):
            config.preset_name = "mutated"  # type: ignore[misc]

    def test_blocks_external_bind_by_default(self) -> None:
        """Binding to 0.0.0.0 is blocked unless explicitly allowed."""
        with pytest.raises(ValidationError, match="exposes ChaosLLM"):
            ChaosLLMConfig(server={"host": "0.0.0.0", "port": 8000})

    def test_allows_external_bind_when_enabled(self) -> None:
        """allow_external_bind=True permits 0.0.0.0."""
        config = ChaosLLMConfig(
            server={"host": "0.0.0.0", "port": 8100},
            allow_external_bind=True,
        )
        assert config.server.host == "0.0.0.0"

    def test_blocks_ipv6_all_interfaces(self) -> None:
        """Binding to :: is blocked by default."""
        with pytest.raises(ValidationError, match="exposes ChaosLLM"):
            ChaosLLMConfig(server={"host": "::", "port": 8000})

    def test_extra_fields_rejected(self) -> None:
        """Unknown top-level fields raise ValidationError."""
        with pytest.raises(ValidationError):
            ChaosLLMConfig(unknown_field="value")


class TestErrorInjectionConfig:
    """Tests for ErrorInjectionConfig validation."""

    def test_negative_percentage_rejected(self) -> None:
        """Negative percentage raises ValidationError."""
        with pytest.raises(ValidationError):
            ErrorInjectionConfig(rate_limit_pct=-1.0)

    def test_over_100_percentage_rejected(self) -> None:
        """Percentage > 100 raises ValidationError."""
        with pytest.raises(ValidationError):
            ErrorInjectionConfig(rate_limit_pct=101.0)

    def test_boundary_zero_accepted(self) -> None:
        """0% is valid."""
        config = ErrorInjectionConfig(rate_limit_pct=0.0)
        assert config.rate_limit_pct == 0.0

    def test_boundary_100_accepted(self) -> None:
        """100% is valid."""
        config = ErrorInjectionConfig(rate_limit_pct=100.0)
        assert config.rate_limit_pct == 100.0

    def test_retry_after_range_validated(self) -> None:
        """retry_after_sec min must be <= max."""
        with pytest.raises(ValidationError, match="retry_after_sec"):
            ErrorInjectionConfig(retry_after_sec=[10, 1])

    def test_timeout_sec_range_validated(self) -> None:
        """timeout_sec min must be <= max."""
        with pytest.raises(ValidationError, match="timeout_sec"):
            ErrorInjectionConfig(timeout_sec=[60, 10])

    def test_slow_response_sec_range_validated(self) -> None:
        """slow_response_sec min must be <= max."""
        with pytest.raises(ValidationError, match="slow_response_sec"):
            ErrorInjectionConfig(slow_response_sec=[30, 5])

    def test_connection_stall_sec_range_validated(self) -> None:
        """connection_stall_sec min must be <= max."""
        with pytest.raises(ValidationError, match="connection_stall_sec"):
            ErrorInjectionConfig(connection_stall_sec=[60, 10])

    def test_connection_stall_start_sec_range_validated(self) -> None:
        """connection_stall_start_sec min must be <= max."""
        with pytest.raises(ValidationError, match="connection_stall_start_sec"):
            ErrorInjectionConfig(connection_stall_start_sec=[10, 1])

    def test_connection_failed_lead_sec_range_validated(self) -> None:
        """connection_failed_lead_sec min must be <= max."""
        with pytest.raises(ValidationError, match="connection_failed_lead_sec"):
            ErrorInjectionConfig(connection_failed_lead_sec=[10, 1])

    def test_negative_range_value_rejected(self) -> None:
        """Negative values in range fields are rejected."""
        with pytest.raises(ValidationError, match="non-negative"):
            ErrorInjectionConfig(retry_after_sec=[-1, 5])

    def test_selection_mode_default(self) -> None:
        """Default selection mode is priority."""
        config = ErrorInjectionConfig()
        assert config.selection_mode == "priority"

    def test_selection_mode_weighted(self) -> None:
        """Weighted selection mode is accepted."""
        config = ErrorInjectionConfig(selection_mode="weighted")
        assert config.selection_mode == "weighted"

    def test_selection_mode_invalid(self) -> None:
        """Invalid selection mode raises ValidationError."""
        with pytest.raises(ValidationError):
            ErrorInjectionConfig(selection_mode="invalid_mode")

    def test_range_parses_from_list(self) -> None:
        """Range fields parse from list input."""
        config = ErrorInjectionConfig(retry_after_sec=[5, 15])
        assert config.retry_after_sec == (5, 15)

    def test_frozen_model(self) -> None:
        """ErrorInjectionConfig is immutable."""
        config = ErrorInjectionConfig()
        with pytest.raises(ValidationError):
            config.rate_limit_pct = 50.0  # type: ignore[misc]

    def test_extra_fields_rejected(self) -> None:
        """Unknown fields raise ValidationError."""
        with pytest.raises(ValidationError):
            ErrorInjectionConfig(unknown_pct=5.0)


class TestBurstConfig:
    """Tests for BurstConfig validation."""

    def test_burst_disabled_by_default(self) -> None:
        """Burst is disabled by default."""
        config = BurstConfig()
        assert config.enabled is False

    def test_valid_burst_timing(self) -> None:
        """Valid burst timing is accepted."""
        config = BurstConfig(enabled=True, interval_sec=30, duration_sec=5)
        assert config.duration_sec < config.interval_sec

    def test_burst_duration_must_be_less_than_interval(self) -> None:
        """duration_sec >= interval_sec raises ValidationError when enabled."""
        with pytest.raises(ValidationError, match="duration_sec"):
            BurstConfig(enabled=True, interval_sec=10, duration_sec=10)

    def test_burst_invalid_timing_allowed_when_disabled(self) -> None:
        """Invalid timing is allowed when burst is disabled."""
        config = BurstConfig(enabled=False, interval_sec=5, duration_sec=10)
        assert config.duration_sec > config.interval_sec

    def test_burst_rate_limit_pct_bounds(self) -> None:
        """Burst rate_limit_pct must be in [0, 100]."""
        with pytest.raises(ValidationError):
            BurstConfig(rate_limit_pct=-1.0)
        with pytest.raises(ValidationError):
            BurstConfig(rate_limit_pct=101.0)


class TestRandomResponseConfig:
    """Tests for RandomResponseConfig validation."""

    def test_min_words_must_be_positive(self) -> None:
        """min_words must be > 0."""
        with pytest.raises(ValidationError):
            RandomResponseConfig(min_words=0)

    def test_max_words_must_be_positive(self) -> None:
        """max_words must be > 0."""
        with pytest.raises(ValidationError):
            RandomResponseConfig(max_words=0)

    def test_min_must_be_lte_max(self) -> None:
        """min_words must be <= max_words."""
        with pytest.raises(ValidationError, match="min_words"):
            RandomResponseConfig(min_words=100, max_words=10)

    def test_vocabulary_english(self) -> None:
        """English vocabulary is accepted."""
        config = RandomResponseConfig(vocabulary="english")
        assert config.vocabulary == "english"

    def test_vocabulary_lorem(self) -> None:
        """Lorem vocabulary is accepted."""
        config = RandomResponseConfig(vocabulary="lorem")
        assert config.vocabulary == "lorem"

    def test_vocabulary_invalid(self) -> None:
        """Invalid vocabulary raises ValidationError."""
        with pytest.raises(ValidationError):
            RandomResponseConfig(vocabulary="klingon")


class TestResponseConfig:
    """Tests for ResponseConfig validation."""

    def test_valid_modes(self) -> None:
        """All four response modes are accepted."""
        for mode in ("random", "template", "echo", "preset"):
            config = ResponseConfig(mode=mode)
            assert config.mode == mode

    def test_invalid_mode_rejected(self) -> None:
        """Invalid response mode raises ValidationError."""
        with pytest.raises(ValidationError):
            ResponseConfig(mode="invalid")

    def test_max_template_length_must_be_positive(self) -> None:
        """max_template_length must be > 0."""
        with pytest.raises(ValidationError):
            ResponseConfig(max_template_length=0)


class TestErrorInjectionPercentageWarning:
    """Tests for total percentage warning in weighted mode."""

    def test_weighted_mode_warns_when_total_exceeds_100(self) -> None:
        """Weighted mode warns when total error percentages exceed 100%."""
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ErrorInjectionConfig(
                selection_mode="weighted",
                rate_limit_pct=60.0,
                timeout_pct=60.0,
            )
            assert len(w) == 1
            assert "reach or exceed 100%" in str(w[0].message)
            assert "No successful responses" in str(w[0].message)

    def test_weighted_mode_no_warning_under_100(self) -> None:
        """Weighted mode does not warn when total is under 100%."""
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ErrorInjectionConfig(
                selection_mode="weighted",
                rate_limit_pct=30.0,
                timeout_pct=20.0,
            )
            assert len(w) == 0

    def test_weighted_mode_warns_when_total_equals_100(self) -> None:
        """Weighted mode warns when total error percentages equal exactly 100%."""
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ErrorInjectionConfig(
                selection_mode="weighted",
                rate_limit_pct=50.0,
                service_unavailable_pct=50.0,
            )
            assert len(w) == 1
            assert "100.0%" in str(w[0].message)
            assert "No successful responses" in str(w[0].message)

    def test_priority_mode_no_warning_even_above_100(self) -> None:
        """Priority mode never warns about total percentages."""
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ErrorInjectionConfig(
                selection_mode="priority",
                rate_limit_pct=60.0,
                timeout_pct=60.0,
            )
            assert len(w) == 0
