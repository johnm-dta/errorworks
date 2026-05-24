# ChaosSMTP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `ChaosSMTP`, a fake SMTP receiving server that injects SMTP-stage failures, records metrics, supports runtime admin updates, and fits the existing errorworks composition model.

**Architecture:** Add `src/errorworks/smtp/` as a third domain beside `llm` and `web`. The SMTP listener uses `aiosmtpd` for real SMTP protocol handling, composes the shared `InjectionEngine`, `MetricsStore`, `LatencySimulator`, and config loader, and exposes admin parity through a Starlette sidecar app owned by `ChaosSMTPServer`.

**Tech Stack:** Python 3.12+, `aiosmtpd>=1.4.6,<2`, Pydantic v2, Typer, Starlette, uvicorn, SQLite-backed `MetricsStore`, `smtplib` integration tests, pytest.

**Spec:** `docs/superpowers/specs/2026-05-24-chaossmtp-design.md`

---

## File Responsibility Map

Create these SMTP package files:

- `src/errorworks/smtp/__init__.py`: public exports and package docstring.
- `src/errorworks/smtp/config.py`: `ChaosSMTPConfig`, `SMTPServerConfig`, `SMTPAdminConfig`, `SMTPCaptureConfig`, `SMTPErrorInjectionConfig`, `SMTPBurstConfig`, preset loading, and config precedence.
- `src/errorworks/smtp/message_capture.py`: safe envelope/message capture with discard, metadata, and full modes.
- `src/errorworks/smtp/error_injector.py`: SMTP-stage error decision model over `InjectionEngine`.
- `src/errorworks/smtp/metrics.py`: SMTP metrics schema and typed recorder.
- `src/errorworks/smtp/server.py`: `ChaosSMTPServer`, `aiosmtpd` handler/controller integration, admin sidecar app, runtime config swap, metrics recording.
- `src/errorworks/smtp/cli.py`: standalone `chaossmtp` CLI and config flag mapping.
- `src/errorworks/smtp/presets/*.yaml`: `silent`, `gentle`, `realistic`, `stress_delivery`, and `stress_extreme`.

Modify these shared project files:

- `pyproject.toml`: add `aiosmtpd` dependency, console script, pytest marker.
- `src/errorworks/__init__.py`: add `smtp` to `__all__`.
- `src/errorworks/engine/cli.py`: mount SMTP Typer app as `chaosengine smtp`.
- `mkdocs.yml`: add ChaosSMTP guide nav entry.
- `README.md`, `docs/index.md`, `docs/architecture.md`, `docs/guide/*`, `docs/reference/*`: document the new server.

Create these tests and fixtures:

- `tests/unit/smtp/conftest.py`: expose `chaossmtp_server`.
- `tests/unit/smtp/test_config.py`: config defaults, validation, preset loading, serialization.
- `tests/unit/smtp/test_message_capture.py`: capture modes and truncation.
- `tests/unit/smtp/test_error_injector.py`: deterministic stage decisions.
- `tests/unit/smtp/test_metrics.py`: metrics schema and outcome aggregation.
- `tests/unit/smtp/test_server.py`: server lifecycle, admin app, successful SMTP transactions, runtime updates.
- `tests/unit/smtp/test_cli.py`: CLI config override assembly and output.
- `tests/integration/test_smtp_pipeline.py`: preset-to-config-to-server pipeline with `smtplib`.
- `tests/fixtures/chaossmtp.py`: pytest fixture with real loopback socket helpers.

## Implementation Rules

- Keep all config models frozen and `extra="forbid"`.
- Do not use the removed standard-library `smtpd` module.
- Do not relay mail externally.
- Bind SMTP and admin listeners to `127.0.0.1` by default.
- Store message bodies only when `capture.mode == "full"`.
- Use file-backed metrics databases whenever tests start a real listener.
- Follow the existing config snapshot pattern before SMTP stage handling.
- Keep every slice independently testable and committable.

---

## Task 1: Add Dependency, Package Shell, and Public CLI Wiring

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/errorworks/__init__.py`
- Modify: `src/errorworks/engine/cli.py`
- Create: `src/errorworks/smtp/__init__.py`
- Create: `src/errorworks/smtp/cli.py`
- Test: `tests/unit/smtp/test_cli.py`
- Test: `tests/unit/smtp/conftest.py`

- [ ] **Step 1: Write the failing package and CLI tests**

Create `tests/unit/smtp/test_cli.py`:

```python
"""Tests for ChaosSMTP CLI entry points."""

from typer.testing import CliRunner

from errorworks.engine.cli import app as engine_app
from errorworks.smtp.cli import app


runner = CliRunner()


def test_chaossmtp_cli_has_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "ChaosSMTP" in result.stdout
    assert "serve" in result.stdout
    assert "presets" in result.stdout


def test_chaosengine_mounts_smtp_subcommand() -> None:
    result = runner.invoke(engine_app, ["--help"])
    assert result.exit_code == 0
    assert "smtp" in result.stdout
```

Create `tests/unit/smtp/conftest.py`:

```python
"""Conftest for ChaosSMTP unit tests."""
```

- [ ] **Step 2: Run the tests to verify the missing package fails**

Run:

```bash
uv run pytest tests/unit/smtp/test_cli.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'errorworks.smtp'`.

- [ ] **Step 3: Add the package shell and minimal CLI**

Add `aiosmtpd` and the console script to `pyproject.toml`:

```toml
dependencies = [
    # SMTP server
    "aiosmtpd>=1.4.6,<2",
]

[project.scripts]
chaossmtp = "errorworks.smtp.cli:main"
```

Keep the existing dependency and script entries; insert the new dependency near the HTTP server dependencies and the new script near `chaosweb`.

Add the pytest marker to `pyproject.toml`:

```toml
markers = [
    "chaossmtp: Configure ChaosSMTP server for the test",
]
```

Modify `src/errorworks/__init__.py`:

```python
__all__ = [
    "__version__",
    "engine",
    "llm",
    "llm_mcp",
    "smtp",
    "testing",
    "web",
]
```

Create `src/errorworks/smtp/cli.py`:

```python
"""CLI for ChaosSMTP fake SMTP server."""

from __future__ import annotations

import typer

app = typer.Typer(
    name="chaossmtp",
    help="ChaosSMTP: Fake SMTP server for outbound email resilience testing.",
    no_args_is_help=True,
)


@app.command()
def serve() -> None:
    """Start the ChaosSMTP fake SMTP server."""
    typer.echo("ChaosSMTP serve requires the server implementation from Task 9.", err=True)
    raise typer.Exit(2)


@app.command()
def presets() -> None:
    """List available preset configurations."""
    typer.echo("No presets found.")


def main() -> None:
    """Entry point for chaossmtp CLI."""
    app()


if __name__ == "__main__":
    main()
```

Create `src/errorworks/smtp/__init__.py`:

```python
"""ChaosSMTP: Fake SMTP server for outbound email resilience testing."""

__all__ = [
    "cli",
]
```

Modify `src/errorworks/engine/cli.py`:

```python
from errorworks.smtp.cli import app as smtp_app

app.add_typer(smtp_app, name="smtp", help="ChaosSMTP: Fake SMTP server for outbound email resilience testing.")
```

- [ ] **Step 4: Run the package and CLI tests**

Run:

```bash
uv run pytest tests/unit/smtp/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 5: Run import sorting/formatting for touched files**

Run:

```bash
uv run ruff format src/errorworks/smtp src/errorworks/engine/cli.py tests/unit/smtp/test_cli.py
uv run ruff check --fix src/errorworks/smtp src/errorworks/engine/cli.py tests/unit/smtp/test_cli.py
```

