"""Thread-safe SQLite metrics storage with schema-driven DDL.

The MetricsStore is a composable utility that handles all SQLite
infrastructure: thread-local connection management, WAL mode, DDL
generation from MetricsSchema, run info tracking, and data export.

Each chaos plugin composes a MetricsStore and adds typed wrappers
for recording domain-specific request data.
"""

import sqlite3
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

from errorworks.engine.types import ColumnDef, MetricsConfig, MetricsSchema

logger = structlog.get_logger(__name__)


def _column_ddl(col: ColumnDef) -> str:
    """Generate a single column DDL fragment from a ColumnDef."""
    col_def = f"    {col.name} {col.sql_type}"
    if col.primary_key:
        col_def += " PRIMARY KEY"
    if not col.nullable and not col.primary_key:
        col_def += " NOT NULL"
    if col.default is not None:
        col_def += f" DEFAULT {col.default}"
    return col_def


def _create_table_ddl(table_name: str, columns: tuple[ColumnDef, ...]) -> str:
    """Generate a CREATE TABLE IF NOT EXISTS statement."""
    col_defs = ",\n".join(_column_ddl(col) for col in columns)
    return f"CREATE TABLE IF NOT EXISTS {table_name} (\n{col_defs}\n);"


def _generate_ddl(schema: MetricsSchema) -> str:
    """Generate CREATE TABLE statements from a MetricsSchema.

    Args:
        schema: The metrics schema definition.

    Returns:
        SQL DDL string with all CREATE TABLE and CREATE INDEX statements.
    """
    parts: list[str] = []

    parts.append(_create_table_ddl("requests", schema.request_columns))
    parts.append(_create_table_ddl("timeseries", schema.timeseries_columns))

    # --- run_info table (always present) ---
    parts.append(
        "CREATE TABLE IF NOT EXISTS run_info (\n"
        "    run_id TEXT PRIMARY KEY,\n"
        "    started_utc TEXT NOT NULL,\n"
        "    config_json TEXT NOT NULL,\n"
        "    preset_name TEXT\n"
        ");"
    )

    # --- indexes ---
    for index_name, column_name in schema.request_indexes:
        parts.append(f"CREATE INDEX IF NOT EXISTS {index_name} ON requests({column_name});")

    return "\n\n".join(parts)


