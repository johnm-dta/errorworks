"""Public pytest fixtures for in-process errorworks testing."""

from __future__ import annotations

import time
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from starlette.testclient import TestClient

from errorworks.blob.config import ChaosBlobConfig
from errorworks.blob.server import ChaosBlobServer
from errorworks.llm.config import ChaosLLMConfig
from errorworks.llm.server import ChaosLLMServer
from errorworks.web.config import ChaosWebConfig
from errorworks.web.server import ChaosWebServer

if TYPE_CHECKING:
    import httpx

TEST_ADMIN_TOKEN = "test-admin-token"


@dataclass
class ChaosLLMFixture:
    """In-process ChaosLLM fixture object."""

    client: TestClient
    server: ChaosLLMServer
    metrics_db_path: Path

    @property
    def url(self) -> str:
        return "http://testserver"

    @property
    def metrics_db(self) -> Path:
        return self.metrics_db_path

    @property
    def admin_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.server.get_admin_token()}"}

    @property
    def run_id(self) -> str:
        return self.server.run_id

    def get_stats(self) -> dict[str, Any]:
        return self.server.get_stats()

    def export_metrics(self) -> dict[str, Any]:
        return self.server.export_metrics()

    def update_config(self, updates: dict[str, Any]) -> None:
        self.server.update_config(updates)

    def reset(self) -> str:
        return self.server.reset()

    def wait_for_requests(self, count: int, timeout: float = 10.0) -> bool:
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            if self.get_stats()["total_requests"] >= count:
                return True
            time.sleep(0.01)
        return False

    def post_completion(
        self,
        messages: list[dict[str, Any]] | None = None,
        model: str = "gpt-4",
        **kwargs: Any,
    ) -> httpx.Response:
        if messages is None:
            messages = [{"role": "user", "content": "Hello"}]
        return self.client.post("/v1/chat/completions", json={"model": model, "messages": messages, **kwargs})


@dataclass
class ChaosWebFixture:
    """In-process ChaosWeb fixture object."""

    client: TestClient
    server: ChaosWebServer
    metrics_db_path: Path

    @property
    def base_url(self) -> str:
        return "http://testserver"

    @property
    def metrics_db(self) -> Path:
        return self.metrics_db_path

    @property
    def admin_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.server.get_admin_token()}"}

    @property
    def run_id(self) -> str:
        return self.server.run_id

    def fetch_page(
        self,
        path: str = "/",
        *,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        return self.client.get(path, headers=headers, follow_redirects=follow_redirects)

    def get_stats(self) -> dict[str, Any]:
        return self.server.get_stats()

    def export_metrics(self) -> dict[str, Any]:
        return self.server.export_metrics()

    def update_config(self, updates: dict[str, Any]) -> None:
        self.server.update_config(updates)

    def reset(self) -> str:
        return self.server.reset()

    def wait_for_requests(self, count: int, timeout: float = 10.0) -> bool:
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            if self.get_stats()["total_requests"] >= count:
                return True
            time.sleep(0.01)
        return False


@dataclass
class ChaosBlobFixture:
    """In-process ChaosBlob fixture object."""

    client: TestClient
    server: ChaosBlobServer
    metrics_db_path: Path

    @property
    def base_url(self) -> str:
        return "http://testserver"

    @property
    def metrics_db(self) -> Path:
        return self.metrics_db_path

    @property
    def admin_headers(self) -> dict[str, str]:
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

    def update_config(self, updates: dict[str, Any]) -> None:
        self.server.update_config(updates)

    def reset(self) -> str:
        return self.server.reset()

    def wait_for_requests(self, count: int, timeout: float = 10.0) -> bool:
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            if self.get_stats()["total_requests"] >= count:
                return True
            time.sleep(0.01)
        return False


@pytest.fixture
def chaosllm_server(tmp_path: Path) -> Generator[ChaosLLMFixture, None, None]:
    """Create an in-process ChaosLLM server for pytest."""
    config = ChaosLLMConfig(
        server={"admin_token": TEST_ADMIN_TOKEN},
        metrics={"database": str(tmp_path / "chaosllm-metrics.db")},
        latency={"base_ms": 0, "jitter_ms": 0},
    )
    server = ChaosLLMServer(config)
    client = TestClient(server.app)
    try:
        yield ChaosLLMFixture(client=client, server=server, metrics_db_path=Path(config.metrics.database))
    finally:
        client.close()


@pytest.fixture
def chaosweb_server(tmp_path: Path) -> Generator[ChaosWebFixture, None, None]:
    """Create an in-process ChaosWeb server for pytest."""
    config = ChaosWebConfig(
        server={"admin_token": TEST_ADMIN_TOKEN},
        metrics={"database": str(tmp_path / "chaosweb-metrics.db")},
        latency={"base_ms": 0, "jitter_ms": 0},
    )
    server = ChaosWebServer(config)
    client = TestClient(server.app)
    try:
        yield ChaosWebFixture(client=client, server=server, metrics_db_path=Path(config.metrics.database))
    finally:
        client.close()


@pytest.fixture
def chaosblob(tmp_path: Path) -> Generator[ChaosBlobFixture, None, None]:
    """Create an in-process ChaosBlob server for pytest."""
    config = ChaosBlobConfig(
        server={"admin_token": TEST_ADMIN_TOKEN},
        metrics={"database": str(tmp_path / "chaosblob-metrics.db")},
        latency={"base_ms": 0, "jitter_ms": 0},
    )
    server = ChaosBlobServer(config)
    client = TestClient(server.app)
    try:
        yield ChaosBlobFixture(client=client, server=server, metrics_db_path=Path(config.metrics.database))
    finally:
        client.close()
        server.close()


__all__ = [
    "TEST_ADMIN_TOKEN",
    "ChaosBlobFixture",
    "ChaosLLMFixture",
    "ChaosWebFixture",
    "chaosblob",
    "chaosllm_server",
    "chaosweb_server",
]