Expected: PASS or fixed files only.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/errorworks/__init__.py src/errorworks/engine/cli.py src/errorworks/smtp tests/unit/smtp
git commit -m "feat: add ChaosSMTP package and CLI shell"
```

---

## Task 2: Build SMTP Configuration and Presets

**Files:**
- Create: `src/errorworks/smtp/config.py`
- Create: `src/errorworks/smtp/presets/silent.yaml`
- Create: `src/errorworks/smtp/presets/gentle.yaml`
- Create: `src/errorworks/smtp/presets/realistic.yaml`
- Create: `src/errorworks/smtp/presets/stress_delivery.yaml`
- Create: `src/errorworks/smtp/presets/stress_extreme.yaml`
- Modify: `src/errorworks/smtp/__init__.py`
- Test: `tests/unit/smtp/test_config.py`

- [ ] **Step 1: Write failing config tests**

Create `tests/unit/smtp/test_config.py`:

```python
"""Tests for ChaosSMTP configuration."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from errorworks.smtp.config import (
    ChaosSMTPConfig,
    SMTPAdminConfig,
    SMTPCaptureConfig,
    SMTPErrorInjectionConfig,
    SMTPServerConfig,
    list_presets,
    load_config,
)


def test_default_config_uses_loopback_ports() -> None:
    config = ChaosSMTPConfig()
    assert config.smtp.host == "127.0.0.1"
    assert config.smtp.port == 2525
    assert config.admin.host == "127.0.0.1"
    assert config.admin.port == 8525
    assert config.capture.mode == "metadata"


def test_config_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ChaosSMTPConfig(unknown=True)


def test_external_bind_blocked_by_default() -> None:
    with pytest.raises(ValidationError, match="exposes ChaosSMTP"):
        ChaosSMTPConfig(smtp={"host": "0.0.0.0"})


def test_external_bind_can_be_explicitly_allowed() -> None:
    config = ChaosSMTPConfig(smtp=SMTPServerConfig(host="0.0.0.0"), allow_external_bind=True)
    assert config.smtp.host == "0.0.0.0"


def test_workers_are_not_part_of_smtp_config() -> None:
    with pytest.raises(ValidationError):
        SMTPServerConfig(workers=2)


def test_capture_mode_values() -> None:
    assert SMTPCaptureConfig(mode="discard").mode == "discard"
    assert SMTPCaptureConfig(mode="metadata").mode == "metadata"
    assert SMTPCaptureConfig(mode="full").mode == "full"
    with pytest.raises(ValidationError):
        SMTPCaptureConfig(mode="raw")


def test_range_fields_accept_lists() -> None:
    config = SMTPErrorInjectionConfig(retry_after_sec=[2, 7], connection_stall_sec=[3, 9])
    assert config.retry_after_sec == (2, 7)
    assert config.connection_stall_sec == (3, 9)


def test_invalid_range_rejected() -> None:
    with pytest.raises(ValidationError, match="retry_after_sec"):
        SMTPErrorInjectionConfig(retry_after_sec=[10, 1])


def test_admin_config_has_token() -> None:
    config = SMTPAdminConfig()
    assert config.admin_token


def test_list_presets_contains_expected_names() -> None:
    assert set(list_presets()) == {"silent", "gentle", "realistic", "stress_delivery", "stress_extreme"}


def test_all_presets_load() -> None:
    for preset in list_presets():
        config = load_config(preset=preset)
        assert isinstance(config, ChaosSMTPConfig)
        assert config.preset_name == preset


def test_config_file_overlay(tmp_path: Path) -> None:
    overlay = tmp_path / "smtp.yaml"
    overlay.write_text(yaml.dump({"error_injection": {"rcpt_to_tempfail_pct": 100.0}}))
    config = load_config(preset="silent", config_file=overlay)
    assert config.error_injection.rcpt_to_tempfail_pct == 100.0


def test_cli_overrides_win(tmp_path: Path) -> None:
    overlay = tmp_path / "smtp.yaml"
    overlay.write_text(yaml.dump({"smtp": {"port": 2526}}))
    config = load_config(
        preset="silent",
        config_file=overlay,
        cli_overrides={"smtp": {"port": 2527}},
    )
    assert config.smtp.port == 2527
```

- [ ] **Step 2: Run config tests to verify failure**

Run:

```bash
uv run pytest tests/unit/smtp/test_config.py -q
```

Expected: FAIL because `errorworks.smtp.config` does not exist.

- [ ] **Step 3: Implement config models and loader**

Create `src/errorworks/smtp/config.py` with this structure:

```python
"""Configuration schema and loading for ChaosSMTP server."""

from __future__ import annotations

import secrets
import warnings
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from errorworks.engine.config_loader import list_presets as _list_presets
from errorworks.engine.config_loader import load_config as _load_config
from errorworks.engine.config_loader import load_preset as _load_preset
from errorworks.engine.types import DANGEROUS_BIND_HOSTS, LatencyConfig, MetricsConfig
from errorworks.engine.validators import parse_range as _parse_range
from errorworks.engine.validators import validate_ranges as _validate_ranges

DEFAULT_MEMORY_DB = "file:chaossmtp-metrics?mode=memory&cache=shared"


class SMTPServerConfig(BaseModel):
    """SMTP listener binding and protocol configuration."""

    model_config = {"frozen": True, "extra": "forbid"}

    host: str = Field(default="127.0.0.1", min_length=1, pattern=r"^[a-zA-Z0-9.:\[\]-]+$")
    port: int = Field(default=2525, gt=0, le=65535)
    hostname: str = Field(default="chaossmtp.local", min_length=1)
    data_size_limit: int = Field(default=10_485_760, gt=0)
    enable_smtputf8: bool = True
    require_starttls: bool = False


class SMTPAdminConfig(BaseModel):
    """HTTP admin sidecar configuration."""

    model_config = {"frozen": True, "extra": "forbid"}

    enabled: bool = True
    host: str = Field(default="127.0.0.1", min_length=1, pattern=r"^[a-zA-Z0-9.:\[\]-]+$")
    port: int = Field(default=8525, gt=0, le=65535)
    admin_token: str = Field(default_factory=lambda: secrets.token_urlsafe(32), min_length=1)


class SMTPCaptureConfig(BaseModel):
    """Message capture configuration."""

    model_config = {"frozen": True, "extra": "forbid"}

    mode: Literal["discard", "metadata", "full"] = "metadata"
    max_message_bytes: int = Field(default=1_048_576, ge=0)


class SMTPBurstConfig(BaseModel):
    """Burst pattern configuration for SMTP temporary failures."""

    model_config = {"frozen": True, "extra": "forbid"}

    enabled: bool = False
    interval_sec: int = Field(default=30, gt=0)
    duration_sec: int = Field(default=5, gt=0)
    tempfail_pct: float = Field(default=80.0, ge=0.0, le=100.0)
    rate_limit_pct: float = Field(default=50.0, ge=0.0, le=100.0)

    @model_validator(mode="after")
    def validate_timing(self) -> "SMTPBurstConfig":
        if self.enabled and self.duration_sec >= self.interval_sec:
            raise ValueError(
                f"duration_sec ({self.duration_sec}) must be less than interval_sec ({self.interval_sec}) when burst is enabled"
            )
        return self


class SMTPErrorInjectionConfig(BaseModel):
    """SMTP-stage error injection configuration."""

    model_config = {"frozen": True, "extra": "forbid"}

    rate_limit_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    mail_from_tempfail_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    mail_from_reject_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    rcpt_to_tempfail_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    rcpt_to_reject_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    data_tempfail_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    data_reject_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    accept_then_drop_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    banner_reject_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    malformed_reply_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    wrong_reply_code_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    connection_reset_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    connection_stall_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    slow_response_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    retry_after_sec: tuple[int, int] = (1, 30)
    connection_stall_sec: tuple[int, int] = (30, 60)
    slow_response_sec: tuple[int, int] = (3, 15)
    burst: SMTPBurstConfig = Field(default_factory=SMTPBurstConfig)
    selection_mode: Literal["priority", "weighted"] = "priority"

    @field_validator("retry_after_sec", "connection_stall_sec", "slow_response_sec", mode="before")
    @classmethod
    def parse_range(cls, value: Any) -> tuple[int, int]:
        return _parse_range(value)

    @model_validator(mode="after")
    def validate_ranges(self) -> "SMTPErrorInjectionConfig":
        _validate_ranges(
            {
                "retry_after_sec": self.retry_after_sec,
                "connection_stall_sec": self.connection_stall_sec,
                "slow_response_sec": self.slow_response_sec,
            }
        )
        return self

    @model_validator(mode="after")
    def warn_total_percentage(self) -> "SMTPErrorInjectionConfig":
        if self.selection_mode != "weighted":
            return self
        total = sum(getattr(self, name) for name in type(self).model_fields if name.endswith("_pct"))
        if total >= 100.0:
            warnings.warn(
                f"Total SMTP error percentages ({total:.1f}%) reach or exceed 100% in weighted mode. No successful messages will be generated.",
            )
        return self


class ChaosSMTPConfig(BaseModel):
    """Top-level ChaosSMTP configuration."""

    model_config = {"frozen": True, "extra": "forbid"}

    smtp: SMTPServerConfig = Field(default_factory=SMTPServerConfig)
    admin: SMTPAdminConfig = Field(default_factory=SMTPAdminConfig)
    metrics: MetricsConfig = Field(default_factory=lambda: MetricsConfig(database=DEFAULT_MEMORY_DB))
    latency: LatencyConfig = Field(default_factory=LatencyConfig)
    capture: SMTPCaptureConfig = Field(default_factory=SMTPCaptureConfig)
    error_injection: SMTPErrorInjectionConfig = Field(default_factory=SMTPErrorInjectionConfig)
    preset_name: str | None = None
    allow_external_bind: bool = False

    @model_validator(mode="after")
    def validate_host_binding(self) -> "ChaosSMTPConfig":
        dangerous = self.smtp.host in DANGEROUS_BIND_HOSTS or self.admin.host in DANGEROUS_BIND_HOSTS
        if dangerous and not self.allow_external_bind:
            raise ValueError(
                "Binding ChaosSMTP to all interfaces exposes ChaosSMTP to the network. "
                "Use allow_external_bind: true to override, or bind to 127.0.0.1."
            )
        return self


def _get_presets_dir() -> Path:
    return Path(__file__).parent / "presets"


def list_presets() -> list[str]:
    return _list_presets(_get_presets_dir())


def load_preset(preset_name: str) -> dict[str, Any]:
    return _load_preset(_get_presets_dir(), preset_name)


def load_config(
    *,
    preset: str | None = None,
    config_file: Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> ChaosSMTPConfig:
    return _load_config(
        ChaosSMTPConfig,
        _get_presets_dir(),
        preset=preset,
        config_file=config_file,
        cli_overrides=cli_overrides,
    )
```

Update `src/errorworks/smtp/__init__.py` exports:

```python
from errorworks.smtp.config import (
    DEFAULT_MEMORY_DB,
    ChaosSMTPConfig,
    SMTPAdminConfig,
    SMTPBurstConfig,
    SMTPCaptureConfig,
    SMTPErrorInjectionConfig,
    SMTPServerConfig,
    list_presets,
    load_config,
    load_preset,
)

__all__ = [
    "DEFAULT_MEMORY_DB",
    "ChaosSMTPConfig",
    "SMTPAdminConfig",
    "SMTPBurstConfig",
    "SMTPCaptureConfig",
    "SMTPErrorInjectionConfig",
    "SMTPServerConfig",
    "list_presets",
    "load_config",
    "load_preset",
]
```

- [ ] **Step 4: Add presets**

Create `src/errorworks/smtp/presets/silent.yaml`:

```yaml
# ChaosSMTP Preset: silent
latency:
  base_ms: 10
  jitter_ms: 5
capture:
  mode: metadata
error_injection:
  selection_mode: priority
```

Create `src/errorworks/smtp/presets/gentle.yaml`:

```yaml
# ChaosSMTP Preset: gentle
latency:
  base_ms: 50
  jitter_ms: 20
capture:
  mode: metadata
error_injection:
  selection_mode: priority
  rcpt_to_tempfail_pct: 1.0
  data_tempfail_pct: 1.0
```

Create `src/errorworks/smtp/presets/realistic.yaml`:

```yaml
# ChaosSMTP Preset: realistic
latency:
  base_ms: 120
  jitter_ms: 60
capture:
  mode: metadata
error_injection:
  selection_mode: priority
  rate_limit_pct: 3.0
  rcpt_to_tempfail_pct: 4.0
  data_tempfail_pct: 3.0
  data_reject_pct: 1.0
  slow_response_pct: 2.0
  burst:
    enabled: true
    interval_sec: 60
    duration_sec: 8
    tempfail_pct: 50.0
    rate_limit_pct: 40.0
```

Create `src/errorworks/smtp/presets/stress_delivery.yaml`:

```yaml
# ChaosSMTP Preset: stress_delivery
latency:
  base_ms: 200
  jitter_ms: 100
capture:
  mode: metadata
error_injection:
  selection_mode: priority
  rate_limit_pct: 10.0
  mail_from_tempfail_pct: 5.0
  rcpt_to_tempfail_pct: 15.0
  rcpt_to_reject_pct: 8.0
  data_tempfail_pct: 12.0
  data_reject_pct: 8.0
  accept_then_drop_pct: 2.0
  slow_response_pct: 5.0
  burst:
    enabled: true
    interval_sec: 45
    duration_sec: 10
    tempfail_pct: 80.0
    rate_limit_pct: 70.0
```

Create `src/errorworks/smtp/presets/stress_extreme.yaml`:

```yaml
# ChaosSMTP Preset: stress_extreme
latency:
  base_ms: 300
  jitter_ms: 200
capture:
  mode: metadata
error_injection:
  selection_mode: weighted
  rate_limit_pct: 15.0
  mail_from_tempfail_pct: 8.0
  mail_from_reject_pct: 5.0
  rcpt_to_tempfail_pct: 15.0
  rcpt_to_reject_pct: 10.0
  data_tempfail_pct: 12.0
  data_reject_pct: 10.0
  accept_then_drop_pct: 5.0
  connection_reset_pct: 4.0
  connection_stall_pct: 3.0
  slow_response_pct: 8.0
  malformed_reply_pct: 2.0
  wrong_reply_code_pct: 2.0
  burst:
    enabled: true
    interval_sec: 30
    duration_sec: 8
    tempfail_pct: 90.0
    rate_limit_pct: 85.0
```

- [ ] **Step 5: Run config tests**

Run:

```bash
uv run pytest tests/unit/smtp/test_config.py -q
```

Expected: PASS.

- [ ] **Step 6: Run formatting and targeted type check**

Run:

```bash
uv run ruff format src/errorworks/smtp/config.py src/errorworks/smtp/__init__.py tests/unit/smtp/test_config.py
uv run ruff check --fix src/errorworks/smtp/config.py src/errorworks/smtp/__init__.py tests/unit/smtp/test_config.py
uv run mypy src/errorworks/smtp/config.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/errorworks/smtp tests/unit/smtp/test_config.py
git commit -m "feat: add ChaosSMTP configuration and presets"
```

---

## Task 3: Add Message Capture

**Files:**
- Create: `src/errorworks/smtp/message_capture.py`
- Modify: `src/errorworks/smtp/__init__.py`
- Test: `tests/unit/smtp/test_message_capture.py`

- [ ] **Step 1: Write failing message capture tests**

Create `tests/unit/smtp/test_message_capture.py`:

```python
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
```

- [ ] **Step 2: Run capture tests to verify failure**

Run:

```bash
uv run pytest tests/unit/smtp/test_message_capture.py -q
```

Expected: FAIL because `message_capture.py` does not exist.

- [ ] **Step 3: Implement message capture**

Create `src/errorworks/smtp/message_capture.py`:

```python
"""Message capture helpers for ChaosSMTP."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser

