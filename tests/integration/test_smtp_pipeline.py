"""Integration tests for the ChaosSMTP pipeline: preset -> config -> server -> SMTP."""

import smtplib
from email.message import EmailMessage
from pathlib import Path

import pytest

from errorworks.smtp.config import load_config
from errorworks.smtp.server import ChaosSMTPServer

pytestmark = pytest.mark.integration


def _message() -> EmailMessage:
    message = EmailMessage()
    message["From"] = "sender@example.com"
    message["To"] = "recipient@example.com"
    message["Subject"] = "Integration test"
    message.set_content("hello")
    return message


def _server_from_preset(
    tmp_path: Path,
    preset: str,
    *,
    config_file: Path | None = None,
    cli_overrides: dict[str, object] | None = None,
) -> ChaosSMTPServer:
    overrides: dict[str, object] = {
        "smtp": {"port": 0},
        "metrics": {"database": str(tmp_path / f"{preset}.db")},
        "latency": {"base_ms": 0, "jitter_ms": 0},
    }
    if cli_overrides:
        overrides.update(cli_overrides)
    config = load_config(preset=preset, config_file=config_file, cli_overrides=overrides)
    return ChaosSMTPServer(config)


def test_silent_preset_accepts_message(tmp_path: Path) -> None:
    server = _server_from_preset(tmp_path, "silent")
    server.start()
    try:
        with smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client:
            result = client.send_message(_message())

        assert result == {}
        assert server.get_stats()["total_requests"] == 1
        assert server.export_metrics()["messages"][0]["subject"] == "Integration test"
    finally:
        server.stop()


def test_config_overlay_can_force_recipient_reject(tmp_path: Path) -> None:
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text("error_injection:\n  rcpt_to_reject_pct: 100.0\n")
    server = _server_from_preset(tmp_path, "silent", config_file=overlay)
    server.start()
    try:
        with (
            smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client,
            pytest.raises(smtplib.SMTPRecipientsRefused) as exc_info,
        ):
            client.send_message(_message())

        refused = exc_info.value.recipients["recipient@example.com"]
        assert refused[0] == 550
        assert server.get_stats()["total_requests"] == 1
        assert server.get_stats()["requests_by_outcome"] == {"permfailed": 1}
    finally:
        server.stop()
