"""Unit tests for the InjectionEngine composable utility.

Tests the burst state machine, priority/weighted selection, should_trigger,
and reset behavior in isolation from any specific chaos plugin.
"""

from __future__ import annotations

import random

from hypothesis import assume, given
from hypothesis import strategies as st

from errorworks.engine.injection_engine import InjectionEngine
from errorworks.engine.types import BurstConfig, ErrorSpec

# =============================================================================
# Burst State Machine
# =============================================================================


class TestBurstStateMachine:
    """Tests for burst timing and state transitions."""

    def test_burst_disabled_by_default(self) -> None:
        """Default config has burst disabled."""
        engine = InjectionEngine()
        assert not engine.is_in_burst()

    def test_burst_enabled_at_start(self) -> None:
        """At t=0, burst is active (start of first interval)."""
        clock = 0.0
        engine = InjectionEngine(
            burst_config=BurstConfig(enabled=True, interval_sec=30, duration_sec=5),
            time_func=lambda: clock,
        )
        assert engine.is_in_burst()

    def test_burst_inactive_after_duration(self) -> None:
        """After burst duration elapses, burst is inactive."""
        clock = [0.0]
        engine = InjectionEngine(
            burst_config=BurstConfig(enabled=True, interval_sec=30, duration_sec=5),
            time_func=lambda: clock[0],
        )
        # Initialize
        engine._get_elapsed()
        clock[0] = 6.0
        assert not engine.is_in_burst()

    def test_burst_reactivates_at_next_interval(self) -> None:
        """Burst reactivates at the next interval boundary."""
        clock = [0.0]
        engine = InjectionEngine(
            burst_config=BurstConfig(enabled=True, interval_sec=30, duration_sec=5),
            time_func=lambda: clock[0],
        )
        engine._get_elapsed()
        # After first burst
        clock[0] = 10.0
        assert not engine.is_in_burst()
        # At second burst start
        clock[0] = 30.0
        assert engine.is_in_burst()

    def test_check_burst_periodicity(self) -> None:
        """_check_burst returns correct values across multiple intervals."""
        engine = InjectionEngine(
            burst_config=BurstConfig(enabled=True, interval_sec=10, duration_sec=3),
        )
        # In burst at t=0.5
        assert engine._check_burst(0.5)
        # Out of burst at t=5
        assert not engine._check_burst(5.0)
        # In burst at t=10.5 (second interval)
        assert engine._check_burst(10.5)
        # Out of burst at t=15
        assert not engine._check_burst(15.0)

    def test_burst_disabled_always_false(self) -> None:
        """Disabled burst always returns False."""
        engine = InjectionEngine(
            burst_config=BurstConfig(enabled=False, interval_sec=10, duration_sec=3),
        )
        for t in [0.0, 1.0, 5.0, 10.0, 100.0]:
            assert not engine._check_burst(t)


# =============================================================================
# should_trigger
# =============================================================================


class TestShouldTrigger:
    """Tests for percentage-based trigger checks."""

    def test_zero_percent_never_triggers(self) -> None:
        """0% never triggers regardless of RNG state."""
        engine = InjectionEngine(rng=random.Random(42))
        for _ in range(100):
            assert not engine.should_trigger(0.0)

    def test_negative_percent_never_triggers(self) -> None:
        """-5% never triggers (edge case)."""
        engine = InjectionEngine(rng=random.Random(42))
        for _ in range(100):
            assert not engine.should_trigger(-5.0)

    def test_100_percent_always_triggers(self) -> None:
        """100% always triggers regardless of RNG state."""
        engine = InjectionEngine(rng=random.Random(42))
        for _ in range(100):
            assert engine.should_trigger(100.0)

    def test_deterministic_with_seed(self) -> None:
        """Same seed produces same trigger sequence."""
        engine1 = InjectionEngine(rng=random.Random(99))
        engine2 = InjectionEngine(rng=random.Random(99))
        for _ in range(100):
            assert engine1.should_trigger(50.0) == engine2.should_trigger(50.0)


# =============================================================================
# Priority Selection
# =============================================================================


class TestPrioritySelection:
    """Tests for priority-based selection mode."""

    def test_empty_specs_returns_none(self) -> None:
        """No specs means success (None)."""
        engine = InjectionEngine(selection_mode="priority")
        assert engine.select([]) is None

    def test_all_zero_weight_returns_none(self) -> None:
        """Specs with 0% weight never fire."""
        engine = InjectionEngine(selection_mode="priority", rng=random.Random(42))
        specs = [ErrorSpec("a", 0.0), ErrorSpec("b", 0.0)]
        for _ in range(100):
            assert engine.select(specs) is None

    def test_100_weight_first_always_wins(self) -> None:
        """First spec at 100% always fires in priority mode."""
        engine = InjectionEngine(selection_mode="priority", rng=random.Random(42))
        specs = [ErrorSpec("first", 100.0), ErrorSpec("second", 100.0)]
        for _ in range(100):
            result = engine.select(specs)
            assert result is not None
            assert result.tag == "first"

    def test_priority_order_matters(self) -> None:
        """In priority mode, earlier specs have precedence."""
        engine = InjectionEngine(selection_mode="priority", rng=random.Random(42))
        specs = [ErrorSpec("high", 100.0), ErrorSpec("low", 100.0)]
        result = engine.select(specs)
        assert result is not None
        assert result.tag == "high"

    def test_priority_skips_zero_weight(self) -> None:
        """Priority mode skips 0%-weight specs and fires the next one."""
        engine = InjectionEngine(selection_mode="priority", rng=random.Random(42))
        specs = [ErrorSpec("disabled", 0.0), ErrorSpec("active", 100.0)]
        result = engine.select(specs)
        assert result is not None
        assert result.tag == "active"