from errorworks.smtp.config import SMTPCaptureConfig

_SAFE_HEADERS = ("from", "to", "cc", "bcc", "subject", "message-id", "date")


@dataclass(frozen=True, slots=True)
class CapturedMessage:
    """Captured SMTP message data."""

    transaction_id: str
    mail_from: str
    rcpt_tos: tuple[str, ...]
    message_size_bytes: int
    subject: str | None
    headers: dict[str, str]
    body: bytes | None
    truncated: bool


class MessageCapture:
    """Capture SMTP messages according to configured storage mode."""

    def __init__(self, config: SMTPCaptureConfig) -> None:
        self._config = config
        self._messages: list[CapturedMessage] = []
        self._lock = threading.Lock()

    @property
    def config(self) -> SMTPCaptureConfig:
        return self._config

    def capture(
        self,
        *,
        transaction_id: str,
        mail_from: str,
        rcpt_tos: list[str],
        data: bytes,
    ) -> CapturedMessage:
        parsed = BytesParser(policy=policy.default).parsebytes(data)
        safe_headers = {
            name: str(parsed[name])
            for name in _SAFE_HEADERS
            if parsed[name] is not None
        }
        subject = safe_headers.get("subject")
        body: bytes | None = None
        truncated = False
        if self._config.mode == "full":
            limit = self._config.max_message_bytes
            body = data[:limit]
            truncated = len(data) > limit

        record = CapturedMessage(
            transaction_id=transaction_id,
            mail_from=mail_from,
            rcpt_tos=tuple(rcpt_tos),
            message_size_bytes=len(data),
            subject=subject if self._config.mode != "discard" else None,
            headers=safe_headers if self._config.mode != "discard" else {},
            body=body,
            truncated=truncated,
        )

        if self._config.mode != "discard":
            with self._lock:
                self._messages.append(record)
        return record

    def list_messages(self) -> list[CapturedMessage]:
        with self._lock:
            return list(self._messages)

    def reset(self) -> None:
        with self._lock:
            self._messages.clear()
```

Update `src/errorworks/smtp/__init__.py`:

```python
from errorworks.smtp.message_capture import CapturedMessage, MessageCapture

__all__ = [
    "CapturedMessage",
    "MessageCapture",
]
```

Keep the config exports from Task 2.

- [ ] **Step 4: Run capture tests**

Run:

```bash
uv run pytest tests/unit/smtp/test_message_capture.py -q
```

Expected: PASS.

- [ ] **Step 5: Run formatting and targeted type check**

Run:

```bash
uv run ruff format src/errorworks/smtp/message_capture.py src/errorworks/smtp/__init__.py tests/unit/smtp/test_message_capture.py
uv run ruff check --fix src/errorworks/smtp/message_capture.py src/errorworks/smtp/__init__.py tests/unit/smtp/test_message_capture.py
uv run mypy src/errorworks/smtp/message_capture.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/errorworks/smtp/message_capture.py src/errorworks/smtp/__init__.py tests/unit/smtp/test_message_capture.py
git commit -m "feat: add ChaosSMTP message capture"
```

---

## Task 4: Add SMTP Error Injector

**Files:**
- Create: `src/errorworks/smtp/error_injector.py`
- Modify: `src/errorworks/smtp/__init__.py`
- Test: `tests/unit/smtp/test_error_injector.py`

- [ ] **Step 1: Write failing error injector tests**

Create `tests/unit/smtp/test_error_injector.py`:

```python
"""Tests for ChaosSMTP error injection."""

import random

from errorworks.smtp.config import SMTPErrorInjectionConfig
from errorworks.smtp.error_injector import SMTPErrorCategory, SMTPErrorInjector, SMTPStage


def test_success_when_no_percentages_enabled() -> None:
    injector = SMTPErrorInjector(SMTPErrorInjectionConfig(), rng=random.Random(1))
    decision = injector.decide(SMTPStage.RCPT)
    assert decision.error_type is None
    assert decision.reply_code is None


def test_rcpt_tempfail_maps_to_451() -> None:
    injector = SMTPErrorInjector(SMTPErrorInjectionConfig(rcpt_to_tempfail_pct=100.0), rng=random.Random(1))
    decision = injector.decide(SMTPStage.RCPT)
    assert decision.error_type == "rcpt_to_tempfail"
    assert decision.reply_code == 451
    assert decision.category == SMTPErrorCategory.COMMAND


def test_rcpt_reject_maps_to_550() -> None:
    injector = SMTPErrorInjector(SMTPErrorInjectionConfig(rcpt_to_reject_pct=100.0), rng=random.Random(1))
    decision = injector.decide(SMTPStage.RCPT)
    assert decision.error_type == "rcpt_to_reject"
    assert decision.reply_code == 550


def test_data_reject_maps_to_554() -> None:
    injector = SMTPErrorInjector(SMTPErrorInjectionConfig(data_reject_pct=100.0), rng=random.Random(1))
    decision = injector.decide(SMTPStage.DATA)
    assert decision.error_type == "data_reject"
    assert decision.reply_code == 554


def test_stage_filters_unrelated_errors() -> None:
    injector = SMTPErrorInjector(SMTPErrorInjectionConfig(data_reject_pct=100.0), rng=random.Random(1))
    decision = injector.decide(SMTPStage.RCPT)
    assert decision.error_type is None


def test_burst_overrides_tempfail_rates() -> None:
    calls = iter([0.0, 1.0])
    injector = SMTPErrorInjector(
        SMTPErrorInjectionConfig(
            burst={"enabled": True, "interval_sec": 30, "duration_sec": 5, "tempfail_pct": 100.0},
        ),
        rng=random.Random(1),
        time_func=lambda: next(calls),
    )
    decision = injector.decide(SMTPStage.RCPT)
    assert decision.error_type == "rcpt_to_tempfail"


def test_reset_clears_burst_state() -> None:
    injector = SMTPErrorInjector(SMTPErrorInjectionConfig(burst={"enabled": True}), rng=random.Random(1))
    injector.is_in_burst()
    injector.reset()
    assert isinstance(injector.is_in_burst(), bool)
```

- [ ] **Step 2: Run injector tests to verify failure**

Run:

```bash
uv run pytest tests/unit/smtp/test_error_injector.py -q
```

Expected: FAIL because `error_injector.py` does not exist.

- [ ] **Step 3: Implement stage-aware decisions**

Create `src/errorworks/smtp/error_injector.py`:

```python
"""Error injection logic for ChaosSMTP."""

from __future__ import annotations

import random as random_module
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from errorworks.engine.injection_engine import InjectionEngine
from errorworks.engine.types import BurstConfig as EngineBurstConfig
from errorworks.engine.types import ErrorSpec
from errorworks.smtp.config import SMTPErrorInjectionConfig


class SMTPStage(StrEnum):
    CONNECT = "connect"
    MAIL = "mail"
    RCPT = "rcpt"
    DATA = "data"
    ACCEPT = "accept"


class SMTPErrorCategory(StrEnum):
    COMMAND = "command"
    CONNECTION = "connection"
    MALFORMED = "malformed"


@dataclass(frozen=True, slots=True)
class SMTPErrorDecision:
    """Result of an SMTP error injection decision."""

    error_type: str | None
    stage: SMTPStage | None = None
    reply_code: int | None = None
    message: str | None = None
    category: SMTPErrorCategory | None = None
    delay_sec: float | None = None

    @classmethod
    def success(cls) -> "SMTPErrorDecision":
        return cls(error_type=None)

    @property
    def should_inject(self) -> bool:
        return self.error_type is not None

    @property
    def reply_line(self) -> str:
        if self.reply_code is None or self.message is None:
            raise ValueError("SMTPErrorDecision has no reply line")
        return f"{self.reply_code} {self.message}"


_STAGE_TAGS: dict[SMTPStage, tuple[str, ...]] = {
    SMTPStage.CONNECT: ("banner_reject", "connection_reset", "connection_stall", "slow_response", "malformed_reply", "wrong_reply_code"),
    SMTPStage.MAIL: ("mail_from_tempfail", "mail_from_reject", "rate_limit", "connection_reset", "connection_stall", "slow_response"),
    SMTPStage.RCPT: ("rcpt_to_tempfail", "rcpt_to_reject", "rate_limit", "connection_reset", "connection_stall", "slow_response"),
    SMTPStage.DATA: ("data_tempfail", "data_reject", "connection_reset", "connection_stall", "slow_response", "malformed_reply", "wrong_reply_code"),
    SMTPStage.ACCEPT: ("accept_then_drop",),
}