def _get_bucket_utc(timestamp_utc: str, bucket_sec: int) -> str:
    """Calculate the time bucket for a given timestamp.

    Bucket boundaries are calculated from time-of-day (hours, minutes,
    seconds) within the same date. Uses timedelta arithmetic to avoid
    invalid hour/minute values with large bucket sizes.

    Args:
        timestamp_utc: ISO-formatted timestamp string.
        bucket_sec: Bucket size in seconds.

    Returns:
        ISO-formatted bucket timestamp (truncated to bucket boundary).
    """
    try:
        dt = datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError as e:
        raise ValueError(f"Invalid timestamp for bucket calculation: {timestamp_utc!r}") from e
    total_seconds = dt.hour * 3600 + dt.minute * 60 + dt.second
    bucket_seconds = (total_seconds // bucket_sec) * bucket_sec
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    bucket_dt = midnight + timedelta(seconds=bucket_seconds)
    return bucket_dt.isoformat()


class MetricsStore:
    """Thread-safe SQLite metrics storage with schema-driven DDL.

    Handles thread-local connection management, WAL mode, DDL generation,
    run info tracking, stats computation, and data export. Each chaos plugin
    composes this and adds typed wrappers.

    Usage:
        store = MetricsStore(config, schema=LLM_METRICS_SCHEMA)
        store.record(request_id="abc", timestamp_utc="...", endpoint="/chat", outcome="success")
        stats = store.get_stats()
    """

    def __init__(
        self,
        config: MetricsConfig,
        schema: MetricsSchema,
        *,
        run_id: str | None = None,
    ) -> None:
        """Initialize the metrics store.

        Args:
            config: Metrics configuration.
            schema: Schema definition for requests and timeseries tables.
            run_id: Optional run ID (default: auto-generated UUID).
        """
        self._config = config
        self._schema = schema
        self._run_id = run_id if run_id is not None else str(uuid.uuid4())
        self._started_utc = datetime.now(UTC).isoformat()

        # Thread-local storage for connections, keyed by thread ID
        self._local = threading.local()
        self._lock = threading.Lock()
        self._connections: dict[int, sqlite3.Connection] = {}

        # Detect in-memory databases and URI usage
        self._use_uri = config.database.startswith("file:")
        self._is_memory_db = config.database == ":memory:" or "mode=memory" in config.database

        # Ensure database directory exists for file-backed databases
        if not self._is_memory_db and not self._use_uri:
            db_path = Path(config.database)
            if db_path.parent != Path("."):
                db_path.parent.mkdir(parents=True, exist_ok=True)

        # Generate and cache DDL
        self._ddl = _generate_ddl(schema)

        # Cache column names for insert queries
        self._request_col_names = tuple(c.name for c in schema.request_columns)
        self._timeseries_col_names = tuple(c.name for c in schema.timeseries_columns)

        # Initialize schema
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create a thread-local database connection."""
        try:
            connection: sqlite3.Connection = self._local.connection
            return connection
        except AttributeError:
            self._cleanup_stale_connections()
            conn = sqlite3.connect(
                self._config.database,
                check_same_thread=False,
                timeout=30.0,
                uri=self._use_uri,
            )
            try:
                if self._is_memory_db:
                    conn.execute("PRAGMA journal_mode=MEMORY")
                    conn.execute("PRAGMA synchronous=OFF")
                else:
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("PRAGMA synchronous=NORMAL")
                conn.row_factory = sqlite3.Row
            except sqlite3.Error:
                conn.close()
                raise
            self._local.connection = conn
            thread_id = threading.get_ident()
            with self._lock:
                self._connections[thread_id] = conn
            return conn

    def _cleanup_stale_connections(self) -> None:
        """Close connections from threads that have exited."""
        live_thread_ids = {t.ident for t in threading.enumerate()}
        with self._lock:
            dead_ids = [tid for tid in self._connections if tid not in live_thread_ids]
            failed_count = 0
            for tid in dead_ids:
                try:
                    self._connections[tid].close()
                except sqlite3.Error:
                    failed_count += 1
                    logger.warning("failed to close stale connection for thread %s", tid, exc_info=True)
                del self._connections[tid]
            if failed_count:
                logger.error("Failed to close %d stale connection(s) during cleanup", failed_count)

    def _init_schema(self) -> None:
        """Initialize database schema."""
        conn = self._get_connection()
        try:
            conn.executescript(self._ddl)
            conn.commit()
        except sqlite3.Error as e:
            raise type(e)(
                f"Failed to initialize metrics schema for database '{self._config.database}': {e}"
            ) from e

    @property
    def run_id(self) -> str:
        """Get the current run ID."""
        return self._run_id

    @property
    def started_utc(self) -> str:
        """Get the run start time in UTC."""
        return self._started_utc

    @property
    def request_column_names(self) -> tuple[str, ...]:
        """Column names for the requests table."""
        return self._request_col_names

    @property
    def timeseries_column_names(self) -> tuple[str, ...]:
        """Column names for the timeseries table."""
        return self._timeseries_col_names

    def commit(self) -> None:
        """Commit the current transaction on the thread-local connection.

        Call this after batching multiple write operations (record,
        update_timeseries, update_bucket_latency) to commit them
        atomically as a single transaction.
        """
        conn = self._get_connection()
        conn.commit()

    def record(self, **kwargs: Any) -> None:
        """Insert a row into the requests table.

        Column names and values are passed as keyword arguments.
        Only columns defined in the schema are accepted.

        Note: Does NOT auto-commit. Call commit() after batching
        all writes for a single logical request.

        Args:
            **kwargs: Column name=value pairs for the requests table.

        Raises:
            ValueError: If any kwarg key is not a column in the schema.
        """
        unknown = set(kwargs) - set(self._request_col_names)
        if unknown:
            raise ValueError(f"Unknown columns for requests table: {sorted(unknown)}. Valid columns: {sorted(self._request_col_names)}")
        conn = self._get_connection()
        cols = list(kwargs.keys())
        vals = list(kwargs.values())
        placeholders = ", ".join("?" for _ in cols)
        col_str = ", ".join(cols)
        conn.execute(
            f"INSERT INTO requests ({col_str}) VALUES ({placeholders})",
            vals,
        )

    def update_timeseries(self, bucket_utc: str, **counters: int) -> None:
        """Upsert a timeseries bucket with counter increments.

        Note: Does NOT auto-commit. Call commit() after batching
        all writes for a single logical request.

        Args:
            bucket_utc: The bucket timestamp (ISO format).
            **counters: Column name=increment pairs for timeseries columns.
                        Only integer counter columns should be passed.
        """
        unknown = set(counters) - set(self._timeseries_col_names)
        if unknown:
            raise ValueError(f"Unknown columns for timeseries table: {sorted(unknown)}. Valid columns: {sorted(self._timeseries_col_names)}")

        conn = self._get_connection()

        # Always include bucket_utc and requests_total
        insert_cols = ["bucket_utc", "requests_total"]
        insert_vals: list[Any] = [bucket_utc, 1]
        update_parts: list[str] = ["requests_total = requests_total + 1"]
        update_vals: list[Any] = []

        for col_name, value in counters.items():
            insert_cols.append(col_name)
            insert_vals.append(value)
            update_parts.append(f"{col_name} = {col_name} + ?")
            update_vals.append(value)

        insert_placeholders = ", ".join("?" for _ in insert_cols)
        insert_col_str = ", ".join(insert_cols)
        update_str = ", ".join(update_parts)

        sql = f"INSERT INTO timeseries ({insert_col_str}) VALUES ({insert_placeholders}) ON CONFLICT(bucket_utc) DO UPDATE SET {update_str}"
        conn.execute(sql, insert_vals + update_vals)

    def update_bucket_latency(self, bucket_utc: str, latency_ms: float | None) -> None:
        """Recalculate latency statistics for a time-series bucket.

        Args:
            bucket_utc: The bucket timestamp.
            latency_ms: The latency to record (triggers recalculation if not None).
        """
        if latency_ms is None:
            return

        conn = self._get_connection()
        bucket_end = (datetime.fromisoformat(bucket_utc) + timedelta(seconds=self._config.timeseries_bucket_sec)).isoformat()

        cursor = conn.execute(
            """
            SELECT latency_ms FROM requests
            WHERE timestamp_utc >= ? AND timestamp_utc < ? AND latency_ms IS NOT NULL
            ORDER BY latency_ms
            """,
            (bucket_utc, bucket_end),
        )
        latencies = [row[0] for row in cursor.fetchall()]
        if not latencies:
            return

        avg_latency = sum(latencies) / len(latencies)
        p99_index = min(int(len(latencies) * 0.99), len(latencies) - 1)
        p99_latency = latencies[p99_index]

        conn.execute(
            "UPDATE timeseries SET avg_latency_ms = ?, p99_latency_ms = ? WHERE bucket_utc = ?",
            (avg_latency, p99_latency, bucket_utc),
        )

    def rebuild_timeseries(
        self,
        classify: Callable[[sqlite3.Row], dict[str, int | float | None]],
    ) -> None:
        """Rebuild all timeseries buckets from raw request data.

        Clears the timeseries table and re-aggregates from the requests table
        using a caller-supplied classifier. This keeps domain-specific outcome
        classification in the domain layer while database access stays here.

        Args:
            classify: A callable that receives a sqlite3.Row from the requests
                table and returns a dict of counter column names to increment
                values (e.g. ``{"requests_success": 1, "requests_rate_limited": 0}``).
                Must also return a ``"latency_ms"`` key with ``float | None``.
        """
        conn = self._get_connection()
        bucket_sec = self._config.timeseries_bucket_sec

        try:
            conn.execute("DELETE FROM timeseries")

            cursor = conn.execute(
                "SELECT DISTINCT timestamp_utc FROM requests ORDER BY timestamp_utc",
            )
            timestamps = [row[0] for row in cursor.fetchall()]

            seen_buckets: set[str] = set()
            for ts in timestamps:
                bucket = _get_bucket_utc(ts, bucket_sec)
                if bucket in seen_buckets:
                    continue
                seen_buckets.add(bucket)

                bucket_end = (datetime.fromisoformat(bucket) + timedelta(seconds=bucket_sec)).isoformat()

                rows = conn.execute(
                    """
                    SELECT * FROM requests
                    WHERE timestamp_utc >= ? AND timestamp_utc < ?
                    """,
                    (bucket, bucket_end),
                ).fetchall()

                if not rows:
                    continue

                # Aggregate counters and latencies across all rows in this bucket
                totals: dict[str, int] = {}
                latencies: list[float] = []

                for row in rows:
                    classified = classify(row)
                    latency = classified.pop("latency_ms", None)
                    for col, value in classified.items():
                        if isinstance(value, int):
                            totals[col] = totals.get(col, 0) + value
                    if latency is not None:
                        latencies.append(float(latency))

                # Build and execute the upsert (reuse update_timeseries column logic)
                insert_cols = ["bucket_utc", "requests_total"]
                insert_vals: list[Any] = [bucket, len(rows)]
                for col, value in totals.items():
                    insert_cols.append(col)
                    insert_vals.append(value)

                placeholders = ", ".join("?" for _ in insert_cols)
                col_str = ", ".join(insert_cols)
                conn.execute(
                    f"INSERT INTO timeseries ({col_str}) VALUES ({placeholders})",
                    insert_vals,
                )

                # Latency stats
                if latencies:
                    avg_latency = sum(latencies) / len(latencies)
                    latencies.sort()
                    p99_index = min(int(len(latencies) * 0.99), len(latencies) - 1)
                    p99_latency = latencies[p99_index]
                    conn.execute(
                        "UPDATE timeseries SET avg_latency_ms = ?, p99_latency_ms = ? WHERE bucket_utc = ?",
                        (avg_latency, p99_latency, bucket),
                    )

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def get_bucket_utc(self, timestamp_utc: str) -> str:
        """Calculate the time bucket for a timestamp.

        Args:
            timestamp_utc: ISO-formatted timestamp.

        Returns:
            ISO-formatted bucket timestamp.
        """
        return _get_bucket_utc(timestamp_utc, self._config.timeseries_bucket_sec)

    def get_stats(self) -> dict[str, Any]:
        """Get summary statistics for the current run.

        Stats are derived from the schema — only columns present in
        request_columns are queried. This avoids hardcoding plugin-specific
        column names like 'outcome' or 'status_code'.

        Returns:
            Dictionary with summary statistics. Keys are conditional on
            which columns exist in the schema.
        """
        conn = self._get_connection()
        col_names = set(self._request_col_names)

        cursor = conn.execute("SELECT COUNT(*) FROM requests")
        total_requests = cursor.fetchone()[0]

        stats: dict[str, Any] = {
            "run_id": self._run_id,
            "started_utc": self._started_utc,
            "total_requests": total_requests,
        }

        if "outcome" in col_names:
            cursor = conn.execute("SELECT outcome, COUNT(*) FROM requests GROUP BY outcome")
            requests_by_outcome = {row[0]: row[1] for row in cursor.fetchall()}
            stats["requests_by_outcome"] = requests_by_outcome

            if total_requests > 0:
                error_count = sum(count for outcome, count in requests_by_outcome.items() if outcome != "success")
                stats["error_rate"] = (error_count / total_requests) * 100
            else:
                stats["error_rate"] = 0.0

        if "status_code" in col_names:
            cursor = conn.execute("SELECT status_code, COUNT(*) FROM requests WHERE status_code IS NOT NULL GROUP BY status_code")
            stats["requests_by_status_code"] = {row[0]: row[1] for row in cursor.fetchall()}

        if "latency_ms" in col_names:
            cursor = conn.execute("SELECT AVG(latency_ms), MAX(latency_ms) FROM requests WHERE latency_ms IS NOT NULL")
            row = cursor.fetchone()

            cursor = conn.execute("SELECT latency_ms FROM requests WHERE latency_ms IS NOT NULL ORDER BY latency_ms")
            latencies = [r[0] for r in cursor.fetchall()]

            p50_latency = None
            p95_latency = None
            p99_latency = None

            if latencies:
                p50_latency = latencies[min(int(len(latencies) * 0.50), len(latencies) - 1)]
                p95_latency = latencies[min(int(len(latencies) * 0.95), len(latencies) - 1)]
                p99_latency = latencies[min(int(len(latencies) * 0.99), len(latencies) - 1)]

            stats["latency_stats"] = {
                "avg_ms": row[0],
                "p50_ms": p50_latency,
                "p95_ms": p95_latency,
                "p99_ms": p99_latency,
                "max_ms": row[1],
            }

        return stats

    def export_data(self) -> dict[str, Any]:
        """Export raw requests and time-series data."""
        conn = self._get_connection()
        requests = [dict(row) for row in conn.execute("SELECT * FROM requests ORDER BY timestamp_utc")]
        timeseries = [dict(row) for row in conn.execute("SELECT * FROM timeseries ORDER BY bucket_utc")]
        return {
            "run_id": self._run_id,
            "started_utc": self._started_utc,
            "requests": requests,
            "timeseries": timeseries,
        }

    def save_run_info(
        self,
        config_json: str,
        preset_name: str | None = None,
    ) -> None:
        """Save run information to the database."""
        conn = self._get_connection()
        conn.execute(
            "INSERT OR REPLACE INTO run_info (run_id, started_utc, config_json, preset_name) VALUES (?, ?, ?, ?)",
            (self._run_id, self._started_utc, config_json, preset_name),
        )
        conn.commit()

    def get_requests(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        outcome: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get request records from the database."""
        conn = self._get_connection()
        if outcome is not None:
            cursor = conn.execute(
                "SELECT * FROM requests WHERE outcome = ? ORDER BY timestamp_utc DESC LIMIT ? OFFSET ?",
                (outcome, limit, offset),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM requests ORDER BY timestamp_utc DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        return [dict(row) for row in cursor.fetchall()]

    def get_timeseries(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Get time-series records from the database."""
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT * FROM timeseries ORDER BY bucket_utc DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(row) for row in cursor.fetchall()]

    def reset(
        self,
        *,
        config_json: str | None = None,
        preset_name: str | None = None,
    ) -> None:
        """Reset all metrics tables and start a new run."""
        with self._lock:
            self._run_id = str(uuid.uuid4())
            self._started_utc = datetime.now(UTC).isoformat()

        conn = self._get_connection()

        if config_json is None:
            cursor = conn.execute("SELECT config_json, preset_name FROM run_info LIMIT 1")
            row = cursor.fetchone()
            if row is not None:
                config_json = row["config_json"]
                if preset_name is None:
                    preset_name = row["preset_name"]

        conn.execute("DELETE FROM requests")
        conn.execute("DELETE FROM timeseries")

        if config_json is not None:
            conn.execute("DELETE FROM run_info")
            conn.execute(
                "INSERT INTO run_info (run_id, started_utc, config_json, preset_name) VALUES (?, ?, ?, ?)",
                (self._run_id, self._started_utc, config_json, preset_name),
            )
        conn.commit()

    def close(self) -> None:
        """Close all database connections across all threads."""
        with self._lock:
            failed_count = 0
            for tid, conn in self._connections.items():
                try:
                    conn.close()
                except sqlite3.Error:
                    failed_count += 1
                    logger.warning("failed to close connection for thread %s", tid, exc_info=True)
            if failed_count:
                logger.error("Failed to close %d connection(s) during shutdown", failed_count)
            self._connections.clear()
            # Reset thread-local storage so _get_connection() won't return
            # a closed connection if called again on the same thread.
            self._local = threading.local()
