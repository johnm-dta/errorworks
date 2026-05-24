"""Error injection logic for ChaosBlob."""

from __future__ import annotations

import random as random_module
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from errorworks.blob.config import BlobErrorInjectionConfig
from errorworks.engine.injection_engine import InjectionEngine
from errorworks.engine.types import BurstConfig as EngineBurstConfig
from errorworks.engine.types import ErrorSpec, SelectionMode


class BlobOperation(StrEnum):
    """Blob/object-storage operation kinds."""

    PUT = "put"
    GET = "get"
    HEAD = "head"
    DELETE = "delete"
    LIST = "list"


class BlobErrorCategory(StrEnum):
    """Categories of blob errors the injector can produce."""

    HTTP = "http"
    CONNECTION = "connection"
    BODY_CORRUPTION = "body_corruption"
    LIST_CORRUPTION = "list_corruption"
    METADATA_CORRUPTION = "metadata_corruption"


@dataclass(frozen=True, slots=True)
class BlobErrorDecision:
    """Result of a blob error injection decision.

    A decision exists only when an injection has been chosen — ``decide()``
    returns ``BlobErrorDecision | None`` and never produces a decision with a
    missing ``error_type`` or ``category``. The remaining fields are
    category-specific: HTTP-shaped errors carry ``status_code`` / ``s3_code``
    (and optionally ``retry_after_sec`` for SlowDown); connection / corruption
    errors leave them as ``None``.
    """

    error_type: str
    category: BlobErrorCategory
    status_code: int | None = None
    s3_code: str | None = None
    retry_after_sec: int | None = None


BLOB_HTTP_ERRORS: dict[str, tuple[int, str]] = {
    "slow_down": (503, "SlowDown"),
    "access_denied": (403, "AccessDenied"),
    "not_found": (404, "NoSuchKey"),
    "service_unavailable": (503, "ServiceUnavailable"),
    "internal_error": (500, "InternalError"),
    "bad_gateway": (502, "BadGateway"),
    "gateway_timeout": (504, "GatewayTimeout"),
}

BLOB_CONNECTION_ERRORS: set[str] = {
    "timeout",
    "connection_reset",
    "connection_stall",
    "slow_response",
}

BLOB_BODY_CORRUPTION_ERRORS: set[str] = {
    "truncated_body",
    "wrong_content_length",
    "checksum_mismatch",
}

BLOB_LIST_CORRUPTION_ERRORS: set[str] = {
    "stale_list",
    "malformed_xml",
}