class SMTPErrorInjector:
    """Decides per-stage SMTP error injection behavior."""

    def __init__(
        self,
        config: SMTPErrorInjectionConfig,
        *,
        time_func: Callable[[], float] | None = None,
        rng: random_module.Random | None = None,
    ) -> None:
        self._config = config
        self._rng = rng if rng is not None else random_module.Random()
        self._engine = InjectionEngine(
            selection_mode=config.selection_mode,
            burst_config=EngineBurstConfig(
                enabled=config.burst.enabled,
                interval_sec=config.burst.interval_sec,
                duration_sec=config.burst.duration_sec,
            ),
            time_func=time_func,
            rng=self._rng,
        )

    @property
    def config(self) -> SMTPErrorInjectionConfig:
        return self._config

    def _pick_delay(self, value_range: tuple[int, int]) -> float:
        return self._rng.uniform(*value_range)

    def _build_specs(self, stage: SMTPStage) -> list[ErrorSpec]:
        in_burst = self._engine.is_in_burst()
        tempfail_pct = self._config.burst.tempfail_pct if in_burst else self._config.rcpt_to_tempfail_pct
        rate_limit_pct = self._config.burst.rate_limit_pct if in_burst else self._config.rate_limit_pct
        weights = {
            "rate_limit": rate_limit_pct,
            "mail_from_tempfail": self._config.mail_from_tempfail_pct,
            "mail_from_reject": self._config.mail_from_reject_pct,
            "rcpt_to_tempfail": tempfail_pct,
            "rcpt_to_reject": self._config.rcpt_to_reject_pct,
            "data_tempfail": self._config.data_tempfail_pct,
            "data_reject": self._config.data_reject_pct,
            "accept_then_drop": self._config.accept_then_drop_pct,
            "banner_reject": self._config.banner_reject_pct,
            "malformed_reply": self._config.malformed_reply_pct,
            "wrong_reply_code": self._config.wrong_reply_code_pct,
            "connection_reset": self._config.connection_reset_pct,
            "connection_stall": self._config.connection_stall_pct,
            "slow_response": self._config.slow_response_pct,
        }
        return [ErrorSpec(tag, weights[tag]) for tag in _STAGE_TAGS[stage]]

    def _build_decision(self, stage: SMTPStage, tag: str) -> SMTPErrorDecision:
        if tag == "rate_limit":
            return SMTPErrorDecision(tag, stage, 450, "4.7.0 Mailbox temporarily unavailable due to rate limiting", SMTPErrorCategory.COMMAND)
        if tag == "mail_from_tempfail":
            return SMTPErrorDecision(tag, stage, 451, "4.3.0 Temporary sender failure", SMTPErrorCategory.COMMAND)
        if tag == "mail_from_reject":
            return SMTPErrorDecision(tag, stage, 550, "5.1.0 Sender rejected", SMTPErrorCategory.COMMAND)
        if tag == "rcpt_to_tempfail":
            return SMTPErrorDecision(tag, stage, 451, "4.3.0 Temporary recipient failure", SMTPErrorCategory.COMMAND)
        if tag == "rcpt_to_reject":
            return SMTPErrorDecision(tag, stage, 550, "5.1.1 Recipient rejected", SMTPErrorCategory.COMMAND)
        if tag == "data_tempfail":
            return SMTPErrorDecision(tag, stage, 451, "4.3.0 Temporary message failure", SMTPErrorCategory.COMMAND)
        if tag == "data_reject":
            return SMTPErrorDecision(tag, stage, 554, "5.6.0 Message rejected", SMTPErrorCategory.COMMAND)
        if tag == "accept_then_drop":
            return SMTPErrorDecision(tag, stage, 250, "2.0.0 Accepted but dropped by chaos policy", SMTPErrorCategory.COMMAND)
        if tag == "banner_reject":
            return SMTPErrorDecision(tag, stage, 421, "4.3.2 Service not available", SMTPErrorCategory.COMMAND)
        if tag == "malformed_reply":
            return SMTPErrorDecision(tag, stage, 299, "malformed reply", SMTPErrorCategory.MALFORMED)
        if tag == "wrong_reply_code":
            return SMTPErrorDecision(tag, stage, 252, "2.5.2 Cannot VRFY user, accepting chaos path", SMTPErrorCategory.MALFORMED)
        if tag == "connection_reset":
            return SMTPErrorDecision(tag, stage, category=SMTPErrorCategory.CONNECTION)
        if tag == "connection_stall":
            return SMTPErrorDecision(
                tag,
                stage,
                category=SMTPErrorCategory.CONNECTION,
                delay_sec=self._pick_delay(self._config.connection_stall_sec),
            )
        if tag == "slow_response":
            return SMTPErrorDecision(
                tag,
                stage,
                category=SMTPErrorCategory.CONNECTION,
                delay_sec=self._pick_delay(self._config.slow_response_sec),
            )
        raise ValueError(f"Unknown SMTP error tag: {tag}")

    def decide(self, stage: SMTPStage) -> SMTPErrorDecision:
        selected = self._engine.select(self._build_specs(stage))
        if selected is None:
            return SMTPErrorDecision.success()
        return self._build_decision(stage, selected.tag)

    def reset(self) -> None:
        self._engine.reset()

    def is_in_burst(self) -> bool:
        return self._engine.is_in_burst()
```

Update `src/errorworks/smtp/__init__.py`:

```python
from errorworks.smtp.error_injector import SMTPErrorCategory, SMTPErrorDecision, SMTPErrorInjector, SMTPStage

__all__ = [
    "SMTPErrorCategory",
    "SMTPErrorDecision",
    "SMTPErrorInjector",
    "SMTPStage",
]
```

Keep prior exports.

- [ ] **Step 4: Run injector tests**

Run:

```bash
uv run pytest tests/unit/smtp/test_error_injector.py -q
```

Expected: PASS.

- [ ] **Step 5: Run formatting and targeted type check**

Run:

```bash
uv run ruff format src/errorworks/smtp/error_injector.py src/errorworks/smtp/__init__.py tests/unit/smtp/test_error_injector.py
uv run ruff check --fix src/errorworks/smtp/error_injector.py src/errorworks/smtp/__init__.py tests/unit/smtp/test_error_injector.py
uv run mypy src/errorworks/smtp/error_injector.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/errorworks/smtp/error_injector.py src/errorworks/smtp/__init__.py tests/unit/smtp/test_error_injector.py
git commit -m "feat: add ChaosSMTP stage-aware error injector"
```

---

## Task 5: Add SMTP Metrics Recorder

**Files:**
- Create: `src/errorworks/smtp/metrics.py`
- Modify: `src/errorworks/smtp/__init__.py`
- Test: `tests/unit/smtp/test_metrics.py`

- [ ] **Step 1: Write failing metrics tests**

Create `tests/unit/smtp/test_metrics.py`:

```python
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
```

- [ ] **Step 2: Run metrics tests to verify failure**

Run:

```bash
uv run pytest tests/unit/smtp/test_metrics.py -q
```

Expected: FAIL because `metrics.py` does not exist.

- [ ] **Step 3: Implement metrics schema and recorder**

Create `src/errorworks/smtp/metrics.py`:

```python
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
```

Update `src/errorworks/smtp/__init__.py`:

```python
from errorworks.smtp.metrics import SMTPMetricsRecorder

__all__ = [
    "SMTPMetricsRecorder",
]
```

Keep prior exports.

- [ ] **Step 4: Run metrics tests**

Run:

```bash
uv run pytest tests/unit/smtp/test_metrics.py -q
```

Expected: PASS.

- [ ] **Step 5: Run formatting and targeted type check**

Run:

```bash
uv run ruff format src/errorworks/smtp/metrics.py src/errorworks/smtp/__init__.py tests/unit/smtp/test_metrics.py
uv run ruff check --fix src/errorworks/smtp/metrics.py src/errorworks/smtp/__init__.py tests/unit/smtp/test_metrics.py
uv run mypy src/errorworks/smtp/metrics.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/errorworks/smtp/metrics.py src/errorworks/smtp/__init__.py tests/unit/smtp/test_metrics.py
git commit -m "feat: add ChaosSMTP metrics recorder"
```

---

## Task 6: Implement SMTP Listener and Successful Delivery

**Files:**
- Create: `src/errorworks/smtp/server.py`
- Modify: `src/errorworks/smtp/__init__.py`
- Test: `tests/unit/smtp/test_server.py`
- Test: `tests/fixtures/chaossmtp.py`
- Modify: `tests/unit/smtp/conftest.py`

- [ ] **Step 1: Write failing server lifecycle and delivery tests**

Create `tests/unit/smtp/test_server.py`:

```python
"""Tests for ChaosSMTP server."""

