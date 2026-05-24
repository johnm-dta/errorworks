"""ChaosBlob TestClient fixture for in-process object-storage pipeline tests."""

from __future__ import annotations

import threading
import time
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from starlette.testclient import TestClient

from errorworks.blob.config import ChaosBlobConfig, load_config
from errorworks.blob.server import ChaosBlobServer

if TYPE_CHECKING:
    import httpx

# Fixed token for test fixtures - deterministic and known by tests.
TEST_ADMIN_TOKEN = "test-admin-token"


@dataclass
class ChaosBlobFixture:
    """Pytest fixture object for ChaosBlob server."""

    client: TestClient
    server: ChaosBlobServer
    metrics_db_path: Path
    _request_count: int = field(default=0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    @property
    def base_url(self) -> str:
        return "http://testserver"

    @property
    def port(self) -> int:
        return 8300

    @property
    def metrics_db(self) -> Path:
        return self.metrics_db_path

    @property
    def admin_url(self) -> str:
        return f"{self.base_url}/admin"

    @property
    def admin_headers(self) -> dict[str, str]:
        """Headers with admin auth token for /admin/* endpoints."""
        return {"Authorization": f"Bearer {self.server.get_admin_token()}"}

    @property
    def run_id(self) -> str:
        return self.server.run_id

    def put_object(self, bucket: str, key: str, body: bytes, headers: dict[str, str] | None = None) -> httpx.Response:
        return self.client.put(f"/{bucket}/{key}", content=body, headers=headers or {})

    def get_object(self, bucket: str, key: str, headers: dict[str, str] | None = None) -> httpx.Response:
        return self.client.get(f"/{bucket}/{key}", headers=headers or {})

    def head_object(self, bucket: str, key: str, headers: dict[str, str] | None = None) -> httpx.Response:
        return self.client.head(f"/{bucket}/{key}", headers=headers or {})

    def delete_object(self, bucket: str, key: str) -> httpx.Response:
        return self.client.delete(f"/{bucket}/{key}")

    def list_objects(self, bucket: str, *, prefix: str = "", max_keys: int = 1000) -> httpx.Response:
        return self.client.get(f"/{bucket}", params={"list-type": "2", "prefix": prefix, "max-keys": str(max_keys)})

    def get_stats(self) -> dict[str, Any]:
        return self.server.get_stats()

    def export_metrics(self) -> dict[str, Any]:
        return self.server.export_metrics()

    def update_config(
        self,
        *,
        updates: dict[str, Any] | None = None,
        slow_down_pct: float | None = None,
        access_denied_pct: float | None = None,
        not_found_pct: float | None = None,
        service_unavailable_pct: float | None = None,
        internal_error_pct: float | None = None,
        bad_gateway_pct: float | None = None,
        gateway_timeout_pct: float | None = None,
        timeout_pct: float | None = None,
        connection_reset_pct: float | None = None,
        connection_stall_pct: float | None = None,
        slow_response_pct: float | None = None,
        truncated_body_pct: float | None = None,
        wrong_content_length_pct: float | None = None,
        checksum_mismatch_pct: float | None = None,
        metadata_corruption_pct: float | None = None,
        stale_list_pct: float | None = None,
        malformed_xml_pct: float | None = None,
        selection_mode: str | None = None,
        base_ms: int | None = None,
        jitter_ms: int | None = None,
        max_object_bytes: int | None = None,
    ) -> None:
        """Update runtime configuration for the server.

        Raw ``updates`` are applied first. Typed helper arguments are merged on
        top, so explicit helper parameters win if both forms set the same field.
        """
        config_updates: dict[str, Any] = {key: dict(value) if isinstance(value, dict) else value for key, value in (updates or {}).items()}
        error_updates: dict[str, float | str] = {}
        for key, val in [
            ("slow_down_pct", slow_down_pct),
            ("access_denied_pct", access_denied_pct),
            ("not_found_pct", not_found_pct),
            ("service_unavailable_pct", service_unavailable_pct),
            ("internal_error_pct", internal_error_pct),
            ("bad_gateway_pct", bad_gateway_pct),
            ("gateway_timeout_pct", gateway_timeout_pct),
            ("timeout_pct", timeout_pct),
            ("connection_reset_pct", connection_reset_pct),
            ("connection_stall_pct", connection_stall_pct),
            ("slow_response_pct", slow_response_pct),
            ("truncated_body_pct", truncated_body_pct),
            ("wrong_content_length_pct", wrong_content_length_pct),
            ("checksum_mismatch_pct", checksum_mismatch_pct),
            ("metadata_corruption_pct", metadata_corruption_pct),
            ("stale_list_pct", stale_list_pct),
            ("malformed_xml_pct", malformed_xml_pct),
            ("selection_mode", selection_mode),
        ]:
            if val is not None:
                error_updates[key] = val
        if error_updates:
            section = dict(config_updates.get("error_injection", {}))
            section.update(error_updates)
            config_updates["error_injection"] = section

        latency_updates: dict[str, int] = {}
        if base_ms is not None:
            latency_updates["base_ms"] = base_ms
        if jitter_ms is not None:
            latency_updates["jitter_ms"] = jitter_ms
        if latency_updates:
            section = dict(config_updates.get("latency", {}))
            section.update(latency_updates)
            config_updates["latency"] = section

        storage_updates: dict[str, int | str] = {}
        if max_object_bytes is not None:
            storage_updates["max_object_bytes"] = max_object_bytes
        if storage_updates:
            section = dict(config_updates.get("storage", {}))
            section.update(storage_updates)
            config_updates["storage"] = section

        if config_updates:
            self.server.update_config(config_updates)

    def reset(self) -> str:
        return self.server.reset()

    def wait_for_requests(self, count: int, timeout: float = 10.0) -> bool:
        """Block until at least `count` requests have been recorded."""
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            stats = self.get_stats()
            if stats["total_requests"] >= count:
                return True
            time.sleep(0.01)
        return False


_ERROR_INJECTION_KEYS = [
    "slow_down_pct",
    "access_denied_pct",
    "not_found_pct",
    "service_unavailable_pct",
    "internal_error_pct",
    "bad_gateway_pct",
    "gateway_timeout_pct",
    "timeout_pct",
    "connection_reset_pct",
    "connection_stall_pct",
    "slow_response_pct",
    "truncated_body_pct",
    "wrong_content_length_pct",
    "checksum_mismatch_pct",
    "metadata_corruption_pct",
    "stale_list_pct",
    "malformed_xml_pct",
    "selection_mode",
]

_MARKER_KEYS = frozenset({"preset", "base_ms", "jitter_ms", "max_object_bytes", *_ERROR_INJECTION_KEYS})


def _validate_marker_kwargs(marker: pytest.Mark) -> None:
    unknown_keys = sorted(set(marker.kwargs) - _MARKER_KEYS)
    if unknown_keys:
        valid_keys = ", ".join(sorted(_MARKER_KEYS))
        unknown = ", ".join(unknown_keys)
        raise ValueError(f"Unknown chaosblob marker kwargs: {unknown}. Valid keys: {valid_keys}")


def _build_config_from_marker(
    marker: pytest.Mark | None,
    tmp_path: Path,
) -> ChaosBlobConfig:
    """Build ChaosBlobConfig from pytest marker kwargs."""
    metrics_db_path = tmp_path / "chaosblob-metrics.db"
    base_config: dict[str, Any] = {
        "server": {"admin_token": TEST_ADMIN_TOKEN},
        "metrics": {"database": str(metrics_db_path)},
        "latency": {"base_ms": 0, "jitter_ms": 0},
    }

    if marker is None:
        return ChaosBlobConfig(**base_config)

    _validate_marker_kwargs(marker)
    preset = marker.kwargs.get("preset")
    overrides: dict[str, Any] = {}

    error_overrides: dict[str, float | str] = {}
    for key in _ERROR_INJECTION_KEYS:
        if key in marker.kwargs:
            error_overrides[key] = marker.kwargs[key]
    if error_overrides:
        overrides["error_injection"] = error_overrides

    latency_overrides: dict[str, int] = {}
    if "base_ms" in marker.kwargs:
        latency_overrides["base_ms"] = marker.kwargs["base_ms"]
    if "jitter_ms" in marker.kwargs:
        latency_overrides["jitter_ms"] = marker.kwargs["jitter_ms"]
    if latency_overrides:
        overrides["latency"] = latency_overrides

    storage_overrides: dict[str, int] = {}
    if "max_object_bytes" in marker.kwargs:
        storage_overrides["max_object_bytes"] = marker.kwargs["max_object_bytes"]
    if storage_overrides:
        overrides["storage"] = storage_overrides

    if preset or overrides:
        return load_config(
            preset=preset,
            cli_overrides={**base_config, **overrides} if overrides else base_config,
        )

    return ChaosBlobConfig(**base_config)


@pytest.fixture
def chaosblob(request: pytest.FixtureRequest, tmp_path: Path) -> Generator[ChaosBlobFixture, None, None]:
    """Create a ChaosBlob fake object-storage server for testing."""
    marker = request.node.get_closest_marker("chaosblob")
    config = _build_config_from_marker(marker, tmp_path)
    server = ChaosBlobServer(config)
    with TestClient(server.app) as client:
        metrics_db_path = Path(config.metrics.database)
        fixture = ChaosBlobFixture(client=client, server=server, metrics_db_path=metrics_db_path)
        try:
            yield fixture
        finally:
            server.close()
