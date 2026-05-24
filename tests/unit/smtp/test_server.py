"""Tests for ChaosSMTP server."""

import smtplib
import threading
import time
from email.message import EmailMessage
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from errorworks.engine.types import LatencyConfig, MetricsConfig
from errorworks.smtp.config import ChaosSMTPConfig, SMTPAdminConfig, SMTPBurstConfig, SMTPErrorInjectionConfig, SMTPServerConfig
from errorworks.smtp.server import ChaosSMTPServer, create_admin_app

TEST_ADMIN_TOKEN = "test-admin-token"


def _message() -> EmailMessage:
    message = EmailMessage()
    message["From"] = "sender@example.com"
    message["To"] = "recipient@example.com"
    message["Subject"] = "Delivery test"
    message.set_content("hello from chaossmtp")
    return message


def _config(tmp_path) -> ChaosSMTPConfig:
    return ChaosSMTPConfig(
        smtp=SMTPServerConfig(port=0),
        admin=SMTPAdminConfig(admin_token=TEST_ADMIN_TOKEN),
        metrics=MetricsConfig(database=str(tmp_path / "smtp.db")),
        latency=LatencyConfig(base_ms=0, jitter_ms=0),
    )


def _config_for_port(tmp_path, port: int) -> ChaosSMTPConfig:
    return ChaosSMTPConfig(
        smtp=SMTPServerConfig(port=port),
        admin=SMTPAdminConfig(admin_token=TEST_ADMIN_TOKEN),
        metrics=MetricsConfig(database=str(tmp_path / f"smtp-{port}.db")),
        latency=LatencyConfig(base_ms=0, jitter_ms=0),
    )


def _config_with_error_injection(tmp_path, **overrides: object) -> ChaosSMTPConfig:
    base = _config(tmp_path)
    return ChaosSMTPConfig(
        **{
            **base.model_dump(),
            "error_injection": {
                **base.error_injection.model_dump(),
                **overrides,
            },
        }
    )


def test_server_starts_on_ephemeral_port(tmp_path) -> None:
    server = ChaosSMTPServer(_config(tmp_path))
    server.start()
    try:
        assert server.smtp_port > 0
    finally:
        server.stop()


def test_failed_start_does_not_leave_server_running(tmp_path) -> None:
    first = ChaosSMTPServer(_config(tmp_path))
    first.start()
    second = ChaosSMTPServer(_config_for_port(tmp_path, first.smtp_port))
    try:
        with pytest.raises(OSError):
            second.start()
        assert not second.smtp_running
    finally:
        first.stop()
        second.stop()


def test_stop_closes_metrics_recorder_idempotently(tmp_path) -> None:
    server = ChaosSMTPServer(_config(tmp_path))

    with patch.object(server._metrics_recorder, "close", wraps=server._metrics_recorder.close) as close:
        server.stop()
        server.stop()

    assert close.call_count == 2


def test_stop_after_failed_start_closes_metrics(tmp_path) -> None:
    first = ChaosSMTPServer(_config(tmp_path))
    first.start()
    second = ChaosSMTPServer(_config_for_port(tmp_path, first.smtp_port))
    try:
        with patch.object(second._metrics_recorder, "close", wraps=second._metrics_recorder.close) as close:
            with pytest.raises(OSError):
                second.start()
            second.stop()
        close.assert_called_once()
    finally:
        first.stop()
        second.stop()


def test_silent_server_accepts_message(tmp_path) -> None:
    server = ChaosSMTPServer(_config(tmp_path))
    server.start()
    try:
        with smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client:
            result = client.send_message(_message())
        assert result == {}
        stats = server.get_stats()
        assert stats["total_requests"] == 1
        assert server.list_messages()[0].subject == "Delivery test"
    finally:
        server.stop()


def test_capture_update_preserves_existing_messages(tmp_path) -> None:
    server = ChaosSMTPServer(_config(tmp_path))
    server.start()
    try:
        with smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client:
            client.send_message(_message())
        server.update_config({"capture": {"mode": "full"}})
        assert server.list_messages()[0].subject == "Delivery test"
        assert server.export_metrics()["messages"][0]["subject"] == "Delivery test"
    finally:
        server.stop()