from email.message import EmailMessage
import smtplib

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
        smtp=SMTPServerConfig(port=0),
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
```

- [ ] **Step 2: Run server tests to verify failure**

Run:

```bash
uv run pytest tests/unit/smtp/test_server.py -q
```

Expected: FAIL because `server.py` does not exist.

- [ ] **Step 3: Implement initial server, handler, and admin app**

Create `src/errorworks/smtp/server.py` with these public surfaces:

```python
"""SMTP listener and admin sidecar for ChaosSMTP."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

import structlog
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import Envelope, Session
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from errorworks.engine import admin
from errorworks.engine.config_loader import deep_merge
from errorworks.engine.latency import LatencySimulator
from errorworks.engine.types import LatencyConfig
from errorworks.smtp.config import ChaosSMTPConfig, SMTPCaptureConfig, SMTPErrorInjectionConfig
from errorworks.smtp.error_injector import SMTPErrorCategory, SMTPErrorDecision, SMTPErrorInjector, SMTPStage
from errorworks.smtp.message_capture import CapturedMessage, MessageCapture
from errorworks.smtp.metrics import SMTPMetricsRecorder

logger = structlog.get_logger(__name__)


class _ChaosSMTPHandler:
    """aiosmtpd handler that delegates SMTP stages to ChaosSMTPServer."""

    def __init__(self, owner: ChaosSMTPServer) -> None:
        self._owner = owner

    async def handle_MAIL(self, server: Any, session: Session, envelope: Envelope, address: str, mail_options: list[str]) -> str:
        decision = await self._owner.handle_stage(SMTPStage.MAIL, session=session, mail_from=address)
        if decision.should_inject:
            return decision.reply_line
        envelope.mail_from = address
        envelope.mail_options.extend(mail_options)
        return "250 2.1.0 OK"

    async def handle_RCPT(self, server: Any, session: Session, envelope: Envelope, address: str, rcpt_options: list[str]) -> str:
        decision = await self._owner.handle_stage(SMTPStage.RCPT, session=session, rcpt_to=address)
        if decision.should_inject:
            return decision.reply_line
        envelope.rcpt_tos.append(address)
        envelope.rcpt_options.extend(rcpt_options)
        return "250 2.1.5 OK"

    async def handle_DATA(self, server: Any, session: Session, envelope: Envelope) -> str:
        return await self._owner.handle_data(session=session, envelope=envelope)
```

In the same file, implement `ChaosSMTPServer`:

```python
class ChaosSMTPServer:
    """Main ChaosSMTP server class."""

    def __init__(self, config: ChaosSMTPConfig) -> None:
        self._config = config
        self._config_lock = threading.Lock()
        self._error_injector = SMTPErrorInjector(config.error_injection)
        self._capture = MessageCapture(config.capture)
        self._latency_simulator = LatencySimulator(config.latency)
        self._metrics_recorder = SMTPMetricsRecorder(config.metrics)
        self._controller: Controller | None = None
        self._record_run_info()
        self._admin_app = create_admin_app(self)

    @property
    def admin_app(self) -> Starlette:
        return self._admin_app

    @property
    def run_id(self) -> str:
        return self._metrics_recorder.run_id

    @property
    def smtp_host(self) -> str:
        return self._config.smtp.host

    @property
    def smtp_port(self) -> int:
        if self._controller is not None and self._controller.server is not None and self._controller.server.sockets:
            return int(self._controller.server.sockets[0].getsockname()[1])
        return self._config.smtp.port

    @property
    def smtp_running(self) -> bool:
        return self._controller is not None

    def start(self) -> None:
        if self._controller is not None:
            return
        self._controller = Controller(
            _ChaosSMTPHandler(self),
            hostname=self._config.smtp.host,
            port=self._config.smtp.port,
            ready_timeout=5.0,
        )
        self._controller.start()

    def stop(self) -> None:
        if self._controller is not None:
            self._controller.stop()
            self._controller = None

    def get_admin_token(self) -> str:
        return self._config.admin.admin_token

    def get_stats(self) -> dict[str, Any]:
        return self._metrics_recorder.get_stats()

    def export_metrics(self) -> dict[str, Any]:
        data = self._metrics_recorder.export_data()
        data["messages"] = [asdict(message) for message in self._capture.list_messages()]
        data["config"] = {
            "smtp": self._config.smtp.model_dump(),
            "admin": self._config.admin.model_dump(exclude={"admin_token"}),
            "metrics": self._config.metrics.model_dump(),
            **self.get_current_config(),
        }
        return data

    def list_messages(self) -> list[CapturedMessage]:
        return self._capture.list_messages()

    def reset(self) -> str:
        self._error_injector.reset()
        self._capture.reset()
        self._metrics_recorder.reset()
        self._record_run_info()
        return self._metrics_recorder.run_id
```

Add request handling and record helpers in `ChaosSMTPServer`:

```python
    async def handle_stage(
        self,
        stage: SMTPStage,
        *,
        session: Session,
        mail_from: str | None = None,
        rcpt_to: str | None = None,
    ) -> SMTPErrorDecision:
        with self._config_lock:
            error_injector = self._error_injector
            latency_simulator = self._latency_simulator
        decision = error_injector.decide(stage)
        delay = latency_simulator.simulate()
        if decision.delay_sec is not None:
            delay += decision.delay_sec
        if delay > 0:
            await asyncio.sleep(delay)
        if decision.should_inject:
            self._record_transaction(
                session=session,
                outcome=_outcome_for_decision(decision),
                stage=stage,
                decision=decision,
                mail_from=mail_from,
                rcpt_count=1 if rcpt_to else None,
                latency_ms=delay * 1000,
                injected_delay_ms=decision.delay_sec * 1000 if decision.delay_sec else None,
            )
        return decision

    async def handle_data(self, *, session: Session, envelope: Envelope) -> str:
        start = time.monotonic()
        with self._config_lock:
            error_injector = self._error_injector
            capture = self._capture
            latency_simulator = self._latency_simulator
        decision = error_injector.decide(SMTPStage.DATA)
        delay = latency_simulator.simulate()
        if decision.delay_sec is not None:
            delay += decision.delay_sec
        if delay > 0:
            await asyncio.sleep(delay)
        elapsed_ms = (time.monotonic() - start) * 1000
        if decision.should_inject:
            self._record_transaction(
                session=session,
                outcome=_outcome_for_decision(decision),
                stage=SMTPStage.DATA,
                decision=decision,
                mail_from=envelope.mail_from,
                rcpt_count=len(envelope.rcpt_tos),
                rcpt_tos=list(envelope.rcpt_tos),
                message_size_bytes=len(envelope.content or b""),
                latency_ms=elapsed_ms,
                injected_delay_ms=decision.delay_sec * 1000 if decision.delay_sec else None,
            )
            return decision.reply_line
        transaction_id = str(uuid.uuid4())
        captured = capture.capture(
            transaction_id=transaction_id,
            mail_from=envelope.mail_from or "",
            rcpt_tos=list(envelope.rcpt_tos),
            data=envelope.content or b"",
        )
        self._record_transaction(
            session=session,
            outcome="success",
            stage=SMTPStage.DATA,
            transaction_id=transaction_id,
            mail_from=envelope.mail_from,
            rcpt_count=len(envelope.rcpt_tos),
            rcpt_tos=list(envelope.rcpt_tos),
            message_size_bytes=captured.message_size_bytes,
            subject=captured.subject,
            reply_code=250,
            latency_ms=elapsed_ms,
        )
        return "250 2.0.0 OK"
```

Add helper functions:

```python
def _outcome_for_decision(decision: SMTPErrorDecision) -> str:
    if decision.category == SMTPErrorCategory.CONNECTION:
        return "connection_error"
    if decision.category == SMTPErrorCategory.MALFORMED:
        return "malformed_protocol"
    if decision.error_type == "accept_then_drop":
        return "accepted_then_dropped"
    if decision.reply_code is not None and 400 <= decision.reply_code < 500:
        return "tempfailed"
    if decision.reply_code is not None and 500 <= decision.reply_code < 600:
        return "permfailed"
    return "error_injected"
```

Add `_record_transaction`, `_record_run_info`, `get_current_config`, and `update_config` using the same deep-merge pattern as LLM/Web. In this task, `update_config` must support `error_injection`, `capture`, and `latency`.

Add `create_admin_app(server)`:

```python
def create_admin_app(server: ChaosSMTPServer) -> Starlette:
    routes = [
        Route("/health", server._health_endpoint, methods=["GET"]),
        Route("/admin/config", server._admin_config_endpoint, methods=["GET", "POST"]),
        Route("/admin/stats", server._admin_stats_endpoint, methods=["GET"]),
        Route("/admin/reset", server._admin_reset_endpoint, methods=["POST"]),
        Route("/admin/export", server._admin_export_endpoint, methods=["GET"]),
    ]
    app = Starlette(debug=False, routes=routes)
    app.state.server = server
    return app
```

The endpoint methods should delegate admin routes to `errorworks.engine.admin` and return health JSON:

```python
    async def _health_endpoint(self, request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "healthy",
                "smtp_running": self.smtp_running,
                "run_id": self._metrics_recorder.run_id,
                "started_utc": self._metrics_recorder.started_utc,
                "in_burst": self._error_injector.is_in_burst(),
            }
        )
```

Update `src/errorworks/smtp/__init__.py`:

```python
from errorworks.smtp.server import ChaosSMTPServer, create_admin_app

__all__ = [
    "ChaosSMTPServer",
    "create_admin_app",
]
```

- [ ] **Step 4: Run the silent delivery tests**

Run:

```bash
uv run pytest tests/unit/smtp/test_server.py::test_server_starts_on_ephemeral_port tests/unit/smtp/test_server.py::test_silent_server_accepts_message tests/unit/smtp/test_server.py::test_health_endpoint_reports_smtp_status -q
```

Expected: PASS.

- [ ] **Step 5: Run formatting and targeted type check**

Run:

```bash
uv run ruff format src/errorworks/smtp/server.py src/errorworks/smtp/__init__.py tests/unit/smtp/test_server.py
uv run ruff check --fix src/errorworks/smtp/server.py src/errorworks/smtp/__init__.py tests/unit/smtp/test_server.py
uv run mypy src/errorworks/smtp/server.py
```

Expected: PASS. If mypy reports missing `aiosmtpd` stubs, add a narrow override for `aiosmtpd.*` in `pyproject.toml`:

```toml
[[tool.mypy.overrides]]
module = [
    "aiosmtpd.*",
    "mcp.*",
    "hypothesis.*",
]
ignore_missing_imports = true
```

- [ ] **Step 6: Commit**

```bash
git add src/errorworks/smtp tests/unit/smtp/test_server.py pyproject.toml
git commit -m "feat: add ChaosSMTP listener and admin app"
```

---

## Task 7: Implement SMTP Failure Paths and Runtime Admin Updates

**Files:**
- Modify: `src/errorworks/smtp/server.py`
- Test: `tests/unit/smtp/test_server.py`

- [ ] **Step 1: Add failing server tests for SMTP-stage failures**

Append to `tests/unit/smtp/test_server.py`:

```python
import pytest


def test_rcpt_tempfail_returns_smtp_recipients_refused(tmp_path) -> None:
    base = _config(tmp_path)
    config = ChaosSMTPConfig(
        **{
            **base.model_dump(),
            "error_injection": {"rcpt_to_tempfail_pct": 100.0},
        }
    )
    server = ChaosSMTPServer(config)
    server.start()
    try:
        with smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client:
            with pytest.raises(smtplib.SMTPRecipientsRefused) as exc_info:
                client.send_message(_message())
        refused = exc_info.value.recipients["recipient@example.com"]
        assert refused[0] == 451
        assert server.get_stats()["total_requests"] == 1
    finally:
        server.stop()


def test_data_reject_returns_smtp_data_error(tmp_path) -> None:
    base = _config(tmp_path)
    config = ChaosSMTPConfig(
        **{
            **base.model_dump(),
            "error_injection": {"data_reject_pct": 100.0},
        }
    )
    server = ChaosSMTPServer(config)
    server.start()
    try:
        with smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client:
            with pytest.raises(smtplib.SMTPDataError) as exc_info:
                client.send_message(_message())
        assert exc_info.value.smtp_code == 554
        assert server.get_stats()["total_requests"] == 1
    finally:
        server.stop()


def test_admin_config_update_changes_subsequent_transaction(tmp_path) -> None:
    server = ChaosSMTPServer(_config(tmp_path))
    server.start()
    try:
        with TestClient(server.admin_app) as admin_client:
            response = admin_client.post(
                "/admin/config",
                headers={"Authorization": f"Bearer {TEST_ADMIN_TOKEN}"},
                json={"error_injection": {"rcpt_to_reject_pct": 100.0}},
            )
            assert response.status_code == 200
        with smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client:
            with pytest.raises(smtplib.SMTPRecipientsRefused) as exc_info:
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
        with TestClient(server.admin_app) as admin_client:
            response = admin_client.post("/admin/reset", headers={"Authorization": f"Bearer {TEST_ADMIN_TOKEN}"})
        assert response.status_code == 200
        assert server.get_stats()["total_requests"] == 0
        assert server.list_messages() == []
    finally:
        server.stop()
```

- [ ] **Step 2: Run the new tests to verify failure**

Run:

```bash
uv run pytest tests/unit/smtp/test_server.py -q
```

Expected: FAIL on one or more SMTP failure behaviors.

- [ ] **Step 3: Complete failure behavior in server**

Modify `src/errorworks/smtp/server.py`:

- Ensure `handle_MAIL` and `handle_RCPT` return `decision.reply_line` without mutating the envelope when decisions are command failures.
- Ensure `handle_DATA` records one transaction for DATA-stage command failures.
- Ensure `update_config` deep-merges and swaps these sections:

```python
    def update_config(self, updates: dict[str, Any]) -> None:
        new_error: SMTPErrorInjector | None = None
        new_capture: MessageCapture | None = None
        new_latency: LatencySimulator | None = None

        if "error_injection" in updates:
            current = self._error_injector.config.model_dump()
            merged = deep_merge(current, updates["error_injection"])
            new_error = SMTPErrorInjector(SMTPErrorInjectionConfig(**merged))

        if "capture" in updates:
            current = self._capture.config.model_dump()
            merged = deep_merge(current, updates["capture"])
            new_capture = MessageCapture(SMTPCaptureConfig(**merged))

        if "latency" in updates:
            current = self._latency_simulator.config.model_dump()
            merged = deep_merge(current, updates["latency"])
            new_latency = LatencySimulator(LatencyConfig(**merged))

        with self._config_lock:
            if new_error is not None:
                self._error_injector = new_error
            if new_capture is not None:
                self._capture = new_capture
            if new_latency is not None:
                self._latency_simulator = new_latency
```

- Ensure `get_current_config` returns:

```python
    def get_current_config(self) -> dict[str, Any]:
        with self._config_lock:
            return {
                "error_injection": self._error_injector.config.model_dump(),
                "capture": self._capture.config.model_dump(),
                "latency": self._latency_simulator.config.model_dump(),
            }
```

- Ensure admin endpoint methods delegate:

```python
    async def _admin_config_endpoint(self, request: Request) -> JSONResponse:
        return await admin.handle_admin_config(request, self)
```

Repeat the same pattern for stats, reset, and export.

- [ ] **Step 4: Run server tests**

Run:

```bash
uv run pytest tests/unit/smtp/test_server.py -q
```

Expected: PASS.

- [ ] **Step 5: Run formatting and targeted type check**

Run:

```bash
uv run ruff format src/errorworks/smtp/server.py tests/unit/smtp/test_server.py
uv run ruff check --fix src/errorworks/smtp/server.py tests/unit/smtp/test_server.py
uv run mypy src/errorworks/smtp/server.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/errorworks/smtp/server.py tests/unit/smtp/test_server.py
git commit -m "feat: add ChaosSMTP failure handling and runtime updates"
```

---

## Task 8: Implement Protocol-Level Failure Hooks

**Files:**
- Modify: `src/errorworks/smtp/server.py`
- Test: `tests/unit/smtp/test_server.py`

- [ ] **Step 1: Add failing tests for connection and protocol failures**

Append to `tests/unit/smtp/test_server.py`:

```python
def test_connection_reset_disconnects_client(tmp_path) -> None:
    base = _config(tmp_path)
    config = ChaosSMTPConfig(
        **{
            **base.model_dump(),
            "error_injection": {"connection_reset_pct": 100.0},
        }
    )
    server = ChaosSMTPServer(config)
    server.start()
    try:
        with smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client:
            with pytest.raises(smtplib.SMTPServerDisconnected):
                client.send_message(_message())
        assert server.get_stats()["total_requests"] >= 1
    finally:
        server.stop()


def test_wrong_reply_code_is_recorded_as_malformed_protocol(tmp_path) -> None:
    base = _config(tmp_path)
    config = ChaosSMTPConfig(
        **{
            **base.model_dump(),
            "error_injection": {"wrong_reply_code_pct": 100.0},
        }
    )
    server = ChaosSMTPServer(config)
    server.start()
    try:
        with smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client:
            with pytest.raises(smtplib.SMTPDataError):
                client.send_message(_message())
        stats = server.export_metrics()
        assert stats["requests"][0]["outcome"] == "malformed_protocol"
    finally:
        server.stop()


def test_malformed_reply_disconnects_client(tmp_path) -> None:
    base = _config(tmp_path)
    config = ChaosSMTPConfig(
        **{
            **base.model_dump(),
            "error_injection": {"malformed_reply_pct": 100.0},
        }
    )
    server = ChaosSMTPServer(config)
    server.start()
    try:
        with smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client:
            with pytest.raises(smtplib.SMTPServerDisconnected):
                client.send_message(_message())
        stats = server.export_metrics()
        assert stats["requests"][0]["outcome"] == "malformed_protocol"
    finally:
        server.stop()
```

- [ ] **Step 2: Run protocol failure tests to verify failure**

Run:

```bash
uv run pytest tests/unit/smtp/test_server.py::test_connection_reset_disconnects_client tests/unit/smtp/test_server.py::test_wrong_reply_code_is_recorded_as_malformed_protocol tests/unit/smtp/test_server.py::test_malformed_reply_disconnects_client -q
```

Expected: FAIL because `server.py` does not yet close transports or emit malformed replies.

- [ ] **Step 3: Pass the SMTP protocol object into stage handling**

Modify `_ChaosSMTPHandler` methods in `src/errorworks/smtp/server.py` so the owner can close the active transport:

```python
    async def handle_MAIL(self, server: Any, session: Session, envelope: Envelope, address: str, mail_options: list[str]) -> str:
        decision = await self._owner.handle_stage(SMTPStage.MAIL, session=session, smtp_server=server, mail_from=address)
        if decision.should_inject:
            return _reply_for_decision(decision)
        envelope.mail_from = address
        envelope.mail_options.extend(mail_options)
        return "250 2.1.0 OK"

    async def handle_RCPT(self, server: Any, session: Session, envelope: Envelope, address: str, rcpt_options: list[str]) -> str:
        decision = await self._owner.handle_stage(SMTPStage.RCPT, session=session, smtp_server=server, rcpt_to=address)
        if decision.should_inject:
            return _reply_for_decision(decision)
        envelope.rcpt_tos.append(address)
        envelope.rcpt_options.extend(rcpt_options)
        return "250 2.1.5 OK"
```

Modify `handle_DATA` to pass the SMTP protocol object:

```python
    async def handle_DATA(self, server: Any, session: Session, envelope: Envelope) -> str:
        return await self._owner.handle_data(smtp_server=server, session=session, envelope=envelope)
```

- [ ] **Step 4: Add transport helpers**

Add these helpers near `_outcome_for_decision`:

```python
def _transport_from_smtp(smtp_server: Any) -> Any:
    transport = getattr(smtp_server, "transport", None)
    if transport is not None:
        return transport
    writer = getattr(smtp_server, "_writer", None)
    if writer is not None:
        return getattr(writer, "transport", None)
    return None


def _close_smtp_transport(smtp_server: Any) -> None:
    transport = _transport_from_smtp(smtp_server)
    if transport is not None:
        transport.close()


def _write_raw_smtp_reply(smtp_server: Any, payload: bytes) -> None:
    transport = _transport_from_smtp(smtp_server)
    if transport is not None:
        transport.write(payload)


def _reply_for_decision(decision: SMTPErrorDecision) -> str:
    if decision.reply_code is not None and decision.message is not None:
        return decision.reply_line
    return "421 4.3.0 Connection closed by chaos policy"
```

- [ ] **Step 5: Handle connection and malformed decisions**

Modify `handle_stage` and `handle_data` signatures to accept `smtp_server: Any`.

In both methods, after a decision is created and metrics are recorded, handle these categories before returning normal reply lines:

```python
        if decision.error_type == "connection_reset":
            _close_smtp_transport(smtp_server)
            return decision
        if decision.error_type == "connection_stall":
            if decision.delay_sec is not None:
                await asyncio.sleep(decision.delay_sec)
            _close_smtp_transport(smtp_server)
            return decision
        if decision.error_type == "malformed_reply":
            _write_raw_smtp_reply(smtp_server, b"XYZ malformed SMTP reply\r\n")
            _close_smtp_transport(smtp_server)
            return decision
```

For `wrong_reply_code`, return `decision.reply_line` after recording metrics. The client should treat the unexpected code as an SMTP error, and metrics should classify it as `malformed_protocol`.

- [ ] **Step 6: Run protocol failure tests**

Run:

```bash
uv run pytest tests/unit/smtp/test_server.py::test_connection_reset_disconnects_client tests/unit/smtp/test_server.py::test_wrong_reply_code_is_recorded_as_malformed_protocol tests/unit/smtp/test_server.py::test_malformed_reply_disconnects_client -q
```

Expected: PASS.

- [ ] **Step 7: Run all SMTP server tests**

Run:

```bash
uv run pytest tests/unit/smtp/test_server.py -q
```

Expected: PASS.

- [ ] **Step 8: Run formatting and targeted type check**

Run:

```bash
uv run ruff format src/errorworks/smtp/server.py tests/unit/smtp/test_server.py
uv run ruff check --fix src/errorworks/smtp/server.py tests/unit/smtp/test_server.py
uv run mypy src/errorworks/smtp/server.py
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/errorworks/smtp/server.py tests/unit/smtp/test_server.py
git commit -m "feat: add ChaosSMTP protocol failure hooks"
```

---

## Task 9: Complete CLI Serve, Presets, and Show-Config

**Files:**
- Modify: `src/errorworks/smtp/cli.py`
- Test: `tests/unit/smtp/test_cli.py`

- [ ] **Step 1: Add failing CLI behavior tests**

Append to `tests/unit/smtp/test_cli.py`:

```python
from unittest.mock import patch


def test_presets_lists_expected_names() -> None:
    result = runner.invoke(app, ["presets"])
    assert result.exit_code == 0
    assert "silent" in result.stdout
    assert "realistic" in result.stdout
    assert "stress_delivery" in result.stdout


def test_show_config_outputs_yaml() -> None:
    result = runner.invoke(app, ["show-config", "--preset", "silent"])
    assert result.exit_code == 0
    assert "smtp:" in result.stdout
    assert "error_injection:" in result.stdout


def test_serve_builds_config_and_starts_server() -> None:
    with patch("errorworks.smtp.cli.ChaosSMTPServer") as server_cls:
        server = server_cls.return_value
        server.smtp_host = "127.0.0.1"
        server.smtp_port = 2525
        server.admin_app = object()
        with patch("errorworks.smtp.cli.uvicorn.run") as uvicorn_run:
            result = runner.invoke(app, ["serve", "--preset", "silent", "--port", "2526", "--admin-port", "8526"])
    assert result.exit_code == 0
    server.start.assert_called_once()
    uvicorn_run.assert_called_once()
```

- [ ] **Step 2: Run CLI tests to verify failure**

Run:

```bash
uv run pytest tests/unit/smtp/test_cli.py -q
```

Expected: FAIL because CLI does not yet load config, list presets, or start the server.

- [ ] **Step 3: Implement full CLI**

Replace `src/errorworks/smtp/cli.py` with a Typer app matching LLM/Web patterns:

```python
"""CLI for ChaosSMTP fake SMTP server."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

