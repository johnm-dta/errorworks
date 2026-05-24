"""Tests for ChaosBlob error injector."""

from __future__ import annotations

import random
import typing

from errorworks.blob.config import BlobBurstConfig, BlobErrorInjectionConfig
from errorworks.blob.error_injector import BlobErrorCategory, BlobErrorDecision, BlobErrorInjector, BlobOperation


def test_blob_error_decision_required_fields_are_non_optional() -> None:
    """BlobErrorDecision should not permit error_type=None or category=None.

    The dataclass previously typed these as Optional even though decide() never
    produces such a decision — it either returns None (no injection) or a
    decision with both fields set. The Optional types invited every consumer to
    add defensive checks that could never fire."""
    hints = typing.get_type_hints(BlobErrorDecision)
    # error_type and category are mandatory; status_code / s3_code / retry_after_sec stay optional.
    assert hints["error_type"] is str, f"error_type should be `str`, got {hints['error_type']!r}"
    assert hints["category"] is BlobErrorCategory, f"category should be `BlobErrorCategory`, got {hints['category']!r}"


class FixedRandom(random.Random):
    """A Random instance that returns a fixed value for testing."""

    def __init__(self, value: float) -> None:
        super().__init__()
        self._fixed_value = value

    def random(self) -> float:
        return self._fixed_value


def test_slow_down_returns_s3_http_error_with_retry_after() -> None:
    """slow_down_pct=100 produces 503 SlowDown with Retry-After."""
    config = BlobErrorInjectionConfig(slow_down_pct=100.0, retry_after_sec=(7, 7))
    injector = BlobErrorInjector(config, rng=random.Random(123))

    decision = injector.decide(BlobOperation.GET)

    assert decision is not None
    assert decision.error_type == "slow_down"
    assert decision.category == BlobErrorCategory.HTTP
    assert decision.status_code == 503
    assert decision.s3_code == "SlowDown"
    assert decision.retry_after_sec == 7


def test_truncated_body_returns_body_corruption_for_get() -> None:
    """truncated_body_pct=100 produces a body corruption decision on GET."""
    config = BlobErrorInjectionConfig(truncated_body_pct=100.0)
    injector = BlobErrorInjector(config)

    decision = injector.decide(BlobOperation.GET)

    assert decision is not None
    assert decision.error_type == "truncated_body"
    assert decision.category == BlobErrorCategory.BODY_CORRUPTION
    assert decision.status_code is None
    assert decision.s3_code is None


def test_stale_list_only_applies_to_list_operations() -> None:
    """stale_list is scoped to LIST operations."""
    config = BlobErrorInjectionConfig(stale_list_pct=100.0)
    injector = BlobErrorInjector(config)

    assert injector.decide(BlobOperation.GET) is None

    decision = injector.decide(BlobOperation.LIST)

    assert decision is not None
    assert decision.error_type == "stale_list"
    assert decision.category == BlobErrorCategory.LIST_CORRUPTION


def test_burst_elevates_slow_down() -> None:
    """Burst mode can elevate slow_down above the base rate."""
    current_time = [0.0]
    burst = BlobBurstConfig(
        enabled=True,
        interval_sec=10,
        duration_sec=5,
        slow_down_pct=100.0,
        service_unavailable_pct=0.0,
    )
    config = BlobErrorInjectionConfig(slow_down_pct=0.0, burst=burst)
    injector = BlobErrorInjector(config, time_func=lambda: current_time[0], rng=random.Random(123))

    decision = injector.decide(BlobOperation.GET)

    assert decision is not None
    assert decision.error_type == "slow_down"
    assert decision.status_code == 503
    assert decision.s3_code == "SlowDown"

    current_time[0] = 6.0
    assert injector.decide(BlobOperation.GET) is None


def test_burst_elevates_service_unavailable() -> None:
    """Burst mode can elevate service_unavailable above the base rate."""
    current_time = [0.0]
    burst = BlobBurstConfig(
        enabled=True,
        interval_sec=10,
        duration_sec=5,
        slow_down_pct=0.0,
        service_unavailable_pct=100.0,
    )
    config = BlobErrorInjectionConfig(service_unavailable_pct=0.0, burst=burst)
    injector = BlobErrorInjector(config, time_func=lambda: current_time[0], rng=random.Random(123))

    decision = injector.decide(BlobOperation.GET)

    assert decision is not None
    assert decision.error_type == "service_unavailable"
    assert decision.status_code == 503
    assert decision.s3_code == "ServiceUnavailable"

    current_time[0] = 6.0
    assert injector.decide(BlobOperation.GET) is None


def test_reset_clears_burst_timing_through_engine() -> None:
    """reset clears the composed engine's burst start time."""
    current_time = [0.0]
    burst = BlobBurstConfig(enabled=True, interval_sec=10, duration_sec=3)
    config = BlobErrorInjectionConfig(burst=burst)
    injector = BlobErrorInjector(config, time_func=lambda: current_time[0])

    assert injector.is_in_burst() is True

    current_time[0] = 5.0
    assert injector.is_in_burst() is False

    injector.reset()

    assert injector.is_in_burst() is True


def test_priority_prefers_connection_then_http_then_corruption() -> None:
    """Connection errors win over HTTP errors, which win over corruption."""
    config = BlobErrorInjectionConfig(
        timeout_pct=100.0,
        slow_down_pct=100.0,
        truncated_body_pct=100.0,
    )
    injector = BlobErrorInjector(config, rng=FixedRandom(0.0))

    decision = injector.decide(BlobOperation.GET)

    assert decision is not None
    assert decision.error_type == "timeout"
    assert decision.category == BlobErrorCategory.CONNECTION


def test_body_corruption_is_get_only_and_metadata_is_get_or_head() -> None:
    """Body corruption is GET-only; metadata corruption also applies to HEAD."""
    body_config = BlobErrorInjectionConfig(truncated_body_pct=100.0)
    body_injector = BlobErrorInjector(body_config)

    assert body_injector.decide(BlobOperation.HEAD) is None

    metadata_config = BlobErrorInjectionConfig(metadata_corruption_pct=100.0)
    metadata_injector = BlobErrorInjector(metadata_config)

    decision = metadata_injector.decide(BlobOperation.HEAD)

    assert decision is not None
    assert decision.error_type == "metadata_corruption"
    assert decision.category == BlobErrorCategory.METADATA_CORRUPTION
