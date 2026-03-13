"""Error injection logic for ChaosLLM.

The ErrorInjector decides per-request whether to inject an error based on
configured percentages. It supports HTTP-level errors, connection-level
failures, and malformed responses. A burst state machine (delegated to
InjectionEngine) elevates error rates periodically to simulate real-world
LLM provider stress.
"""

import random as random_module
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from errorworks.engine.injection_engine import InjectionEngine
from errorworks.engine.types import BurstConfig as EngineBurstConfig
from errorworks.engine.types import ErrorSpec
from errorworks.engine.validators import validate_error_decision
from errorworks.llm.config import ErrorInjectionConfig


class ErrorCategory(StrEnum):
    """Categories of errors the injector can produce."""

    HTTP = "http"  # Returns an HTTP error status code
    CONNECTION = "connection"  # Connection-level failures (timeout, reset, slow)
    MALFORMED = "malformed"  # Returns 200 but with bad content


@dataclass(frozen=True, slots=True)
class ErrorDecision:
    """Result of an error injection decision.

    Attributes:
        error_type: The type of error to inject, or None for a successful response
        status_code: HTTP status code (HTTP errors or timeout responses)
        retry_after_sec: Value for Retry-After header (429/529 only)
        delay_sec: Delay before responding or disconnecting (timeout/slow_response/stall)
        start_delay_sec: Lead time before a connection failure or stall
        category: The category of error (HTTP, CONNECTION, or MALFORMED)
        malformed_type: Specific malformation for MALFORMED category
    """

    error_type: str | None
    status_code: int | None = None
    retry_after_sec: int | None = None
    delay_sec: float | None = None
    start_delay_sec: float | None = None
    category: ErrorCategory | None = None
    malformed_type: str | None = None

    def __post_init__(self) -> None:
        """Validate invariants between fields."""
        validate_error_decision(
            error_type=self.error_type,
            category=self.category,
            status_code=self.status_code,
            retry_after_sec=self.retry_after_sec,
            delay_sec=self.delay_sec,
            start_delay_sec=self.start_delay_sec,
            malformed_type=self.malformed_type,
            http_category=ErrorCategory.HTTP,
            connection_category=ErrorCategory.CONNECTION,
            malformed_category=ErrorCategory.MALFORMED,
            valid_error_types=HTTP_ERRORS.keys() | CONNECTION_ERRORS | {"malformed"},
            valid_malformed_types=MALFORMED_TYPES,
        )

    @classmethod
    def success(cls) -> "ErrorDecision":
        """Create a decision for a successful (no error) response."""
        return cls(error_type=None)

    @classmethod
    def http_error(
        cls,
        error_type: str,
        status_code: int,
        retry_after_sec: int | None = None,
    ) -> "ErrorDecision":
        """Create a decision for an HTTP-level error."""
        return cls(
            error_type=error_type,
            status_code=status_code,
            retry_after_sec=retry_after_sec,
            category=ErrorCategory.HTTP,
        )

    @classmethod
    def connection_error(
        cls,
        error_type: str,
        delay_sec: float | None = None,
        start_delay_sec: float | None = None,
        status_code: int | None = None,
    ) -> "ErrorDecision":
        """Create a decision for a connection-level failure."""
        return cls(
            error_type=error_type,
            category=ErrorCategory.CONNECTION,
            delay_sec=delay_sec,
            start_delay_sec=start_delay_sec,
            status_code=status_code,
        )

    @classmethod
    def malformed_response(cls, malformed_type: str) -> "ErrorDecision":
        """Create a decision for a malformed response (200 with bad content)."""
        return cls(
            error_type="malformed",
            status_code=200,
            category=ErrorCategory.MALFORMED,
            malformed_type=malformed_type,
        )

    @property
    def should_inject(self) -> bool:
        """Return True if an error should be injected."""
        return self.error_type is not None

    @property
    def is_connection_level(self) -> bool:
        """Return True if error is a connection-level error (used by server request handler to route to connection-level error handling)."""
        return self.category == ErrorCategory.CONNECTION

    @property
    def is_malformed(self) -> bool:
        """Return True if error is a malformed response (used by server request handler to route to malformed response handling)."""
        return self.category == ErrorCategory.MALFORMED


# HTTP error types with their status codes.
# Exported for external consumers (e.g., response generators, test assertions).
HTTP_ERRORS: dict[str, int] = {
    "rate_limit": 429,
    "capacity_529": 529,
    "service_unavailable": 503,
    "bad_gateway": 502,
    "gateway_timeout": 504,
    "internal_error": 500,
    "forbidden": 403,
    "not_found": 404,
}

# Connection-level error types.
# Exported for external consumers (e.g., response generators, test assertions).
CONNECTION_ERRORS: set[str] = {
    "timeout",
    "connection_failed",
    "connection_stall",
    "connection_reset",
    "slow_response",
}

# Malformed response types.
# Exported for external consumers (e.g., response generators, test assertions).
MALFORMED_TYPES: set[str] = {
    "invalid_json",
    "truncated",
    "empty_body",
    "missing_fields",
    "wrong_content_type",
}