import pydantic
import typer
import uvicorn
import yaml

from errorworks.smtp.config import list_presets, load_config
from errorworks.smtp.server import ChaosSMTPServer

app = typer.Typer(
    name="chaossmtp",
    help="ChaosSMTP: Fake SMTP server for outbound email resilience testing.",
    no_args_is_help=True,
)
```

Implement `serve` with these options:

```python
@app.command()
def serve(
    preset: Annotated[str | None, typer.Option("--preset", "-p")] = None,
    config_file: Annotated[Path | None, typer.Option("--config", "-c", exists=True, file_okay=True, dir_okay=False, resolve_path=True)] = None,
    host: Annotated[str | None, typer.Option("--host", "-h")] = None,
    port: Annotated[int | None, typer.Option("--port", "-P", min=1, max=65535)] = None,
    admin_host: Annotated[str | None, typer.Option("--admin-host")] = None,
    admin_port: Annotated[int | None, typer.Option("--admin-port", min=1, max=65535)] = None,
    database: Annotated[str | None, typer.Option("--database", "-d")] = None,
    rcpt_to_tempfail_pct: Annotated[float | None, typer.Option("--rcpt-to-tempfail-pct", min=0.0, max=100.0)] = None,
    rcpt_to_reject_pct: Annotated[float | None, typer.Option("--rcpt-to-reject-pct", min=0.0, max=100.0)] = None,
    data_tempfail_pct: Annotated[float | None, typer.Option("--data-tempfail-pct", min=0.0, max=100.0)] = None,
    data_reject_pct: Annotated[float | None, typer.Option("--data-reject-pct", min=0.0, max=100.0)] = None,
    rate_limit_pct: Annotated[float | None, typer.Option("--rate-limit-pct", min=0.0, max=100.0)] = None,
    base_ms: Annotated[int | None, typer.Option("--base-ms", min=0)] = None,
    jitter_ms: Annotated[int | None, typer.Option("--jitter-ms", min=0)] = None,
    capture_mode: Annotated[str | None, typer.Option("--capture-mode")] = None,
) -> None:
    """Start the ChaosSMTP fake SMTP server."""
