"""Error injection logic for ChaosWeb.

The WebErrorInjector decides per-request whether to inject an error based on
configured percentages. It supports HTTP-level errors, connection-level
failures, content malformations, and redirect injection (including SSRF
redirects to private IPs). A burst state machine (delegated to InjectionEngine)
elevates error rates periodically to simulate anti-scraping escalation.
"""

import random as random_module
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from errorworks.engine.injection_engine import InjectionEngine
from errorworks.engine.types import BurstConfig as EngineBurstConfig
from errorworks.engine.types import ErrorSpec
from errorworks.web.config import WebErrorInjectionConfig


class WebErrorCategory(Enum):
    """Categories of errors the web injector can produce."""

    HTTP = "http"  # Returns an HTTP error status code
    CONNECTION = "connection"  # Connection-level failures (timeout, reset, slow, incomplete)
    MALFORMED = "malformed"  # Returns 200 but with corrupted content
    REDIRECT = "redirect"  # Returns 301/302 redirect (loops or SSRF injection)


# HTTP error types with their status codes.
WEB_HTTP_ERRORS: dict[str, int] = {
    "rate_limit": 429,
    "forbidden": 403,
    "not_found": 404,
    "gone": 410,
    "payment_required": 402,
    "unavailable_for_legal": 451,
    "service_unavailable": 503,
    "bad_gateway": 502,
    "gateway_timeout": 504,
    "internal_error": 500,
}

# Connection-level error types.
WEB_CONNECTION_ERRORS: set[str] = {
    "timeout",
    "connection_reset",
    "connection_stall",
    "slow_response",
    "incomplete_response",
}

# Content malformation types.
WEB_MALFORMED_TYPES: set[str] = {
    "wrong_content_type",
    "encoding_mismatch",
    "truncated_html",
    "invalid_encoding",
    "charset_confusion",
    "malformed_meta",
}

# Redirect injection types.
WEB_REDIRECT_TYPES: set[str] = {
    "redirect_loop",
    "ssrf_redirect",
}

# SSRF redirect targets — comprehensive set covering all blocked IP ranges.
# Each target represents a real attack vector that validate_url_for_ssrf must block.
SSRF_TARGETS: list[str] = [
    # Cloud metadata endpoints
    "http://169.254.169.254/latest/meta-data/",  # AWS metadata
    "http://metadata.google.internal/",  # GCP metadata
    "http://169.254.169.254/metadata/instance",  # Azure metadata
    # Private networks (RFC 1918)
    "http://192.168.1.1/",  # Class C private
    "http://10.0.0.1/",  # Class A private
    "http://172.16.0.1/",  # Class B private
    # Loopback
    "http://127.0.0.1:8080/",  # IPv4 loopback
    # CGNAT (RFC 6598)
    "http://100.64.0.1/",  # CGNAT shared space
    # Current network
    "http://0.0.0.0/",  # Current network (RFC 1122)
    # IPv6 variants
    "http://[::1]/",  # IPv6 loopback
    "http://[::ffff:169.254.169.254]/",  # IPv4-mapped IPv6 (bypass vector)
    # Encoding tricks
    "http://2852039166/",  # Decimal IP for 169.254.169.254
]


