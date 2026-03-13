"""Configuration schema and loading for ChaosWeb server.

Uses Pydantic for validation with frozen (immutable) models.
Configuration precedence: CLI > YAML file > preset > defaults.

Shared config types (ServerConfig, MetricsConfig, LatencyConfig) are imported
from errorworks.engine — the shared utility layer for all chaos plugins.
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
    LatencyConfig,
    MetricsConfig,
    ServerConfig,
)
from errorworks.engine.validators import (
    parse_range as _parse_range,
)
from errorworks.engine.validators import (
    validate_ranges as _validate_ranges,
)

# Default shared in-memory SQLite database for ephemeral metrics
DEFAULT_MEMORY_DB = "file:chaosweb-metrics?mode=memory&cache=shared"


# === Web Content Generation ===


class RandomContentConfig(BaseModel):
    """Random HTML content generation settings."""

    model_config = {"frozen": True, "extra": "forbid"}

    min_words: int = Field(
        default=50,
        gt=0,
        description="Minimum words in generated HTML body",
    )
    max_words: int = Field(
        default=500,
        gt=0,
        description="Maximum words in generated HTML body",
    )
    vocabulary: Literal["english", "lorem"] = Field(
        default="english",
        description="Word source: 'english' for common words, 'lorem' for Lorem Ipsum",
    )

    @model_validator(mode="after")
    def validate_word_range(self) -> "RandomContentConfig":
        """Ensure min_words <= max_words."""
        if self.min_words > self.max_words:
            raise ValueError(f"min_words ({self.min_words}) must be <= max_words ({self.max_words})")
        return self


class TemplateContentConfig(BaseModel):
    """Template-based HTML content generation settings."""

    model_config = {"frozen": True, "extra": "forbid"}

    body: str = Field(
        default=(
            "<html><head><title>{{ path | default('Page') }}</title></head>"
            "<body><h1>{{ path | default('Page') }}</h1>"
            "<p>{{ random_words(100, 300) }}</p></body></html>"
        ),
        description="Jinja2 template for HTML response body",
    )


class PresetContentConfig(BaseModel):
    """Preset bank HTML content generation settings."""

    model_config = {"frozen": True, "extra": "forbid"}

    file: str = Field(
        default="./pages.jsonl",
        description="Path to JSONL file with HTML page snapshots",
    )
    selection: Literal["random", "sequential"] = Field(
        default="random",
        description="How to select pages: 'random' or 'sequential' cycling",
    )


class WebContentConfig(BaseModel):
    """HTML content generation configuration.

    Four generation modes:
    - random: Syntactically valid HTML with random content
    - template: Jinja2 HTML template rendering (SandboxedEnvironment)
    - preset: Real HTML snapshots from JSONL file
    - echo: Reflect request information as HTML
    """

    model_config = {"frozen": True, "extra": "forbid"}

    mode: Literal["random", "template", "echo", "preset"] = Field(
        default="random",
        description="Content generation mode",
    )
    allow_header_overrides: bool = Field(
        default=True,
        description=("Allow X-Fake-Content-Mode header to override content generation. Set to false to ignore per-request overrides."),
    )
    max_template_length: int = Field(
        default=10_000,
        gt=0,
        description="Maximum length for template strings (config or header override)",
    )
    default_content_type: str = Field(
        default="text/html; charset=utf-8",
        description="Default Content-Type header for successful responses",
    )
    random: RandomContentConfig = Field(
        default_factory=RandomContentConfig,
        description="Settings for random mode",
    )
    template: TemplateContentConfig = Field(
        default_factory=TemplateContentConfig,
        description="Settings for template mode",
    )
    preset: PresetContentConfig = Field(
        default_factory=PresetContentConfig,
        description="Settings for preset mode",
    )


# === Error Injection ===


class WebBurstConfig(BaseModel):
    """Burst pattern configuration for simulating anti-scraping escalation.

    During a burst, rate_limit_pct and forbidden_pct are temporarily elevated
    to simulate coordinated anti-bot responses.
    """

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
    def _validate_burst_timing(self) -> "WebBurstConfig":
        if self.enabled and self.duration_sec >= self.interval_sec:
            raise ValueError(
                f"duration_sec ({self.duration_sec}) must be less than interval_sec ({self.interval_sec}) when burst is enabled"
            )
        return self
    rate_limit_pct: float = Field(
        default=80.0,
        ge=0.0,
        le=100.0,
        description="Rate limit (429) percentage during burst (0-100)",
    )
    forbidden_pct: float = Field(
        default=50.0,
        ge=0.0,
        le=100.0,
        description="Forbidden (403) percentage during burst (0-100)",
    )


class WebErrorInjectionConfig(BaseModel):
    """Error injection configuration for web scraping chaos scenarios.

    Percentages are 0-100 (e.g., 5.0 means 5% of requests). In priority mode,
    errors are evaluated in order and the first match wins. In weighted mode,
    errors are selected proportionally by weight.

    Error categories (priority order):
    1. Connection-level (highest) - timeout, reset, stall, slow, incomplete
    2. Redirect injection - SSRF redirects, redirect loops
    3. HTTP-level - status code errors (429, 403, 404, etc.)
    4. Content malformations (lowest) - encoding, truncation, charset
    """

    model_config = {"frozen": True, "extra": "forbid"}

    # === HTTP-Level Errors ===

    rate_limit_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="429 Rate Limit percentage (anti-scraping throttle)",
    )
    forbidden_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="403 Forbidden percentage (bot detection)",
    )
    not_found_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="404 Not Found percentage (deleted page)",
    )
    gone_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="410 Gone percentage (permanent deletion)",
    )
    payment_required_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="402 Payment Required percentage (quota exceeded)",
    )
    unavailable_for_legal_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="451 Unavailable for Legal Reasons percentage (geo-blocking)",
    )
    service_unavailable_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="503 Service Unavailable percentage (maintenance)",
    )
    bad_gateway_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="502 Bad Gateway percentage",
    )
    gateway_timeout_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="504 Gateway Timeout percentage",
    )
    internal_error_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="500 Internal Server Error percentage",
    )

    # === Retry-After header for rate limits ===

    retry_after_sec: tuple[int, int] = Field(
        default=(1, 30),
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
    connection_reset_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage of requests that RST the TCP connection",
    )
    connection_stall_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage of requests that stall then disconnect",
    )
    connection_stall_start_sec: tuple[int, int] = Field(
        default=(0, 2),
        description="Initial delay before stalling [min, max] seconds",
    )
    connection_stall_sec: tuple[int, int] = Field(
        default=(30, 60),
        description="How long to stall before disconnect [min, max] seconds",
    )
    slow_response_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage of requests with artificially slow responses",
    )
    slow_response_sec: tuple[int, int] = Field(
        default=(3, 15),
        description="Slow response delay range [min, max] seconds",
    )
    incomplete_response_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage of responses that disconnect mid-body",
    )
    incomplete_response_bytes: tuple[int, int] = Field(
        default=(100, 1000),
        description="How many bytes to send before disconnecting [min, max]",
    )

    # === Content Malformations ===

    wrong_content_type_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage of responses with wrong Content-Type (e.g., application/pdf)",
    )
    encoding_mismatch_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage with UTF-8 header but ISO-8859-1 body",
    )
    truncated_html_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage with HTML cut off mid-tag",
    )
    invalid_encoding_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage with non-decodable bytes in declared encoding",
    )
    charset_confusion_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage with conflicting charset declarations (header vs meta)",
    )
    malformed_meta_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage with invalid <meta http-equiv='refresh'> directives",
    )

    # === Redirect Injection ===

    redirect_loop_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage of requests that enter redirect loops",
    )
    max_redirect_loop_hops: int = Field(
        default=10,
        ge=3,
        description="Maximum hops in a redirect loop before terminating (minimum 3)",
    )
    ssrf_redirect_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage of requests redirected to private IPs (SSRF testing)",
    )

    # === Burst Configuration ===

    burst: WebBurstConfig = Field(
        default_factory=WebBurstConfig,
        description="Burst pattern configuration (anti-scraping escalation)",
    )

    # === Selection Mode ===

    selection_mode: Literal["priority", "weighted"] = Field(
        default="priority",
        description="Error selection strategy: priority (first match) or weighted mix",
    )

    @field_validator(
        "retry_after_sec",
        "timeout_sec",
        "connection_stall_start_sec",
        "connection_stall_sec",
        "slow_response_sec",
        "incomplete_response_bytes",
        mode="before",
    )
    @classmethod
    def parse_range(cls, v: Any) -> tuple[int, int]:
        """Parse [min, max] range from list or tuple."""
        return _parse_range(v)

    @model_validator(mode="after")
    def validate_ranges(self) -> "WebErrorInjectionConfig":
        """Ensure min <= max for all range fields."""
        _validate_ranges({
            "retry_after_sec": self.retry_after_sec,
            "timeout_sec": self.timeout_sec,
            "connection_stall_start_sec": self.connection_stall_start_sec,
            "connection_stall_sec": self.connection_stall_sec,
            "slow_response_sec": self.slow_response_sec,
            "incomplete_response_bytes": self.incomplete_response_bytes,
        })
        return self

    @model_validator(mode="after")
    def warn_total_percentage(self) -> "WebErrorInjectionConfig":
        """Warn when total error percentages exceed 100% in weighted mode."""
        if self.selection_mode != "weighted":
            return self
        total = sum(
            getattr(self, name)
            for name in type(self).model_fields
            if name.endswith("_pct")
        )
        if total > 100.0:
            warnings.warn(
                f"Total error percentages ({total:.1f}%) exceed 100% in weighted mode. "
                f"No successful responses will be generated.",
                stacklevel=2,
            )
        return self


# === Top-Level Config ===


class ChaosWebConfig(BaseModel):
    """Top-level ChaosWeb server configuration.

    Configuration precedence (highest to lowest):
    1. CLI flags
    2. YAML config file
    3. Preset defaults
    4. Built-in defaults

    Uses ServerConfig, MetricsConfig, and LatencyConfig from the shared
    engine layer (errorworks.engine.types).
    """

    model_config = {"frozen": True, "extra": "forbid"}

    server: ServerConfig = Field(
        default_factory=lambda: ServerConfig(port=8200),
        description="Server binding configuration (default port 8200)",
    )
    metrics: MetricsConfig = Field(
        default_factory=lambda: MetricsConfig(database=DEFAULT_MEMORY_DB),
        description="Metrics storage configuration",
    )
    content: WebContentConfig = Field(
        default_factory=WebContentConfig,
        description="HTML content generation configuration",
    )
    latency: LatencyConfig = Field(
        default_factory=LatencyConfig,
        description="Latency simulation configuration",
    )
    error_injection: WebErrorInjectionConfig = Field(
        default_factory=WebErrorInjectionConfig,
        description="Error injection configuration",
    )
    allow_external_bind: bool = Field(
        default=False,
        description="Allow binding to 0.0.0.0 or :: (all interfaces). Blocked by default for safety.",
    )
    preset_name: str | None = Field(
        default=None,
        description="Preset name used to build this config (if any)",
    )

    @model_validator(mode="after")
    def validate_host_binding(self) -> "ChaosWebConfig":
        """Block binding to all interfaces unless explicitly allowed.

        ChaosWeb is a testing tool that should only bind to localhost.
        Binding to 0.0.0.0 or :: exposes the chaos server to the network,
        which could be used to inject errors into non-test traffic.
        """
        if self.server.host in DANGEROUS_BIND_HOSTS and not self.allow_external_bind:
            raise ValueError(
                f"Binding to '{self.server.host}' exposes ChaosWeb to the network. "
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
) -> ChaosWebConfig:
    """Load ChaosWeb configuration with precedence handling.

    Precedence (highest to lowest):
    1. cli_overrides - Direct overrides from CLI flags
    2. config_file - User's YAML configuration file
    3. preset - Named preset configuration
    4. defaults - Built-in Pydantic defaults
    """
    return _load_config(
        ChaosWebConfig,
        _get_presets_dir(),
        preset=preset,
        config_file=config_file,
        cli_overrides=cli_overrides,
    )