class ErrorInjector:
    """Decides per-request whether to inject an error.

    Composes an InjectionEngine for burst state machine and selection
    algorithms, while retaining LLM-specific error types and decisions.

    Usage:
        config = ErrorInjectionConfig(rate_limit_pct=5.0)
        injector = ErrorInjector(config)
        decision = injector.decide()
        if decision.should_inject:
            # Handle the error injection
            ...
    """

    def __init__(
        self,
        config: ErrorInjectionConfig,
        *,
        time_func: Callable[[], float] | None = None,
        rng: random_module.Random | None = None,
    ) -> None:
        """Initialize the error injector.

        Args:
            config: Error injection configuration
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
    def config(self) -> ErrorInjectionConfig:
        """Current error injection configuration (frozen/immutable)."""
        return self._config

    def _pick_retry_after(self) -> int:
        """Pick a random Retry-After value from the configured range."""
        min_sec, max_sec = self._config.retry_after_sec
        return self._rng.randint(min_sec, max_sec)

    def _pick_timeout_delay(self) -> float:
        """Pick a random timeout delay from the configured range."""
        min_sec, max_sec = self._config.timeout_sec
        return self._rng.uniform(min_sec, max_sec)

    def _build_timeout_decision(self) -> ErrorDecision:
        """Build a timeout decision with a mix of disconnects and 504 responses."""
        delay = self._pick_timeout_delay()
        # 50/50 mix: some timeouts respond with 504, others drop the connection.
        return_504 = self._engine.should_trigger(50.0)
        status_code = 504 if return_504 else None
        return ErrorDecision.connection_error("timeout", delay_sec=delay, status_code=status_code)

    def _pick_connection_failed_lead(self) -> float:
        """Pick a lead time before a connection failure."""
        min_sec, max_sec = self._config.connection_failed_lead_sec
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

    def _build_specs(self) -> list[ErrorSpec]:
        """Build the error spec list with burst-adjusted weights.

        Order matters for priority mode — connection errors first,
        then HTTP errors, then malformed responses.
        """
        in_burst = self._engine.is_in_burst()
        rl_pct = self._config.burst.rate_limit_pct if in_burst else self._config.rate_limit_pct
        cap_pct = self._config.burst.capacity_pct if in_burst else self._config.capacity_529_pct

        return [
            # Connection-level (highest priority)
            ErrorSpec("connection_failed", self._config.connection_failed_pct),
            ErrorSpec("connection_stall", self._config.connection_stall_pct),
            ErrorSpec("timeout", self._config.timeout_pct),
            ErrorSpec("connection_reset", self._config.connection_reset_pct),
            ErrorSpec("slow_response", self._config.slow_response_pct),
            # HTTP-level (burst-adjusted for rate_limit and capacity)
            ErrorSpec("rate_limit", rl_pct),
            ErrorSpec("capacity_529", cap_pct),
            ErrorSpec("service_unavailable", self._config.service_unavailable_pct),
            ErrorSpec("bad_gateway", self._config.bad_gateway_pct),
            ErrorSpec("gateway_timeout", self._config.gateway_timeout_pct),
            ErrorSpec("internal_error", self._config.internal_error_pct),
            ErrorSpec("forbidden", self._config.forbidden_pct),
            ErrorSpec("not_found", self._config.not_found_pct),
            # Malformed responses
            ErrorSpec("invalid_json", self._config.invalid_json_pct),
            ErrorSpec("truncated", self._config.truncated_pct),
            ErrorSpec("empty_body", self._config.empty_body_pct),
            ErrorSpec("missing_fields", self._config.missing_fields_pct),
            ErrorSpec("wrong_content_type", self._config.wrong_content_type_pct),
        ]

    def _build_decision(self, tag: str) -> ErrorDecision:
        """Map a selected error tag to a domain-specific ErrorDecision."""
        # Connection-level errors
        if tag == "connection_failed":
            return ErrorDecision.connection_error(
                "connection_failed",
                start_delay_sec=self._pick_connection_failed_lead(),
            )
        if tag == "connection_stall":
            return ErrorDecision.connection_error(
                "connection_stall",
                delay_sec=self._pick_connection_stall_delay(),
                start_delay_sec=self._pick_connection_stall_start(),
            )
        if tag == "timeout":
            return self._build_timeout_decision()
        if tag == "connection_reset":
            return ErrorDecision.connection_error("connection_reset")
        if tag == "slow_response":
            return ErrorDecision.connection_error(
                "slow_response",
                delay_sec=self._pick_slow_response_delay(),
            )

        # HTTP errors with special handling
        if tag == "rate_limit":
            return ErrorDecision.http_error("rate_limit", 429, retry_after_sec=self._pick_retry_after())
        if tag == "capacity_529":
            return ErrorDecision.http_error("capacity_529", 529, retry_after_sec=self._pick_retry_after())

        # Generic HTTP errors
        if tag in HTTP_ERRORS:
            return ErrorDecision.http_error(tag, HTTP_ERRORS[tag])

        # Malformed responses
        if tag in MALFORMED_TYPES:
            return ErrorDecision.malformed_response(tag)

        msg = f"Unknown error tag: {tag}"
        raise ValueError(msg)

    def decide(self) -> ErrorDecision:
        """Decide whether to inject an error for this request.

        Errors are evaluated based on selection_mode:
        - priority: first matching error wins (current default)
        - weighted: errors are chosen by configured weights

        Priority order (when selection_mode=priority):
        1. Connection-level errors (connection_failed, connection_stall, timeout, connection_reset, slow_response)
        2. HTTP errors (rate_limit, capacity_529, service_unavailable, etc.)
        3. Malformed responses

        Returns:
            ErrorDecision indicating what error (if any) to inject
        """
        specs = self._build_specs()
        selected = self._engine.select(specs)
        if selected is None:
            return ErrorDecision.success()
        return self._build_decision(selected.tag)

    def reset(self) -> None:
        """Reset the injector state (clears burst timing)."""
        self._engine.reset()

    def is_in_burst(self) -> bool:
        """Check if currently in burst mode (for observability)."""
        return self._engine.is_in_burst()