@dataclass(frozen=True, slots=True)
class WebErrorDecision:
    """Result of a web error injection decision.

    Extends ChaosLLM's ErrorDecision with web-specific fields for redirect
    injection, encoding mismatches, and incomplete responses.
    """

    error_type: str | None
    status_code: int | None = None
    retry_after_sec: int | None = None
    delay_sec: float | None = None
    start_delay_sec: float | None = None
    category: WebErrorCategory | None = None
    malformed_type: str | None = None
    # Web-specific fields
    redirect_target: str | None = None  # URL for SSRF redirect
    redirect_hops: int | None = None  # Hop count for redirect loops
    incomplete_bytes: int | None = None  # Bytes to send before disconnect
    encoding_actual: str | None = None  # Actual encoding for mismatch scenarios

    def __post_init__(self) -> None:
        """Validate invariants between fields."""
        if self.error_type is None:
            # Success case: no other fields should be set
            if self.category is not None:
                raise ValueError("Success decision must not have a category")
            return

        if self.category is None:
            raise ValueError(f"Error decision '{self.error_type}' must have a category")

        if self.category == WebErrorCategory.HTTP:
            if self.status_code is None:
                raise ValueError(f"HTTP error '{self.error_type}' must have a status_code")
            if not (100 <= self.status_code <= 599):
                raise ValueError(f"HTTP status_code must be 100-599, got {self.status_code}")
            if self.malformed_type is not None:
                raise ValueError("HTTP error must not have malformed_type")

        elif self.category == WebErrorCategory.CONNECTION:
            if self.retry_after_sec is not None:
                raise ValueError("Connection error must not have retry_after_sec")
            if self.malformed_type is not None:
                raise ValueError("Connection error must not have malformed_type")

        elif self.category == WebErrorCategory.MALFORMED:
            if self.malformed_type is None:
                raise ValueError("Malformed error must have malformed_type")
            if self.status_code is not None and self.status_code != 200:
                raise ValueError(f"Malformed error must have status_code 200, got {self.status_code}")

        elif self.category == WebErrorCategory.REDIRECT:
            if self.redirect_target is None and self.redirect_hops is None:
                raise ValueError("Redirect error must have redirect_target or redirect_hops")

        if self.retry_after_sec is not None and self.retry_after_sec < 0:
            raise ValueError(f"retry_after_sec must be non-negative, got {self.retry_after_sec}")
        if self.delay_sec is not None and self.delay_sec < 0:
            raise ValueError(f"delay_sec must be non-negative, got {self.delay_sec}")
        if self.start_delay_sec is not None and self.start_delay_sec < 0:
            raise ValueError(f"start_delay_sec must be non-negative, got {self.start_delay_sec}")
        if self.incomplete_bytes is not None and self.incomplete_bytes < 0:
            raise ValueError(f"incomplete_bytes must be non-negative, got {self.incomplete_bytes}")

    @classmethod
    def success(cls) -> "WebErrorDecision":
        """Create a decision for a successful (no error) response."""
        return cls(error_type=None)

    @classmethod
    def http_error(
        cls,
        error_type: str,
        status_code: int,
        retry_after_sec: int | None = None,
    ) -> "WebErrorDecision":
        """Create a decision for an HTTP-level error."""
        return cls(
            error_type=error_type,
            status_code=status_code,
            retry_after_sec=retry_after_sec,
            category=WebErrorCategory.HTTP,
        )

    @classmethod
    def connection_error(
        cls,
        error_type: str,
        delay_sec: float | None = None,
        start_delay_sec: float | None = None,
        status_code: int | None = None,
        incomplete_bytes: int | None = None,
    ) -> "WebErrorDecision":
        """Create a decision for a connection-level failure."""
        return cls(
            error_type=error_type,
            category=WebErrorCategory.CONNECTION,
            delay_sec=delay_sec,
            start_delay_sec=start_delay_sec,
            status_code=status_code,
            incomplete_bytes=incomplete_bytes,
        )

    @classmethod
    def malformed_content(
        cls,
        malformed_type: str,
        encoding_actual: str | None = None,
    ) -> "WebErrorDecision":
        """Create a decision for a malformed content response (200 with bad content)."""
        return cls(
            error_type="malformed",
            status_code=200,
            category=WebErrorCategory.MALFORMED,
            malformed_type=malformed_type,
            encoding_actual=encoding_actual,
        )

    @classmethod
    def redirect(
        cls,
        redirect_type: str,
        *,
        redirect_target: str | None = None,
        redirect_hops: int | None = None,
    ) -> "WebErrorDecision":
        """Create a decision for a redirect injection."""
        return cls(
            error_type=redirect_type,
            status_code=301,
            category=WebErrorCategory.REDIRECT,
            redirect_target=redirect_target,
            redirect_hops=redirect_hops,
        )

    @property
    def should_inject(self) -> bool:
        """Return True if an error should be injected."""
        return self.error_type is not None

    @property
    def is_connection_level(self) -> bool:
        """Return True if error is a connection-level error."""
        return self.category == WebErrorCategory.CONNECTION

    @property
    def is_malformed(self) -> bool:
        """Return True if error is a malformed content response."""
        return self.category == WebErrorCategory.MALFORMED

    @property
    def is_redirect(self) -> bool:
        """Return True if error is a redirect injection."""
        return self.category == WebErrorCategory.REDIRECT


