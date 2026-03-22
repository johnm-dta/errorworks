"""Metrics storage and aggregation for ChaosLLM server.

The MetricsRecorder provides typed wrappers around the shared MetricsStore
for LLM-specific request recording and outcome classification.
"""

import sqlite3
from typing import Any, NamedTuple

from errorworks.engine.metrics_store import MetricsStore
from errorworks.engine.types import ColumnDef, MetricsConfig, MetricsSchema, SqlType

# Schema definition for LLM metrics tables.
LLM_METRICS_SCHEMA = MetricsSchema(
    request_columns=(
        ColumnDef("request_id", SqlType.TEXT, nullable=False, primary_key=True),
        ColumnDef("timestamp_utc", SqlType.TEXT, nullable=False),
        ColumnDef("endpoint", SqlType.TEXT, nullable=False),
        ColumnDef("deployment", SqlType.TEXT),
        ColumnDef("model", SqlType.TEXT),
        ColumnDef("outcome", SqlType.TEXT, nullable=False),
        ColumnDef("status_code", SqlType.INTEGER),
        ColumnDef("error_type", SqlType.TEXT),
        ColumnDef("injection_type", SqlType.TEXT),
        ColumnDef("latency_ms", SqlType.REAL),
        ColumnDef("injected_delay_ms", SqlType.REAL),
        ColumnDef("message_count", SqlType.INTEGER),
        ColumnDef("prompt_tokens_approx", SqlType.INTEGER),
        ColumnDef("response_tokens", SqlType.INTEGER),
        ColumnDef("response_mode", SqlType.TEXT),
    ),
    timeseries_columns=(
        ColumnDef("bucket_utc", SqlType.TEXT, nullable=False, primary_key=True),
        ColumnDef("requests_total", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_success", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_rate_limited", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_capacity_error", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_server_error", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_client_error", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_connection_error", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_malformed", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("avg_latency_ms", SqlType.REAL),
        ColumnDef("p99_latency_ms", SqlType.REAL),
    ),
    request_indexes=(
        ("idx_requests_timestamp", "timestamp_utc"),
        ("idx_requests_outcome", "outcome"),
        ("idx_requests_endpoint", "endpoint"),
    ),
)


class OutcomeClassification(NamedTuple):
    """Classification of a request outcome for time-series aggregation."""

    is_success: bool
    is_rate_limited: bool
    is_capacity_error: bool
    is_server_error: bool
    is_client_error: bool
    is_connection_error: bool
    is_malformed: bool


_LLM_CONNECTION_ERROR_TYPES = frozenset({
    "timeout",
    "connection_failed",
    "connection_stall",
    "connection_reset",
})


def _classify_outcome(
    outcome: str,
    status_code: int | None,
    error_type: str | None,
) -> OutcomeClassification:
    """Classify an outcome for time-series aggregation."""
    is_connection_error = error_type in _LLM_CONNECTION_ERROR_TYPES
    return OutcomeClassification(
        is_success=outcome == "success",
        is_rate_limited=status_code == 429,
        is_capacity_error=status_code == 529,
        is_server_error=status_code is not None and 500 <= status_code < 600 and status_code != 529 and not is_connection_error,
        is_client_error=status_code is not None and 400 <= status_code < 500 and status_code != 429,
        is_connection_error=is_connection_error,
        is_malformed=outcome == "error_malformed",
    )


def _classify_row(row: sqlite3.Row) -> dict[str, int | float | None]:
    """Classify a request row for timeseries rebuild.

    Adapter between sqlite3.Row and _classify_outcome, returning the
    counter dict expected by MetricsStore.rebuild_timeseries().
    """
    c = _classify_outcome(row["outcome"], row["status_code"], row["error_type"])

    return {
        "requests_success": int(c.is_success),
        "requests_rate_limited": int(c.is_rate_limited),
        "requests_capacity_error": int(c.is_capacity_error),
        "requests_server_error": int(c.is_server_error),
        "requests_client_error": int(c.is_client_error),
        "requests_connection_error": int(c.is_connection_error),
        "requests_malformed": int(c.is_malformed),
        "latency_ms": row["latency_ms"],
    }


class MetricsRecorder:
    """Thread-safe SQLite metrics recorder for ChaosLLM.

    Composes a MetricsStore for all SQLite infrastructure, adding LLM-specific
    typed wrappers for request recording and outcome classification.

    Usage:
        config = MetricsConfig(database="./metrics.db")
        recorder = MetricsRecorder(config)

        # Record a request
        recorder.record_request(
            request_id="abc123",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            endpoint="/chat/completions",
            outcome="success",
            latency_ms=150.5,
        )

        # Get statistics
        stats = recorder.get_stats()

        # Reset for new run
        recorder.reset()
    """

    def __init__(
        self,
        config: MetricsConfig,
        *,
        run_id: str | None = None,
    ) -> None:
        """Initialize the metrics recorder.

        Args:
            config: Metrics configuration
            run_id: Optional run ID (default: auto-generated UUID)
        """
        self._config = config
        self._store = MetricsStore(config, LLM_METRICS_SCHEMA, run_id=run_id)

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
        endpoint: str,
        outcome: str,
        deployment: str | None = None,
        model: str | None = None,
        status_code: int | None = None,
        error_type: str | None = None,
        injection_type: str | None = None,
        latency_ms: float | None = None,
        injected_delay_ms: float | None = None,
        message_count: int | None = None,
        prompt_tokens_approx: int | None = None,
        response_tokens: int | None = None,
        response_mode: str | None = None,
    ) -> None:
        """Record a single request to the metrics database.

        This method is thread-safe. Each thread uses its own connection.
        Writes may block briefly under high concurrency due to SQLite's
        single-writer constraint.

        Args:
            request_id: Unique identifier for this request
            timestamp_utc: ISO-formatted timestamp in UTC
            endpoint: The API endpoint (e.g., '/chat/completions')
            outcome: Request outcome ('success', 'error_injected', 'error_malformed')
            deployment: Azure deployment name (optional)
            model: Model name (optional)
            status_code: HTTP status code (optional)
            error_type: Type of error if any (optional)
            injection_type: Type of injected behavior if any (optional)
            latency_ms: Total response latency in milliseconds (optional)
            injected_delay_ms: Artificial delay injected in milliseconds (optional)
            message_count: Number of messages in the request (optional)
            prompt_tokens_approx: Approximate prompt token count (optional)
            response_tokens: Number of response tokens (optional)
            response_mode: Response generation mode (optional)
        """
        # Insert into requests table
        self._store.record(
            request_id=request_id,
            timestamp_utc=timestamp_utc,
            endpoint=endpoint,
            outcome=outcome,
            deployment=deployment,
            model=model,
            status_code=status_code,
            error_type=error_type,
            injection_type=injection_type,
            latency_ms=latency_ms,
            injected_delay_ms=injected_delay_ms,
            message_count=message_count,
            prompt_tokens_approx=prompt_tokens_approx,
            response_tokens=response_tokens,
            response_mode=response_mode,
        )

        # Classify and update time-series
        c = _classify_outcome(outcome, status_code, error_type)

        bucket = self._store.get_bucket_utc(timestamp_utc)
        self._store.update_timeseries(
            bucket,
            requests_success=int(c.is_success),
            requests_rate_limited=int(c.is_rate_limited),
            requests_capacity_error=int(c.is_capacity_error),
            requests_server_error=int(c.is_server_error),
            requests_client_error=int(c.is_client_error),
            requests_connection_error=int(c.is_connection_error),
            requests_malformed=int(c.is_malformed),
        )

        # Update latency statistics for the bucket
        self._store.update_bucket_latency(bucket, latency_ms)

        # Commit all three operations atomically
        self._store.commit()

    def update_timeseries(self) -> None:
        """Recalculate all time-series buckets from raw request data.

        This is useful for rebuilding aggregations after data corrections
        or for ensuring consistency.
        """
        self._store.rebuild_timeseries(_classify_row)

    def reset(
        self,
        *,
        config_json: str | None = None,
        preset_name: str | None = None,
    ) -> None:
        """Reset all metrics tables and start a new run."""
        self._store.reset(config_json=config_json, preset_name=preset_name)

    def get_stats(self) -> dict[str, Any]:
        """Get summary statistics for the current run."""
        return self._store.get_stats()

    def export_data(self) -> dict[str, Any]:
        """Export raw requests and time-series data for external analysis or archival."""
        return self._store.export_data()

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
