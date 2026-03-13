"""Unit tests for engine type validation (__post_init__ and Pydantic validators).

Covers every validation branch in ErrorSpec, BurstConfig, ColumnDef,
MetricsSchema, and ServerConfig to ensure invalid inputs are rejected
and boundary values are accepted.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from errorworks.engine.types import (
    BurstConfig,
    ColumnDef,
    ErrorSpec,
    MetricsSchema,
    ServerConfig,
)

# =============================================================================
# ErrorSpec validation
# =============================================================================


class TestErrorSpecValidation:
    """Tests for ErrorSpec.__post_init__ validation."""

    def test_valid_construction(self) -> None:
        spec = ErrorSpec(tag="rate_limit", weight=50.0)
        assert spec.tag == "rate_limit"
        assert spec.weight == 50.0

    def test_zero_weight_is_valid(self) -> None:
        """Zero weight is a valid boundary value (disabled spec)."""
        spec = ErrorSpec(tag="disabled", weight=0.0)
        assert spec.weight == 0.0

    def test_empty_tag_raises(self) -> None:
        with pytest.raises(ValueError, match="tag must not be empty"):
            ErrorSpec(tag="", weight=1.0)

    @pytest.mark.parametrize("weight", [-1.0, -0.01, -100.0])
    def test_negative_weight_raises(self, weight: float) -> None:
        with pytest.raises(ValueError, match="weight must be non-negative"):
            ErrorSpec(tag="test", weight=weight)

    def test_nan_weight_raises(self) -> None:
        with pytest.raises(ValueError, match="weight must be finite"):
            ErrorSpec(tag="test", weight=float("nan"))

    @pytest.mark.parametrize("weight", [float("inf"), float("-inf")])
    def test_infinite_weight_raises(self, weight: float) -> None:
        with pytest.raises(ValueError, match="weight must be finite"):
            ErrorSpec(tag="test", weight=weight)

    def test_negative_inf_rejected_as_non_finite(self) -> None:
        """Negative infinity hits the 'finite' check before the 'non-negative' check."""
        with pytest.raises(ValueError, match="weight must be finite"):
            ErrorSpec(tag="test", weight=-math.inf)


# =============================================================================
# BurstConfig validation
# =============================================================================


class TestBurstConfigValidation:
    """Tests for BurstConfig.__post_init__ validation."""

    def test_valid_defaults(self) -> None:
        config = BurstConfig()
        assert config.enabled is False
        assert config.interval_sec == 30.0
        assert config.duration_sec == 5.0

    def test_valid_enabled(self) -> None:
        config = BurstConfig(enabled=True, interval_sec=30.0, duration_sec=5.0)
        assert config.enabled is True

    @pytest.mark.parametrize("interval", [-1.0, -0.01])
    def test_negative_interval_raises(self, interval: float) -> None:
        with pytest.raises(ValueError, match="interval_sec must be positive"):
            BurstConfig(interval_sec=interval)

    def test_zero_interval_raises(self) -> None:
        with pytest.raises(ValueError, match="interval_sec must be positive"):
            BurstConfig(interval_sec=0.0)

    @pytest.mark.parametrize("duration", [-1.0, -0.01])
    def test_negative_duration_raises(self, duration: float) -> None:
        with pytest.raises(ValueError, match="duration_sec must be positive"):
            BurstConfig(duration_sec=duration)

    def test_zero_duration_raises(self) -> None:
        with pytest.raises(ValueError, match="duration_sec must be positive"):
            BurstConfig(duration_sec=0.0)

    def test_duration_gte_interval_when_enabled_raises(self) -> None:
        """duration_sec >= interval_sec is invalid when burst is enabled."""
        with pytest.raises(ValueError, match=r"duration_sec.*must be less than interval_sec"):
            BurstConfig(enabled=True, interval_sec=10.0, duration_sec=10.0)

    def test_duration_greater_than_interval_when_enabled_raises(self) -> None:
        with pytest.raises(ValueError, match=r"duration_sec.*must be less than interval_sec"):
            BurstConfig(enabled=True, interval_sec=10.0, duration_sec=15.0)

    def test_duration_gte_interval_when_disabled_is_valid(self) -> None:
        """When disabled, the duration >= interval check is skipped."""
        config = BurstConfig(enabled=False, interval_sec=10.0, duration_sec=10.0)
        assert config.duration_sec == 10.0

    def test_duration_greater_than_interval_when_disabled_is_valid(self) -> None:
        config = BurstConfig(enabled=False, interval_sec=5.0, duration_sec=20.0)
        assert config.duration_sec == 20.0


# =============================================================================
# ColumnDef validation
# =============================================================================


class TestColumnDefValidation:
    """Tests for ColumnDef.__post_init__ validation."""

    def test_valid_column(self) -> None:
        col = ColumnDef(name="request_id", sql_type="TEXT", nullable=False, primary_key=True)
        assert col.name == "request_id"

    def test_valid_column_with_default(self) -> None:
        col = ColumnDef(name="count", sql_type="INTEGER", default="0")
        assert col.default == "0"

    def test_valid_column_with_string_default(self) -> None:
        col = ColumnDef(name="status", sql_type="TEXT", default="'pending'")
        assert col.default == "'pending'"

    def test_valid_column_with_null_default(self) -> None:
        col = ColumnDef(name="extra", sql_type="TEXT", default="NULL")
        assert col.default == "NULL"

    def test_empty_name_raises(self) -> None:
        with pytest.raises(ValueError, match="name must not be empty"):
            ColumnDef(name="", sql_type="TEXT")

    @pytest.mark.parametrize(
        "name",
        [
            "1bad",        # starts with digit
            "has space",   # contains space
            "drop;table",  # contains semicolon
            "col-name",    # contains hyphen
            "col.name",    # contains dot
        ],
    )
    def test_invalid_column_name_raises(self, name: str) -> None:
        with pytest.raises(ValueError, match="must be a valid SQL identifier"):
            ColumnDef(name=name, sql_type="TEXT")

    def test_valid_column_names(self) -> None:
        """Underscores and mixed case are valid SQL identifiers."""
        for name in ["_private", "Col123", "UPPER", "lower_case", "a"]:
            col = ColumnDef(name=name, sql_type="TEXT")
            assert col.name == name

    @pytest.mark.parametrize("sql_type", ["VARCHAR", "STRING", "INT", "bool", "FLOAT", ""])
    def test_invalid_sql_type_raises(self, sql_type: str) -> None:
        with pytest.raises(ValueError, match="sql_type must be one of"):
            ColumnDef(name="col", sql_type=sql_type)

    @pytest.mark.parametrize("sql_type", ["TEXT", "INTEGER", "REAL", "BLOB", "NUMERIC"])
    def test_valid_sql_types(self, sql_type: str) -> None:
        col = ColumnDef(name="col", sql_type=sql_type)
        assert col.sql_type == sql_type

    def test_primary_key_nullable_raises(self) -> None:
        with pytest.raises(ValueError, match="primary_key columns cannot be nullable"):
            ColumnDef(name="id", sql_type="INTEGER", nullable=True, primary_key=True)

    def test_primary_key_not_nullable_is_valid(self) -> None:
        col = ColumnDef(name="id", sql_type="INTEGER", nullable=False, primary_key=True)
        assert col.primary_key is True

    @pytest.mark.parametrize(
        "default",
        [
            "DROP TABLE",        # SQL injection attempt
            "1; DROP TABLE",     # embedded semicolon
            "random()",          # function call
            "''||evil''",        # concatenation attempt
        ],
    )
    def test_invalid_default_raises(self, default: str) -> None:
        with pytest.raises(ValueError, match="default must be NULL, a numeric literal, or a single-quoted string"):
            ColumnDef(name="col", sql_type="TEXT", default=default)


# =============================================================================
# MetricsSchema validation
# =============================================================================


def _minimal_request_columns() -> tuple[ColumnDef, ...]:
    """Return the minimum required request columns."""
    return (ColumnDef(name="timestamp_utc", sql_type="TEXT"),)


def _minimal_timeseries_columns() -> tuple[ColumnDef, ...]:
    """Return the minimum required timeseries columns."""
    return (
        ColumnDef(name="bucket_utc", sql_type="TEXT", nullable=False, primary_key=True),
        ColumnDef(name="requests_total", sql_type="INTEGER", default="0"),
    )


class TestMetricsSchemaValidation:
    """Tests for MetricsSchema.__post_init__ validation."""

    def test_valid_minimal_schema(self) -> None:
        schema = MetricsSchema(
            request_columns=_minimal_request_columns(),
            timeseries_columns=_minimal_timeseries_columns(),
        )
        assert len(schema.request_columns) == 1
        assert len(schema.timeseries_columns) == 2

    def test_empty_request_columns_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one request column"):
            MetricsSchema(
                request_columns=(),
                timeseries_columns=_minimal_timeseries_columns(),
            )

    def test_empty_timeseries_columns_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one timeseries column"):
            MetricsSchema(
                request_columns=_minimal_request_columns(),
                timeseries_columns=(),
            )

    def test_duplicate_request_column_names_raises(self) -> None:
        with pytest.raises(ValueError, match="Duplicate request column names"):
            MetricsSchema(
                request_columns=(
                    ColumnDef(name="timestamp_utc", sql_type="TEXT"),
                    ColumnDef(name="timestamp_utc", sql_type="INTEGER"),
                ),
                timeseries_columns=_minimal_timeseries_columns(),
            )

    def test_duplicate_timeseries_column_names_raises(self) -> None:
        with pytest.raises(ValueError, match="Duplicate timeseries column names"):
            MetricsSchema(
                request_columns=_minimal_request_columns(),
                timeseries_columns=(
                    ColumnDef(name="bucket_utc", sql_type="TEXT", nullable=False, primary_key=True),
                    ColumnDef(name="requests_total", sql_type="INTEGER", default="0"),
                    ColumnDef(name="requests_total", sql_type="REAL"),
                ),
            )

    def test_index_referencing_nonexistent_column_raises(self) -> None:
        with pytest.raises(ValueError, match=r"references column 'missing'.*does not exist"):
            MetricsSchema(
                request_columns=_minimal_request_columns(),
                timeseries_columns=_minimal_timeseries_columns(),
                request_indexes=(("idx_missing", "missing"),),
            )

    def test_valid_index_referencing_existing_column(self) -> None:
        schema = MetricsSchema(
            request_columns=_minimal_request_columns(),
            timeseries_columns=_minimal_timeseries_columns(),
            request_indexes=(("idx_timestamp", "timestamp_utc"),),
        )
        assert len(schema.request_indexes) == 1

    def test_invalid_index_name_raises(self) -> None:
        with pytest.raises(ValueError, match="Index name must be a valid SQL identifier"):
            MetricsSchema(
                request_columns=_minimal_request_columns(),
                timeseries_columns=_minimal_timeseries_columns(),
                request_indexes=(("bad;name", "timestamp_utc"),),
            )

    def test_missing_bucket_utc_in_timeseries_raises(self) -> None:
        with pytest.raises(ValueError, match=r"timeseries_columns must include.*bucket_utc"):
            MetricsSchema(
                request_columns=_minimal_request_columns(),
                timeseries_columns=(
                    ColumnDef(name="requests_total", sql_type="INTEGER", default="0"),
                ),
            )

    def test_missing_requests_total_in_timeseries_raises(self) -> None:
        with pytest.raises(ValueError, match=r"timeseries_columns must include.*requests_total"):
            MetricsSchema(
                request_columns=_minimal_request_columns(),
                timeseries_columns=(
                    ColumnDef(name="bucket_utc", sql_type="TEXT", nullable=False, primary_key=True),
                ),
            )

    def test_missing_timestamp_utc_in_request_columns_raises(self) -> None:
        with pytest.raises(ValueError, match="request_columns must include 'timestamp_utc'"):
            MetricsSchema(
                request_columns=(ColumnDef(name="other_col", sql_type="TEXT"),),
                timeseries_columns=_minimal_timeseries_columns(),
            )

    def test_bucket_utc_not_primary_key_raises(self) -> None:
        with pytest.raises(ValueError, match=r"bucket_utc.*must have primary_key=True"):
            MetricsSchema(
                request_columns=_minimal_request_columns(),
                timeseries_columns=(
                    ColumnDef(name="bucket_utc", sql_type="TEXT"),  # nullable=True, primary_key=False
                    ColumnDef(name="requests_total", sql_type="INTEGER", default="0"),
                ),
            )


# =============================================================================
# ServerConfig (Pydantic) validation
# =============================================================================


class TestServerConfigValidation:
    """Tests for ServerConfig Pydantic field validators."""

    def test_valid_defaults(self) -> None:
        config = ServerConfig()
        assert config.host == "127.0.0.1"
        assert config.port == 8000
        assert config.workers == 4

    def test_valid_custom(self) -> None:
        config = ServerConfig(host="0.0.0.0", port=9090, workers=2)
        assert config.port == 9090

    @pytest.mark.parametrize("port", [0, -1, -100])
    def test_port_zero_or_negative_raises(self, port: int) -> None:
        with pytest.raises(ValidationError):
            ServerConfig(port=port)

    def test_port_above_65535_raises(self) -> None:
        with pytest.raises(ValidationError):
            ServerConfig(port=65536)

    def test_port_65535_is_valid(self) -> None:
        config = ServerConfig(port=65535)
        assert config.port == 65535

    def test_port_1_is_valid(self) -> None:
        config = ServerConfig(port=1)
        assert config.port == 1

    @pytest.mark.parametrize("workers", [0, -1, -10])
    def test_workers_zero_or_negative_raises(self, workers: int) -> None:
        with pytest.raises(ValidationError):
            ServerConfig(workers=workers)

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            ServerConfig(unknown_field="value")  # type: ignore[call-arg]

    def test_frozen_model(self) -> None:
        config = ServerConfig()
        with pytest.raises(ValidationError):
            config.port = 9999  # type: ignore[misc]