def test_inflight_data_uses_request_capture_policy_when_config_changes(tmp_path) -> None:
    config = ChaosSMTPConfig(
        smtp=SMTPServerConfig(port=0),
        admin=SMTPAdminConfig(admin_token=TEST_ADMIN_TOKEN),
        metrics=MetricsConfig(database=str(tmp_path / "smtp-capture-race.db")),
        latency=LatencyConfig(base_ms=400, jitter_ms=0),
    )
    server = ChaosSMTPServer(config)
    server.start()
    errors: list[BaseException] = []
    try:
        with smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client:
            client.ehlo()
            assert client.mail("sender@example.com")[0] == 250
            assert client.rcpt("recipient@example.com")[0] == 250

            started = threading.Event()

            def send_data() -> None:
                started.set()
                try:
                    code, message = client.data(_message().as_bytes())
                    assert code == 250
                    assert message
                except BaseException as exc:
                    errors.append(exc)

            sender = threading.Thread(target=send_data)
            sender.start()
            assert started.wait(timeout=1)
            time.sleep(0.05)

            server.update_config({"capture": {"mode": "discard"}})
            sender.join(timeout=2)
            assert not sender.is_alive()
        if errors:
            raise errors[0]

        messages = server.list_messages()
        assert len(messages) == 1
        assert messages[0].subject == "Delivery test"
        requests = server.export_metrics()["requests"]
        assert requests[0]["capture_mode"] == "metadata"
    finally:
        server.stop()


def test_accept_then_drop_returns_success_without_capturing_message(tmp_path) -> None:
    config = ChaosSMTPConfig(
        smtp=SMTPServerConfig(port=0),
        admin=SMTPAdminConfig(admin_token=TEST_ADMIN_TOKEN),
        metrics=MetricsConfig(database=str(tmp_path / "smtp-drop.db")),
        latency=LatencyConfig(base_ms=0, jitter_ms=0),
        error_injection=SMTPErrorInjectionConfig(accept_then_drop_pct=100.0),
    )
    server = ChaosSMTPServer(config)
    server.start()
    try:
        with smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client:
            result = client.send_message(_message())
        assert result == {}
        assert server.list_messages() == []
        stats = server.get_stats()
        assert stats["total_requests"] == 1
        assert stats["requests_by_outcome"] == {"accepted_then_dropped": 1}
    finally:
        server.stop()


def test_health_endpoint_reports_smtp_status(tmp_path) -> None:
    server = ChaosSMTPServer(_config(tmp_path))
    app = create_admin_app(server)
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "smtp_running" in data
    assert "run_id" in data


def test_rcpt_tempfail_returns_smtp_recipients_refused(tmp_path) -> None:
    server = ChaosSMTPServer(_config_with_error_injection(tmp_path, rcpt_to_tempfail_pct=100.0))
    server.start()
    try:
        with (
            smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client,
            pytest.raises(smtplib.SMTPRecipientsRefused) as exc_info,
        ):
            client.send_message(_message())
        refused = exc_info.value.recipients["recipient@example.com"]
        assert refused[0] == 451
        assert server.get_stats()["total_requests"] == 1
    finally:
        server.stop()


def test_data_reject_returns_smtp_data_error(tmp_path) -> None:
    server = ChaosSMTPServer(_config_with_error_injection(tmp_path, data_reject_pct=100.0))
    server.start()
    try:
        with (
            smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client,
            pytest.raises(smtplib.SMTPDataError) as exc_info,
        ):
            client.send_message(_message())
        assert exc_info.value.smtp_code == 554
        assert server.get_stats()["total_requests"] == 1
    finally:
        server.stop()


