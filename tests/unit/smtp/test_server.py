"""Tests for ChaosSMTP server."""

import smtplib
from email.message import EmailMessage

from starlette.testclient import TestClient

from errorworks.engine.types import LatencyConfig, MetricsConfig
from errorworks.smtp.config import ChaosSMTPConfig, SMTPAdminConfig, SMTPServerConfig
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
        smtp=SMTPServerConfig().model_copy(update={"port": 0}),
        admin=SMTPAdminConfig(admin_token=TEST_ADMIN_TOKEN),
        metrics=MetricsConfig(database=str(tmp_path / "smtp.db")),
        latency=LatencyConfig(base_ms=0, jitter_ms=0),
    )


def test_server_starts_on_ephemeral_port(tmp_path) -> None:
    server = ChaosSMTPServer(_config(tmp_path))
    server.start()
    try:
        assert server.smtp_port > 0
    finally:
        server.stop()


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
