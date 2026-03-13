"""Burst state machine and selection algorithms for chaos error injection.

The InjectionEngine is a composable utility — NOT a base class. Each chaos
plugin creates an InjectionEngine instance and delegates burst/selection
logic to it while retaining full ownership of its error types and decisions.

Usage:
    engine = InjectionEngine(
        selection_mode=SelectionMode.PRIORITY,
        burst_config=BurstConfig(enabled=True, interval_sec=30, duration_sec=5),
    )

    # Plugin checks engine.is_in_burst() and builds burst-aware specs,
    # then passes them to engine.select()
    specs = [ErrorSpec("rate_limit", 10.0), ErrorSpec("timeout", 5.0)]
    selected = engine.select(specs)
    if selected is not None:
        # Map selected.tag back to a domain-specific decision
        ...
"""

import random as random_module
import threading
import time
from collections.abc import Callable

from errorworks.engine.types import BurstConfig, ErrorSpec, SelectionMode


class InjectionEngine:
    """Burst state machine + priority/weighted error selection.

    Thread-safe for burst state management. The RNG is not thread-safe —
    callers are expected to snapshot the engine reference per-request (see
    config snapshot pattern) rather than sharing concurrent calls to select().

    The engine handles:
    - Periodic burst windows (is the system currently in a burst?)
    - `should_trigger(pct)` — random check against a percentage
    - `select(specs)` — priority or weighted selection from a spec list

    The engine does NOT know about HTTP status codes, connection errors,
    or any domain-specific error types. Callers build ErrorSpec lists
    and interpret the selected tag.
    """

    def __init__(
        self,
        *,
        selection_mode: SelectionMode | str = SelectionMode.PRIORITY,
        burst_config: BurstConfig | None = None,
        time_func: Callable[[], float] | None = None,
        rng: random_module.Random | None = None,
    ) -> None:
        """Initialize the injection engine.

        Args:
            selection_mode: "priority" (first triggered wins) or "weighted" (proportional).
            burst_config: Burst state machine configuration (disabled by default).
            time_func: Time function for testing (default: time.monotonic).
            rng: Random instance for testing (default: creates new Random instance).
        """
        self._selection_mode = SelectionMode(selection_mode)
        self._burst_config = burst_config if burst_config is not None else BurstConfig()
        self._time_func = time_func if time_func is not None else time.monotonic
        self._rng = rng if rng is not None else random_module.Random()

        # Burst state machine
        self._lock = threading.Lock()
        self._start_time: float | None = None

    @property
    def selection_mode(self) -> SelectionMode:
        """Current selection mode."""
        return self._selection_mode

    def _get_elapsed(self) -> float:
        """Get elapsed time since first call, initializing start time if needed."""
        with self._lock:
            current = self._time_func()
            if self._start_time is None:
                self._start_time = current
            return current - self._start_time

    def is_in_burst(self) -> bool:
        """Check if currently in a burst window (for observability).

        Returns:
            True if the burst state machine is in an active burst window.
        """
        elapsed = self._get_elapsed()
        return self._check_burst(elapsed)

    def _check_burst(self, elapsed: float) -> bool:
        """Determine if we're currently in a burst period.

        Bursts occur periodically:
        - Every burst.interval_sec seconds, a burst starts
        - Each burst lasts for burst.duration_sec seconds
        """
        if not self._burst_config.enabled:
            return False

        interval = self._burst_config.interval_sec
        duration = self._burst_config.duration_sec
        position_in_interval = elapsed % interval
        return position_in_interval < duration

    def should_trigger(self, percentage: float) -> bool:
        """Determine if an error should trigger based on percentage.

        Args:
            percentage: Error percentage (0-100).

        Returns:
            True if the error should trigger.
        """
        if percentage <= 0:
            return False
        return self._rng.random() * 100 < percentage

    def select(self, specs: list[ErrorSpec]) -> ErrorSpec | None:
        """Select an error from the spec list based on selection mode.

        In priority mode, specs are evaluated in order — first triggered wins.
        In weighted mode, a single error is selected proportionally.

        Args:
            specs: Ordered list of error specifications with weights.
                   In priority mode, order determines precedence.
                   In weighted mode, order is irrelevant.

        Returns:
            The selected ErrorSpec, or None if no error fires (success).
        """
        if self._selection_mode is SelectionMode.WEIGHTED:
            return self._select_weighted(specs)
        return self._select_priority(specs)

    def _select_priority(self, specs: list[ErrorSpec]) -> ErrorSpec | None:
        """Priority-based selection: first triggered spec wins."""
        for spec in specs:
            if self.should_trigger(spec.weight):
                return spec
        return None

    def _select_weighted(self, specs: list[ErrorSpec]) -> ErrorSpec | None:
        """Weighted selection: choose proportionally from spec weights.

        Success probability is implicitly max(0, 100 - total_weight).
        """
        choices: list[ErrorSpec] = [s for s in specs if s.weight > 0]
        if not choices:
            return None

        total_weight = sum(s.weight for s in choices)
        if total_weight <= 0:
            return None

        success_weight = max(0.0, 100.0 - total_weight)
        roll = self._rng.random() * (total_weight + success_weight)
        if roll >= total_weight:
            return None

        threshold = 0.0
        for spec in choices:
            threshold += spec.weight
            if roll < threshold:
                return spec

        return None

    def reset(self) -> None:
        """Reset the engine state (clears burst timing)."""
        with self._lock:
            self._start_time = None
