"""Latency simulation for chaos testing servers.

The LatencySimulator adds configurable artificial delays to make fake
servers behave more like real services with network latency and processing time.
"""

import random as random_module

from errorworks.engine.types import LatencyConfig


class LatencySimulator:
    """Adds artificial delays to simulate real service latency.

    Stateless per-call. The RNG is not thread-safe — callers are expected
    to snapshot the simulator reference per-request (see config snapshot
    pattern) rather than sharing concurrent calls to simulate().

    Usage:
        config = LatencyConfig(base_ms=50, jitter_ms=30)
        simulator = LatencySimulator(config)
        delay = simulator.simulate()  # Returns seconds for asyncio.sleep()
        await asyncio.sleep(delay)
    """

    def __init__(
        self,
        config: LatencyConfig,
        *,
        rng: random_module.Random | None = None,
    ) -> None:
        """Initialize the latency simulator.

        Args:
            config: Latency simulation configuration.
            rng: Random instance for testing (default: creates new Random instance).
                 Inject a seeded random.Random() for deterministic testing.
        """
        self._config = config
        self._rng = rng if rng is not None else random_module.Random()

    @property
    def config(self) -> LatencyConfig:
        """Current latency simulation configuration (frozen/immutable)."""
        return self._config

    def simulate(self) -> float:
        """Calculate a simulated latency delay.

        Returns the delay in seconds (suitable for asyncio.sleep()).
        The delay is: (base_ms + random_jitter) / 1000.0

        Where random_jitter is uniformly distributed in [-jitter_ms, +jitter_ms].
        The result is clamped to a minimum of 0 (no negative delays).

        Returns:
            Delay in seconds (float).
        """
        base_ms = self._config.base_ms
        jitter_ms = self._config.jitter_ms
        jitter = self._rng.uniform(-jitter_ms, jitter_ms)
        delay_ms = max(0.0, base_ms + jitter)
        return delay_ms / 1000.0

    def simulate_slow_response(self, min_sec: int, max_sec: int) -> float:
        """Calculate a slow response delay.

        Used for slow_response error injection where the delay is specified
        in seconds as a [min, max] range.

        Args:
            min_sec: Minimum delay in seconds.
            max_sec: Maximum delay in seconds.

        Returns:
            Delay in seconds (float).
        """
        return self._rng.uniform(min_sec, max_sec)