def test_admin_config_update_changes_subsequent_transaction(tmp_path) -> None:
    base = _config(tmp_path)
    config = ChaosSMTPConfig(
        **{
            **base.model_dump(),
            "error_injection": SMTPErrorInjectionConfig(
                data_reject_pct=7.5,
                accept_then_drop_pct=23.5,
                burst=SMTPBurstConfig(
                    enabled=True,
                    interval_sec=37,
                    duration_sec=11,
                    tempfail_pct=0.0,
                    rate_limit_pct=0.0,
                ),
            ).model_dump(),
        }
    )
    server = ChaosSMTPServer(config)
    server.start()
    try:
        with TestClient(server.admin_app) as admin_client:
            response = admin_client.post(
                "/admin/config",
                headers={"Authorization": f"Bearer {TEST_ADMIN_TOKEN}"},
                json={"error_injection": {"rcpt_to_reject_pct": 100.0}},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["config"]["error_injection"]["rcpt_to_reject_pct"] == 100.0
        assert data["config"]["error_injection"]["data_reject_pct"] == 7.5
        assert data["config"]["error_injection"]["accept_then_drop_pct"] == 23.5
        assert data["config"]["error_injection"]["burst"]["enabled"] is True
        assert data["config"]["error_injection"]["burst"]["interval_sec"] == 37
        assert data["config"]["error_injection"]["burst"]["duration_sec"] == 11

        with (
            smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client,
            pytest.raises(smtplib.SMTPRecipientsRefused) as exc_info,
        ):
            client.send_message(_message())
        refused = exc_info.value.recipients["recipient@example.com"]
        assert refused[0] == 550
    finally:
        server.stop()


def test_admin_reset_clears_metrics_and_capture(tmp_path) -> None:
    server = ChaosSMTPServer(_config(tmp_path))
    server.start()
    try:
        with smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client:
            client.send_message(_message())
        assert server.get_stats()["total_requests"] == 1
        assert server.list_messages()

        with TestClient(server.admin_app) as admin_client:
            response = admin_client.post("/admin/reset", headers={"Authorization": f"Bearer {TEST_ADMIN_TOKEN}"})
        assert response.status_code == 200
        assert server.get_stats()["total_requests"] == 0
        assert server.list_messages() == []
    finally:
        server.stop()


def test_failed_mail_command_does_not_mutate_envelope_and_records_once(tmp_path) -> None:
    server = ChaosSMTPServer(_config_with_error_injection(tmp_path, mail_from_reject_pct=100.0))
    server.start()
    try:
        with smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client:
            client.ehlo()
            code, _ = client.mail("sender@example.com")
            assert code == 550

            server.update_config({"error_injection": {"mail_from_reject_pct": 0.0}})
            code, _ = client.rcpt("recipient@example.com")
            assert code == 503

        requests = server.export_metrics()["requests"]
        assert len(requests) == 1
        request = requests[0]
        assert request["smtp_stage"] == "mail"
        assert request["reply_code"] == 550
        assert request["outcome"] == "permfailed"
    finally:
        server.stop()


def test_failed_rcpt_command_does_not_mutate_envelope_and_records_once(tmp_path) -> None:
    server = ChaosSMTPServer(_config_with_error_injection(tmp_path, rcpt_to_reject_pct=100.0))
    server.start()
    try:
        with smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client:
            client.ehlo()
            assert client.mail("sender@example.com")[0] == 250
            code, _ = client.rcpt("recipient@example.com")
            assert code == 550

            server.update_config({"error_injection": {"rcpt_to_reject_pct": 0.0}})
            with pytest.raises(smtplib.SMTPDataError) as exc_info:
                client.data(_message().as_bytes())
            assert exc_info.value.smtp_code == 503

        requests = server.export_metrics()["requests"]
        assert len(requests) == 1
        request = requests[0]
        assert request["smtp_stage"] == "rcpt"
        assert request["reply_code"] == 550
        assert request["outcome"] == "permfailed"
    finally:
        server.stop()


def test_connection_reset_disconnects_client(tmp_path) -> None:
    server = ChaosSMTPServer(_config_with_error_injection(tmp_path, connection_reset_pct=100.0))
    server.start()
    try:
        with smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client, pytest.raises(smtplib.SMTPServerDisconnected):
            client.send_message(_message())
        assert server.get_stats()["total_requests"] >= 1
    finally:
        server.stop()


def test_wrong_reply_code_is_recorded_as_malformed_protocol(tmp_path) -> None:
    server = ChaosSMTPServer(_config_with_error_injection(tmp_path, wrong_reply_code_pct=100.0))
    server.start()
    try:
        with smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client, pytest.raises(smtplib.SMTPDataError):
            client.send_message(_message())
        stats = server.export_metrics()
        assert stats["requests"][0]["outcome"] == "malformed_protocol"
    finally:
        server.stop()


def test_malformed_reply_disconnects_client(tmp_path) -> None:
    server = ChaosSMTPServer(_config_with_error_injection(tmp_path, malformed_reply_pct=100.0))
    server.start()
    try:
        with smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client, pytest.raises(smtplib.SMTPServerDisconnected):
            client.send_message(_message())
        stats = server.export_metrics()
        assert stats["requests"][0]["outcome"] == "malformed_protocol"
    finally:
        server.stop()


def test_slow_response_continues_to_successful_delivery(tmp_path) -> None:
    server = ChaosSMTPServer(_config_with_error_injection(tmp_path, slow_response_pct=100.0, slow_response_sec=(0, 0)))
    server.start()
    try:
        with smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client:
            result = client.send_message(_message())

        assert result == {}
        assert server.list_messages()[0].subject == "Delivery test"
        assert server.get_stats()["requests_by_outcome"] == {"success": 1}
        assert server.export_metrics()["requests"][0]["outcome"] == "success"
    finally:
        server.stop()