class BlobErrorInjector:
    """Decides per-request whether to inject a blob/object-storage error."""

    def __init__(
        self,
        config: BlobErrorInjectionConfig,
        *,
        time_func: Callable[[], float] | None = None,
        rng: random_module.Random | None = None,
    ) -> None:
        """Initialize the blob error injector."""
        self._config = config
        self._rng = rng if rng is not None else random_module.Random()
        self._engine = InjectionEngine(
            selection_mode=SelectionMode(config.selection_mode),
            burst_config=EngineBurstConfig(
                enabled=config.burst.enabled,
                interval_sec=config.burst.interval_sec,
                duration_sec=config.burst.duration_sec,
            ),
            time_func=time_func,
            rng=self._rng,
        )

    @property
    def config(self) -> BlobErrorInjectionConfig:
        """Current blob error injection configuration."""
        return self._config

    def _pick_retry_after(self) -> int:
        """Pick a random Retry-After value from the configured range."""
        min_sec, max_sec = self._config.retry_after_sec
        return self._rng.randint(min_sec, max_sec)

    def pick_delay(self, delay_range: tuple[int, int]) -> float:
        """Pick a random delay value from a configured range."""
        min_sec, max_sec = delay_range
        if min_sec == max_sec:
            return float(min_sec)
        return self._rng.uniform(min_sec, max_sec)

    def _build_specs(self, operation: BlobOperation) -> list[ErrorSpec]:
        """Build operation-scoped error specs in priority order."""
        in_burst = self._engine.is_in_burst()
        slow_down_pct = self._config.burst.slow_down_pct if in_burst else self._config.slow_down_pct
        service_unavailable_pct = self._config.burst.service_unavailable_pct if in_burst else self._config.service_unavailable_pct

        specs = [
            ErrorSpec("timeout", self._config.timeout_pct),
            ErrorSpec("connection_reset", self._config.connection_reset_pct),
            ErrorSpec("connection_stall", self._config.connection_stall_pct),
            ErrorSpec("slow_response", self._config.slow_response_pct),
            ErrorSpec("slow_down", slow_down_pct),
            ErrorSpec("access_denied", self._config.access_denied_pct),
            ErrorSpec("not_found", self._config.not_found_pct),
            ErrorSpec("service_unavailable", service_unavailable_pct),
            ErrorSpec("internal_error", self._config.internal_error_pct),
            ErrorSpec("bad_gateway", self._config.bad_gateway_pct),
            ErrorSpec("gateway_timeout", self._config.gateway_timeout_pct),
        ]

        if operation is BlobOperation.GET:
            specs.extend(
                [
                    ErrorSpec("truncated_body", self._config.truncated_body_pct),
                    ErrorSpec("wrong_content_length", self._config.wrong_content_length_pct),
                    ErrorSpec("checksum_mismatch", self._config.checksum_mismatch_pct),
                ]
            )

        if operation in {BlobOperation.GET, BlobOperation.HEAD}:
            specs.append(ErrorSpec("metadata_corruption", self._config.metadata_corruption_pct))

        if operation is BlobOperation.LIST:
            specs.extend(
                [
                    ErrorSpec("stale_list", self._config.stale_list_pct),
                    ErrorSpec("malformed_xml", self._config.malformed_xml_pct),
                ]
            )

        return specs

    def _build_decision(self, tag: str) -> BlobErrorDecision:
        """Map a selected error tag to a blob-specific decision."""
        if tag == "timeout":
            return BlobErrorDecision(
                error_type="timeout",
                category=BlobErrorCategory.CONNECTION,
                status_code=504,
                s3_code="RequestTimeout",
            )
        if tag in BLOB_CONNECTION_ERRORS:
            return BlobErrorDecision(error_type=tag, category=BlobErrorCategory.CONNECTION)

        if tag in BLOB_HTTP_ERRORS:
            status_code, s3_code = BLOB_HTTP_ERRORS[tag]
            retry_after_sec = self._pick_retry_after() if tag == "slow_down" else None
            return BlobErrorDecision(
                error_type=tag,
                category=BlobErrorCategory.HTTP,
                status_code=status_code,
                s3_code=s3_code,
                retry_after_sec=retry_after_sec,
            )

        if tag in BLOB_BODY_CORRUPTION_ERRORS:
            return BlobErrorDecision(error_type=tag, category=BlobErrorCategory.BODY_CORRUPTION)
        if tag in BLOB_LIST_CORRUPTION_ERRORS:
            return BlobErrorDecision(error_type=tag, category=BlobErrorCategory.LIST_CORRUPTION)
        if tag == "metadata_corruption":
            return BlobErrorDecision(error_type=tag, category=BlobErrorCategory.METADATA_CORRUPTION)

        msg = f"Unknown error tag: {tag}"
        raise ValueError(msg)

    def decide(self, operation: BlobOperation) -> BlobErrorDecision | None:
        """Decide whether to inject an error for the given blob operation."""
        selected = self._engine.select(self._build_specs(operation))
        if selected is None:
            return None
        return self._build_decision(selected.tag)

    def reset(self) -> None:
        """Reset the injector state (clears burst timing)."""
        self._engine.reset()

    def is_in_burst(self) -> bool:
        """Check if currently in burst mode."""
        return self._engine.is_in_burst()