```

Inside `serve`, build `cli_overrides` exactly like LLM/Web:

```python
    cli_overrides: dict[str, Any] = {}
    smtp_overrides: dict[str, Any] = {}
    if host is not None:
        smtp_overrides["host"] = host
    if port is not None:
        smtp_overrides["port"] = port
    if smtp_overrides:
        cli_overrides["smtp"] = smtp_overrides

    admin_overrides: dict[str, Any] = {}
    if admin_host is not None:
        admin_overrides["host"] = admin_host
    if admin_port is not None:
        admin_overrides["port"] = admin_port
    if admin_overrides:
        cli_overrides["admin"] = admin_overrides

    if database is not None:
        cli_overrides["metrics"] = {"database": database}

    error_overrides = {
        key: value
        for key, value in {
            "rate_limit_pct": rate_limit_pct,
            "rcpt_to_tempfail_pct": rcpt_to_tempfail_pct,
            "rcpt_to_reject_pct": rcpt_to_reject_pct,
            "data_tempfail_pct": data_tempfail_pct,
            "data_reject_pct": data_reject_pct,
        }.items()
        if value is not None
    }
    if error_overrides:
        cli_overrides["error_injection"] = error_overrides

    latency_overrides = {key: value for key, value in {"base_ms": base_ms, "jitter_ms": jitter_ms}.items() if value is not None}
    if latency_overrides:
        cli_overrides["latency"] = latency_overrides

    if capture_mode is not None:
        cli_overrides["capture"] = {"mode": capture_mode}
