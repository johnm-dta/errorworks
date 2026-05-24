"""Tests for the ChaosSMTP pytest fixture."""

import smtplib
from email.message import EmailMessage

import pytest


def _message() -> EmailMessage:
    message = EmailMessage()
    message["From"] = "sender@example.com"
    message["To"] = "recipient@example.com"
    message["Subject"] = "Fixture test"
    message.set_content("hello")
    return message


def test_fixture_sends_message(chaossmtp_server) -> None:
    result = chaossmtp_server.send_message(_message())

    assert result == {}
    assert chaossmtp_server.wait_for_messages(1, timeout=1.0)
    assert chaossmtp_server.get_stats()["total_requests"] == 1
    assert chaossmtp_server.export_metrics()["messages"][0]["subject"] == "Fixture test"


def test_fixture_update_config_can_force_recipient_reject(chaossmtp_server) -> None:
    chaossmtp_server.update_config(rcpt_to_reject_pct=100.0)

    with pytest.raises(smtplib.SMTPRecipientsRefused):
        chaossmtp_server.send_message(_message())

    assert chaossmtp_server.wait_for_requests(1, timeout=1.0)
    assert not chaossmtp_server.wait_for_messages(1, timeout=0.05)
    assert chaossmtp_server.get_stats()["total_requests"] == 1
    assert chaossmtp_server.export_metrics()["messages"] == []


@pytest.mark.chaossmtp(rcpt_to_reject_pct=100.0)
def test_fixture_marker_can_force_recipient_reject(chaossmtp_server) -> None:
    with pytest.raises(smtplib.SMTPRecipientsRefused):
        chaossmtp_server.send_message(_message())

    assert chaossmtp_server.wait_for_requests(1, timeout=1.0)
    assert not chaossmtp_server.wait_for_messages(1, timeout=0.05)
    assert chaossmtp_server.get_stats()["requests_by_outcome"] == {"permfailed": 1}


@pytest.mark.chaossmtp(preset="silent", base_ms=7)
def test_fixture_marker_deep_merges_partial_latency_override(chaossmtp_server) -> None:
    latency = chaossmtp_server.server.get_current_config()["latency"]

    assert latency["base_ms"] == 7
    assert latency["jitter_ms"] == 0
