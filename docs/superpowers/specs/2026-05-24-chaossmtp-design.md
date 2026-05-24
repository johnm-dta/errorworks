# ChaosSMTP Server

**Date:** 2026-05-24
**Status:** Approved
**Author:** Codex

## Summary

Add a third chaos domain, `ChaosSMTP`, for testing outbound email clients against
a fake SMTP receiving server. The feature fits the existing errorworks
composition model, but it should not be implemented as a direct Starlette/ASGI
copy of ChaosLLM or ChaosWeb. SMTP is a stateful TCP protocol, so the SMTP
listener should use an SMTP protocol library and expose the existing HTTP admin
surface through a sidecar admin app.

Implementation note: the landed implementation intentionally defers
CONNECT/banner-stage injection until there is a real listener hook for the SMTP
banner. `require_starttls: true` is rejected until TLS context configuration is
exposed. Message capture also includes a bounded `max_messages` buffer.

## Orientation Findings

The current project shape supports this direction:

- `docs/architecture.md` already describes new server types such as email,
  gRPC, and GraphQL as expected extensions of the shared engine.
- `docs/superpowers/specs/2026-03-16-professionalize-package-design.md`
  explicitly planned the docs structure so future email-style domains could be
  added without restructuring.
- ChaosLLM and ChaosWeb both compose the same shared engine components:
  `InjectionEngine`, `MetricsStore`, `LatencySimulator`, and config loading via
  Pydantic models and presets.
- Runtime admin behavior is shared through `engine.admin.ChaosServer`, but that
  implementation is HTTP/Starlette-specific. SMTP has no natural `/admin/*`
  route surface.
- The project targets Python 3.12+, where the old standard-library `smtpd`
  module is not available. A new SMTP server should use `aiosmtpd` or a custom
  asyncio protocol implementation, not `smtpd`.
- Filigree has no current SMTP/email issue. The closest future-facing tracker
  item is `errorworks-b7c9325bcf`, "New Chaos Domains (Queue, Storage, Auth)".

## Decision

Proceed with a `ChaosSMTP` design, with these constraints:

1. Use a domain-specific SMTP listener instead of trying to make SMTP look like
   an HTTP ASGI app.
2. Keep the shared engine composition pattern: domain-specific config, error
   injector, metrics recorder, capture component, CLI, presets, docs, and tests.
3. Keep runtime admin parity by running a small HTTP admin sidecar that delegates
   to the existing `engine.admin` handlers.
4. Treat real loopback sockets as acceptable for SMTP tests and document that
   this is the exception to the existing "no sockets" fixture story.
5. Do not build a production mail relay. ChaosSMTP accepts or rejects messages
   for tests; it never relays mail externally.

## Alternatives Considered

### Recommended: `aiosmtpd` Listener Plus HTTP Admin Sidecar

Use `aiosmtpd` for the SMTP protocol listener, implement domain behavior in a
handler plus a small custom SMTP protocol subclass where handler hooks are not
enough, and run an optional Starlette admin sidecar for `/health` and
`/admin/*`.

Pros:

- Matches Python 3.12 reality.
- Avoids hand-rolling SMTP parsing and multiline reply handling.
- Preserves the existing runtime admin/config/metrics ergonomics.
- Lets tests exercise real `smtplib` behavior over loopback sockets.

Cons:

- Adds a new runtime dependency.
- The server is no longer a pure ASGI app.
- Some failure modes, such as malformed replies or banner-level disconnects,
  may require custom protocol hooks rather than handler-only code.

### Lower Dependency: Custom `asyncio.Protocol` SMTP Server

Implement only the subset of SMTP needed for tests directly with asyncio.

Pros:

- No new dependency.
- Full control over malformed protocol replies and connection-level failures.

Cons:

- High protocol risk for low product value.
- Easy to accidentally build an incomplete or non-compliant SMTP server.
- More maintenance burden than the current web/LLM adapters.

### Simulated Email over HTTP

Expose an HTTP endpoint that accepts email-like payloads and injects email
delivery errors.

Pros:

- Reuses the current ASGI shape and fixtures exactly.
- Lowest implementation effort.

Cons:

