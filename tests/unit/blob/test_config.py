from __future__ import annotations

import warnings

import pytest
from pydantic import ValidationError

from errorworks.blob.config import (
    BlobErrorInjectionConfig,
    BlobStorageConfig,
    ChaosBlobConfig,
    list_presets,
    load_config,
)


def test_default_config_uses_blob_port_and_memory_database() -> None:
    config = ChaosBlobConfig()
    assert config.server.port == 8300
    assert config.metrics.database == "file:chaosblob-metrics?mode=memory&cache=shared"
    assert config.storage.max_object_bytes == 10 * 1024 * 1024


def test_list_presets_includes_expected_blob_profiles() -> None:
    assert list_presets() == ["gentle", "realistic", "silent", "stress_extreme", "stress_storage"]


def test_load_realistic_preset() -> None:
    config = load_config(preset="realistic")
    assert config.preset_name == "realistic"
    assert config.error_injection.slow_down_pct > 0
    assert config.error_injection.stale_list_pct > 0


def test_rejects_weighted_mode_at_or_above_one_hundred_percent() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        BlobErrorInjectionConfig(selection_mode="weighted", slow_down_pct=80.0, internal_error_pct=20.0)
    assert any("total error weights are >= 100" in str(item.message) for item in caught)


def test_rejects_invalid_object_size_limit() -> None:
    with pytest.raises(ValidationError):
        BlobStorageConfig(max_object_bytes=0)


def test_rejects_workers_with_memory_metrics_database() -> None:
    with pytest.raises(ValidationError, match="requires a file-backed metrics database"):
        ChaosBlobConfig(server={"workers": 2})
