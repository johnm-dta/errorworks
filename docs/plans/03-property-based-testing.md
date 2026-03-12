# Plan 03 — Property-Based Testing

**Parent:** [00-test-remediation-overview.md](00-test-remediation-overview.md)
**Priority:** Medium
**Target files:**
- `tests/unit/engine/test_config_loader.py` (add to existing)
- `tests/unit/engine/test_injection_engine.py` (add to existing)
- `tests/unit/llm/test_error_injector.py` (add to existing)
- `tests/unit/web/test_error_injector.py` (add to existing)
- `tests/unit/llm/test_latency_simulator.py` (add to existing — note: lives under `llm/`, not `engine/`)

## Context

Hypothesis is already a dev dependency (`hypothesis>=6.98,<7`) but is unused. The
codebase has several components with properties well-suited to generative testing:

- `deep_merge` has algebraic properties (identity, associativity-like)
- Error injectors have statistical rate guarantees
- Latency simulators have bounded output ranges
- Burst state machines have timing invariants

The existing deterministic tests use `FixedRandom` to pin randomness, which is
good for regression tests but doesn't explore the input space.

## Setup

### .gitignore

Add `.hypothesis/` to `.gitignore` — Hypothesis stores its example database there
and it should not be committed:

```
# Hypothesis test database
.hypothesis/
```

### pyproject.toml

```toml
[tool.hypothesis]
database_backend = "directory"
```

## Test Catalog

### 1. `deep_merge` Properties (`test_config_loader.py`)

Import: `from errorworks.engine.config_loader import deep_merge`

| Property | Hypothesis strategy |
|----------|-------------------|
| **Identity**: `deep_merge(d, {}) == d` and `deep_merge({}, d) == d` | `st.dictionaries(st.text(), st.integers())` |
| **Override wins**: `deep_merge(d1, d2)[k] == d2[k]` for flat keys in d2 | Nested dict strategy |
| **No key loss**: `set(deep_merge(d1, d2).keys()) ⊇ set(d1.keys()) ∪ set(d2.keys())` | Nested dict strategy |
| **Nested override**: nested dicts merge recursively, non-dicts replace | Recursive dict strategy |

```python
from hypothesis import given, strategies as st
from errorworks.engine.config_loader import deep_merge

# Strategy for config-like nested dicts (2 levels deep)
config_values = st.one_of(st.integers(), st.floats(allow_nan=False), st.text(max_size=20), st.booleans())
flat_dicts = st.dictionaries(st.text(min_size=1, max_size=10), config_values, max_size=5)
nested_dicts = st.dictionaries(
    st.text(min_size=1, max_size=10),
    st.one_of(config_values, flat_dicts),
    max_size=5,
)

@given(d=nested_dicts)
def test_deep_merge_identity(d):
    """Merging with empty dict returns equivalent dict."""
    assert deep_merge(d, {}) == d
    assert deep_merge({}, d) == d

@given(d1=nested_dicts, d2=nested_dicts)
def test_deep_merge_no_key_loss(d1, d2):
    """Merge result contains all keys from both inputs."""
    result = deep_merge(d1, d2)
    assert set(result.keys()) == set(d1.keys()) | set(d2.keys())
```

**Note:** `deep_merge` returns a new dict — it does not mutate inputs. If `d`
contains nested mutable dicts, the returned dict may share references, but
equality checks still work correctly for testing.

### 2. Error Rate Accuracy (`test_error_injector.py` — LLM and Web)

Import paths:
- LLM: `from errorworks.llm.error_injector import ErrorInjector`
  Config: `from errorworks.llm.config import ErrorInjectionConfig`
- Web: `from errorworks.web.error_injector import WebErrorInjector`
  Config: `from errorworks.web.config import WebErrorInjectionConfig`

| Property | Strategy |
|----------|----------|
| **Rate accuracy**: configured rate ≈ observed rate (within ±5%) over 2000 samples | `st.floats(min_value=5.0, max_value=95.0)` |
| **Zero rate = no errors**: rate 0% → 0 injections | Fixed |
| **100% rate = all errors**: rate 100% → all injections | Fixed |
| **Total rate cap**: sum of all error types ≤ 100% observed | Multiple `st.floats` |

```python
from hypothesis import given, settings, strategies as st
from errorworks.llm.config import ErrorInjectionConfig
from errorworks.llm.error_injector import ErrorInjector

@settings(max_examples=200)
@given(rate=st.floats(min_value=5.0, max_value=95.0))
def test_error_rate_accuracy(rate):
    """Observed injection rate should approximate configured rate."""
    config = ErrorInjectionConfig(rate_limit_pct=rate)
    injector = ErrorInjector(config)
    n = 2000
    injected = sum(1 for _ in range(n) if injector.decide().should_inject)
    observed_pct = (injected / n) * 100
    # Allow ±5% tolerance for statistical variance
    assert abs(observed_pct - rate) < 5.0, (
        f"Configured {rate}%, observed {observed_pct}%"
    )
```

**Web variant:** Use `WebErrorInjectionConfig` and `WebErrorInjector` (not
`ErrorInjector`) — the web class has a different name. The `decide()` method
and `.should_inject` property work identically.

### 3. Latency Simulator Bounds (`test_latency_simulator.py`)

Import: `from errorworks.engine.latency import LatencySimulator`
Config: `from errorworks.engine.types import LatencyConfig`