```

Then load config, start SMTP, and run the admin sidecar:

```python
    try:
        config = load_config(preset=preset, config_file=config_file, cli_overrides=cli_overrides)
    except FileNotFoundError as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e
    except (pydantic.ValidationError, yaml.YAMLError, ValueError) as e:
        typer.secho(f"Configuration error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e

    server = ChaosSMTPServer(config)
    server.start()
    typer.secho(f"Starting ChaosSMTP server on {server.smtp_host}:{server.smtp_port}", fg=typer.colors.GREEN)
    if config.admin.enabled:
        typer.echo(f"  Admin: http://{config.admin.host}:{config.admin.port}")
    typer.echo(f"  Metrics DB: {config.metrics.database}")
    try:
        if config.admin.enabled:
            uvicorn.run(server.admin_app, host=config.admin.host, port=config.admin.port, workers=1, log_level="info")
        else:
            asyncio.run(_wait_forever())
    finally:
        server.stop()
```

Add `_wait_forever`, `presets`, `show_config`, and `main`:

```python
async def _wait_forever() -> None:
    while True:
        await asyncio.sleep(3600)
```

Use the same `show-config` output logic as LLM/Web.

- [ ] **Step 4: Run CLI tests**

Run:

```bash
uv run pytest tests/unit/smtp/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 5: Run formatting and targeted type check**

Run:

```bash
uv run ruff format src/errorworks/smtp/cli.py tests/unit/smtp/test_cli.py
uv run ruff check --fix src/errorworks/smtp/cli.py tests/unit/smtp/test_cli.py
uv run mypy src/errorworks/smtp/cli.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/errorworks/smtp/cli.py tests/unit/smtp/test_cli.py
git commit -m "feat: add ChaosSMTP CLI"
```

---

## Task 10: Add Pytest Fixture and SMTP Integration Tests

**Files:**
- Create: `tests/fixtures/chaossmtp.py`
- Modify: `tests/unit/smtp/conftest.py`
- Create: `tests/unit/smtp/test_fixture.py`
- Create: `tests/integration/test_smtp_pipeline.py`

- [ ] **Step 1: Write failing fixture tests**

Create `tests/unit/smtp/test_fixture.py`:

```python
"""Tests for the ChaosSMTP pytest fixture."""

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
    assert chaossmtp_server.wait_for_messages(1)
    assert chaossmtp_server.get_stats()["total_requests"] == 1


def test_fixture_update_config(chaossmtp_server) -> None:
    chaossmtp_server.update_config(rcpt_to_reject_pct=100.0)
    with pytest.raises(Exception):
        chaossmtp_server.send_message(_message())
```

Create `tests/integration/test_smtp_pipeline.py`:

```python
"""Integration tests for the ChaosSMTP pipeline: preset -> config -> server -> SMTP."""

from email.message import EmailMessage
import smtplib

import pytest

from errorworks.engine.types import LatencyConfig, MetricsConfig
from errorworks.smtp.config import ChaosSMTPConfig, SMTPServerConfig, load_config
from errorworks.smtp.server import ChaosSMTPServer

pytestmark = pytest.mark.integration


def _message() -> EmailMessage:
    message = EmailMessage()
    message["From"] = "sender@example.com"
    message["To"] = "recipient@example.com"
    message["Subject"] = "Integration test"
    message.set_content("hello")
    return message


def _server_from_preset(tmp_path, preset: str, overrides: dict | None = None) -> ChaosSMTPServer:
    merged = {
        "smtp": {"port": 0},
        "metrics": {"database": str(tmp_path / f"{preset}.db")},
        "latency": {"base_ms": 0, "jitter_ms": 0},
    }
    if overrides:
        merged.update(overrides)
    config = load_config(preset=preset, cli_overrides=merged)
    return ChaosSMTPServer(config)


def test_silent_preset_accepts_message(tmp_path) -> None:
    server = _server_from_preset(tmp_path, "silent")
    server.start()
    try:
        with smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client:
            result = client.send_message(_message())
        assert result == {}
        assert server.get_stats()["total_requests"] == 1
    finally:
        server.stop()


def test_config_overlay_can_force_recipient_reject(tmp_path) -> None:
    config = ChaosSMTPConfig(
        smtp=SMTPServerConfig(port=0),
        metrics=MetricsConfig(database=str(tmp_path / "smtp.db")),
        latency=LatencyConfig(base_ms=0, jitter_ms=0),
        error_injection={"rcpt_to_reject_pct": 100.0},
    )
    server = ChaosSMTPServer(config)
    server.start()
    try:
        with smtplib.SMTP(server.smtp_host, server.smtp_port, timeout=5) as client:
            with pytest.raises(smtplib.SMTPRecipientsRefused):
                client.send_message(_message())
        assert server.get_stats()["total_requests"] == 1
    finally:
        server.stop()
```

- [ ] **Step 2: Run fixture and integration tests to verify failure**

Run:

```bash
uv run pytest tests/unit/smtp/test_fixture.py tests/integration/test_smtp_pipeline.py -q
```

Expected: FAIL because `chaossmtp_server` fixture does not exist.

- [ ] **Step 3: Implement fixture**

Create `tests/fixtures/chaossmtp.py`:

```python
"""ChaosSMTP fixture for real loopback SMTP testing."""

from __future__ import annotations

import smtplib
import time
from collections.abc import Generator
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest

from errorworks.smtp.config import ChaosSMTPConfig, load_config
from errorworks.smtp.server import ChaosSMTPServer

TEST_ADMIN_TOKEN = "test-admin-token"


@dataclass
class ChaosSMTPFixture:
    server: ChaosSMTPServer
    metrics_db_path: Path

    @property
    def host(self) -> str:
        return self.server.smtp_host

    @property
    def port(self) -> int:
        return self.server.smtp_port

    @property
    def metrics_db(self) -> Path:
        return self.metrics_db_path

    def send_message(self, message: EmailMessage) -> dict[str, tuple[int, bytes]]:
        with smtplib.SMTP(self.host, self.port, timeout=5) as client:
            return client.send_message(message)

    def get_stats(self) -> dict[str, Any]:
        return self.server.get_stats()

    def export_metrics(self) -> dict[str, Any]:
        return self.server.export_metrics()

    def update_config(
        self,
        *,
        rcpt_to_tempfail_pct: float | None = None,
        rcpt_to_reject_pct: float | None = None,
        data_tempfail_pct: float | None = None,
        data_reject_pct: float | None = None,
        rate_limit_pct: float | None = None,
    ) -> None:
        error_updates = {
            key: value
            for key, value in {
                "rcpt_to_tempfail_pct": rcpt_to_tempfail_pct,
                "rcpt_to_reject_pct": rcpt_to_reject_pct,
                "data_tempfail_pct": data_tempfail_pct,
                "data_reject_pct": data_reject_pct,
                "rate_limit_pct": rate_limit_pct,
            }.items()
            if value is not None
        }
        if error_updates:
            self.server.update_config({"error_injection": error_updates})

    def reset(self) -> str:
        return self.server.reset()

    def wait_for_messages(self, count: int, timeout: float = 10.0) -> bool:
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            if self.get_stats()["total_requests"] >= count:
                return True
            time.sleep(0.01)
        return False


def _build_config_from_marker(marker: pytest.Mark | None, tmp_path: Path) -> ChaosSMTPConfig:
    base_config: dict[str, Any] = {
        "smtp": {"port": 0},
        "admin": {"admin_token": TEST_ADMIN_TOKEN},
        "metrics": {"database": str(tmp_path / "chaossmtp-metrics.db")},
        "latency": {"base_ms": 0, "jitter_ms": 0},
    }
    if marker is None:
        return ChaosSMTPConfig(**base_config)
    preset = marker.kwargs.get("preset")
    overrides: dict[str, Any] = {}
    error_overrides = {
        key: marker.kwargs[key]
        for key in [
            "rate_limit_pct",
            "rcpt_to_tempfail_pct",
            "rcpt_to_reject_pct",
            "data_tempfail_pct",
            "data_reject_pct",
        ]
        if key in marker.kwargs
    }
    if error_overrides:
        overrides["error_injection"] = error_overrides
    return load_config(preset=preset, cli_overrides={**base_config, **overrides})


@pytest.fixture
def chaossmtp_server(request: pytest.FixtureRequest, tmp_path: Path) -> Generator[ChaosSMTPFixture, None, None]:
    marker = request.node.get_closest_marker("chaossmtp")
    config = _build_config_from_marker(marker, tmp_path)
    server = ChaosSMTPServer(config)
    server.start()
    try:
        yield ChaosSMTPFixture(server=server, metrics_db_path=Path(config.metrics.database))
    finally:
        server.stop()
```

Modify `tests/unit/smtp/conftest.py`:

```python
"""Conftest for ChaosSMTP unit tests."""

from tests.fixtures.chaossmtp import chaossmtp_server  # noqa: F401
```

- [ ] **Step 4: Run fixture and integration tests**

Run:

```bash
uv run pytest tests/unit/smtp/test_fixture.py tests/integration/test_smtp_pipeline.py -q
```

Expected: PASS.

- [ ] **Step 5: Run formatting and targeted type check**

Run:

```bash
uv run ruff format tests/fixtures/chaossmtp.py tests/unit/smtp tests/integration/test_smtp_pipeline.py
uv run ruff check --fix tests/fixtures/chaossmtp.py tests/unit/smtp tests/integration/test_smtp_pipeline.py
uv run mypy tests/fixtures/chaossmtp.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/chaossmtp.py tests/unit/smtp tests/integration/test_smtp_pipeline.py
git commit -m "test: add ChaosSMTP fixture and integration coverage"
```

---

## Task 11: Add Documentation and References

**Files:**
- Modify: `README.md`
- Modify: `docs/index.md`
- Modify: `docs/architecture.md`
- Create: `docs/guide/chaossmtp.md`
- Modify: `docs/guide/presets.md`
- Modify: `docs/guide/configuration.md`
- Modify: `docs/guide/metrics.md`
- Modify: `docs/guide/testing-fixtures.md`
- Modify: `docs/reference/cli.md`
- Modify: `docs/reference/api.md`
- Modify: `docs/reference/config-schema.md`
- Modify: `mkdocs.yml`

- [ ] **Step 1: Add docs page skeleton**

Create `docs/guide/chaossmtp.md`:

```markdown
# ChaosSMTP Guide

ChaosSMTP is a fake SMTP receiving server that injects configurable faults into outbound email delivery tests. Point an SMTP client at ChaosSMTP instead of a real mail server to verify retries, permanent failure handling, and delivery metrics before production mail leaves your system.

## Quick Start

```bash
uv run chaossmtp serve --preset=realistic
```

Send a message with Python:

```python
from email.message import EmailMessage
import smtplib

message = EmailMessage()
message["From"] = "sender@example.com"
message["To"] = "recipient@example.com"
message["Subject"] = "Test"
message.set_content("hello")

with smtplib.SMTP("127.0.0.1", 2525, timeout=5) as client:
    client.send_message(message)
```

## SMTP Listener

| Setting | Default | Description |
|---|---:|---|
| Host | `127.0.0.1` | Loopback-only by default. |
| SMTP port | `2525` | Non-privileged SMTP test port. |
| Admin port | `8525` | HTTP admin sidecar. |

## Error Injection

| Error Type | Config Field | Typical Reply |
|---|---|---|
| Rate limit | `rate_limit_pct` | `450` |
| MAIL FROM temporary failure | `mail_from_tempfail_pct` | `451` |
| MAIL FROM permanent rejection | `mail_from_reject_pct` | `550` |
| RCPT TO temporary failure | `rcpt_to_tempfail_pct` | `451` |
| RCPT TO permanent rejection | `rcpt_to_reject_pct` | `550` |
| DATA temporary failure | `data_tempfail_pct` | `451` |
| DATA permanent rejection | `data_reject_pct` | `554` |
| Accepted then dropped | `accept_then_drop_pct` | `250` |

## Capture Modes

- `discard`: record metrics only.
- `metadata`: record envelope metadata and safe headers. This is the default.
- `full`: store message bytes up to `max_message_bytes`.

## Admin

ChaosSMTP uses the same HTTP admin sidecar pattern as the other servers:

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" http://127.0.0.1:8525/admin/stats
```

## Safety

ChaosSMTP never relays mail. It accepts or rejects messages locally for tests.
```

- [ ] **Step 2: Add navigation entry**

Modify `mkdocs.yml` under `Guide`:

```yaml
  - Guide:
    - ChaosLLM: guide/chaosllm.md
    - ChaosWeb: guide/chaosweb.md
    - ChaosSMTP: guide/chaossmtp.md
```

- [ ] **Step 3: Update top-level docs and README**

Add a ChaosSMTP bullet wherever ChaosLLM and ChaosWeb are listed:

```markdown
**ChaosSMTP** — a fake SMTP receiving server for outbound email resilience tests. Inject temporary recipient failures, DATA rejections, rate limits, slow replies, and accepted-but-dropped messages without relaying mail.
```

Add this quick usage example to `README.md`:

```bash
# SMTP server
chaossmtp serve --preset=realistic --port=2525
```

- [ ] **Step 4: Update reference docs**

In `docs/reference/cli.md`, add a `chaossmtp` section mirroring LLM/Web:

```markdown
## `chaossmtp` -- ChaosSMTP Server

```bash
chaossmtp serve --preset=realistic
chaosengine smtp serve --preset=stress_delivery
```

Key flags: `--host`, `--port`, `--admin-host`, `--admin-port`, `--database`, `--rcpt-to-tempfail-pct`, `--rcpt-to-reject-pct`, `--data-tempfail-pct`, `--data-reject-pct`, `--rate-limit-pct`, `--capture-mode`.
```

In `docs/reference/api.md`, add an SMTP section that explains the SMTP listener and the HTTP admin sidecar. In `docs/reference/config-schema.md`, add `ChaosSMTPConfig`, `SMTPServerConfig`, `SMTPAdminConfig`, `SMTPCaptureConfig`, and `SMTPErrorInjectionConfig` tables with defaults from `config.py`.

- [ ] **Step 5: Update guide docs**

Update:

- `docs/guide/presets.md`: add SMTP preset table.
- `docs/guide/configuration.md`: add SMTP YAML example.
- `docs/guide/metrics.md`: add SMTP metrics fields.
- `docs/guide/testing-fixtures.md`: add `chaossmtp_server` fixture section and state that SMTP uses an ephemeral loopback socket because standard SMTP clients require a real TCP connection.
- `docs/architecture.md`: add `smtp/` package to the tree and explain that SMTP is a protocol adapter with an HTTP admin sidecar.

- [ ] **Step 6: Build docs**

Run:

```bash
uv run mkdocs build --strict
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add README.md docs mkdocs.yml
git commit -m "docs: document ChaosSMTP"
```

---

## Task 12: Final Validation and Release-Readiness Sweep

**Files:**
- Modify only files required to fix failures from the validation commands.

- [ ] **Step 1: Run focused SMTP test suite**

Run:

```bash
uv run pytest tests/unit/smtp tests/integration/test_smtp_pipeline.py -q
```

Expected: PASS.

- [ ] **Step 2: Run relevant integration suites**

Run:

```bash
uv run pytest tests/integration -q
```

Expected: PASS. Existing LLM/Web integration tests must remain green.

- [ ] **Step 3: Run full unit tests**

Run:

```bash
uv run pytest tests/unit -q
```

Expected: PASS.

- [ ] **Step 4: Run lint, format check, and type check**

Run:

```bash
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src
```

Expected: PASS.

- [ ] **Step 5: Run package CLI smoke tests**

Run:

```bash
uv run chaossmtp --help
uv run chaossmtp presets
uv run chaossmtp show-config --preset=realistic
uv run chaosengine smtp --help
```

Expected:

- Help commands exit 0 and mention ChaosSMTP.
- Presets output includes `silent`, `gentle`, `realistic`, `stress_delivery`, and `stress_extreme`.
- Show-config output includes `smtp`, `admin`, `metrics`, `capture`, `latency`, and `error_injection`.

- [ ] **Step 6: Manual runtime smoke**

Start the server:

```bash
uv run chaossmtp serve --preset=silent --port=2525 --admin-port=8525 --database=/tmp/chaossmtp-smoke.db
```

In another terminal, send a message:

```bash
python - <<'PY'
from email.message import EmailMessage
import smtplib

message = EmailMessage()
message["From"] = "sender@example.com"
message["To"] = "recipient@example.com"
message["Subject"] = "Smoke"
message.set_content("hello")

with smtplib.SMTP("127.0.0.1", 2525, timeout=5) as client:
    print(client.send_message(message))
PY
```

Expected: `{}` printed by the Python snippet.

Then query stats:

```bash
curl -s -H "Authorization: Bearer <printed-admin-token>" http://127.0.0.1:8525/admin/stats
```

Expected: JSON with `"total_requests": 1`.

- [ ] **Step 7: Commit final fixes**

If any validation fixes were needed:

```bash
git add src tests docs README.md pyproject.toml mkdocs.yml
git commit -m "fix: stabilize ChaosSMTP validation"
```

If no fixes were needed, do not create an empty commit.

## Spec Coverage Checklist

- `ChaosSMTP` package: Tasks 1-6.
- `aiosmtpd` listener instead of stdlib `smtpd`: Tasks 1 and 6.
- HTTP admin sidecar: Tasks 6 and 7.
- Config precedence and frozen models: Task 2.
- Runtime admin updates: Task 7.
- SMTP-stage and protocol-level error model: Tasks 4, 7, and 8.
- Metrics schema and aggregation: Task 5.
- CLI and unified CLI: Tasks 1 and 9.
- Presets: Task 2.
- Pytest fixture with loopback socket: Task 10.
- Integration tests with `smtplib`: Tasks 6 and 10.
- Docs and reference updates: Task 11.
- Safety constraints and no relay behavior: Tasks 6, 9, 11, and 12.
