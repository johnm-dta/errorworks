"""ChaosEngine: Shared utilities for chaos testing servers.

Provides composition-based building blocks used by ChaosLLM, ChaosWeb, and
future chaos plugins (ChaosFile, ChaosSQL, etc.):

- InjectionEngine: Burst state machine + priority/weighted error selection
- MetricsStore: Thread-safe SQLite with schema-driven DDL
- LatencySimulator: Configurable artificial latency
- Config loading: deep_merge, preset loading, YAML precedence

Each chaos plugin *composes* these utilities rather than inheriting from
base classes, avoiding covariant return type friction and HTTP-leakage
into non-HTTP domains.
"""

from errorworks.engine.config_loader import (
    deep_merge,
    list_presets,
    load_preset,
)
from errorworks.engine.injection_engine import InjectionEngine
from errorworks.engine.latency import LatencySimulator
from errorworks.engine.metrics_store import MetricsStore
from errorworks.engine.types import (
    DANGEROUS_BIND_HOSTS,
    BurstConfig,
    ColumnDef,
    ErrorSpec,
    LatencyConfig,
    MetricsConfig,
    MetricsSchema,
    SelectionMode,
    ServerConfig,
    SqlType,
)
from errorworks.engine.vocabulary import ENGLISH_VOCABULARY, LOREM_VOCABULARY

__all__ = [
    "DANGEROUS_BIND_HOSTS",
    "ENGLISH_VOCABULARY",
    "LOREM_VOCABULARY",
    "BurstConfig",
    "ColumnDef",
    "ErrorSpec",
    "InjectionEngine",
    "LatencyConfig",
    "LatencySimulator",
    "MetricsConfig",
    "MetricsSchema",
    "MetricsStore",
    "SelectionMode",
    "ServerConfig",
    "SqlType",
    "deep_merge",
    "list_presets",
    "load_preset",
]