**IMPORTANT:** `LatencySimulator.simulate()` returns delay in **seconds** (float),
not milliseconds. `LatencyConfig` accepts `base_ms` and `jitter_ms` in milliseconds.
All bound assertions must convert accordingly.

| Property | Strategy |
|----------|----------|
| **Lower bound**: latency ≥ max(0, base_ms - jitter_ms) / 1000 | `st.integers(0, 500)` for both |
| **Upper bound**: latency ≤ (base_ms + jitter_ms) / 1000 | Same |
| **Zero jitter = deterministic**: jitter=0 → latency == base_ms / 1000 | `st.integers(0, 500)` for base |
| **Non-negative**: latency ≥ 0 always | Any valid config |

```python
from hypothesis import given, strategies as st
from errorworks.engine.latency import LatencySimulator
from errorworks.engine.types import LatencyConfig

@given(
    base_ms=st.integers(min_value=0, max_value=500),
    jitter_ms=st.integers(min_value=0, max_value=500),
)
def test_latency_within_bounds(base_ms, jitter_ms):
    """Simulated latency must stay within [base-jitter, base+jitter] (converted to seconds)."""
    config = LatencyConfig(base_ms=base_ms, jitter_ms=jitter_ms)
    sim = LatencySimulator(config)
    for _ in range(100):
        latency_sec = sim.simulate()
        assert latency_sec >= max(0, base_ms - jitter_ms) / 1000.0
        assert latency_sec <= (base_ms + jitter_ms) / 1000.0

@given(base_ms=st.integers(min_value=0, max_value=500))
def test_latency_zero_jitter_deterministic(base_ms):
    """With jitter=0, latency should always equal base_ms (in seconds)."""
    config = LatencyConfig(base_ms=base_ms, jitter_ms=0)
    sim = LatencySimulator(config)
    for _ in range(50):
        assert sim.simulate() == base_ms / 1000.0
```

### 4. Burst Timing Invariants (`test_injection_engine.py`)

Import: `from errorworks.engine.injection_engine import InjectionEngine`
Config: `from errorworks.engine.types import BurstConfig`

The `InjectionEngine` constructor requires `selection_mode` as its first
argument, plus optional `burst_config` and `time_func` (a callable returning
current time as float) for deterministic time control in tests. Use a mutable
closure to advance simulated time:

| Property | Strategy |
|----------|----------|
| **Burst never exceeds duration**: after `duration_sec` elapses, burst deactivates | `st.integers(1, 60)` for interval/duration |
| **Burst activates on schedule**: burst fires within `interval_sec` window | Time sequence strategy |
| **Duration < interval**: enforced by Pydantic, but verify engine respects it | Valid config pairs |

```python
from hypothesis import given, assume, strategies as st
from errorworks.engine.injection_engine import InjectionEngine
from errorworks.engine.types import BurstConfig

@given(
    interval=st.integers(min_value=2, max_value=30),
    duration=st.integers(min_value=1, max_value=15),
)
def test_burst_never_exceeds_duration(interval, duration):
    """Burst should deactivate after duration_sec."""
    assume(duration < interval)  # Pydantic constraint

    config = BurstConfig(enabled=True, interval_sec=interval, duration_sec=duration)
    current_time = 0.0
    engine = InjectionEngine(
        selection_mode="priority",
        burst_config=config,
        time_func=lambda: current_time,
    )

    # Advance to just after second burst cycle starts (elapsed % interval ≈ 0)
    current_time = float(interval) + 0.01
    assert engine.is_in_burst(), "Burst should be active at start of cycle"

    # Advance to just after burst should end (interval + duration)
    current_time = float(interval + duration) + 0.01
    assert not engine.is_in_burst(), "Burst should be inactive after duration elapses"
```

### 5. Config Validation Roundtrip (`test_config.py` — both LLM and Web)

Add to both `tests/unit/llm/test_config.py` and `tests/unit/web/test_config.py`:

Import (LLM): `from errorworks.llm.config import ChaosLLMConfig`
Import (Web): `from errorworks.web.config import ChaosWebConfig`

| Property | Strategy |
|----------|----------|
| **Valid config survives roundtrip**: `Config(**config.model_dump()) == config` | Config strategy |
| **model_dump is JSON-serializable**: no unserializable types | Any valid config |

```python
import json
from errorworks.llm.config import ChaosLLMConfig

def test_config_roundtrip():
    """Default config survives dump/reload roundtrip."""
    config = ChaosLLMConfig()
    dumped = config.model_dump()
    restored = ChaosLLMConfig(**dumped)
    assert restored == config

def test_config_json_serializable():
    """Config model_dump produces JSON-serializable output."""
    config = ChaosLLMConfig()
    dumped = config.model_dump()
    # Should not raise
    json.dumps(dumped, default=str)
```

**Note:** Full Hypothesis-driven config generation (random field values) is
possible but complex due to inter-field constraints. Start with the roundtrip
tests above using default configs, then consider adding `@given` with constrained
strategies if coverage gaps appear.

## Implementation Notes

### Hypothesis Settings

Use `@settings(max_examples=200)` for statistical tests (more samples = tighter
bounds) and default settings for algebraic property tests.

### What NOT to Property-Test

- HTTP response format (deterministic, better as example-based tests)
- SQL queries (too slow for generative testing, mocked DB not useful)
- CLI flag parsing (Typer handles this, covered by Plan 01)
- Content generation (output is intentionally random, hard to assert properties)
