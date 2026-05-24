"""Configuration schema and loading for ChaosSMTP server."""

from __future__ import annotations

import ipaddress
import secrets
import socket
import warnings
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from errorworks.engine.config_loader import list_presets as _list_presets
from errorworks.engine.config_loader import load_config as _load_config
from errorworks.engine.config_loader import load_preset as _load_preset
from errorworks.engine.types import DANGEROUS_BIND_HOSTS, LatencyConfig, MetricsConfig
from errorworks.engine.validators import parse_range as _parse_range
from errorworks.engine.validators import validate_ranges as _validate_ranges

DEFAULT_MEMORY_DB = "file:chaossmtp-metrics?mode=memory&cache=shared"


def _is_dangerous_bind_host(host: str) -> bool:
    if host in DANGEROUS_BIND_HOSTS:
        return True

    address = host.removeprefix("[").removesuffix("]")
    try:
        return ipaddress.ip_address(address).is_unspecified
    except ValueError:
        pass

    if not all(char.isdigit() or char in ".xXabcdefABCDEF" for char in host):
        return False

    try:
        return socket.inet_ntoa(socket.inet_aton(host)) == "0.0.0.0"
    except OSError:
        return False


class SMTPServerConfig(BaseModel):
    """SMTP listener binding and protocol configuration."""

    model_config = {"frozen": True, "extra": "forbid"}

    host: str = Field(default="127.0.0.1", min_length=1, pattern=r"^[a-zA-Z0-9.:\[\]-]+$")
    port: int = Field(default=2525, ge=0, le=65535)
    hostname: str = Field(default="chaossmtp.local", min_length=1)
    data_size_limit: int = Field(default=10_485_760, gt=0)
    enable_smtputf8: bool = True
    require_starttls: bool = False


class SMTPAdminConfig(BaseModel):
    """HTTP admin sidecar configuration."""

    model_config = {"frozen": True, "extra": "forbid"}

    enabled: bool = True
    host: str = Field(default="127.0.0.1", min_length=1, pattern=r"^[a-zA-Z0-9.:\[\]-]+$")
    port: int = Field(default=8525, gt=0, le=65535)
    admin_token: str = Field(default_factory=lambda: secrets.token_urlsafe(32), min_length=1)


class SMTPCaptureConfig(BaseModel):
    """Message capture configuration."""

    model_config = {"frozen": True, "extra": "forbid"}

    mode: Literal["discard", "metadata", "full"] = "metadata"
    max_message_bytes: int = Field(default=1_048_576, ge=0)


class SMTPBurstConfig(BaseModel):
    """Burst pattern configuration for SMTP temporary failures."""

    model_config = {"frozen": True, "extra": "forbid"}

    enabled: bool = False
    interval_sec: int = Field(default=30, gt=0)
    duration_sec: int = Field(default=5, gt=0)
    tempfail_pct: float = Field(default=80.0, ge=0.0, le=100.0)
    rate_limit_pct: float = Field(default=50.0, ge=0.0, le=100.0)

    @model_validator(mode="after")
    def validate_timing(self) -> SMTPBurstConfig:
        if self.enabled and self.duration_sec >= self.interval_sec:
            raise ValueError(
                f"duration_sec ({self.duration_sec}) must be less than interval_sec ({self.interval_sec}) when burst is enabled"
            )
        return self


class SMTPErrorInjectionConfig(BaseModel):
    """SMTP-stage error injection configuration."""

    model_config = {"frozen": True, "extra": "forbid"}

    rate_limit_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    mail_from_tempfail_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    mail_from_reject_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    rcpt_to_tempfail_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    rcpt_to_reject_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    data_tempfail_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    data_reject_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    accept_then_drop_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    banner_reject_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    malformed_reply_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    wrong_reply_code_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    connection_reset_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    connection_stall_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    slow_response_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    retry_after_sec: tuple[int, int] = (1, 30)
    connection_stall_sec: tuple[int, int] = (30, 60)
    slow_response_sec: tuple[int, int] = (3, 15)
    burst: SMTPBurstConfig = Field(default_factory=SMTPBurstConfig)
    selection_mode: Literal["priority", "weighted"] = "priority"

    @field_validator("retry_after_sec", "connection_stall_sec", "slow_response_sec", mode="before")
    @classmethod
    def parse_range(cls, value: Any) -> tuple[int, int]:
        return _parse_range(value)

    @model_validator(mode="after")
    def validate_ranges(self) -> SMTPErrorInjectionConfig:
        _validate_ranges(
            {
                "retry_after_sec": self.retry_after_sec,
                "connection_stall_sec": self.connection_stall_sec,
                "slow_response_sec": self.slow_response_sec,
            }
        )
        return self

    @model_validator(mode="after")
    def warn_total_percentage(self) -> SMTPErrorInjectionConfig:
        if self.selection_mode != "weighted":
            return self
        total = sum(getattr(self, name) for name in type(self).model_fields if name.endswith("_pct"))
        if total >= 100.0:
            warnings.warn(
                f"Total SMTP error percentages ({total:.1f}%) reach or exceed 100% in weighted mode. No successful messages will be generated.",
                stacklevel=2,
            )
        return self


class ChaosSMTPConfig(BaseModel):
    """Top-level ChaosSMTP configuration."""

    model_config = {"frozen": True, "extra": "forbid"}

    smtp: SMTPServerConfig = Field(default_factory=SMTPServerConfig)
    admin: SMTPAdminConfig = Field(default_factory=SMTPAdminConfig)
    metrics: MetricsConfig = Field(default_factory=lambda: MetricsConfig(database=DEFAULT_MEMORY_DB))
    latency: LatencyConfig = Field(default_factory=LatencyConfig)
    capture: SMTPCaptureConfig = Field(default_factory=SMTPCaptureConfig)
    error_injection: SMTPErrorInjectionConfig = Field(default_factory=SMTPErrorInjectionConfig)
    preset_name: str | None = None
    allow_external_bind: bool = False

    @model_validator(mode="after")
    def validate_host_binding(self) -> ChaosSMTPConfig:
        dangerous = _is_dangerous_bind_host(self.smtp.host) or _is_dangerous_bind_host(self.admin.host)
        if dangerous and not self.allow_external_bind:
            raise ValueError(
                "Binding ChaosSMTP to all interfaces exposes ChaosSMTP to the network. "
                "Use allow_external_bind: true to override, or bind to 127.0.0.1."
            )
        return self


def _get_presets_dir() -> Path:
    return Path(__file__).parent / "presets"


def list_presets() -> list[str]:
    return _list_presets(_get_presets_dir())


def load_preset(preset_name: str) -> dict[str, Any]:
    return _load_preset(_get_presets_dir(), preset_name)


def load_config(
    *,
    preset: str | None = None,
    config_file: Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> ChaosSMTPConfig:
    return _load_config(
        ChaosSMTPConfig,
        _get_presets_dir(),
        preset=preset,
        config_file=config_file,
        cli_overrides=cli_overrides,
    )