- Does not test real SMTP clients, SMTP reply codes, EHLO/MAIL/RCPT/DATA
  behavior, or transport failures.
- Does not satisfy the requested "SMTP server" capability.

## Proposed Package Shape

```text
src/errorworks/smtp/
├── __init__.py
├── cli.py
├── config.py
├── error_injector.py
├── metrics.py
├── message_capture.py
├── server.py
└── presets/
    ├── silent.yaml
    ├── gentle.yaml
    ├── realistic.yaml
    ├── stress_delivery.yaml
    └── stress_extreme.yaml

tests/unit/smtp/
├── test_cli.py
├── test_config.py
├── test_error_injector.py
├── test_message_capture.py
├── test_metrics.py
└── test_server.py

tests/integration/test_smtp_pipeline.py
tests/fixtures/chaossmtp.py
docs/guide/chaossmtp.md
```

Add console scripts and unified CLI mounting:

```toml
chaossmtp = "errorworks.smtp.cli:main"
```

```python
app.add_typer(smtp_app, name="smtp", help="ChaosSMTP: Fake SMTP server for outbound email resilience testing.")
```

## Configuration Model

`ChaosSMTPConfig` should follow the current Pydantic style:

- `frozen=True`
- `extra="forbid"`
- config precedence: CLI flags > config file > preset > defaults
- runtime updates create new component instances and swap references under a
  lock

Top-level sections:

```yaml
smtp:
  host: 127.0.0.1
  port: 2525
  hostname: chaossmtp.local
  data_size_limit: 10485760
  enable_smtputf8: true
  require_starttls: false  # true rejected until TLS context support exists

admin:
  enabled: true
  host: 127.0.0.1
  port: 8525
  admin_token: generated

metrics:
  database: file:chaossmtp-metrics?mode=memory&cache=shared
  timeseries_bucket_sec: 1

latency:
  base_ms: 50
  jitter_ms: 30

capture:
  mode: metadata
  max_message_bytes: 1048576
  max_messages: 1000

error_injection:
  selection_mode: priority
  rate_limit_pct: 0.0
  mail_from_tempfail_pct: 0.0
  mail_from_reject_pct: 0.0
  rcpt_to_tempfail_pct: 0.0
  rcpt_to_reject_pct: 0.0
  data_tempfail_pct: 0.0
  data_reject_pct: 0.0
  accept_then_drop_pct: 0.0
  malformed_reply_pct: 0.0
  connection_reset_pct: 0.0
  connection_stall_pct: 0.0
  slow_response_pct: 0.0
  burst:
    enabled: false
    interval_sec: 30
    duration_sec: 5
    tempfail_pct: 80.0
    rate_limit_pct: 50.0
```

Do not reuse the existing `ServerConfig` unchanged for the SMTP listener. Its
`workers` field and uvicorn-oriented validation are HTTP-server concerns.
Instead, create `SMTPServerConfig` and `AdminConfig`. Reuse `MetricsConfig` and
`LatencyConfig`.

`capture.mode` values:

- `discard`: accept mail but store no envelope or body details beyond metrics.
- `metadata`: store envelope metadata, recipient count, size, and selected safe
  headers. This is the default.
- `full`: store full message bytes up to `max_message_bytes` for test fixtures.
- `max_messages`: cap stored message records and drop oldest records first.

## Error Model

SMTP errors should be grouped by protocol stage. This is clearer than trying to
reuse HTTP labels like "server_error" directly.

### Session and Connection Failures

| Field | Behavior |
| --- | --- |
| `connection_reset_pct` | Drop the connection during the selected SMTP stage. |
| `connection_stall_pct` | Stall, then disconnect. |
| `slow_response_pct` | Delay before returning an otherwise valid SMTP reply. |

### SMTP Command Failures

