"""Shared types for chaos testing infrastructure.

Contains configuration models shared across all chaos plugins (ServerConfig,
MetricsConfig, LatencyConfig) and generic types for the injection engine
(ErrorSpec, BurstConfig) and metrics store (MetricsSchema).
"""

from __future__ import annotations

import math
import re
import secrets
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, Field


class SelectionMode(StrEnum):
    """Selection algorithm for the injection engine."""

    PRIORITY = "priority"
    WEIGHTED = "weighted"


# =============================================================================
# Shared Configuration Models
# =============================================================================


class ServerConfig(BaseModel):
    """Server binding and worker configuration."""

    model_config = {"frozen": True, "extra": "forbid"}

    host: str = Field(
        default="127.0.0.1",
        min_length=1,
        description="Host address to bind to",
    )
    port: int = Field(
        default=8000,
        gt=0,
        le=65535,
        description="Port to listen on",
    )
    workers: int = Field(
        default=4,
        gt=0,
        description="Number of uvicorn workers",
    )
    admin_token: str = Field(
        default_factory=lambda: secrets.token_urlsafe(32),
        min_length=1,
        description=(
            "Bearer token required for /admin/* endpoints. "
            "Requests must include 'Authorization: Bearer <token>'. "
            "Auto-generated if not specified."
        ),
    )


class MetricsConfig(BaseModel):
    """Metrics storage configuration."""

    model_config = {"frozen": True, "extra": "forbid"}

    database: str = Field(
        default="file:chaos-metrics?mode=memory&cache=shared",
        description="SQLite database path for metrics storage (in-memory by default)",
    )
    timeseries_bucket_sec: int = Field(
        default=1,
        gt=0,
        description="Time-series aggregation bucket size in seconds",
    )


class LatencyConfig(BaseModel):
    """Latency simulation configuration."""

    model_config = {"frozen": True, "extra": "forbid"}

    base_ms: int = Field(
        default=50,
        ge=0,
        description="Base latency in milliseconds",
    )
    jitter_ms: int = Field(
        default=30,
        ge=0,
        description="Random jitter added to base latency (+/- ms)",
    )


# =============================================================================
# Injection Engine Types
# =============================================================================


@dataclass(frozen=True, slots=True)
class ErrorSpec:
    """A single error specification for the injection engine.

    ErrorSpec is the currency between a chaos plugin and the InjectionEngine.
    The plugin builds a list of ErrorSpec objects (with domain-specific tags),
    and the engine selects which one fires based on weights and burst state.

    Attributes:
        tag: Opaque identifier for this error type (e.g., "rate_limit", "timeout").
             The engine doesn't interpret this — the caller uses it to map back
             to a domain-specific decision.
        weight: Probability weight for this error (non-negative, typically 0-100
             but may exceed 100 during burst adjustment).
    """

    tag: str
    weight: float

    def __post_init__(self) -> None:
        if not self.tag:
            raise ValueError("ErrorSpec tag must not be empty")
        if not math.isfinite(self.weight):
            raise ValueError(f"ErrorSpec weight must be finite, got {self.weight}")
        if self.weight < 0:
            raise ValueError(f"ErrorSpec weight must be non-negative, got {self.weight}")


@dataclass(frozen=True, slots=True)
class BurstConfig:
    """Burst state machine configuration.

    Configures periodic burst windows where the injection engine reports
    elevated error rates.

    Attributes:
        enabled: Whether burst mode is active.
        interval_sec: Time between burst starts in seconds.
        duration_sec: How long each burst lasts in seconds.
    """

    enabled: bool = False
    interval_sec: float = 30.0
    duration_sec: float = 5.0

    def __post_init__(self) -> None:
        if self.interval_sec <= 0:
            raise ValueError(f"interval_sec must be positive, got {self.interval_sec}")
        if self.duration_sec <= 0:
            raise ValueError(f"duration_sec must be positive, got {self.duration_sec}")
        if self.enabled and self.duration_sec >= self.interval_sec:
            raise ValueError(
                f"duration_sec ({self.duration_sec}) must be less than interval_sec ({self.interval_sec}) when burst is enabled"
            )


# =============================================================================
# Metrics Store Types
# =============================================================================


_VALID_SQL_TYPES = frozenset({"TEXT", "INTEGER", "REAL", "BLOB", "NUMERIC"})
_VALID_COLUMN_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Safe DEFAULT expressions: NULL, numeric literals, quoted strings.
# Prevents SQL injection in DDL generation where defaults are interpolated via f-string.
_VALID_DEFAULT = re.compile(
    r"^(?:NULL|'[^'\x00-\x1f\x7f]*'|[+-]?\d+(?:\.\d+)?)$",
    re.IGNORECASE,
)

