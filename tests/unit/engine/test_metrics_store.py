"""Unit tests for the MetricsStore composable utility.

Tests schema-driven DDL generation, record/query operations,
time-series bucketing, stats computation, and lifecycle management.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from errorworks.engine.metrics_store import MetricsStore, _column_ddl, _generate_ddl, _get_bucket_utc
from errorworks.engine.types import ColumnDef, MetricsConfig, MetricsSchema, SqlType

# Minimal test schema for MetricsStore unit tests.
_TEST_SCHEMA = MetricsSchema(
    request_columns=(
        ColumnDef("request_id", SqlType.TEXT, nullable=False, primary_key=True),
        ColumnDef("timestamp_utc", SqlType.TEXT, nullable=False),
        ColumnDef("outcome", SqlType.TEXT, nullable=False),
        ColumnDef("status_code", SqlType.INTEGER),
        ColumnDef("latency_ms", SqlType.REAL),
    ),
    timeseries_columns=(
        ColumnDef("bucket_utc", SqlType.TEXT, nullable=False, primary_key=True),
        ColumnDef("requests_total", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_success", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_error", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("avg_latency_ms", SqlType.REAL),
        ColumnDef("p99_latency_ms", SqlType.REAL),
    ),
    request_indexes=(
        ("idx_req_ts", "timestamp_utc"),
        ("idx_req_outcome", "outcome"),
    ),
)


# =============================================================================
# ColumnDef Validation
# =============================================================================


class TestColumnDefValidation:
    """Tests for ColumnDef default value validation (SQL injection prevention)."""

    def test_valid_numeric_default(self) -> None:
        """Numeric defaults are accepted."""
        col = ColumnDef("count", SqlType.INTEGER, default="0")
        assert col.default == "0"

    def test_valid_null_default(self) -> None:
        """NULL default is accepted."""
        col = ColumnDef("value", SqlType.TEXT, default="NULL")
        assert col.default == "NULL"

    def test_valid_quoted_string_default(self) -> None:
        """Single-quoted string default is accepted."""
        col = ColumnDef("status", SqlType.TEXT, default="'active'")
        assert col.default == "'active'"

    def test_valid_negative_numeric_default(self) -> None:
        """Negative numeric default is accepted."""
        col = ColumnDef("offset_val", SqlType.INTEGER, default="-1")
        assert col.default == "-1"

    def test_valid_float_default(self) -> None:
        """Float default is accepted."""
        col = ColumnDef("ratio", SqlType.REAL, default="0.5")
        assert col.default == "0.5"

    def test_no_default_is_fine(self) -> None:
        """None default is accepted (no DEFAULT clause)."""
        col = ColumnDef("name", SqlType.TEXT, default=None)
        assert col.default is None

    def test_sql_injection_in_default_raises(self) -> None:
        """SQL injection attempt in default is rejected."""
        with pytest.raises(ValueError, match="default must be"):
            ColumnDef("x", SqlType.TEXT, default="0; DROP TABLE requests")

    def test_subquery_in_default_raises(self) -> None:
        """Subquery in default is rejected."""
        with pytest.raises(ValueError, match="default must be"):
            ColumnDef("x", SqlType.TEXT, default="(SELECT 1)")

    def test_function_call_in_default_raises(self) -> None:
        """Function call in default is rejected."""
        with pytest.raises(ValueError, match="default must be"):
            ColumnDef("x", SqlType.TEXT, default="CURRENT_TIMESTAMP")

    def test_unquoted_string_in_default_raises(self) -> None:
        """Unquoted string in default is rejected."""
        with pytest.raises(ValueError, match="default must be"):
            ColumnDef("x", SqlType.TEXT, default="active")


# =============================================================================
# DDL Generation
# =============================================================================


class TestDDLGeneration:
    """Tests for _generate_ddl function."""

    def test_generates_requests_table(self) -> None:
        """DDL includes CREATE TABLE for requests."""
        ddl = _generate_ddl(_TEST_SCHEMA)
        assert "CREATE TABLE IF NOT EXISTS requests" in ddl
        assert "request_id TEXT PRIMARY KEY" in ddl
        assert "timestamp_utc TEXT NOT NULL" in ddl
        assert "status_code INTEGER" in ddl

    def test_generates_timeseries_table(self) -> None:
        """DDL includes CREATE TABLE for timeseries."""
        ddl = _generate_ddl(_TEST_SCHEMA)
        assert "CREATE TABLE IF NOT EXISTS timeseries" in ddl
        assert "bucket_utc TEXT PRIMARY KEY" in ddl
        assert "requests_total INTEGER NOT NULL" in ddl

    def test_generates_run_info_table(self) -> None:
        """DDL always includes run_info table."""
        ddl = _generate_ddl(_TEST_SCHEMA)
        assert "CREATE TABLE IF NOT EXISTS run_info" in ddl

    def test_generates_indexes(self) -> None:
        """DDL includes CREATE INDEX for each request_indexes entry."""
        ddl = _generate_ddl(_TEST_SCHEMA)
        assert "CREATE INDEX IF NOT EXISTS idx_req_ts ON requests(timestamp_utc)" in ddl
        assert "CREATE INDEX IF NOT EXISTS idx_req_outcome ON requests(outcome)" in ddl

    def test_default_values_in_ddl(self) -> None:
        """Columns with defaults include DEFAULT clause."""
        ddl = _generate_ddl(_TEST_SCHEMA)
        assert "DEFAULT 0" in ddl

    def test_no_indexes_when_empty(self) -> None:
        """Schema with no indexes generates no CREATE INDEX."""
        schema = MetricsSchema(
            request_columns=(
                ColumnDef("id", SqlType.TEXT, nullable=False, primary_key=True),
                ColumnDef("timestamp_utc", SqlType.TEXT, nullable=False),
            ),
            timeseries_columns=(
                ColumnDef("bucket_utc", SqlType.TEXT, nullable=False, primary_key=True),
                ColumnDef("requests_total", SqlType.INTEGER, nullable=False, default="0"),
            ),
        )
        ddl = _generate_ddl(schema)
        assert "CREATE INDEX" not in ddl

    def test_primary_key_text_column_emits_not_null(self) -> None:
        """TEXT PRIMARY KEY columns must emit NOT NULL for SQLite correctness."""
        col = ColumnDef(name="id", sql_type=SqlType.TEXT, nullable=False, primary_key=True)
        ddl = _column_ddl(col)
        assert "PRIMARY KEY" in ddl
        assert "NOT NULL" in ddl


# =============================================================================
# Bucket Calculation
# =============================================================================


class TestGetBucketUtc:
    """Tests for _get_bucket_utc helper."""

    def test_truncates_to_second(self) -> None:
        """Bucket truncates microseconds with 1-second bucket."""
        bucket = _get_bucket_utc("2024-01-15T10:30:45.123456+00:00", 1)
        assert bucket == "2024-01-15T10:30:45+00:00"

    def test_truncates_to_10_seconds(self) -> None:
        """10-second bucket rounds down."""
        bucket = _get_bucket_utc("2024-01-15T10:30:47+00:00", 10)
        assert bucket == "2024-01-15T10:30:40+00:00"

    def test_truncates_to_minute(self) -> None:
        """60-second bucket truncates to minute boundary."""
        bucket = _get_bucket_utc("2024-01-15T10:30:45+00:00", 60)
        assert bucket == "2024-01-15T10:30:00+00:00"

    def test_handles_z_suffix(self) -> None:
        """Handles 'Z' timezone suffix."""
        bucket = _get_bucket_utc("2024-01-15T10:30:45Z", 1)
        assert bucket == "2024-01-15T10:30:45+00:00"

    def test_idempotent(self) -> None:
        """Bucketing an already-bucketed timestamp returns the same value."""
        ts = "2024-01-15T10:30:00+00:00"
        bucket1 = _get_bucket_utc(ts, 60)
        bucket2 = _get_bucket_utc(bucket1, 60)
        assert bucket1 == bucket2

    def test_invalid_timestamp_raises_with_context(self) -> None:
        """Malformed timestamp raises ValueError with the offending value."""
        with pytest.raises(ValueError, match="Invalid timestamp for bucket calculation"):
            _get_bucket_utc("not-a-timestamp", 60)

    def test_empty_timestamp_raises_with_context(self) -> None:
        """Empty string raises ValueError with context."""
        with pytest.raises(ValueError, match="Invalid timestamp for bucket calculation"):
            _get_bucket_utc("", 60)


# =============================================================================
# MetricsStore Record & Query
# =============================================================================


@pytest.fixture()
def store() -> MetricsStore:
    """Create an in-memory MetricsStore for testing."""
    config = MetricsConfig(database=":memory:")
    return MetricsStore(config, _TEST_SCHEMA, run_id="test-run-001")


class TestRecord:
    """Tests for recording requests."""

    def test_record_inserts_row(self, store: MetricsStore) -> None:
        """record() inserts a row into the requests table."""
        store.record(
            request_id="req-1",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            outcome="success",
            status_code=200,
            latency_ms=50.0,
        )
        store.commit()
        rows = store.get_requests()
        assert len(rows) == 1
        assert rows[0]["request_id"] == "req-1"
        assert rows[0]["outcome"] == "success"

    def test_record_with_null_fields(self, store: MetricsStore) -> None:
        """record() handles None/null optional fields."""
        store.record(
            request_id="req-2",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            outcome="success",
        )
        store.commit()
        rows = store.get_requests()
        assert len(rows) == 1
        assert rows[0]["status_code"] is None
        assert rows[0]["latency_ms"] is None


class TestUpdateTimeseries:
    """Tests for timeseries upsert."""

    def test_first_update_creates_bucket(self, store: MetricsStore) -> None:
        """First update creates a new bucket with total=1."""
        store.update_timeseries(
            "2024-01-15T10:30:00+00:00",
            requests_success=1,
        )
        store.commit()
        rows = store.get_timeseries()
        assert len(rows) == 1
        assert rows[0]["requests_total"] == 1
        assert rows[0]["requests_success"] == 1

    def test_second_update_increments(self, store: MetricsStore) -> None:
        """Second update to same bucket increments counters."""
        bucket = "2024-01-15T10:30:00+00:00"
        store.update_timeseries(bucket, requests_success=1)
        store.update_timeseries(bucket, requests_error=1)
        store.commit()
        rows = store.get_timeseries()
        assert len(rows) == 1
        assert rows[0]["requests_total"] == 2
        assert rows[0]["requests_success"] == 1
        assert rows[0]["requests_error"] == 1

    def test_rejects_reserved_columns_as_counters(self, store: MetricsStore) -> None:
        """update_timeseries raises ValueError for reserved column names."""
        with pytest.raises(ValueError, match="Reserved timeseries columns"):
            store.update_timeseries("2024-01-15T10:00:00+00:00", requests_total=1)

        # bucket_utc cannot reach **counters via normal call syntax (Python binds
        # it to the positional parameter), but the guard still protects against
        # programmatic dict-unpacking when the positional arg is omitted.
        with pytest.raises(ValueError, match="Reserved timeseries columns"):
            store.update_timeseries(bucket_utc="2024-01-15T10:00:00+00:00", requests_total=1)


class TestBucketLatency:
    """Tests for latency statistics recalculation."""

    def test_update_bucket_latency_calculates_avg(self, store: MetricsStore) -> None:
        """update_bucket_latency computes avg and p99."""
        ts = "2024-01-15T10:30:00+00:00"
        for i in range(10):
            store.record(
                request_id=f"req-{i}",
                timestamp_utc=ts,
                outcome="success",
                latency_ms=float(i * 10),  # 0, 10, 20, ... 90
            )
        bucket = store.get_bucket_utc(ts)
        store.update_timeseries(bucket, requests_success=1)
        store.update_bucket_latency(bucket, 50.0)
        store.commit()
        rows = store.get_timeseries()
        assert len(rows) == 1
        assert rows[0]["avg_latency_ms"] is not None

    def test_update_bucket_latency_none_is_noop(self, store: MetricsStore) -> None:
        """update_bucket_latency with None latency does nothing."""
        store.update_bucket_latency("2024-01-15T10:30:00+00:00", None)
        # No crash, no data


# =============================================================================
# Stats
# =============================================================================


class TestGetStats:
    """Tests for summary statistics."""

    def test_empty_stats(self, store: MetricsStore) -> None:
        """Stats from empty database."""
        stats = store.get_stats()
        assert stats["run_id"] == "test-run-001"
        assert stats["total_requests"] == 0
        assert stats["error_rate"] == 0.0

    def test_stats_with_data(self, store: MetricsStore) -> None:
        """Stats with mixed outcomes."""
        store.record(
            request_id="s1",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            outcome="success",
            status_code=200,
            latency_ms=50.0,
        )
        store.record(
            request_id="e1",
            timestamp_utc="2024-01-15T10:30:01+00:00",
            outcome="error",
            status_code=500,
            latency_ms=100.0,
        )
        store.commit()
        stats = store.get_stats()
        assert stats["total_requests"] == 2
        assert stats["requests_by_outcome"]["success"] == 1
        assert stats["requests_by_outcome"]["error"] == 1
        assert stats["error_rate"] == 50.0
        assert stats["latency_stats"]["avg_ms"] == 75.0


# =============================================================================
# Export & Reset
# =============================================================================


class TestExportData:
    """Tests for data export."""

    def test_export_empty(self, store: MetricsStore) -> None:
        """Export from empty database."""
        data = store.export_data()
        assert data["run_id"] == "test-run-001"
        assert data["requests"] == []
        assert data["timeseries"] == []

    def test_export_with_data(self, store: MetricsStore) -> None:
        """Export includes recorded requests."""
        store.record(
            request_id="req-1",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            outcome="success",
        )
        store.commit()
        data = store.export_data()
        assert len(data["requests"]) == 1
        assert data["requests"][0]["request_id"] == "req-1"


class TestReset:
    """Tests for reset behavior."""

    def test_reset_clears_data(self, store: MetricsStore) -> None:
        """Reset clears all requests and generates a new run_id."""
        store.record(
            request_id="req-1",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            outcome="success",
        )
        store.commit()
        old_run_id = store.run_id
        store.reset()
        assert store.get_requests() == []
        assert store.run_id != old_run_id

    def test_reset_preserves_config_json(self, store: MetricsStore) -> None:
        """Reset preserves config_json from previous run_info."""
        store.save_run_info('{"test": true}', preset_name="test")
        store.reset()
        # The config was preserved
        conn = store._get_connection()
        cursor = conn.execute("SELECT config_json, preset_name FROM run_info LIMIT 1")
        row = cursor.fetchone()
        assert row is not None
        assert row["config_json"] == '{"test": true}'

    def test_reset_uses_most_recent_run_info(self) -> None:
        """Reset picks the most recent run_info row when multiple exist.

        Regression test: LIMIT 1 without ORDER BY returns a non-deterministic
        row. The fix adds ORDER BY started_utc DESC to ensure the latest config
        is preserved across resets.
        """
        config = MetricsConfig(database=":memory:")
        store = MetricsStore(config, _TEST_SCHEMA, run_id="run-old")
        store.save_run_info('{"version": "old"}', preset_name="old_preset")

        # Simulate a second run by inserting directly
        conn = store._get_connection()
        conn.execute(
            "INSERT INTO run_info (run_id, started_utc, config_json, preset_name) VALUES (?, ?, ?, ?)",
            ("run-new", "2099-01-01T00:00:00+00:00", '{"version": "new"}', "new_preset"),
        )
        conn.commit()

        store.reset()

        # Verify the newest config was preserved
        cursor = conn.execute("SELECT config_json, preset_name FROM run_info")
        row = cursor.fetchone()
        assert row is not None
        assert row["config_json"] == '{"version": "new"}'
        assert row["preset_name"] == "new_preset"


# =============================================================================
# Run Info
# =============================================================================


class TestRunInfo:
    """Tests for run info tracking."""

    def test_run_id_set_by_init(self, store: MetricsStore) -> None:
        """Run ID matches what was provided at init."""
        assert store.run_id == "test-run-001"

    def test_started_utc_set(self, store: MetricsStore) -> None:
        """started_utc is a non-empty ISO string."""
        assert store.started_utc is not None
        assert "T" in store.started_utc

    def test_save_run_info(self, store: MetricsStore) -> None:
        """save_run_info persists to database."""
        store.save_run_info('{"config": "value"}', preset_name="gentle")
        conn = store._get_connection()
        cursor = conn.execute("SELECT * FROM run_info")
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert dict(rows[0])["preset_name"] == "gentle"


# =============================================================================
# Close
# =============================================================================


class TestPercentileAccuracy:
    """Tests for percentile calculation accuracy with small sample sizes."""

    def test_p50_nearest_rank_small_sample(self, store: MetricsStore) -> None:
        """p50 uses nearest-rank formula: ceil(N*0.50)-1, not int(N*0.50).

        With 10 sorted values [1..10], p50 should be index 4 = 5.0.
        The old int(10*0.50)=5 gives index 5 = 6.0 (wrong).
        """
        for i in range(10):
            store.record(
                request_id=f"p-{i}",
                timestamp_utc=f"2024-01-15T10:30:{i:02d}+00:00",
                outcome="success",
                status_code=200,
                latency_ms=float(i + 1),  # 1.0, 2.0, ..., 10.0
            )
        store.commit()

        stats = store.get_stats()
        latency = stats["latency_stats"]
        assert latency["p50_ms"] == 5.0, f"p50 should be 5.0 (index 4), got {latency['p50_ms']}"
        assert latency["p95_ms"] == 10.0, f"p95 should be 10.0 (index 9), got {latency['p95_ms']}"
        assert latency["p99_ms"] == 10.0, f"p99 should be 10.0 (index 9), got {latency['p99_ms']}"

    def test_p50_single_value(self, store: MetricsStore) -> None:
        """Single value: all percentiles should return that value."""
        store.record(
            request_id="solo",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            outcome="success",
            latency_ms=42.0,
        )
        store.commit()

        stats = store.get_stats()
        latency = stats["latency_stats"]
        assert latency["p50_ms"] == 42.0
        assert latency["p95_ms"] == 42.0
        assert latency["p99_ms"] == 42.0

    def test_p50_two_values(self, store: MetricsStore) -> None:
        """Two values [1.0, 2.0]: p50=ceil(2*0.50)-1=0 -> 1.0."""
        for i in range(2):
            store.record(
                request_id=f"p-{i}",
                timestamp_utc=f"2024-01-15T10:30:0{i}+00:00",
                outcome="success",
                latency_ms=float(i + 1),
            )
        store.commit()

        stats = store.get_stats()
        latency = stats["latency_stats"]
        assert latency["p50_ms"] == 1.0


class TestClose:
    """Tests for connection cleanup."""

    def test_close_clears_connections(self) -> None:
        """close() empties the connection list."""
        config = MetricsConfig(database=":memory:")
        store = MetricsStore(config, _TEST_SCHEMA)
        # Ensure at least one connection
        store._get_connection()
        assert len(store._connections) > 0
        store.close()
        assert len(store._connections) == 0


# =============================================================================
# Pagination
# =============================================================================


class TestPagination:
    """Tests for request/timeseries pagination."""

    def test_get_requests_limit(self, store: MetricsStore) -> None:
        """get_requests respects limit parameter."""
        for i in range(5):
            store.record(
                request_id=f"req-{i}",
                timestamp_utc=f"2024-01-15T10:30:0{i}+00:00",
                outcome="success",
            )
        store.commit()
        rows = store.get_requests(limit=3)
        assert len(rows) == 3

    def test_get_requests_by_outcome(self, store: MetricsStore) -> None:
        """get_requests filters by outcome."""
        store.record(request_id="s1", timestamp_utc="2024-01-15T10:30:00+00:00", outcome="success")
        store.record(request_id="e1", timestamp_utc="2024-01-15T10:30:01+00:00", outcome="error")
        store.commit()
        rows = store.get_requests(outcome="success")
        assert len(rows) == 1
        assert rows[0]["outcome"] == "success"

    def test_get_requests_outcome_filter_without_outcome_column(self) -> None:
        """get_requests raises ValueError when filtering by outcome on a schema without that column."""
        schema_no_outcome = MetricsSchema(
            request_columns=(
                ColumnDef("request_id", SqlType.TEXT, nullable=False, primary_key=True),
                ColumnDef("timestamp_utc", SqlType.TEXT, nullable=False),
            ),
            timeseries_columns=(
                ColumnDef("bucket_utc", SqlType.TEXT, nullable=False, primary_key=True),
                ColumnDef("requests_total", SqlType.INTEGER, nullable=False, default="0"),
            ),
        )
        config = MetricsConfig(database=":memory:")
        store = MetricsStore(config, schema_no_outcome)
        with pytest.raises(ValueError, match="outcome"):
            store.get_requests(outcome="success")
        store.close()

    def test_get_timeseries_limit(self, store: MetricsStore) -> None:
        """get_timeseries respects limit parameter."""
        for i in range(5):
            store.update_timeseries(f"2024-01-15T10:3{i}:00+00:00", requests_success=1)
        store.commit()
        rows = store.get_timeseries(limit=3)
        assert len(rows) == 3


# =============================================================================
# Rebuild Timeseries
# =============================================================================


class TestRebuildTimeseries:
    """Tests for rebuild_timeseries method."""

    def _classify(self, row):
        """Simple classifier for testing: maps outcome to counter columns."""
        outcome = row["outcome"]
        latency = row["latency_ms"]
        return {
            "requests_success": 1 if outcome == "success" else 0,
            "requests_error": 1 if outcome == "error" else 0,
            "latency_ms": latency,
        }

    def test_rebuilds_from_requests(self) -> None:
        """rebuild_timeseries creates timeseries rows from request data."""
        config = MetricsConfig(database=":memory:", timeseries_bucket_sec=60)
        s = MetricsStore(config, _TEST_SCHEMA, run_id="test-rebuild")

        s.record(request_id="r1", timestamp_utc="2024-01-15T10:30:05+00:00", outcome="success", latency_ms=50.0)
        s.record(request_id="r2", timestamp_utc="2024-01-15T10:30:15+00:00", outcome="success", latency_ms=100.0)
        s.record(request_id="r3", timestamp_utc="2024-01-15T10:30:25+00:00", outcome="error", latency_ms=200.0)
        s.commit()

        s.rebuild_timeseries(self._classify)

        rows = s.get_timeseries()
        assert len(rows) == 1  # All within same 60-second bucket
        row = rows[0]
        assert row["requests_total"] == 3
        assert row["requests_success"] == 2
        assert row["requests_error"] == 1

    def test_rebuild_computes_latency_stats(self) -> None:
        """rebuild_timeseries computes avg and p99 latency."""
        config = MetricsConfig(database=":memory:", timeseries_bucket_sec=60)
        s = MetricsStore(config, _TEST_SCHEMA, run_id="test-latency")

        for i in range(10):
            s.record(
                request_id=f"r{i}",
                timestamp_utc=f"2024-01-15T10:30:{i:02d}+00:00",
                outcome="success",
                latency_ms=float(10 * (i + 1)),  # 10, 20, ..., 100
            )
        s.commit()

        s.rebuild_timeseries(self._classify)

        rows = s.get_timeseries()
        assert len(rows) == 1
        row = rows[0]
        assert row["avg_latency_ms"] == pytest.approx(55.0)  # mean of 10..100
        assert row["p99_latency_ms"] == 100.0  # p99 of 10 values = max

    def test_rebuild_clears_old_timeseries(self, store: MetricsStore) -> None:
        """rebuild_timeseries removes existing timeseries data before rebuilding."""
        store.update_timeseries("2024-01-15T10:30:00+00:00", requests_success=999)
        store.commit()

        store.record(request_id="r1", timestamp_utc="2024-01-15T10:30:05+00:00", outcome="success", latency_ms=50.0)
        store.commit()

        store.rebuild_timeseries(self._classify)

        rows = store.get_timeseries()
        assert len(rows) == 1
        assert rows[0]["requests_total"] == 1  # Not 999

    def test_rebuild_multiple_buckets(self) -> None:
        """rebuild_timeseries creates separate rows for different time buckets."""
        config = MetricsConfig(database=":memory:", timeseries_bucket_sec=10)
        s = MetricsStore(config, _TEST_SCHEMA, run_id="test-run-002")

        # Two requests in different 10-second buckets
        s.record(request_id="r1", timestamp_utc="2024-01-15T10:30:05+00:00", outcome="success", latency_ms=50.0)
        s.record(request_id="r2", timestamp_utc="2024-01-15T10:30:15+00:00", outcome="error", latency_ms=100.0)
        s.commit()

        s.rebuild_timeseries(self._classify)

        rows = s.get_timeseries()
        assert len(rows) == 2

    def test_rebuild_single_request(self, store: MetricsStore) -> None:
        """rebuild_timeseries handles single request correctly."""
        store.record(request_id="r1", timestamp_utc="2024-01-15T10:30:05+00:00", outcome="success", latency_ms=42.0)
        store.commit()

        store.rebuild_timeseries(self._classify)

        rows = store.get_timeseries()
        assert len(rows) == 1
        assert rows[0]["requests_total"] == 1
        assert rows[0]["avg_latency_ms"] == pytest.approx(42.0)
        assert rows[0]["p99_latency_ms"] == pytest.approx(42.0)

    def test_rebuild_aggregates_float_values(self, store: MetricsStore) -> None:
        """rebuild_timeseries correctly sums float counter values from classify().

        Regression test: the classify() return type allows int | float | None,
        but aggregation previously only summed isinstance(value, int), silently
        dropping float values.
        """

        def classify_with_floats(row):
            return {
                "requests_success": 0.5,  # float counter
                "requests_error": 0.5,
                "latency_ms": row["latency_ms"],
            }

        store.record(request_id="r1", timestamp_utc="2024-01-15T10:30:05+00:00", outcome="success", latency_ms=50.0)
        store.record(request_id="r2", timestamp_utc="2024-01-15T10:30:05.500+00:00", outcome="error", latency_ms=100.0)
        store.commit()

        store.rebuild_timeseries(classify_with_floats)

        rows = store.get_timeseries()
        assert len(rows) == 1
        assert rows[0]["requests_total"] == 2
        assert rows[0]["requests_success"] == pytest.approx(1.0)  # 0.5 + 0.5
        assert rows[0]["requests_error"] == pytest.approx(1.0)  # 0.5 + 0.5

    def test_rebuild_no_latency(self, store: MetricsStore) -> None:
        """rebuild_timeseries handles requests with no latency."""

        def classify_no_latency(row):
            return {"requests_success": 1, "requests_error": 0, "latency_ms": None}

        store.record(request_id="r1", timestamp_utc="2024-01-15T10:30:05+00:00", outcome="success")
        store.commit()

        store.rebuild_timeseries(classify_no_latency)

        rows = store.get_timeseries()
        assert len(rows) == 1
        assert rows[0]["requests_total"] == 1
        assert rows[0]["avg_latency_ms"] is None

    def test_rebuild_does_not_mutate_classify_dict(self) -> None:
        """rebuild_timeseries must not mutate the dict returned by classify."""
        config = MetricsConfig(database=":memory:", timeseries_bucket_sec=60)
        s = MetricsStore(config, _TEST_SCHEMA, run_id="test-no-mutate")

        s.record(request_id="r1", timestamp_utc="2024-01-15T10:30:05+00:00", outcome="success", latency_ms=50.0)
        s.commit()

        # classify returns a cached dict; rebuild must not pop keys from it
        cached: dict[str, object] = {"requests_success": 1, "requests_error": 0, "latency_ms": 50.0}

        def classify_cached(row: Any) -> dict[str, object]:
            return cached

        s.rebuild_timeseries(classify_cached)

        assert "latency_ms" in cached, "rebuild_timeseries mutated the classify callback's returned dict"


# =============================================================================
# Thread Safety
# =============================================================================


class TestThreadSafety:
    """Tests for MetricsStore thread-safe operation."""

    def test_concurrent_record_and_commit(self, tmp_path) -> None:
        """Multiple threads can record and commit concurrently without data loss."""
        # Use a file-backed DB (WAL mode) since :memory: is per-connection
        config = MetricsConfig(database=str(tmp_path / "thread_test.db"))
        store = MetricsStore(config, _TEST_SCHEMA, run_id="thread-test")

        n_threads = 8
        n_records_per_thread = 50
        errors: list[Exception] = []
        lock = threading.Lock()

        def worker(thread_id: int) -> None:
            try:
                for i in range(n_records_per_thread):
                    store.record(
                        request_id=f"t{thread_id}-r{i}",
                        timestamp_utc="2024-01-15T10:30:00+00:00",
                        outcome="success",
                        status_code=200,
                        latency_ms=float(i),
                    )
                store.commit()
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"

        rows = store.get_requests(limit=n_threads * n_records_per_thread + 1)
        assert len(rows) == n_threads * n_records_per_thread
        store.close()

    def test_concurrent_read_during_write(self, tmp_path) -> None:
        """get_stats() can be called while other threads are writing."""
        config = MetricsConfig(database=str(tmp_path / "rw_test.db"))
        store = MetricsStore(config, _TEST_SCHEMA, run_id="rw-test")

        errors: list[Exception] = []
        lock = threading.Lock()

        def writer() -> None:
            try:
                for i in range(100):
                    store.record(
                        request_id=f"w-{i}",
                        timestamp_utc="2024-01-15T10:30:00+00:00",
                        outcome="success",
                    )
                store.commit()
            except Exception as exc:
                with lock:
                    errors.append(exc)

        def reader() -> None:
            try:
                for _ in range(20):
                    stats = store.get_stats()
                    assert "total_requests" in stats
            except Exception as exc:
                with lock:
                    errors.append(exc)

        writer_thread = threading.Thread(target=writer)
        reader_threads = [threading.Thread(target=reader) for _ in range(4)]

        writer_thread.start()
        for t in reader_threads:
            t.start()

        writer_thread.join()
        for t in reader_threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"
        store.close()

    def test_close_during_idle(self, tmp_path) -> None:
        """close() from main thread after worker threads finish."""
        config = MetricsConfig(database=str(tmp_path / "close_test.db"))
        store = MetricsStore(config, _TEST_SCHEMA, run_id="close-test")

        def worker() -> None:
            store.record(
                request_id=f"t{threading.get_ident()}",
                timestamp_utc="2024-01-15T10:30:00+00:00",
                outcome="success",
            )
            store.commit()

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All worker threads are dead; close should clean up their connections
        store.close()
        assert len(store._connections) == 0
