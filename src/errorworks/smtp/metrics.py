"""Metrics storage and aggregation for ChaosSMTP."""

from __future__ import annotations

import sqlite3
from typing import Any, NamedTuple

from errorworks.engine.metrics_store import MetricsStore
from errorworks.engine.types import ColumnDef, MetricsConfig, MetricsSchema, SqlType

SMTP_METRICS_SCHEMA = MetricsSchema(
    request_columns=(
        ColumnDef("transaction_id", SqlType.TEXT, nullable=False, primary_key=True),
        ColumnDef("session_id", SqlType.TEXT, nullable=False),
        ColumnDef("timestamp_utc", SqlType.TEXT, nullable=False),
        ColumnDef("client_addr", SqlType.TEXT),
        ColumnDef("mail_from", SqlType.TEXT),
        ColumnDef("rcpt_count", SqlType.INTEGER),
        ColumnDef("rcpt_domains", SqlType.TEXT),
        ColumnDef("message_size_bytes", SqlType.INTEGER),
        ColumnDef("subject", SqlType.TEXT),
        ColumnDef("outcome", SqlType.TEXT, nullable=False),
        ColumnDef("smtp_stage", SqlType.TEXT),
        ColumnDef("reply_code", SqlType.INTEGER),
        ColumnDef("enhanced_status_code", SqlType.TEXT),
        ColumnDef("error_type", SqlType.TEXT),
        ColumnDef("injection_type", SqlType.TEXT),
        ColumnDef("latency_ms", SqlType.REAL),
        ColumnDef("injected_delay_ms", SqlType.REAL),
        ColumnDef("capture_mode", SqlType.TEXT),
        ColumnDef("tls_used", SqlType.INTEGER),
        ColumnDef("auth_username", SqlType.TEXT),
    ),
    timeseries_columns=(
        ColumnDef("bucket_utc", SqlType.TEXT, nullable=False, primary_key=True),
        ColumnDef("requests_total", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("messages_accepted", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("messages_tempfailed", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("messages_permfailed", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("messages_connection_error", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("messages_malformed_protocol", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("messages_accepted_then_dropped", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("avg_latency_ms", SqlType.REAL),
        ColumnDef("p99_latency_ms", SqlType.REAL),
    ),
    request_indexes=(
        ("idx_smtp_timestamp", "timestamp_utc"),
        ("idx_smtp_outcome", "outcome"),
        ("idx_smtp_stage", "smtp_stage"),
    ),
)


class SMTPOutcomeClassification(NamedTuple):
    accepted: bool
    tempfailed: bool
    permfailed: bool
    connection_error: bool
    malformed_protocol: bool
    accepted_then_dropped: bool


def _classify_outcome(outcome: str, reply_code: int | None, error_type: str | None) -> SMTPOutcomeClassification:
    return SMTPOutcomeClassification(
        accepted=outcome == "success",
        tempfailed=reply_code is not None and 400 <= reply_code < 500 and error_type != "connection_stall",
        permfailed=reply_code is not None and 500 <= reply_code < 600,
        connection_error=outcome == "connection_error",
        malformed_protocol=outcome == "malformed_protocol",
        accepted_then_dropped=outcome == "accepted_then_dropped",
    )


def _classify_row(row: sqlite3.Row) -> dict[str, int | float | None]:
    cls = _classify_outcome(row["outcome"], row["reply_code"], row["error_type"])
    return {
        "messages_accepted": int(cls.accepted),
        "messages_tempfailed": int(cls.tempfailed),
        "messages_permfailed": int(cls.permfailed),
        "messages_connection_error": int(cls.connection_error),
        "messages_malformed_protocol": int(cls.malformed_protocol),
        "messages_accepted_then_dropped": int(cls.accepted_then_dropped),
        "latency_ms": row["latency_ms"],
    }


class SMTPMetricsRecorder:
    """Thread-safe SQLite metrics recorder for ChaosSMTP."""

    def __init__(self, config: MetricsConfig, *, run_id: str | None = None) -> None:
        self._config = config
        self._store = MetricsStore(config, SMTP_METRICS_SCHEMA, run_id=run_id)

    @property
    def run_id(self) -> str:
        return self._store.run_id

    @property
    def started_utc(self) -> str:
        return self._store.started_utc

    def record_transaction(
        self,
        *,
        transaction_id: str,
        session_id: str,
        timestamp_utc: str,
        outcome: str,
        client_addr: str | None = None,
        mail_from: str | None = None,
        rcpt_count: int | None = None,
        rcpt_domains: str | None = None,
        message_size_bytes: int | None = None,
        subject: str | None = None,
        smtp_stage: str | None = None,
        reply_code: int | None = None,
        enhanced_status_code: str | None = None,
        error_type: str | None = None,
        injection_type: str | None = None,
        latency_ms: float | None = None,
        injected_delay_ms: float | None = None,
        capture_mode: str | None = None,
        tls_used: bool | None = None,
        auth_username: str | None = None,
    ) -> None:
        self._store.record(
            transaction_id=transaction_id,
            session_id=session_id,
            timestamp_utc=timestamp_utc,
            client_addr=client_addr,
            mail_from=mail_from,
            rcpt_count=rcpt_count,
            rcpt_domains=rcpt_domains,
            message_size_bytes=message_size_bytes,
            subject=subject,
            outcome=outcome,
            smtp_stage=smtp_stage,
            reply_code=reply_code,
            enhanced_status_code=enhanced_status_code,
            error_type=error_type,
            injection_type=injection_type,
            latency_ms=latency_ms,
            injected_delay_ms=injected_delay_ms,
            capture_mode=capture_mode,
            tls_used=int(tls_used) if tls_used is not None else None,
            auth_username=auth_username,
        )
        cls = _classify_outcome(outcome, reply_code, error_type)
        bucket = self._store.get_bucket_utc(timestamp_utc)
        self._store.update_timeseries(
            bucket,
            messages_accepted=int(cls.accepted),
            messages_tempfailed=int(cls.tempfailed),
            messages_permfailed=int(cls.permfailed),
            messages_connection_error=int(cls.connection_error),
            messages_malformed_protocol=int(cls.malformed_protocol),
            messages_accepted_then_dropped=int(cls.accepted_then_dropped),
        )
        self._store.update_bucket_latency(bucket, latency_ms)
        self._store.commit()

    def update_timeseries(self) -> None:
        self._store.rebuild_timeseries(_classify_row)

    def reset(self, *, config_json: str | None = None, preset_name: str | None = None) -> None:
        self._store.reset(config_json=config_json, preset_name=preset_name)

    def get_stats(self) -> dict[str, Any]:
        return self._store.get_stats()

    def export_data(self, *, limit: int | None = None, offset: int = 0) -> dict[str, Any]:
        return self._store.export_data(limit=limit, offset=offset)

    def save_run_info(self, config_json: str, preset_name: str | None = None) -> None:
        self._store.save_run_info(config_json, preset_name)

    def get_timeseries(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._store.get_timeseries(limit=limit, offset=offset)

    def close(self) -> None:
        self._store.close()
