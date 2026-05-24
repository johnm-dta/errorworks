# ChaosSMTP Guide

ChaosSMTP is a fake SMTP receiving server that injects configurable faults into outbound email delivery tests. Point an SMTP client at ChaosSMTP instead of a real mail server to verify retries, permanent failure handling, capture behavior, and delivery metrics before production mail leaves your system.

ChaosSMTP never relays mail. It accepts, rejects, drops, or captures messages locally for tests.

## Quick Start

```bash
# Start with a production-like delivery fault profile
uv run chaossmtp serve --preset=realistic

# Or use the unified CLI
uv run chaosengine smtp serve --preset=realistic
```

The SMTP listener binds to `127.0.0.1:2525` by default. The HTTP admin sidecar binds to `127.0.0.1:8525`.

## Send a Message with smtplib

```python
from email.message import EmailMessage
import smtplib

message = EmailMessage()
message["From"] = "sender@example.com"
message["To"] = "recipient@example.com"
message["Subject"] = "ChaosSMTP test"
message.set_content("hello from a resilience test")

with smtplib.SMTP("127.0.0.1", 2525, timeout=5) as client:
    refused = client.send_message(message)

assert refused == {}
```

Use normal `smtplib` exceptions to assert failure handling:

```python
import smtplib

try:
    with smtplib.SMTP("127.0.0.1", 2525, timeout=5) as client:
        client.send_message(message)
except smtplib.SMTPRecipientsRefused as exc:
    print(exc.recipients)
except smtplib.SMTPDataError as exc:
    print(exc.smtp_code, exc.smtp_error)
```

## SMTP Listener Defaults

| Setting | Default | Description |
|---|---:|---|
| SMTP host | `127.0.0.1` | Loopback-only bind by default. |
| SMTP port | `2525` | Non-privileged SMTP test port. |
| SMTP hostname | `chaossmtp.local` | Hostname announced to clients. |
| DATA size limit | `10485760` | Maximum DATA payload in bytes. |
| SMTPUTF8 | `true` | Enables SMTPUTF8 support. |
| STARTTLS required | `false` | STARTTLS is not required by default. |
| Admin host | `127.0.0.1` | Loopback-only HTTP admin sidecar. |
| Admin port | `8525` | HTTP admin sidecar port. |
| Metrics database | `file:chaossmtp-metrics?mode=memory&cache=shared` | Shared in-memory SQLite metrics store. |
| Capture mode | `metadata` | Store envelope metadata and safe headers. |

In YAML config, `smtp.port: 0` asks the OS for an ephemeral loopback port. This is useful for fixtures and integration tests. The CLI `--port` flag accepts explicit ports from 1 to 65535.

Binding the SMTP listener or admin sidecar to all interfaces is blocked by default. Set `allow_external_bind: true` only for controlled local test environments.

## Error Injection

ChaosSMTP injects faults at SMTP stages. Percent fields are floats from `0.0` to `100.0`. The current server invokes decisions for MAIL, RCPT, DATA, and ACCEPT handling; CONNECT-stage schema fields are accepted by config and CLI but are not currently called by the listener.

| Error Type | Stage | Config Field | Typical Reply or Behavior |
|---|---|---|---|
| Rate limit | MAIL/RCPT | `rate_limit_pct` | `450 4.7.0 Mailbox temporarily unavailable due to rate limiting` |
| MAIL FROM temporary failure | MAIL | `mail_from_tempfail_pct` | `451 4.3.0 Temporary sender failure` |
| MAIL FROM permanent rejection | MAIL | `mail_from_reject_pct` | `550 5.1.0 Sender rejected` |
| RCPT TO temporary failure | RCPT | `rcpt_to_tempfail_pct` | `451 4.3.0 Temporary recipient failure` |
| RCPT TO permanent rejection | RCPT | `rcpt_to_reject_pct` | `550 5.1.1 Recipient rejected` |
| DATA temporary failure | DATA | `data_tempfail_pct` | `451 4.3.0 Temporary message failure` |
| DATA permanent rejection | DATA | `data_reject_pct` | `554 5.6.0 Message rejected` |
| Accepted then dropped | ACCEPT | `accept_then_drop_pct` | Returns `250`, records `accepted_then_dropped`, and does not capture the message. |
| Banner rejection | CONNECT | `banner_reject_pct` | Schema/CLI field exists; current listener does not invoke CONNECT-stage injection. |
| Malformed reply | DATA | `malformed_reply_pct` | Writes a malformed SMTP reply and closes the transport. |
| Wrong reply code | DATA | `wrong_reply_code_pct` | Returns an unexpected `252` reply and records `malformed_protocol`. |
| Connection reset | MAIL/RCPT/DATA | `connection_reset_pct` | Closes the SMTP transport. |
| Connection stall | MAIL/RCPT/DATA | `connection_stall_pct` | Sleeps for `connection_stall_sec`, then closes the SMTP transport. |
| Slow response | MAIL/RCPT/DATA | `slow_response_pct` | Adds `slow_response_sec` delay, then continues the normal SMTP path. |

