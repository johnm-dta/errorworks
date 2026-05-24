"""Configuration schema and loading for ChaosBlob server."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from errorworks.engine.config_loader import list_presets as _list_presets
from errorworks.engine.config_loader import load_config as _load_config
from errorworks.engine.config_loader import load_preset as _load_preset
from errorworks.engine.types import DANGEROUS_BIND_HOSTS, LatencyConfig, MetricsConfig, ServerConfig
from errorworks.engine.validators import parse_range as _parse_range
from errorworks.engine.validators import validate_ranges as _validate_ranges

__all__ = [
    "DEFAULT_MEMORY_DB",
    "BlobBurstConfig",
    "BlobErrorInjectionConfig",
    "BlobStorageConfig",
    "ChaosBlobConfig",
    "LatencyConfig",
    "MetricsConfig",
    "ServerConfig",
    "list_presets",
    "load_config",
    "load_preset",
]

DEFAULT_MEMORY_DB = "file:chaosblob-metrics?mode=memory&cache=shared"


class BlobBurstConfig(BaseModel):
    """Burst pattern configuration for transient object-storage stress."""

    model_config = {"frozen": True, "extra": "forbid"}

    enabled: bool = Field(default=False, description="Enable burst pattern injection")
    interval_sec: int = Field(default=60, gt=0, description="Time between burst starts in seconds")
    duration_sec: int = Field(default=10, gt=0, description="How long each burst lasts in seconds")
    slow_down_pct: float = Field(default=80.0, ge=0.0, le=100.0, description="SlowDown percentage during burst")
    service_unavailable_pct: float = Field(default=40.0, ge=0.0, le=100.0, description="503 percentage during burst")

    @model_validator(mode="after")
    def _validate_burst_timing(self) -> BlobBurstConfig:
        if self.enabled and self.duration_sec >= self.interval_sec:
            raise ValueError(
                f"duration_sec ({self.duration_sec}) must be less than interval_sec ({self.interval_sec}) when burst is enabled"
            )
        return self


class BlobErrorInjectionConfig(BaseModel):
    """Error injection configuration for blob/object-storage scenarios."""

    model_config = {"frozen": True, "extra": "forbid"}

    slow_down_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="S3 SlowDown error percentage")
    access_denied_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="403 AccessDenied error percentage")
    not_found_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="404 NoSuchKey error percentage")
    service_unavailable_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="503 ServiceUnavailable error percentage")
    internal_error_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="500 InternalError percentage")
    bad_gateway_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="502 BadGateway percentage")
    gateway_timeout_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="504 GatewayTimeout percentage")

    retry_after_sec: tuple[int, int] = Field(default=(1, 30), description="Retry-After value range [min, max] seconds")

    timeout_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Percentage of requests that hang")
    timeout_sec: tuple[int, int] = Field(default=(30, 60), description="How long to hang [min, max] seconds")
    connection_reset_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Percentage of requests that reset")
    connection_stall_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Percentage of requests that stall")
    connection_stall_start_sec: tuple[int, int] = Field(default=(0, 2), description="Delay before stalling [min, max]")
    connection_stall_sec: tuple[int, int] = Field(default=(30, 60), description="Stall duration [min, max] seconds")
    slow_response_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Percentage of slow responses")
    slow_response_sec: tuple[int, int] = Field(default=(3, 15), description="Slow response delay range [min, max] seconds")

    truncated_body_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Percentage of truncated object bodies")
    wrong_content_length_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Percentage with wrong Content-Length")
    checksum_mismatch_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Percentage with checksum mismatch")
    metadata_corruption_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Percentage with corrupted metadata")
    stale_list_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Percentage of stale list responses")
    malformed_xml_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Percentage of malformed XML responses")

    burst: BlobBurstConfig = Field(default_factory=BlobBurstConfig, description="Burst pattern configuration")
    selection_mode: Literal["priority", "weighted"] = Field(default="priority", description="Error selection strategy")

    @field_validator(
        "retry_after_sec",
        "timeout_sec",
        "connection_stall_start_sec",
        "connection_stall_sec",
        "slow_response_sec",
        mode="before",
    )
    @classmethod
    def parse_range(cls, value: Any) -> tuple[int, int]:
        return _parse_range(value)

    @model_validator(mode="after")
    def validate_ranges(self) -> BlobErrorInjectionConfig:
        _validate_ranges(
            {
                "retry_after_sec": self.retry_after_sec,
                "timeout_sec": self.timeout_sec,
                "connection_stall_start_sec": self.connection_stall_start_sec,
                "connection_stall_sec": self.connection_stall_sec,
                "slow_response_sec": self.slow_response_sec,
            }
        )
        return self

    @model_validator(mode="after")
    def warn_total_percentage(self) -> BlobErrorInjectionConfig:
        if self.selection_mode != "weighted":
            return self
        total = sum(getattr(self, name) for name in type(self).model_fields if name.endswith("_pct"))
        if total >= 100.0:
            warnings.warn(  # noqa: B028 - stacklevel is unreliable inside Pydantic model validators
                f"total error weights are >= 100 ({total:.1f}%); success responses may never occur",
            )
        return self


class BlobStorageConfig(BaseModel):
    """Object storage limits and response defaults."""

    model_config = {"frozen": True, "extra": "forbid"}

    max_object_bytes: int = Field(default=10 * 1024 * 1024, gt=0, description="Maximum stored object size in bytes")
    default_content_type: str = Field(default="application/octet-stream", min_length=1, description="Default object content type")
    expose_s3_xml: bool = Field(default=True, description="Return S3-shaped XML error/list responses")


class ChaosBlobConfig(BaseModel):
    """Top-level ChaosBlob server configuration."""

    model_config = {"frozen": True, "extra": "forbid"}

    server: ServerConfig = Field(default_factory=lambda: ServerConfig(port=8300, workers=1), description="Server binding configuration")
    metrics: MetricsConfig = Field(default_factory=lambda: MetricsConfig(database=DEFAULT_MEMORY_DB), description="Metrics storage")
    storage: BlobStorageConfig = Field(default_factory=BlobStorageConfig, description="Blob storage settings")
    latency: LatencyConfig = Field(default_factory=LatencyConfig, description="Latency simulation configuration")
    error_injection: BlobErrorInjectionConfig = Field(default_factory=BlobErrorInjectionConfig, description="Error injection settings")
    allow_external_bind: bool = Field(default=False, description="Allow binding to all interfaces")
    preset_name: str | None = Field(default=None, description="Preset name used to build this config")

    @model_validator(mode="after")
    def validate_workers_metrics_compatible(self) -> ChaosBlobConfig:
        if self.server.workers > 1 and self.metrics.is_in_memory():
            raise ValueError(
                f"workers={self.server.workers} requires a file-backed metrics database; "
                f"the configured in-memory database ({self.metrics.database!r}) cannot be "
                "shared across worker processes. Set metrics.database to a file path "
                "(e.g. 'metrics.db') or set server.workers=1."
            )
        return self

    @model_validator(mode="after")
    def validate_host_binding(self) -> ChaosBlobConfig:
        if self.server.host in DANGEROUS_BIND_HOSTS and not self.allow_external_bind:
            raise ValueError(
                f"Binding to '{self.server.host}' exposes ChaosBlob to the network. "
                "Use allow_external_bind: true to override, or bind to 127.0.0.1."
            )
        return self


def _get_presets_dir() -> Path:
    return Path(__file__).parent / "presets"


def list_presets() -> list[str]:
    """List available preset names."""
    return _list_presets(_get_presets_dir())


def load_preset(preset_name: str) -> dict[str, Any]:
    """Load a preset configuration by name."""
    return _load_preset(_get_presets_dir(), preset_name)


def load_config(
    *,
    preset: str | None = None,
    config_file: Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> ChaosBlobConfig:
    """Load ChaosBlob configuration with precedence handling."""
    return _load_config(
        ChaosBlobConfig,
        _get_presets_dir(),
        preset=preset,
        config_file=config_file,
        cli_overrides=cli_overrides,
    )
