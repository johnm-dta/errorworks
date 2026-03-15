"""Configuration schema and loading for ChaosLLM server.

Uses Pydantic for validation with frozen (immutable) models.
Configuration precedence: CLI > YAML file > preset > defaults.
"""

import warnings
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from errorworks.engine.config_loader import (
    list_presets as _list_presets,
)
from errorworks.engine.config_loader import (
    load_config as _load_config,
)
from errorworks.engine.config_loader import (
    load_preset as _load_preset,
)
from errorworks.engine.types import (
    DANGEROUS_BIND_HOSTS,
)
from errorworks.engine.types import (
    LatencyConfig as LatencyConfig,
)
from errorworks.engine.types import (
    MetricsConfig as MetricsConfig,
)
from errorworks.engine.types import (
    ServerConfig as ServerConfig,
)
from errorworks.engine.validators import (
    parse_range as _parse_range,
)
from errorworks.engine.validators import (
    validate_ranges as _validate_ranges,
)

__all__ = [
    "ChaosLLMConfig",
    "ErrorInjectionConfig",
    "LLMBurstConfig",
    "LatencyConfig",
    "MetricsConfig",
    "PresetResponseConfig",
    "RandomResponseConfig",
    "ResponseConfig",
    "ServerConfig",
    "TemplateResponseConfig",
    "list_presets",
    "load_config",
    "load_preset",
]

# Default shared in-memory SQLite database for ephemeral metrics
DEFAULT_MEMORY_DB = "file:chaosllm-metrics?mode=memory&cache=shared"


class RandomResponseConfig(BaseModel):
    """Random text response generation settings."""

    model_config = {"frozen": True, "extra": "forbid"}

    min_words: int = Field(
        default=10,
        gt=0,
        description="Minimum words in generated response",
    )
    max_words: int = Field(
        default=100,
        gt=0,
        description="Maximum words in generated response",
    )
    vocabulary: Literal["english", "lorem"] = Field(
        default="english",
        description="Word source: 'english' for common words, 'lorem' for Lorem Ipsum",
    )

    @model_validator(mode="after")
    def validate_word_range(self) -> "RandomResponseConfig":
        """Ensure min_words <= max_words."""
        if self.min_words > self.max_words:
            raise ValueError(f"min_words ({self.min_words}) must be <= max_words ({self.max_words})")
        return self


class TemplateResponseConfig(BaseModel):
    """Template-based response generation settings."""

    model_config = {"frozen": True, "extra": "forbid"}

    body: str = Field(
        default='{"result": "ok"}',
        description="Jinja2 template for response body",
    )


class PresetResponseConfig(BaseModel):
    """Preset bank response generation settings."""

    model_config = {"frozen": True, "extra": "forbid"}

    file: str = Field(
        default="./responses.jsonl",
        description="Path to JSONL file with canned responses",
    )
    selection: Literal["random", "sequential"] = Field(
        default="random",
        description="How to select responses: 'random' or 'sequential' cycling",
    )


class ResponseConfig(BaseModel):
    """Response generation configuration."""

    model_config = {"frozen": True, "extra": "forbid"}

    mode: Literal["random", "template", "echo", "preset"] = Field(
        default="random",
        description="Response generation mode",
    )
    allow_header_overrides: bool = Field(
        default=True,
        description=(
            "Allow X-Fake-Response-Mode and X-Fake-Template headers to override "
            "response generation. Set to false to ignore per-request overrides."
        ),
    )
    max_template_length: int = Field(
        default=10_000,
        gt=0,
        description="Maximum length for template strings (config or header override)",
    )
    random: RandomResponseConfig = Field(
        default_factory=RandomResponseConfig,
        description="Settings for random mode",
    )
    template: TemplateResponseConfig = Field(
        default_factory=TemplateResponseConfig,
        description="Settings for template mode",
    )
    preset: PresetResponseConfig = Field(
        default_factory=PresetResponseConfig,
        description="Settings for preset mode",
    )