class WebErrorInjector:
    """Decides per-request whether to inject a web error.

    Composes an InjectionEngine for burst state machine and selection
    algorithms, while retaining web-specific error types and decisions.

    Usage:
        config = WebErrorInjectionConfig(rate_limit_pct=5.0)
        injector = WebErrorInjector(config)
        decision = injector.decide()
        if decision.should_inject:
            # Handle the error injection
            ...
    """

    def __init__(
        self,
        config: WebErrorInjectionConfig,
        *,
        time_func: Callable[[], float] | None = None,
        rng: random_module.Random | None = None,
    ) -> None:
        """Initialize the web error injector.

        Args:
            config: Web error injection configuration
            time_func: Time function for testing (default: time.monotonic)
            rng: Random instance for testing (default: creates new Random instance).
                 Inject a seeded random.Random() for deterministic testing.
        """
        self._config = config
        self._rng = rng if rng is not None else random_module.Random()
        self._engine = InjectionEngine(
            selection_mode=config.selection_mode,
            burst_config=EngineBurstConfig(
                enabled=config.burst.enabled,
                interval_sec=config.burst.interval_sec,
                duration_sec=config.burst.duration_sec,
            ),
            time_func=time_func,
            rng=self._rng,
        )

    @property
    def config(self) -> WebErrorInjectionConfig:
        """Current web error injection configuration (frozen/immutable)."""
        return self._config

    def _pick_retry_after(self) -> int:
        """Pick a random Retry-After value from the configured range."""
        min_sec, max_sec = self._config.retry_after_sec
        return self._rng.randint(min_sec, max_sec)

    def _pick_timeout_delay(self) -> float:
        """Pick a random timeout delay from the configured range."""
        min_sec, max_sec = self._config.timeout_sec
        return self._rng.uniform(min_sec, max_sec)

    def _pick_connection_stall_start(self) -> float:
        """Pick a start delay before stalling the connection."""
        min_sec, max_sec = self._config.connection_stall_start_sec
        return self._rng.uniform(min_sec, max_sec)

    def _pick_connection_stall_delay(self) -> float:
        """Pick a stall duration before disconnect."""
        min_sec, max_sec = self._config.connection_stall_sec
        return self._rng.uniform(min_sec, max_sec)

    def _pick_slow_response_delay(self) -> float:
        """Pick a random slow response delay from the configured range."""
        min_sec, max_sec = self._config.slow_response_sec
        return self._rng.uniform(min_sec, max_sec)

    def _pick_incomplete_bytes(self) -> int:
        """Pick how many bytes to send before disconnecting."""
        min_bytes, max_bytes = self._config.incomplete_response_bytes
        return self._rng.randint(min_bytes, max_bytes)

    def _pick_ssrf_target(self) -> str:
        """Pick a random SSRF redirect target from the target list."""
        return self._rng.choice(SSRF_TARGETS)

    def _pick_redirect_hops(self) -> int:
        """Pick a redirect loop hop count (3 to max_redirect_loop_hops)."""
        return self._rng.randint(3, self._config.max_redirect_loop_hops)

    def _build_specs(self) -> list[ErrorSpec]:
        """Build the error spec list with burst-adjusted weights.

        Order matters for priority mode — connection errors first,
        then redirects, then HTTP errors, then malformations.
        """
        in_burst = self._engine.is_in_burst()
        rl_pct = self._config.burst.rate_limit_pct if in_burst else self._config.rate_limit_pct
        forbidden_pct = self._config.burst.forbidden_pct if in_burst else self._config.forbidden_pct

        return [
            # Connection-level (highest priority)
            ErrorSpec("timeout", self._config.timeout_pct),
            ErrorSpec("connection_reset", self._config.connection_reset_pct),
            ErrorSpec("connection_stall", self._config.connection_stall_pct),
            ErrorSpec("slow_response", self._config.slow_response_pct),
            ErrorSpec("incomplete_response", self._config.incomplete_response_pct),
            # Redirect injection
            ErrorSpec("ssrf_redirect", self._config.ssrf_redirect_pct),
            ErrorSpec("redirect_loop", self._config.redirect_loop_pct),
            # HTTP-level (burst-adjusted for rate_limit and forbidden)
            ErrorSpec("rate_limit", rl_pct),
            ErrorSpec("forbidden", forbidden_pct),
            ErrorSpec("not_found", self._config.not_found_pct),
            ErrorSpec("gone", self._config.gone_pct),
            ErrorSpec("payment_required", self._config.payment_required_pct),
            ErrorSpec("unavailable_for_legal", self._config.unavailable_for_legal_pct),
            ErrorSpec("service_unavailable", self._config.service_unavailable_pct),
            ErrorSpec("bad_gateway", self._config.bad_gateway_pct),
            ErrorSpec("gateway_timeout", self._config.gateway_timeout_pct),
            ErrorSpec("internal_error", self._config.internal_error_pct),
            # Content malformations (lowest priority)
            ErrorSpec("wrong_content_type", self._config.wrong_content_type_pct),
            ErrorSpec("encoding_mismatch", self._config.encoding_mismatch_pct),
            ErrorSpec("truncated_html", self._config.truncated_html_pct),
            ErrorSpec("invalid_encoding", self._config.invalid_encoding_pct),
            ErrorSpec("charset_confusion", self._config.charset_confusion_pct),
            ErrorSpec("malformed_meta", self._config.malformed_meta_pct),
        ]

    def _build_decision(self, tag: str) -> WebErrorDecision:
        """Map a selected error tag to a domain-specific WebErrorDecision."""
        # Connection-level errors
        if tag == "timeout":
            return WebErrorDecision.connection_error("timeout", delay_sec=self._pick_timeout_delay())
        if tag == "connection_reset":
            return WebErrorDecision.connection_error("connection_reset")
        if tag == "connection_stall":
            return WebErrorDecision.connection_error(
                "connection_stall",
                delay_sec=self._pick_connection_stall_delay(),
                start_delay_sec=self._pick_connection_stall_start(),
            )
        if tag == "slow_response":
            return WebErrorDecision.connection_error(
                "slow_response",
                delay_sec=self._pick_slow_response_delay(),
            )
        if tag == "incomplete_response":
            return WebErrorDecision.connection_error(
                "incomplete_response",
                incomplete_bytes=self._pick_incomplete_bytes(),
            )

        # Redirect injection
        if tag == "ssrf_redirect":
            return WebErrorDecision.redirect("ssrf_redirect", redirect_target=self._pick_ssrf_target())
        if tag == "redirect_loop":
            return WebErrorDecision.redirect("redirect_loop", redirect_hops=self._pick_redirect_hops())

        # HTTP errors with special handling
        if tag == "rate_limit":
            return WebErrorDecision.http_error("rate_limit", 429, retry_after_sec=self._pick_retry_after())

        # Generic HTTP errors
        if tag in WEB_HTTP_ERRORS:
            return WebErrorDecision.http_error(tag, WEB_HTTP_ERRORS[tag])

        # Content malformations with special handling
        if tag == "encoding_mismatch":
            return WebErrorDecision.malformed_content("encoding_mismatch", encoding_actual="iso-8859-1")

        # Generic malformations
        if tag in WEB_MALFORMED_TYPES:
            return WebErrorDecision.malformed_content(tag)

        msg = f"Unknown error tag: {tag}"
        raise ValueError(msg)

    def decide(self) -> WebErrorDecision:
        """Decide whether to inject an error for this request.

        Priority order:
        1. Connection-level errors (highest)
        2. Redirect injection
        3. HTTP errors
        4. Content malformations (lowest)

        Returns:
            WebErrorDecision indicating what error (if any) to inject
        """
        specs = self._build_specs()
        selected = self._engine.select(specs)
        if selected is None:
            return WebErrorDecision.success()
        return self._build_decision(selected.tag)

    def reset(self) -> None:
        """Reset the injector state (clears burst timing)."""
        self._engine.reset()

    def is_in_burst(self) -> bool:
        """Check if currently in burst mode (for observability)."""
        return self._engine.is_in_burst()
