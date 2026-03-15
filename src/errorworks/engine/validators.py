"""Shared validation helpers for chaos plugin config and error decisions.

Extracted from ChaosLLM and ChaosWeb config/error_injector modules to
eliminate duplication. These are plain functions — no base classes.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


def parse_range(v: Any) -> tuple[int, int]:
    """Parse [min, max] range from list or tuple.

    Both values must be non-negative integers.

    Use as a Pydantic field_validator(mode="before") for tuple[int, int] fields.
    """
    if isinstance(v, (list, tuple)) and len(v) == 2:
        for i, val in enumerate(v):
            if isinstance(val, float) and not val.is_integer():
                raise ValueError(f"Range values must be integers, got float {val} at index {i}")
        lo, hi = int(v[0]), int(v[1])
        if lo < 0 or hi < 0:
            raise ValueError(f"Range values must be non-negative, got [{lo}, {hi}]")
        return (lo, hi)
    raise ValueError(f"Expected [min, max] range, got {v!r}")


def validate_ranges(ranges: dict[str, tuple[int, int]]) -> None:
    """Ensure min <= max for all range fields.

    Args:
        ranges: Mapping of field name to (min, max) tuple.

    Raises:
        ValueError: If any range has min > max.
    """
    for name, (lo, hi) in ranges.items():
        if lo > hi:
            raise ValueError(f"{name} min ({lo}) must be <= max ({hi})")


def validate_error_decision(
    *,
    error_type: str | None,
    category: StrEnum | None,
    status_code: int | None,
    retry_after_sec: int | None,
    delay_sec: float | None,
    start_delay_sec: float | None,
    malformed_type: str | None,
    http_category: StrEnum,
    connection_category: StrEnum,
    malformed_category: StrEnum,
    valid_error_types: set[str],
    valid_malformed_types: set[str],
) -> None:
    """Validate shared invariants for error decision dataclasses.

    This covers the common validation logic shared between ErrorDecision
    (ChaosLLM) and WebErrorDecision (ChaosWeb). Plugin-specific fields
    (redirect_target, incomplete_bytes, etc.) must be validated by the
    caller after this function returns.

    Args:
        error_type: The error type tag, or None for success.
        category: The error category enum value, or None for success.
        status_code: HTTP status code, if applicable.
        retry_after_sec: Retry-After header value, if applicable.
        delay_sec: Delay before responding, if applicable.
        start_delay_sec: Lead time before failure, if applicable.
        malformed_type: Specific malformation type, if applicable.
        http_category: The HTTP category enum member for comparison.
        connection_category: The CONNECTION category enum member for comparison.
        malformed_category: The MALFORMED category enum member for comparison.
        valid_error_types: Set of all valid error_type values.
        valid_malformed_types: Set of all valid malformed_type values.

    Raises:
        ValueError: If any invariant is violated.
    """
    if error_type is None:
        # Success case: no other fields should be set
        if category is not None:
            raise ValueError("Success decision must not have a category")
        return

    if category is None:
        raise ValueError(f"Error decision '{error_type}' must have a category")

    if error_type not in valid_error_types:
        raise ValueError(f"Unknown error_type '{error_type}'; must be one of {sorted(valid_error_types)}")

    if category == http_category:
        if status_code is None:
            raise ValueError(f"HTTP error '{error_type}' must have a status_code")
        if not (100 <= status_code <= 599):
            raise ValueError(f"HTTP status_code must be 100-599, got {status_code}")
        if malformed_type is not None:
            raise ValueError("HTTP error must not have malformed_type")

    elif category == connection_category:
        if retry_after_sec is not None:
            raise ValueError("Connection error must not have retry_after_sec")
        if malformed_type is not None:
            raise ValueError("Connection error must not have malformed_type")

    elif category == malformed_category:
        if malformed_type is None:
            raise ValueError("Malformed error must have malformed_type")
        if malformed_type not in valid_malformed_types:
            raise ValueError(f"Unknown malformed_type '{malformed_type}'; must be one of {sorted(valid_malformed_types)}")
        if status_code is not None and status_code != 200:
            raise ValueError(f"Malformed error must have status_code 200, got {status_code}")

    if retry_after_sec is not None and retry_after_sec < 0:
        raise ValueError(f"retry_after_sec must be non-negative, got {retry_after_sec}")
    if delay_sec is not None and delay_sec < 0:
        raise ValueError(f"delay_sec must be non-negative, got {delay_sec}")
    if start_delay_sec is not None and start_delay_sec < 0:
        raise ValueError(f"start_delay_sec must be non-negative, got {start_delay_sec}")
