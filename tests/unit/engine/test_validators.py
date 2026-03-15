"""Tests for errorworks.engine.validators."""

from __future__ import annotations

import pytest

from errorworks.engine.validators import parse_range


class TestParseRangeFloatRejection:
    """parse_range must reject floats with fractional parts."""

    def test_rejects_fractional_floats(self) -> None:
        with pytest.raises(ValueError, match="must be integers.*1.5"):
            parse_range([1.5, 3.5])

    def test_rejects_single_fractional_float(self) -> None:
        with pytest.raises(ValueError, match="must be integers.*2.7"):
            parse_range([1, 2.7])

    def test_accepts_exact_integer_floats(self) -> None:
        assert parse_range([3.0, 5.0]) == (3, 5)

    def test_accepts_plain_integers(self) -> None:
        assert parse_range([1, 10]) == (1, 10)