# Hosts that bind to all interfaces — dangerous for a chaos testing server.
# Shared by ChaosLLMConfig and ChaosWebConfig validators.
DANGEROUS_BIND_HOSTS = frozenset({"0.0.0.0", "::", "0:0:0:0:0:0:0:0"})


@dataclass(frozen=True, slots=True)
class ColumnDef:
    """Definition of a single column in a metrics table.

    Attributes:
        name: Column name in the database (must be a valid SQL identifier).
        sql_type: SQLite column type (TEXT, INTEGER, REAL, BLOB, NUMERIC).
        nullable: Whether the column allows NULL values.
        default: Default value expression (e.g., "0", "NULL").
        primary_key: Whether this column is the primary key.
    """

    name: str
    sql_type: str
    nullable: bool = True
    default: str | None = None
    primary_key: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ColumnDef name must not be empty")
        if not _VALID_COLUMN_NAME.match(self.name):
            raise ValueError(f"ColumnDef name must be a valid SQL identifier (letters, digits, underscores), got {self.name!r}")
        if self.sql_type not in _VALID_SQL_TYPES:
            raise ValueError(f"ColumnDef sql_type must be one of {sorted(_VALID_SQL_TYPES)}, got {self.sql_type!r}")
        if self.primary_key and self.nullable:
            raise ValueError(f"ColumnDef '{self.name}': primary_key columns cannot be nullable")
        if self.default is not None and not _VALID_DEFAULT.match(self.default):
            raise ValueError(
                f"ColumnDef '{self.name}': default must be NULL, a numeric literal, or a single-quoted string, got {self.default!r}"
            )


@dataclass(frozen=True, slots=True)
class MetricsSchema:
    """Schema definition for a metrics database.

    Describes the structure of the requests and timeseries tables
    that a specific chaos plugin needs. The MetricsStore generates
    DDL from this schema at initialization.

    Attributes:
        request_columns: Column definitions for the requests table.
        timeseries_columns: Column definitions for the timeseries table.
        request_indexes: Additional indexes on the requests table.
            Each entry is (index_name, column_name).
    """

    request_columns: tuple[ColumnDef, ...]
    timeseries_columns: tuple[ColumnDef, ...]
    request_indexes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.request_columns:
            raise ValueError("MetricsSchema requires at least one request column")
        if not self.timeseries_columns:
            raise ValueError("MetricsSchema requires at least one timeseries column")

        # Check for duplicate column names within each table
        req_names = [c.name for c in self.request_columns]
        req_dupes = {n for n in req_names if req_names.count(n) > 1}
        if req_dupes:
            raise ValueError(f"Duplicate request column names: {sorted(req_dupes)}")

        ts_names = [c.name for c in self.timeseries_columns]
        ts_dupes = {n for n in ts_names if ts_names.count(n) > 1}
        if ts_dupes:
            raise ValueError(f"Duplicate timeseries column names: {sorted(ts_dupes)}")

        # Validate that index columns reference actual request columns
        req_name_set = set(req_names)
        for index_name, col_name in self.request_indexes:
            if col_name not in req_name_set:
                raise ValueError(f"Index '{index_name}' references column '{col_name}' which does not exist in request_columns")

        # Validate index names against _VALID_COLUMN_NAME to prevent DDL injection
        for index_name, _col_name in self.request_indexes:
            if not _VALID_COLUMN_NAME.match(index_name):
                raise ValueError(f"Index name must be a valid SQL identifier (letters, digits, underscores), got {index_name!r}")

        # Validate structural columns required by MetricsStore operations
        ts_name_set = set(ts_names)
        missing_ts = {"bucket_utc", "requests_total"} - ts_name_set
        if missing_ts:
            raise ValueError(f"MetricsSchema timeseries_columns must include {sorted(missing_ts)} (required by update_timeseries)")
        if "timestamp_utc" not in req_name_set:
            raise ValueError("MetricsSchema request_columns must include 'timestamp_utc' (required by rebuild_timeseries)")

        # Verify bucket_utc is a primary key (required by ON CONFLICT(bucket_utc) in update_timeseries)
        bucket_utc_col = next(c for c in self.timeseries_columns if c.name == "bucket_utc")
        if not bucket_utc_col.primary_key:
            raise ValueError(
                "MetricsSchema timeseries column 'bucket_utc' must have primary_key=True "
                "(required by ON CONFLICT(bucket_utc) in update_timeseries)"
            )