class LLMBurstConfig(BaseModel):
    """Burst pattern configuration for simulating provider stress."""

    model_config = {"frozen": True, "extra": "forbid"}

    enabled: bool = Field(
        default=False,
        description="Enable burst pattern injection",
    )
    interval_sec: int = Field(
        default=30,
        gt=0,
        description="Time between burst starts in seconds",
    )
    duration_sec: int = Field(
        default=5,
        gt=0,
        description="How long each burst lasts in seconds",
    )

    @model_validator(mode="after")
    def _validate_burst_timing(self) -> "LLMBurstConfig":
        if self.enabled and self.duration_sec >= self.interval_sec:
            raise ValueError(
                f"duration_sec ({self.duration_sec}) must be less than interval_sec ({self.interval_sec}) when burst is enabled"
            )
        return self

    rate_limit_pct: float = Field(
        default=80.0,
        ge=0.0,
        le=100.0,
        description="Rate limit percentage during burst (0-100)",
    )
    capacity_pct: float = Field(
        default=50.0,
        ge=0.0,
        le=100.0,
        description="Capacity error (529) percentage during burst (0-100)",
    )


class ErrorInjectionConfig(BaseModel):
    """Error injection configuration with all error types.

    Percentages are 0-100 (e.g., 5.0 means 5% of requests). In priority mode,
    errors are evaluated in order and the first match wins. In weighted mode,
    errors are selected proportionally by weight.
    """

    model_config = {"frozen": True, "extra": "forbid"}

    # === HTTP-Level Errors ===

    rate_limit_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="429 Rate Limit error percentage (primary AIMD trigger)",
    )
    capacity_529_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="529 Model Overloaded error percentage (Azure-specific)",
    )
    service_unavailable_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="503 Service Unavailable error percentage",
    )
    bad_gateway_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="502 Bad Gateway error percentage",
    )
    gateway_timeout_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="504 Gateway Timeout error percentage",
    )
    internal_error_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="500 Internal Server Error percentage",
    )
    forbidden_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="403 Forbidden error percentage",
    )
    not_found_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="404 Not Found error percentage",
    )

    # === Retry-After header for rate limits ===

    retry_after_sec: tuple[int, int] = Field(
        default=(1, 5),
        description="Retry-After header value range [min, max] seconds",
    )

    # === Connection-Level Failures ===

    timeout_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage of requests that hang (trigger client timeout)",
    )
    timeout_sec: tuple[int, int] = Field(
        default=(30, 60),
        description="How long to hang before responding [min, max] seconds",
    )
    connection_failed_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage of requests that disconnect after a short lead time",
    )
    connection_failed_lead_sec: tuple[int, int] = Field(
        default=(2, 5),
        description="Lead time before disconnect [min, max] seconds",
    )
    connection_stall_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage of requests that stall the connection then disconnect",
    )
    connection_stall_start_sec: tuple[int, int] = Field(
        default=(0, 2),
        description="Initial delay before stalling [min, max] seconds",
    )
    connection_stall_sec: tuple[int, int] = Field(
        default=(30, 60),
        description="How long to stall before disconnect [min, max] seconds",
    )
    connection_reset_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage of requests that RST the TCP connection",
    )
    slow_response_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage of requests with artificially slow responses",
    )
    slow_response_sec: tuple[int, int] = Field(
        default=(10, 30),
        description="Slow response delay range [min, max] seconds",
    )

    # === Malformed Response Errors ===

    invalid_json_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage of responses with invalid JSON",
    )
    truncated_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage of responses truncated mid-stream",
    )
    empty_body_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage of responses with empty body",
    )
    missing_fields_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage of responses missing required fields",
    )
    wrong_content_type_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage of responses with wrong Content-Type header",
    )

    # === Burst Configuration ===

    burst: LLMBurstConfig = Field(
        default_factory=LLMBurstConfig,
        description="Burst pattern configuration",
    )

    # === Selection Mode ===

    selection_mode: Literal["priority", "weighted"] = Field(
        default="priority",
        description="Error selection strategy: priority (first match) or weighted mix",
    )

    @field_validator(
        "retry_after_sec",
        "timeout_sec",
        "connection_failed_lead_sec",
        "connection_stall_start_sec",
        "connection_stall_sec",
        "slow_response_sec",
        mode="before",
    )
    @classmethod
    def parse_range(cls, v: Any) -> tuple[int, int]:
        """Parse [min, max] range from list or tuple."""
        return _parse_range(v)

    @model_validator(mode="after")
    def validate_ranges(self) -> "ErrorInjectionConfig":
        """Ensure min <= max for all range fields."""
        _validate_ranges(
            {
                "retry_after_sec": self.retry_after_sec,
                "timeout_sec": self.timeout_sec,
                "connection_failed_lead_sec": self.connection_failed_lead_sec,
                "connection_stall_start_sec": self.connection_stall_start_sec,
                "connection_stall_sec": self.connection_stall_sec,
                "slow_response_sec": self.slow_response_sec,
            }
        )
        return self

    @model_validator(mode="after")
    def warn_total_percentage(self) -> "ErrorInjectionConfig":
        """Warn when total error percentages exceed 100% in weighted mode."""
        if self.selection_mode != "weighted":
            return self
        total = sum(getattr(self, name) for name in type(self).model_fields if name.endswith("_pct"))
        if total >= 100.0:
            warnings.warn(
                f"Total error percentages ({total:.1f}%) reach or exceed 100% in weighted mode. No successful responses will be generated.",
                stacklevel=2,
            )
        return self


