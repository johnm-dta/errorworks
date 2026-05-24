"""Tests for ChaosSMTP metrics recorder."""

from errorworks.engine.types import MetricsConfig
from errorworks.smtp.metrics import SMTPMetricsRecorder


def test_record_success_updates_stats(tmp_path) -> None:
    recorder = SMTPMetricsRecorder(MetricsConfig(database=str(tmp_path / "smtp.db")))
    recorder.record_transaction(
        transaction_id="tx-1",
        session_id="session-1",
        timestamp_utc="2026-05-24T00:00:00+00:00",
        client_addr="127.0.0.1",
        outcome="success",
        smtp_stage="data",
        reply_code=250,
        mail_from="sender@example.com",
        rcpt_count=1,
        rcpt_domains="example.com",
        message_size_bytes=128,
        capture_mode="metadata",
        latency_ms=3.5,
    )
    stats = recorder.get_stats()
    assert stats["total_requests"] == 1
    assert stats["requests_by_outcome"]["success"] == 1


def test_record_tempfail_classifies_timeseries(tmp_path) -> None:
    recorder = SMTPMetricsRecorder(MetricsConfig(database=str(tmp_path / "smtp.db")))
    recorder.record_transaction(
        transaction_id="tx-1",
        session_id="session-1",
        timestamp_utc="2026-05-24T00:00:00+00:00",
        client_addr="127.0.0.1",
        outcome="tempfailed",
        smtp_stage="rcpt",
        reply_code=451,
        error_type="rcpt_to_tempfail",
        injection_type="rcpt_to_tempfail",
        capture_mode="metadata",
    )
    timeseries = recorder.get_timeseries()
    assert timeseries[0]["messages_tempfailed"] == 1


def test_connection_error_reply_code_does_not_count_as_tempfail(tmp_path) -> None:
    recorder = SMTPMetricsRecorder(MetricsConfig(database=str(tmp_path / "smtp.db")))
    recorder.record_transaction(
        transaction_id="tx-1",
        session_id="session-1",
        timestamp_utc="2026-05-24T00:00:00+00:00",
        outcome="connection_error",
        reply_code=421,
        error_type="connection_reset",
        capture_mode="metadata",
    )
    timeseries = recorder.get_timeseries()
    assert timeseries[0]["messages_connection_error"] == 1
    assert timeseries[0]["messages_tempfailed"] == 0


def test_malformed_protocol_reply_code_does_not_count_as_permfail(tmp_path) -> None:
    recorder = SMTPMetricsRecorder(MetricsConfig(database=str(tmp_path / "smtp.db")))
    recorder.record_transaction(
        transaction_id="tx-1",
        session_id="session-1",
        timestamp_utc="2026-05-24T00:00:00+00:00",
        outcome="malformed_protocol",
        reply_code=550,
        error_type="bad_command_sequence",
        capture_mode="metadata",
    )
    timeseries = recorder.get_timeseries()
    assert timeseries[0]["messages_malformed_protocol"] == 1
    assert timeseries[0]["messages_permfailed"] == 0


def test_accepted_then_dropped_reply_code_does_not_count_as_accepted(tmp_path) -> None:
    recorder = SMTPMetricsRecorder(MetricsConfig(database=str(tmp_path / "smtp.db")))
    recorder.record_transaction(
        transaction_id="tx-1",
        session_id="session-1",
        timestamp_utc="2026-05-24T00:00:00+00:00",
        outcome="accepted_then_dropped",
        reply_code=250,
        capture_mode="metadata",
    )
    timeseries = recorder.get_timeseries()
    assert timeseries[0]["messages_accepted_then_dropped"] == 1
    assert timeseries[0]["messages_accepted"] == 0


def test_get_requests_returns_filtered_raw_rows(tmp_path) -> None:
    recorder = SMTPMetricsRecorder(MetricsConfig(database=str(tmp_path / "smtp.db")))
    recorder.record_transaction(
        transaction_id="tx-1",
        session_id="session-1",
        timestamp_utc="2026-05-24T00:00:00+00:00",
        outcome="success",
        reply_code=250,
        capture_mode="metadata",
    )
    recorder.record_transaction(
        transaction_id="tx-2",
        session_id="session-1",
        timestamp_utc="2026-05-24T00:00:01+00:00",
        outcome="tempfailed",
        reply_code=451,
        capture_mode="metadata",
    )

    requests = recorder.get_requests(outcome="tempfailed")

    assert len(requests) == 1
    assert requests[0]["transaction_id"] == "tx-2"
    assert requests[0]["outcome"] == "tempfailed"


def test_reset_starts_new_run(tmp_path) -> None:
    recorder = SMTPMetricsRecorder(MetricsConfig(database=str(tmp_path / "smtp.db")))
    original = recorder.run_id
    recorder.reset()
    assert recorder.run_id != original
    assert recorder.get_stats()["total_requests"] == 0


def test_export_contains_requests_and_config_shape(tmp_path) -> None:
    recorder = SMTPMetricsRecorder(MetricsConfig(database=str(tmp_path / "smtp.db")))
    data = recorder.export_data()
    assert data["requests"] == []
    assert data["timeseries"] == []
