"""Tests for ChaosSMTP message capture."""

from email.message import EmailMessage

from errorworks.smtp.config import SMTPCaptureConfig
from errorworks.smtp.message_capture import MessageCapture


def _message_bytes() -> bytes:
    message = EmailMessage()
    message["From"] = "sender@example.com"
    message["To"] = "recipient@example.com"
    message["Subject"] = "Delivery test"
    message.set_content("hello from chaossmtp")
    return message.as_bytes()


def test_discard_mode_captures_only_counts() -> None:
    capture = MessageCapture(SMTPCaptureConfig(mode="discard"))
    record = capture.capture(
        transaction_id="tx-1",
        mail_from="sender@example.com",
        rcpt_tos=["recipient@example.com"],
        data=_message_bytes(),
    )
    assert record.subject is None
    assert record.headers == {}
    assert record.body is None
    assert record.message_size_bytes > 0
    assert capture.list_messages() == []


def test_metadata_mode_stores_safe_headers() -> None:
    capture = MessageCapture(SMTPCaptureConfig(mode="metadata"))
    record = capture.capture(
        transaction_id="tx-1",
        mail_from="sender@example.com",
        rcpt_tos=["recipient@example.com"],
        data=_message_bytes(),
    )
    assert record.subject == "Delivery test"
    assert record.headers["from"] == "sender@example.com"
    assert record.headers["to"] == "recipient@example.com"
    assert record.body is None
    assert capture.list_messages()[0].transaction_id == "tx-1"


def test_full_mode_truncates_body_bytes() -> None:
    capture = MessageCapture(SMTPCaptureConfig(mode="full", max_message_bytes=20))
    record = capture.capture(
        transaction_id="tx-1",
        mail_from="sender@example.com",
        rcpt_tos=["recipient@example.com"],
        data=_message_bytes(),
    )
    assert record.body is not None
    assert len(record.body) == 20
    assert record.truncated is True


def test_reset_clears_captured_messages() -> None:
    capture = MessageCapture(SMTPCaptureConfig(mode="metadata"))
    capture.capture(
        transaction_id="tx-1",
        mail_from="sender@example.com",
        rcpt_tos=["recipient@example.com"],
        data=_message_bytes(),
    )
    assert len(capture.list_messages()) == 1
    capture.reset()
    assert capture.list_messages() == []
