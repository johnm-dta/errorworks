"""Metrics storage and aggregation for ChaosBlob server."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from errorworks.engine.metrics_store import MetricsStore
from errorworks.engine.types import ColumnDef, MetricsConfig, MetricsSchema, SqlType

BLOB_METRICS_SCHEMA = MetricsSchema(
    request_columns=(
        ColumnDef("request_id", SqlType.TEXT, nullable=False, primary_key=True),
        ColumnDef("timestamp_utc", SqlType.TEXT, nullable=False),
        ColumnDef("operation", SqlType.TEXT, nullable=False),
        ColumnDef("bucket", SqlType.TEXT, nullable=False),
        ColumnDef("object_key", SqlType.TEXT),
        ColumnDef("outcome", SqlType.TEXT, nullable=False),
        ColumnDef("status_code", SqlType.INTEGER),
        ColumnDef("error_type", SqlType.TEXT),
        ColumnDef("injection_type", SqlType.TEXT),
        ColumnDef("bytes_in", SqlType.INTEGER),
        ColumnDef("bytes_out", SqlType.INTEGER),
        ColumnDef("etag", SqlType.TEXT),
        ColumnDef("latency_ms", SqlType.REAL),
        ColumnDef("injected_delay_ms", SqlType.REAL),
    ),
    timeseries_columns=(
        ColumnDef("bucket_utc", SqlType.TEXT, nullable=False, primary_key=True),
        ColumnDef("requests_total", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_success", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_slow_down", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_not_found", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_access_denied", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_server_error", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_connection_error", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_corrupted", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_stale_list", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("avg_latency_ms", SqlType.REAL),
        ColumnDef("p99_latency_ms", SqlType.REAL),
    ),
    request_indexes=(
        ("idx_requests_timestamp", "timestamp_utc"),
        ("idx_requests_operation", "operation"),
        ("idx_requests_bucket_key", "bucket", "object_key"),
        ("idx_requests_outcome", "outcome"),
    ),
)


class BlobOutcomeCounter(StrEnum):
    """Mutually-exclusive blob request counter names."""

    SUCCESS = "requests_success"
    SLOW_DOWN = "requests_slow_down"
    NOT_FOUND = "requests_not_found"
    ACCESS_DENIED = "requests_access_denied"
    SERVER_ERROR = "requests_server_error"
    CONNECTION_ERROR = "requests_connection_error"
    CORRUPTED = "requests_corrupted"
    STALE_LIST = "requests_stale_list"


@dataclass(frozen=True, slots=True)
class BlobOutcomeClassification:
    """Classification of a blob request outcome for time-series aggregation."""

    counter: BlobOutcomeCounter | None


_BLOB_CONNECTION_ERROR_TYPES = frozenset({"timeout", "connection_reset", "connection_stall"})
_BLOB_CORRUPTION_ERROR_TYPES = frozenset(
    {
        "truncated_body",
        "wrong_content_length",
        "checksum_mismatch",
        "metadata_corruption",
        "malformed_xml",
    }
)
_BLOB_NOT_FOUND_ERROR_TYPES = frozenset({"not_found", "NoSuchKey"})


def _classify_blob_outcome(
    outcome: str,
    status_code: int | None,
    error_type: str | None,
) -> BlobOutcomeClassification:
    """Classify a blob outcome for time-series aggregation."""
    if error_type == "slow_down":
        return BlobOutcomeClassification(BlobOutcomeCounter.SLOW_DOWN)
    if error_type in _BLOB_CONNECTION_ERROR_TYPES:
        return BlobOutcomeClassification(BlobOutcomeCounter.CONNECTION_ERROR)
    if error_type == "stale_list":
        return BlobOutcomeClassification(BlobOutcomeCounter.STALE_LIST)
    if status_code == 404 or error_type in _BLOB_NOT_FOUND_ERROR_TYPES:
        return BlobOutcomeClassification(BlobOutcomeCounter.NOT_FOUND)
    if outcome == "error_corrupted" or error_type in _BLOB_CORRUPTION_ERROR_TYPES:
        return BlobOutcomeClassification(BlobOutcomeCounter.CORRUPTED)
    if status_code == 403 or error_type == "access_denied":
        return BlobOutcomeClassification(BlobOutcomeCounter.ACCESS_DENIED)
    if status_code is not None and 500 <= status_code < 600:
        return BlobOutcomeClassification(BlobOutcomeCounter.SERVER_ERROR)
    if outcome == "success":
        return BlobOutcomeClassification(BlobOutcomeCounter.SUCCESS)
    return BlobOutcomeClassification(None)


class BlobMetricsRecorder:
    """Thread-safe SQLite metrics recorder for ChaosBlob."""

    def __init__(
        self,
        config: MetricsConfig,
        *,
        run_id: str | None = None,
    ) -> None:
        """Initialize the blob metrics recorder."""
        self._config = config
        self._store = MetricsStore(config, BLOB_METRICS_SCHEMA, run_id=run_id)

    @property
    def run_id(self) -> str:
        """Get the current run ID."""
        return self._store.run_id

    @property
    def started_utc(self) -> str:
        """Get the run start time in UTC."""
        return self._store.started_utc

    def record_request(
        self,
        *,
        request_id: str,
        timestamp_utc: str,
        operation: str,
        bucket: str,
        outcome: str,
        object_key: str | None = None,
        status_code: int | None = None,
        error_type: str | None = None,
        injection_type: str | None = None,
        bytes_in: int | None = None,
        bytes_out: int | None = None,
        etag: str | None = None,
        latency_ms: float | None = None,
        injected_delay_ms: float | None = None,
    ) -> None:
        """Record a single blob request to the metrics database."""
        self._store.record(
            request_id=request_id,
            timestamp_utc=timestamp_utc,
            operation=operation,
            bucket=bucket,
            object_key=object_key,
            outcome=outcome,
            status_code=status_code,
            error_type=error_type,
            injection_type=injection_type,
            bytes_in=bytes_in,
            bytes_out=bytes_out,
            etag=etag,
            latency_ms=latency_ms,
            injected_delay_ms=injected_delay_ms,
        )

        cls = _classify_blob_outcome(outcome, status_code, error_type)
        bucket_utc = self._store.get_bucket_utc(timestamp_utc)
        self._store.update_timeseries(
            bucket_utc,
            requests_success=int(cls.counter is BlobOutcomeCounter.SUCCESS),
            requests_slow_down=int(cls.counter is BlobOutcomeCounter.SLOW_DOWN),
            requests_not_found=int(cls.counter is BlobOutcomeCounter.NOT_FOUND),
            requests_access_denied=int(cls.counter is BlobOutcomeCounter.ACCESS_DENIED),
            requests_server_error=int(cls.counter is BlobOutcomeCounter.SERVER_ERROR),
            requests_connection_error=int(cls.counter is BlobOutcomeCounter.CONNECTION_ERROR),
            requests_corrupted=int(cls.counter is BlobOutcomeCounter.CORRUPTED),
            requests_stale_list=int(cls.counter is BlobOutcomeCounter.STALE_LIST),
        )
        self._store.update_bucket_latency(bucket_utc, latency_ms)
        self._store.commit()

    def get_stats(self) -> dict[str, Any]:
        """Get summary statistics for the current run."""
        stats = self._store.get_stats()
        stats["timeseries"] = self._store.get_timeseries()
        return stats

    def export_data(self, *, limit: int | None = None, offset: int = 0) -> dict[str, Any]:
        """Export raw requests and time-series data."""
        return self._store.export_data(limit=limit, offset=offset)

    def reset(
        self,
        *,
        config_json: str | None = None,
        preset_name: str | None = None,
    ) -> None:
        """Reset all metrics tables and start a new run."""
        self._store.reset(config_json=config_json, preset_name=preset_name)

    def save_run_info(
        self,
        config_json: str,
        preset_name: str | None = None,
    ) -> None:
        """Save run information to the database."""
        self._store.save_run_info(config_json, preset_name)

    def get_requests(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        outcome: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get request records from the database."""
        return self._store.get_requests(limit=limit, offset=offset, outcome=outcome)

    def get_timeseries(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Get time-series records from the database."""
        return self._store.get_timeseries(limit=limit, offset=offset)

    def close(self) -> None:
        """Close all database connections across all threads."""
        self._store.close()
