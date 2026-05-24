"""Tests for ChaosSMTP configuration."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from errorworks.smtp.config import (
    ChaosSMTPConfig,
    SMTPAdminConfig,
    SMTPCaptureConfig,
    SMTPErrorInjectionConfig,
    SMTPServerConfig,
    list_presets,
    load_config,
)


def test_default_config_uses_loopback_ports() -> None:
    config = ChaosSMTPConfig()
    assert config.smtp.host == "127.0.0.1"
    assert config.smtp.port == 2525
    assert config.admin.host == "127.0.0.1"
    assert config.admin.port == 8525
    assert config.capture.mode == "metadata"


def test_config_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ChaosSMTPConfig(unknown=True)


def test_external_bind_blocked_by_default() -> None:
    with pytest.raises(ValidationError, match="exposes ChaosSMTP"):
        ChaosSMTPConfig(smtp={"host": "0.0.0.0"})


def test_smtp_wildcard_alias_blocked_by_default() -> None:
    with pytest.raises(ValidationError, match="exposes ChaosSMTP"):
        ChaosSMTPConfig(smtp={"host": "0"})


def test_smtp_hex_wildcard_alias_blocked_by_default() -> None:
    with pytest.raises(ValidationError, match="exposes ChaosSMTP"):
        ChaosSMTPConfig(smtp={"host": "0x0"})


def test_admin_external_bind_blocked_by_default() -> None:
    with pytest.raises(ValidationError, match="exposes ChaosSMTP"):
        ChaosSMTPConfig(admin={"host": "0.0.0.0"})


def test_admin_wildcard_alias_blocked_by_default() -> None:
    with pytest.raises(ValidationError, match="exposes ChaosSMTP"):
        ChaosSMTPConfig(admin={"host": "0"})


def test_admin_hex_wildcard_alias_blocked_by_default() -> None:
    with pytest.raises(ValidationError, match="exposes ChaosSMTP"):
        ChaosSMTPConfig(admin={"host": "0x0"})


def test_external_bind_can_be_explicitly_allowed() -> None:
    config = ChaosSMTPConfig(smtp=SMTPServerConfig(host="0.0.0.0"), allow_external_bind=True)
    assert config.smtp.host == "0.0.0.0"


def test_admin_external_bind_can_be_explicitly_allowed() -> None:
    config = ChaosSMTPConfig(admin=SMTPAdminConfig(host="0.0.0.0"), allow_external_bind=True)
    assert config.admin.host == "0.0.0.0"


def test_workers_are_not_part_of_smtp_config() -> None:
    with pytest.raises(ValidationError):
        SMTPServerConfig(workers=2)


def test_capture_mode_values() -> None:
    assert SMTPCaptureConfig(mode="discard").mode == "discard"
    assert SMTPCaptureConfig(mode="metadata").mode == "metadata"
    assert SMTPCaptureConfig(mode="full").mode == "full"
    with pytest.raises(ValidationError):
        SMTPCaptureConfig(mode="raw")


def test_range_fields_accept_lists() -> None:
    config = SMTPErrorInjectionConfig(retry_after_sec=[2, 7], connection_stall_sec=[3, 9])
    assert config.retry_after_sec == (2, 7)
    assert config.connection_stall_sec == (3, 9)


def test_invalid_range_rejected() -> None:
    with pytest.raises(ValidationError, match="retry_after_sec"):
        SMTPErrorInjectionConfig(retry_after_sec=[10, 1])


def test_admin_config_has_token() -> None:
    config = SMTPAdminConfig()
    assert config.admin_token


def test_list_presets_contains_expected_names() -> None:
    assert set(list_presets()) == {"silent", "gentle", "realistic", "stress_delivery", "stress_extreme"}


def test_all_presets_load() -> None:
    for preset in list_presets():
        config = load_config(preset=preset)
        assert isinstance(config, ChaosSMTPConfig)
        assert config.preset_name == preset


def test_config_file_overlay(tmp_path: Path) -> None:
    overlay = tmp_path / "smtp.yaml"
    overlay.write_text(yaml.dump({"error_injection": {"rcpt_to_tempfail_pct": 100.0}}))
    config = load_config(preset="silent", config_file=overlay)
    assert config.error_injection.rcpt_to_tempfail_pct == 100.0


def test_cli_overrides_win(tmp_path: Path) -> None:
    overlay = tmp_path / "smtp.yaml"
    overlay.write_text(yaml.dump({"smtp": {"port": 2526}}))
    config = load_config(
        preset="silent",
        config_file=overlay,
        cli_overrides={"smtp": {"port": 2527}},
    )
    assert config.smtp.port == 2527
