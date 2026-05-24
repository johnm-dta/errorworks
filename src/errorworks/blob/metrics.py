"""Metrics storage and aggregation for ChaosBlob server."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import structlog

from errorworks.engine.metrics_store import MetricsStore
from errorworks.engine.types import ColumnDef, MetricsConfig, MetricsSchema, SqlType

logger = structlog.get_logger(__name__)

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
        ColumnDef("requests_unclassified", SqlType.INTEGER, nullable=False, default="0"),
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
    UNCLASSIFIED = "requests_unclassified"


# Guard against silent drift between the counter enum and the timeseries schema.
# A counter name that lacks a matching column means update_timeseries() will pass
# an unknown keyword to MetricsStore and crash at runtime, *after* the response
# has already gone out. Catching it at import is cheap and unambiguous.
_TIMESERIES_COLUMN_NAMES = frozenset(col.name for col in BLOB_METRICS_SCHEMA.timeseries_columns)
_COUNTER_VALUES = frozenset(c.value for c in BlobOutcomeCounter)
_MISSING_COUNTER_COLUMNS = _COUNTER_VALUES - _TIMESERIES_COLUMN_NAMES
assert not _MISSING_COUNTER_COLUMNS, (
    f"BlobOutcomeCounter values without matching schema columns: {sorted(_MISSING_COUNTER_COLUMNS)}. "
    f"Add the column to BLOB_METRICS_SCHEMA.timeseries_columns or remove the counter."
)


@dataclass(frozen=True, slots=True)
class BlobRequestRecord:
    """A single blob-request row, ready for metrics persistence.

    Replaces the 14-positional-kwarg call into ``BlobMetricsRecorder.record_request``
    that previously let callers wire up incoherent combinations (e.g. a "success"
    outcome with an ``error_type`` set, or an "error_injected" outcome whose
    status_code was 200 *and* whose error_type was ``None`` — invisible in the
    time-series and untraceable from the row). ``__post_init__`` enforces the
    cross-field invariants so an illegal record fails fast at construction
    instead of surfacing as a phantom counter weeks later.
    """

    request_id: str
    timestamp_utc: str
    operation: str
    bucket: str
    outcome: str
    object_key: str | None
    status_code: int | None
    error_type: str | None
    injection_type: str | None
    bytes_in: int | None
    bytes_out: int | None
    etag: str | None
    latency_ms: float | None
    injected_delay_ms: float | None

    def __post_init__(self) -> None:
        # success ⇒ no error_type, status must be 2xx/3xx
        if self.outcome == "success":
            if self.error_type is not None:
                msg = (
                    f"invariant: outcome=success requires error_type=None "
                    f"(got error_type={self.error_type!r}, request_id={self.request_id!r})"
                )
                raise ValueError(msg)
            if self.status_code is not None and not (200 <= self.status_code < 400):
                msg = (
                    f"invariant: outcome=success requires 200 <= status_code < 400 "
                    f"(got status_code={self.status_code}, request_id={self.request_id!r})"
                )
                raise ValueError(msg)
            return
        # error_injected / error_corrupted ⇒ must carry an error_type OR a 4xx/5xx status
        if self.outcome in {"error_injected", "error_corrupted"}:
            has_error_type = self.error_type is not None
            has_error_status = self.status_code is not None and self.status_code >= 400
            if not (has_error_type or has_error_status):
                msg = (
                    f"invariant: outcome={self.outcome} requires error_type or status_code >= 400 "
                    f"(got error_type=None, status_code={self.status_code}, request_id={self.request_id!r})"
                )
                raise ValueError(msg)


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
) -> BlobOutcomeCounter:
    """Classify a blob outcome for time-series aggregation.

    Always returns a counter — fall-through cases are bucketed into
    ``UNCLASSIFIED`` and logged at WARNING so drift is visible immediately
    rather than being silently dropped from the time-series.
    """
    if error_type == "slow_down":
        return BlobOutcomeCounter.SLOW_DOWN
    if error_type in _BLOB_CONNECTION_ERROR_TYPES:
        return BlobOutcomeCounter.CONNECTION_ERROR
    if error_type == "stale_list":
        return BlobOutcomeCounter.STALE_LIST
    if status_code == 404 or error_type in _BLOB_NOT_FOUND_ERROR_TYPES:
        return BlobOutcomeCounter.NOT_FOUND
    if outcome == "error_corrupted" or error_type in _BLOB_CORRUPTION_ERROR_TYPES:
        return BlobOutcomeCounter.CORRUPTED
    if status_code == 403 or error_type == "access_denied":
        return BlobOutcomeCounter.ACCESS_DENIED
    if status_code is not None and 500 <= status_code < 600:
        return BlobOutcomeCounter.SERVER_ERROR
    if outcome == "success":
        return BlobOutcomeCounter.SUCCESS
    # Falling through here means a new outcome/error_type was added upstream but
    # never wired into the classifier. Previously this returned a None counter
    # so the request became invisible (requests_total ticked but no per-class
    # counter did). Route it to a dedicated bucket and warn loudly so the drift
    # is detected the moment it happens instead of in a quarterly metrics review.
    logger.warning(
        "blob_outcome_unclassified",
        outcome=outcome,
        status_code=status_code,
        error_type=error_type,
    )
    return BlobOutcomeCounter.UNCLASSIFIED


class BlobMetricsRecorder:
    """Thread-safe SQLite metrics recorder for ChaosBlob."""

    def __init__(
        self,
        config: MetricsConfig,
        *,
        run_id: str | None = None,
    ) -> None:
        """Initialize the blob metrics recorder."""
        # The config is consumed entirely by MetricsStore; the recorder does not
        # retain it because nothing on the recorder reads it back. Keeping the
        # parameter (symmetry with LLM/Web recorders) avoids churning callers.
        self._store = MetricsStore(config, BLOB_METRICS_SCHEMA, run_id=run_id)

    @property
    def run_id(self) -> str:
        """Get the current run ID."""
        return self._store.run_id

    @property
    def started_utc(self) -> str:
        """Get the run start time in UTC."""
        return self._store.started_utc

    def record_request(self, record: BlobRequestRecord) -> None:
        """Record a single blob request to the metrics database.

        The caller builds an immutable, invariant-checked ``BlobRequestRecord``
        so the recorder never has to defend against incoherent field
        combinations (success-with-error-type, error-with-200-and-no-error-type)
        and the wire-up at every call site is one positional argument instead
        of fourteen primitive kwargs.
        """
        self._store.record(
            request_id=record.request_id,
            timestamp_utc=record.timestamp_utc,
            operation=record.operation,
            bucket=record.bucket,
            object_key=record.object_key,
            outcome=record.outcome,
            status_code=record.status_code,
            error_type=record.error_type,
            injection_type=record.injection_type,
            bytes_in=record.bytes_in,
            bytes_out=record.bytes_out,
            etag=record.etag,
            latency_ms=record.latency_ms,
            injected_delay_ms=record.injected_delay_ms,
        )

        counter = _classify_blob_outcome(record.outcome, record.status_code, record.error_type)
        bucket_utc = self._store.get_bucket_utc(record.timestamp_utc)
        self._store.update_timeseries(
            bucket_utc,
            requests_success=int(counter is BlobOutcomeCounter.SUCCESS),
            requests_slow_down=int(counter is BlobOutcomeCounter.SLOW_DOWN),
            requests_not_found=int(counter is BlobOutcomeCounter.NOT_FOUND),
            requests_access_denied=int(counter is BlobOutcomeCounter.ACCESS_DENIED),
            requests_server_error=int(counter is BlobOutcomeCounter.SERVER_ERROR),
            requests_connection_error=int(counter is BlobOutcomeCounter.CONNECTION_ERROR),
            requests_corrupted=int(counter is BlobOutcomeCounter.CORRUPTED),
            requests_stale_list=int(counter is BlobOutcomeCounter.STALE_LIST),
            requests_unclassified=int(counter is BlobOutcomeCounter.UNCLASSIFIED),
        )
        self._store.update_bucket_latency(bucket_utc, record.latency_ms)
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