| Field | Typical Reply | Behavior |
| --- | --- | --- |
| `rate_limit_pct` | `421` or `450` | Simulate provider throttling. |
| `mail_from_tempfail_pct` | `451` | Temporary sender rejection. |
| `mail_from_reject_pct` | `550` | Permanent sender rejection. |
| `rcpt_to_tempfail_pct` | `450` or `451` | Temporary recipient rejection. |
| `rcpt_to_reject_pct` | `550` or `553` | Permanent recipient rejection. |
| `data_tempfail_pct` | `451` | Temporary failure after DATA. |
| `data_reject_pct` | `554` | Permanent transaction failure after DATA. |
| `accept_then_drop_pct` | `250`, then do not capture | Simulate accepted-but-lost delivery. |

### Protocol Malformations

| Field | Behavior |
| --- | --- |
| `malformed_reply_pct` | Emit an invalid reply line or incomplete multiline reply. |
| `wrong_reply_code_pct` | Return a syntactically valid but semantically unexpected code. |

Some protocol malformations may require a custom `aiosmtpd.smtp.SMTP`
subclass. Implementation should start with a spike proving the selected library
can inject banner, command, and DATA-stage failures cleanly.

## Runtime Data Flow

1. `chaossmtp serve` loads config using the shared config loader.
2. `ChaosSMTPServer` builds `SMTPErrorInjector`, `MessageCapture`,
   `LatencySimulator`, and `SMTPMetricsRecorder`.
3. The SMTP listener starts on `smtp.host:smtp.port`.
4. If `admin.enabled` is true, an HTTP admin sidecar starts on
   `admin.host:admin.port`.
5. Each SMTP stage snapshots component references under `_config_lock`.
6. The injector decides whether to inject a stage-appropriate behavior.
7. The server applies latency or connection behavior, returns the SMTP reply,
   captures message metadata/body when appropriate, and records metrics.
8. `POST /admin/config` deep-merges updates, validates new config sections,
   builds new components outside the lock, and swaps them atomically.

## Admin Surface

Admin parity should match ChaosLLM and ChaosWeb:

| Endpoint | Description |
| --- | --- |
| `GET /health` | Sidecar health, SMTP listener status, `run_id`, `started_utc`, `in_burst`. |
| `GET /admin/config` | Current `error_injection`, `capture`, and `latency` config. |
| `POST /admin/config` | Runtime update for those sections. |
| `GET /admin/stats` | Metrics summary. |
| `GET /admin/export` | Raw SMTP transactions, timeseries, and config. |
| `POST /admin/reset` | Reset metrics, capture state, and injector burst timing. |

The sidecar should reuse `engine.admin` handlers where possible. If the health
handler needs to diverge, keep it local to `smtp.server`.

## Metrics Schema

Record one row per SMTP transaction attempt, plus aggregate timeseries rows.

Recommended request columns:

- `transaction_id`
- `session_id`
- `timestamp_utc`
- `client_addr`
- `mail_from`
- `rcpt_count`
- `rcpt_domains`
- `message_size_bytes`
- `subject`
- `outcome`
- `smtp_stage`
- `reply_code`
- `enhanced_status_code`
- `error_type`
- `injection_type`
- `latency_ms`
- `injected_delay_ms`
- `capture_mode`
- `tls_used`
- `auth_username`

Default capture must avoid storing full message bodies in metrics. Full body
capture belongs behind `capture.mode: full`, with truncation enforced by
`max_message_bytes`.

Recommended timeseries counters:

- `requests_total`
- `messages_accepted`
- `messages_tempfailed`
- `messages_permfailed`
- `messages_connection_error`
- `messages_malformed_protocol`
- `messages_accepted_then_dropped`
- `avg_latency_ms`
- `p99_latency_ms`

## CLI Surface

```bash
chaossmtp serve --preset=realistic
chaossmtp serve --port=2525 --admin-port=8525 --database=./smtp-metrics.db
chaossmtp serve --rcpt-to-tempfail-pct=25 --data-reject-pct=5
chaossmtp presets
chaossmtp show-config --preset=stress_delivery

chaosengine smtp serve --preset=realistic
```

The default SMTP port should be `2525`, not `25`, so local development does not
require elevated privileges.

## Presets

Use the same naming pattern as the current servers:

- `silent`: no failures, low latency, metadata capture.
- `gentle`: low temporary failure rate, suitable for basic retry tests.
- `realistic`: modest rate-limit and temporary DATA failures, mild latency,
  periodic burst. If greylisting lands in the first implementation, include a
  low greylisting rate here.