class ChaosLLMConfig(BaseModel):
    """Top-level ChaosLLM server configuration.

    Configuration precedence (highest to lowest):
    1. CLI flags
    2. YAML config file
    3. Preset defaults
    4. Built-in defaults
    """

    model_config = {"frozen": True, "extra": "forbid"}

    server: ServerConfig = Field(
        default_factory=ServerConfig,
        description="Server binding configuration",
    )
    metrics: MetricsConfig = Field(
        default_factory=lambda: MetricsConfig(database=DEFAULT_MEMORY_DB),
        description="Metrics storage configuration",
    )
    response: ResponseConfig = Field(
        default_factory=ResponseConfig,
        description="Response generation configuration",
    )
    latency: LatencyConfig = Field(
        default_factory=LatencyConfig,
        description="Latency simulation configuration",
    )
    error_injection: ErrorInjectionConfig = Field(
        default_factory=ErrorInjectionConfig,
        description="Error injection configuration",
    )
    preset_name: str | None = Field(
        default=None,
        description="Preset name used to build this config (if any)",
    )
    allow_external_bind: bool = Field(
        default=False,
        description="Allow binding to 0.0.0.0 or :: (all interfaces). Blocked by default for safety.",
    )

    @model_validator(mode="after")
    def validate_host_binding(self) -> "ChaosLLMConfig":
        """Block binding to all interfaces unless explicitly allowed.

        ChaosLLM is a testing tool that should only bind to localhost.
        Binding to 0.0.0.0 or :: exposes the chaos server to the network,
        which could be used to inject errors into non-test traffic.
        """
        if self.server.host in DANGEROUS_BIND_HOSTS and not self.allow_external_bind:
            raise ValueError(
                f"Binding to '{self.server.host}' exposes ChaosLLM to the network. "
                f"Use allow_external_bind: true to override, or bind to 127.0.0.1."
            )
        return self


# === Preset Loading ===


def _get_presets_dir() -> Path:
    """Get the presets directory path."""
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
) -> ChaosLLMConfig:
    """Load ChaosLLM configuration with precedence handling.

    Precedence (highest to lowest):
    1. cli_overrides - Direct overrides from CLI flags
    2. config_file - User's YAML configuration file
    3. preset - Named preset configuration
    4. defaults - Built-in Pydantic defaults
    """
    return _load_config(
        ChaosLLMConfig,
        _get_presets_dir(),
        preset=preset,
        config_file=config_file,
        cli_overrides=cli_overrides,
    )
