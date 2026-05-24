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

_ERROR_INJECTION_KEYS = [
    "rate_limit_pct",
    "mail_from_tempfail_pct",
    "mail_from_reject_pct",
    "rcpt_to_tempfail_pct",
    "rcpt_to_reject_pct",
    "data_tempfail_pct",
    "data_reject_pct",
    "accept_then_drop_pct",
    "banner_reject_pct",
    "malformed_reply_pct",
    "wrong_reply_code_pct",
    "connection_reset_pct",
    "connection_stall_pct",
    "slow_response_pct",
    "retry_after_sec",
    "connection_stall_sec",
    "slow_response_sec",
    "selection_mode",
]


@dataclass
class ChaosSMTPFixture:
    """Pytest fixture object for ChaosSMTP server."""

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

    @property
    def run_id(self) -> str:
        return self.server.run_id

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
        rate_limit_pct: float | None = None,
        mail_from_tempfail_pct: float | None = None,
        mail_from_reject_pct: float | None = None,
        rcpt_to_tempfail_pct: float | None = None,
        rcpt_to_reject_pct: float | None = None,
        data_tempfail_pct: float | None = None,
        data_reject_pct: float | None = None,
        accept_then_drop_pct: float | None = None,
        banner_reject_pct: float | None = None,
        malformed_reply_pct: float | None = None,
        wrong_reply_code_pct: float | None = None,
        connection_reset_pct: float | None = None,
        connection_stall_pct: float | None = None,
        slow_response_pct: float | None = None,
        retry_after_sec: tuple[int, int] | None = None,
        connection_stall_sec: tuple[int, int] | None = None,
        slow_response_sec: tuple[int, int] | None = None,
        selection_mode: str | None = None,
        base_ms: int | None = None,
        jitter_ms: int | None = None,
        capture_mode: str | None = None,
        max_message_bytes: int | None = None,
    ) -> None:
        updates: dict[str, Any] = {}
        error_updates: dict[str, Any] = {}
        for key, value in [
            ("rate_limit_pct", rate_limit_pct),
            ("mail_from_tempfail_pct", mail_from_tempfail_pct),
            ("mail_from_reject_pct", mail_from_reject_pct),
            ("rcpt_to_tempfail_pct", rcpt_to_tempfail_pct),
            ("rcpt_to_reject_pct", rcpt_to_reject_pct),
            ("data_tempfail_pct", data_tempfail_pct),
            ("data_reject_pct", data_reject_pct),
            ("accept_then_drop_pct", accept_then_drop_pct),
            ("banner_reject_pct", banner_reject_pct),
            ("malformed_reply_pct", malformed_reply_pct),
            ("wrong_reply_code_pct", wrong_reply_code_pct),
            ("connection_reset_pct", connection_reset_pct),
            ("connection_stall_pct", connection_stall_pct),
            ("slow_response_pct", slow_response_pct),
            ("retry_after_sec", retry_after_sec),
            ("connection_stall_sec", connection_stall_sec),
            ("slow_response_sec", slow_response_sec),
            ("selection_mode", selection_mode),
        ]:
            if value is not None:
                error_updates[key] = value
        if error_updates:
            updates["error_injection"] = error_updates

        latency_updates: dict[str, int] = {}
        if base_ms is not None:
            latency_updates["base_ms"] = base_ms
        if jitter_ms is not None:
            latency_updates["jitter_ms"] = jitter_ms
        if latency_updates:
            updates["latency"] = latency_updates

        capture_updates: dict[str, Any] = {}
        if capture_mode is not None:
            capture_updates["mode"] = capture_mode
        if max_message_bytes is not None:
            capture_updates["max_message_bytes"] = max_message_bytes
        if capture_updates:
            updates["capture"] = capture_updates

        if updates:
            self.server.update_config(updates)

    def reset(self) -> str:
        return self.server.reset()

    def wait_for_messages(self, count: int, timeout: float = 10.0) -> bool:
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            if self.get_stats()["total_requests"] >= count:
                return True
            time.sleep(0.01)
        return False


def _build_config_from_marker(
    marker: pytest.Mark | None,
    tmp_path: Path,
) -> ChaosSMTPConfig:
    metrics_db_path = tmp_path / "chaossmtp-metrics.db"
    base_config: dict[str, Any] = {
        "smtp": {"port": 0},
        "admin": {"admin_token": TEST_ADMIN_TOKEN},
        "metrics": {"database": str(metrics_db_path)},
        "latency": {"base_ms": 0, "jitter_ms": 0},
    }

    if marker is None:
        return ChaosSMTPConfig(**base_config)

    preset = marker.kwargs.get("preset")
    overrides: dict[str, Any] = {}

    error_overrides = {key: marker.kwargs[key] for key in _ERROR_INJECTION_KEYS if key in marker.kwargs}
    if error_overrides:
        overrides["error_injection"] = error_overrides

    latency_overrides: dict[str, int] = {}
    if "base_ms" in marker.kwargs:
        latency_overrides["base_ms"] = marker.kwargs["base_ms"]
    if "jitter_ms" in marker.kwargs:
        latency_overrides["jitter_ms"] = marker.kwargs["jitter_ms"]
    if latency_overrides:
        overrides["latency"] = latency_overrides

    capture_overrides: dict[str, Any] = {}
    if "capture_mode" in marker.kwargs:
        capture_overrides["mode"] = marker.kwargs["capture_mode"]
    if "max_message_bytes" in marker.kwargs:
        capture_overrides["max_message_bytes"] = marker.kwargs["max_message_bytes"]
    if capture_overrides:
        overrides["capture"] = capture_overrides

    if preset or overrides:
        return load_config(preset=preset, cli_overrides={**base_config, **overrides} if overrides else base_config)

    return ChaosSMTPConfig(**base_config)


@pytest.fixture
def chaossmtp_server(request: pytest.FixtureRequest, tmp_path: Path) -> Generator[ChaosSMTPFixture, None, None]:
    """Create a ChaosSMTP server on an ephemeral loopback port."""
    marker = request.node.get_closest_marker("chaossmtp")
    config = _build_config_from_marker(marker, tmp_path)
    server = ChaosSMTPServer(config)
    server.start()
    try:
        yield ChaosSMTPFixture(server=server, metrics_db_path=Path(config.metrics.database))
    finally:
        server.stop()