The `selection_mode` field controls how active errors are chosen:

- `priority` (default): each stage evaluates its configured errors in a fixed order.
- `weighted`: active percentages are treated as weights for a single selection roll.

Burst mode temporarily raises temporary failure and rate-limit percentages:

```yaml
error_injection:
  burst:
    enabled: true
    interval_sec: 60
    duration_sec: 8
    tempfail_pct: 50.0
    rate_limit_pct: 40.0
```

## Capture Modes

ChaosSMTP records accepted messages according to `capture.mode`:

| Mode | What Gets Stored | Use When |
|---|---|---|
| `discard` | Metrics only; no captured message list. | You only need delivery outcomes and latency. |
| `metadata` | Envelope sender, recipients, size, subject, and safe headers. | Default for most tests. |
| `full` | Metadata plus base64-encoded message bytes up to `max_message_bytes`. | You need to assert body content or MIME structure. |

`metadata` and `full` captures are returned under `messages` in `/admin/export` and via the fixture's `export_metrics()` helper.

## Admin Sidecar

ChaosSMTP uses a real SMTP listener plus a separate HTTP admin sidecar for health, metrics, export, reset, and runtime configuration updates.

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/health` | GET | None | Health check with `smtp_running`, `run_id`, `started_utc`, and `in_burst`. |
| `/admin/config` | GET | Bearer token | View runtime-updatable config (`error_injection`, `capture`, `latency`). |
| `/admin/config` | POST | Bearer token | Update runtime config with a partial JSON object. |
| `/admin/stats` | GET | Bearer token | Metrics summary for the current run. |
| `/admin/export` | GET | Bearer token | Raw metrics, captured messages, and run config. |
| `/admin/reset` | POST | Bearer token | Clear metrics and captured messages, then start a new run. |

Admin endpoints require `Authorization: Bearer <admin_token>`. The token is auto-generated unless you set `admin.admin_token` in config or `--admin-token` on the CLI. `chaossmtp show-config` redacts this token, but the running admin endpoints still require it.

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://127.0.0.1:8525/admin/stats

curl -X POST http://127.0.0.1:8525/admin/config \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"error_injection": {"rcpt_to_tempfail_pct": 25.0}}'
```

## Pytest Fixture

The `chaossmtp_server` fixture starts ChaosSMTP on an ephemeral loopback TCP port because standard SMTP clients require a real socket.

```python
from email.message import EmailMessage

def test_mail_delivery(chaossmtp_server):
    message = EmailMessage()
    message["From"] = "sender@example.com"
    message["To"] = "recipient@example.com"
    message["Subject"] = "Fixture test"
    message.set_content("hello")

    assert chaossmtp_server.send_message(message) == {}
    assert chaossmtp_server.wait_for_messages(1)
    assert chaossmtp_server.get_stats()["total_requests"] == 1
```

Use marker kwargs to set presets and error percentages:

```python
import pytest
import smtplib
from email.message import EmailMessage

@pytest.mark.chaossmtp(rcpt_to_reject_pct=100.0)
def test_recipient_rejection(chaossmtp_server):
    message = EmailMessage()
    message["From"] = "sender@example.com"
    message["To"] = "recipient@example.com"
    message["Subject"] = "Fixture test"
    message.set_content("hello")

    with pytest.raises(smtplib.SMTPRecipientsRefused):
        chaossmtp_server.send_message(message)
```

## Related Pages

- [Presets](presets.md) -- Full preset comparison and customization
- [Configuration](configuration.md) -- YAML config file structure and precedence rules
- [Metrics](metrics.md) -- SMTP metrics fields and captured messages
- [Testing Fixtures](testing-fixtures.md) -- Fixture setup and marker options