# =============================================================================
# Weighted Selection
# =============================================================================


class TestWeightedSelection:
    """Tests for weighted selection mode."""

    def test_empty_specs_returns_none(self) -> None:
        """No specs means success (None)."""
        engine = InjectionEngine(selection_mode="weighted")
        assert engine.select([]) is None

    def test_all_zero_weight_returns_none(self) -> None:
        """Specs with 0% weight produce no selection."""
        engine = InjectionEngine(selection_mode="weighted", rng=random.Random(42))
        specs = [ErrorSpec("a", 0.0), ErrorSpec("b", 0.0)]
        for _ in range(100):
            assert engine.select(specs) is None

    def test_single_spec_at_100_always_fires(self) -> None:
        """A single 100%-weight spec always fires."""
        engine = InjectionEngine(selection_mode="weighted", rng=random.Random(42))
        specs = [ErrorSpec("only", 100.0)]
        for _ in range(100):
            result = engine.select(specs)
            assert result is not None
            assert result.tag == "only"

    def test_weighted_distributes_among_specs(self) -> None:
        """With equal weights, both specs appear over many trials."""
        engine = InjectionEngine(selection_mode="weighted", rng=random.Random(42))
        specs = [ErrorSpec("a", 50.0), ErrorSpec("b", 50.0)]
        seen: set[str] = set()
        for _ in range(500):
            result = engine.select(specs)
            if result is not None:
                seen.add(result.tag)
        assert "a" in seen
        assert "b" in seen

    def test_weighted_allows_success(self) -> None:
        """With total weight < 100, some selections return None (success)."""
        engine = InjectionEngine(selection_mode="weighted", rng=random.Random(42))
        specs = [ErrorSpec("a", 10.0)]  # Total 10% → 90% success
        none_count = sum(1 for _ in range(500) if engine.select(specs) is None)
        # Should have many successes
        assert none_count > 200


# =============================================================================
# Selection Mode Property
# =============================================================================


class TestSelectionMode:
    """Tests for selection_mode property."""

    def test_default_mode_is_priority(self) -> None:
        engine = InjectionEngine()
        assert engine.selection_mode == "priority"

    def test_weighted_mode(self) -> None:
        engine = InjectionEngine(selection_mode="weighted")
        assert engine.selection_mode == "weighted"


# =============================================================================
# Reset
# =============================================================================


class TestReset:
    """Tests for engine reset behavior."""

    def test_reset_clears_burst_timing(self) -> None:
        """Reset clears the start time, so burst timing restarts."""
        clock = [0.0]
        engine = InjectionEngine(
            burst_config=BurstConfig(enabled=True, interval_sec=10, duration_sec=3),
            time_func=lambda: clock[0],
        )
        # Start timer
        engine._get_elapsed()
        # Move past first burst
        clock[0] = 5.0
        assert not engine.is_in_burst()

        # Reset
        engine.reset()

        # Now t=5 becomes the new start, so elapsed=0 → in burst
        assert engine.is_in_burst()

    def test_reset_allows_reuse(self) -> None:
        """After reset, engine continues to work normally."""
        engine = InjectionEngine(rng=random.Random(42))
        engine._get_elapsed()
        engine.reset()
        # Should still work
        result = engine.select([ErrorSpec("test", 100.0)])
        assert result is not None
        assert result.tag == "test"


# ---------------------------------------------------------------------------
# Property-based tests for burst timing
# ---------------------------------------------------------------------------


@given(
    interval=st.integers(min_value=2, max_value=30),
    duration=st.integers(min_value=1, max_value=15),
)
def test_burst_never_exceeds_duration(interval: int, duration: int) -> None:
    """Burst should deactivate after duration_sec elapses."""
    assume(duration < interval)

    config = BurstConfig(enabled=True, interval_sec=interval, duration_sec=duration)
    current_time = [0.0]
    engine = InjectionEngine(
        selection_mode="priority",
        burst_config=config,
        time_func=lambda: current_time[0],
    )

    # Initialize _start_time at t=0 to avoid float subtraction precision issues
    assert engine.is_in_burst(), "Burst should be active at t=0 (position 0 < duration)"

    # Advance past burst end within first cycle: elapsed = duration + 0.5
    current_time[0] = float(duration) + 0.5
    assert not engine.is_in_burst(), "Burst should be inactive after duration elapses"

    # Advance to start of next cycle: elapsed = interval + 0.5, position = 0.5 < duration
    current_time[0] = float(interval) + 0.5
    assert engine.is_in_burst(), "Burst should be active at start of next cycle"