- `stress_delivery`: high temporary and permanent recipient/DATA failures for
  email queue retry and dead-letter behavior.
- `stress_extreme`: every category active, including connection and malformed
  protocol failures.

Greylisting is valuable for SMTP but stateful. Include it only if the first
implementation can store a stable envelope fingerprint and retry state without
fighting the current request-aware/stateful work. Otherwise, defer greylisting
to a follow-up requirement.

## Test Strategy

Unit tests:

- Config defaults, validation, serialization round-trip, and preset loading.
- Error injector deterministic decisions with seeded RNG.
- Metrics classification and timeseries aggregation.
- Message capture modes, truncation, and safe metadata extraction.
- CLI config override assembly and `show-config`.

Integration tests:

- Start `ChaosSMTPServer` on an ephemeral loopback port and send mail with
  `smtplib.SMTP`.
- Verify successful `send_message` captures metadata and updates stats.
- Verify 100% `rcpt_to_tempfail_pct` produces a temporary SMTP failure.
- Verify 100% `rcpt_to_reject_pct` produces a permanent SMTP failure.
- Verify 100% `data_reject_pct` rejects after DATA.
- Verify admin config updates affect subsequent SMTP transactions.
- Verify reset clears metrics and capture state.

Fixture:

- Add `chaossmtp_server` with helper methods such as `send_message()`,
  `update_config()`, `get_stats()`, `export_metrics()`, `reset()`, and
  `wait_for_messages()`.
- Use an ephemeral loopback port by default. This is the explicit exception to
  the current no-socket fixture model.

## Documentation Updates

Add:

- README feature bullet and quick usage mention.
- `docs/guide/chaossmtp.md`.
- SMTP sections in `docs/reference/cli.md`, `docs/reference/api.md`, and
  `docs/reference/config-schema.md`.
- `docs/guide/presets.md` SMTP preset table.
- `docs/guide/testing-fixtures.md` SMTP fixture section that explains the
  loopback socket exception.
- `docs/architecture.md` package tree and new-server example update.

## Security and Safety

- Bind SMTP and admin listeners to `127.0.0.1` by default.
- Block `0.0.0.0`, `::`, and equivalent all-interface binds unless
  `allow_external_bind: true`.
- Never relay messages. Return SMTP replies and capture locally only.
- Do not store message bodies by default.
- Redact or omit auth secrets from metrics and exports.
- Keep admin token out of run-info exports, matching ChaosLLM/ChaosWeb.
- STARTTLS and SMTP AUTH can be added later, but the initial server should not
  pretend to provide production-grade mail security.

## Acceptance Criteria

- `uv run chaossmtp serve --preset=realistic` starts an SMTP listener on
  `127.0.0.1:2525` and an admin sidecar on `127.0.0.1:8525`.
- A standard Python `smtplib.SMTP` client can send a message to the silent
  preset and receive successful SMTP replies.
- Config precedence matches existing servers.
- Runtime admin update, stats, export, and reset work for SMTP.
- Metrics record SMTP stage, reply code, outcome, error type, latency, and
  capture mode.
- CLI, docs, presets, unit tests, and integration tests are present.
- No outbound SMTP relay behavior exists.

## Implementation Notes

Implementation should begin with a small spike against `aiosmtpd` to prove the
failure hooks:

1. Normal message acceptance and capture.
2. RCPT-stage temporary and permanent rejection.
3. DATA-stage rejection.
4. Banner reject or connection close.
5. Admin sidecar sharing the same `ChaosSMTPServer` instance.

If the spike shows that malformed replies or banner-level behaviors require too
much custom protocol code, keep those as phase-two work and ship the first
server with command-stage failures, latency, capture, metrics, presets, CLI, and
admin parity.

## References

- Python 3.12 `smtpd` removal and `aiosmtpd` recommendation:
  https://docs.python.org/3.12/library/smtpd.html
- `aiosmtpd` project documentation:
  https://aiosmtpd.aio-libs.org/
- `aiosmtpd.smtp` API and controller customization:
  https://aiosmtpd.aio-libs.org/en/latest/smtp.html
