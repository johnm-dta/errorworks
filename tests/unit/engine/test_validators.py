"""Tests for errorworks.engine.validators."""

from __future__ import annotations

from enum import StrEnum

import pytest

from errorworks.engine.validators import parse_range, validate_error_decision


class _TestCategory(StrEnum):
    HTTP = "http"
    CONNECTION = "connection"
    MALFORMED = "malformed"
    REDIRECT = "redirect"
    UNKNOWN = "unknown"


class TestParseRangeFloatRejection:
    """parse_range must reject floats with fractional parts."""

    def test_rejects_fractional_floats(self) -> None:
        with pytest.raises(ValueError, match=r"must be integers.*1.5"):
            parse_range([1.5, 3.5])

    def test_rejects_single_fractional_float(self) -> None:
        with pytest.raises(ValueError, match=r"must be integers.*2.7"):
            parse_range([1, 2.7])

    def test_accepts_exact_integer_floats(self) -> None:
        assert parse_range([3.0, 5.0]) == (3, 5)

    def test_accepts_plain_integers(self) -> None:
        assert parse_range([1, 10]) == (1, 10)


class TestValidateErrorDecisionUnknownCategory:
    """validate_error_decision must reject unknown error categories."""

    def test_unknown_category_raises_value_error(self) -> None:
        """An unrecognised category raises ValueError instead of silently passing."""
        with pytest.raises(ValueError, match="Unknown error category"):
            validate_error_decision(
                error_type="some_error",
                category=_TestCategory.UNKNOWN,
                status_code=None,
                retry_after_sec=None,
                delay_sec=None,
                start_delay_sec=None,
                malformed_type=None,
                http_category=_TestCategory.HTTP,
                connection_category=_TestCategory.CONNECTION,
                malformed_category=_TestCategory.MALFORMED,
                valid_error_types={"some_error"},
                valid_malformed_types=set(),
            )

    def test_known_category_does_not_raise(self) -> None:
        """A known HTTP category passes validation without error."""
        validate_error_decision(
            error_type="rate_limit",
            category=_TestCategory.HTTP,
            status_code=429,
            retry_after_sec=60,
            delay_sec=None,
            start_delay_sec=None,
            malformed_type=None,
            http_category=_TestCategory.HTTP,
            connection_category=_TestCategory.CONNECTION,
            malformed_category=_TestCategory.MALFORMED,
            valid_error_types={"rate_limit"},
            valid_malformed_types=set(),
        )

    def test_extra_category_accepted(self) -> None:
        """A plugin-specific category listed in extra_categories passes."""
        validate_error_decision(
            error_type="redirect_loop",
            category=_TestCategory.REDIRECT,
            status_code=None,
            retry_after_sec=None,
            delay_sec=None,
            start_delay_sec=None,
            malformed_type=None,
            http_category=_TestCategory.HTTP,
            connection_category=_TestCategory.CONNECTION,
            malformed_category=_TestCategory.MALFORMED,
            valid_error_types={"redirect_loop"},
            valid_malformed_types=set(),
            extra_categories=frozenset({_TestCategory.REDIRECT}),
        )

    def test_extra_category_not_listed_still_raises(self) -> None:
        """A category not in base or extra_categories is still rejected."""
        with pytest.raises(ValueError, match="Unknown error category"):
            validate_error_decision(
                error_type="redirect_loop",
                category=_TestCategory.REDIRECT,
                status_code=None,
                retry_after_sec=None,
                delay_sec=None,
                start_delay_sec=None,
                malformed_type=None,
                http_category=_TestCategory.HTTP,
                connection_category=_TestCategory.CONNECTION,
                malformed_category=_TestCategory.MALFORMED,
                valid_error_types={"redirect_loop"},
                valid_malformed_types=set(),
                # extra_categories not provided — REDIRECT is unknown
            )


class TestValidateErrorDecisionSuccessPath:
    """Success decisions must have no error-related fields set."""

    def test_success_with_status_code_raises(self) -> None:
        """Success decision with status_code set should be rejected."""
        with pytest.raises(ValueError, match="Success decision"):
            validate_error_decision(
                error_type=None,
                category=None,
                status_code=500,
                retry_after_sec=None,
                delay_sec=None,
                start_delay_sec=None,
                malformed_type=None,
                http_category=_TestCategory.HTTP,
                connection_category=_TestCategory.CONNECTION,
                malformed_category=_TestCategory.MALFORMED,
                valid_error_types=set(),
                valid_malformed_types=set(),
            )

    def test_success_with_delay_raises(self) -> None:
        """Success decision with delay_sec set should be rejected."""
        with pytest.raises(ValueError, match="Success decision"):
            validate_error_decision(
                error_type=None,
                category=None,
                status_code=None,
                retry_after_sec=None,
                delay_sec=5.0,
                start_delay_sec=None,
                malformed_type=None,
                http_category=_TestCategory.HTTP,
                connection_category=_TestCategory.CONNECTION,
                malformed_category=_TestCategory.MALFORMED,
                valid_error_types=set(),
                valid_malformed_types=set(),
            )

    def test_success_with_malformed_type_raises(self) -> None:
        """Success decision with malformed_type set should be rejected."""
        with pytest.raises(ValueError, match="Success decision"):
            validate_error_decision(
                error_type=None,
                category=None,
                status_code=None,
                retry_after_sec=None,
                delay_sec=None,
                start_delay_sec=None,
                malformed_type="truncated",
                http_category=_TestCategory.HTTP,
                connection_category=_TestCategory.CONNECTION,
                malformed_category=_TestCategory.MALFORMED,
                valid_error_types=set(),
                valid_malformed_types={"truncated"},
            )

    def test_clean_success_passes(self) -> None:
        """Success decision with all fields None passes validation."""
        validate_error_decision(
            error_type=None,
            category=None,
            status_code=None,
            retry_after_sec=None,
            delay_sec=None,
            start_delay_sec=None,
            malformed_type=None,
            http_category=_TestCategory.HTTP,
            connection_category=_TestCategory.CONNECTION,
            malformed_category=_TestCategory.MALFORMED,
            valid_error_types=set(),
            valid_malformed_types=set(),
        )
