"""Tests for ChaosSMTP server."""

import smtplib
import threading
import time
from email.message import EmailMessage

import pytest
from starlette.testclient import TestClient

from errorworks.engine.types import LatencyConfig, MetricsConfig
from errorworks.smtp.config import ChaosSMTPConfig, SMTPAdminConfig, SMTPErrorInjectionConfig, SMTPServerConfig
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
