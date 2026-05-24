# ChaosBlob Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `chaosblob`, an S3-compatible-ish fake object storage server for testing object-store clients under realistic storage, metadata, listing, checksum, throttling, and download corruption failures.

**Architecture:** Follow the existing ChaosLLM/ChaosWeb composition pattern. `ChaosBlobServer` owns Starlette routing and S3-shaped request/response formatting; shared engine components provide config loading, latency, probabilistic selection, admin endpoints, and SQLite metrics. Blob state lives in a focused in-memory `BlobStore` component that is snapshotted separately from immutable config and reset through the server lifecycle.

**Tech Stack:** Python 3.12, Starlette, Typer, Pydantic v2, SQLite metrics through `MetricsStore`, pytest, httpx TestClient, YAML presets.

---

## Scope

Build the minimum useful object-store chaos surface:

- `PUT /{bucket}/{key:path}` stores an object body and metadata.
- `GET /{bucket}/{key:path}` returns an object body or an injected object/read failure.
- `HEAD /{bucket}/{key:path}` returns object metadata without a body.
- `DELETE /{bucket}/{key:path}` deletes an object and returns a success response.
- `GET /{bucket}?list-type=2&prefix=logs/&continuation-token=<opaque-token>&max-keys=1000` returns S3-style ListObjectsV2 XML.
- Shared `/health` and `/admin/*` endpoints match existing server families.

Do not implement full AWS Signature V4 validation, multipart upload, bucket creation, bucket policies, object versioning, ACLs, presigned URL validation, or cloud-specific SDK quirks in this first plan. The server must accept signed requests as ordinary HTTP requests so clients can point path-style S3-compatible clients at it.

---

## File Structure

Create:

- `src/errorworks/blob/__init__.py` - public package exports and usage docstring.
- `src/errorworks/blob/config.py` - frozen Pydantic config, preset loading, validators.
- `src/errorworks/blob/store.py` - thread-safe in-memory object store.
- `src/errorworks/blob/error_injector.py` - blob-specific injection decisions using `InjectionEngine`.
- `src/errorworks/blob/xml.py` - S3 XML response and error document helpers.
- `src/errorworks/blob/metrics.py` - metrics schema and recorder wrapper.
- `src/errorworks/blob/server.py` - Starlette app and request handlers.
- `src/errorworks/blob/cli.py` - `chaosblob` Typer CLI.
- `src/errorworks/blob/presets/silent.yaml`
- `src/errorworks/blob/presets/gentle.yaml`
- `src/errorworks/blob/presets/realistic.yaml`
- `src/errorworks/blob/presets/stress_storage.yaml`
- `src/errorworks/blob/presets/stress_extreme.yaml`
- `tests/unit/blob/__init__.py`
- `tests/unit/blob/conftest.py`
- `tests/unit/blob/test_config.py`
- `tests/unit/blob/test_store.py`
- `tests/unit/blob/test_error_injector.py`
- `tests/unit/blob/test_xml.py`
- `tests/unit/blob/test_metrics.py`
- `tests/unit/blob/test_server.py`
- `tests/unit/blob/test_cli.py`
- `tests/unit/blob/test_fixture.py`
- `tests/fixtures/chaosblob.py`
- `tests/integration/test_blob_pipeline.py`
- `docs/guide/chaosblob.md`

Modify:

- `pyproject.toml` - add `chaosblob` console script and pytest marker.
- `src/errorworks/engine/cli.py` - mount `chaosengine blob`.
- `README.md` - add ChaosBlob to feature list and usage.
- `docs/index.md` - add ChaosBlob overview.
- `docs/reference/api.md` - add ChaosBlob endpoints.
- `docs/reference/cli.md` - add `chaosblob` command reference.
- `docs/reference/config-schema.md` - add ChaosBlob config tables.
- `docs/guide/configuration.md` - add ChaosBlob example config.
- `docs/guide/presets.md` - add Blob preset table.
- `docs/guide/testing-fixtures.md` - add fixture docs.
- `mkdocs.yml` - add `guide/chaosblob.md` to nav.

---

## Task 1: Add ChaosBlob Config Models and Presets

**Files:**
- Create: `src/errorworks/blob/config.py`
- Create: `src/errorworks/blob/presets/*.yaml`
- Create: `tests/unit/blob/__init__.py`
- Create: `tests/unit/blob/test_config.py`

- [ ] **Step 1: Write failing config tests**

Create `tests/unit/blob/test_config.py`:

```python
from __future__ import annotations

import warnings

import pytest
from pydantic import ValidationError

from errorworks.blob.config import (
    BlobErrorInjectionConfig,
    BlobStorageConfig,
    ChaosBlobConfig,
    list_presets,
    load_config,
)


def test_default_config_uses_blob_port_and_memory_database() -> None:
    config = ChaosBlobConfig()
    assert config.server.port == 8300
    assert config.metrics.database == "file:chaosblob-metrics?mode=memory&cache=shared"
    assert config.storage.max_object_bytes == 10 * 1024 * 1024


def test_list_presets_includes_expected_blob_profiles() -> None:
    assert list_presets() == ["gentle", "realistic", "silent", "stress_extreme", "stress_storage"]


def test_load_realistic_preset() -> None:
    config = load_config(preset="realistic")
    assert config.preset_name == "realistic"
    assert config.error_injection.slow_down_pct > 0
    assert config.error_injection.stale_list_pct > 0


def test_rejects_weighted_mode_at_or_above_one_hundred_percent() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        BlobErrorInjectionConfig(selection_mode="weighted", slow_down_pct=80.0, internal_error_pct=20.0)
    assert any("total error weights are >= 100" in str(item.message) for item in caught)


def test_rejects_invalid_object_size_limit() -> None:
    with pytest.raises(ValidationError):
        BlobStorageConfig(max_object_bytes=0)


def test_rejects_workers_with_memory_metrics_database() -> None:
    with pytest.raises(ValidationError, match="requires a file-backed metrics database"):
        ChaosBlobConfig(server={"workers": 2})
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/blob/test_config.py -q`

Expected: collection/import failure because `errorworks.blob.config` does not exist.

- [ ] **Step 3: Implement `src/errorworks/blob/config.py`**

Use this structure:

```python
"""Configuration schema and loading for ChaosBlob server."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from errorworks.engine.config_loader import list_presets as _list_presets
from errorworks.engine.config_loader import load_config as _load_config
from errorworks.engine.config_loader import load_preset as _load_preset
from errorworks.engine.types import DANGEROUS_BIND_HOSTS, LatencyConfig, MetricsConfig, ServerConfig
from errorworks.engine.validators import parse_range as _parse_range
from errorworks.engine.validators import validate_ranges as _validate_ranges

DEFAULT_MEMORY_DB = "file:chaosblob-metrics?mode=memory&cache=shared"


class BlobBurstConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    enabled: bool = False
    interval_sec: int = Field(default=60, gt=0)
    duration_sec: int = Field(default=10, gt=0)
    slow_down_pct: float = Field(default=80.0, ge=0.0, le=100.0)
    service_unavailable_pct: float = Field(default=40.0, ge=0.0, le=100.0)

    @model_validator(mode="after")
    def _validate_burst_timing(self) -> "BlobBurstConfig":
        if self.enabled and self.duration_sec >= self.interval_sec:
            raise ValueError("duration_sec must be less than interval_sec when burst is enabled")
        return self


class BlobErrorInjectionConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    slow_down_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    access_denied_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    not_found_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    service_unavailable_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    internal_error_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    bad_gateway_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    gateway_timeout_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    timeout_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    timeout_sec: tuple[int, int] = (30, 60)
    connection_reset_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    connection_stall_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    connection_stall_start_sec: tuple[int, int] = (0, 2)
    connection_stall_sec: tuple[int, int] = (30, 60)
    slow_response_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    slow_response_sec: tuple[int, int] = (3, 15)
    truncated_body_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    wrong_content_length_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    checksum_mismatch_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    metadata_corruption_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    stale_list_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    malformed_xml_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    retry_after_sec: tuple[int, int] = (1, 30)
    selection_mode: Literal["priority", "weighted"] = "priority"
    burst: BlobBurstConfig = Field(default_factory=BlobBurstConfig)

    @field_validator("timeout_sec", "connection_stall_start_sec", "connection_stall_sec", "slow_response_sec", "retry_after_sec", mode="before")
    @classmethod
    def _parse_ranges(cls, value: Any) -> tuple[int, int]:
        return _parse_range(value)

    @model_validator(mode="after")
    def _validate_ranges_and_weights(self) -> "BlobErrorInjectionConfig":
        _validate_ranges(
            timeout_sec=self.timeout_sec,
            connection_stall_start_sec=self.connection_stall_start_sec,
            connection_stall_sec=self.connection_stall_sec,
            slow_response_sec=self.slow_response_sec,
            retry_after_sec=self.retry_after_sec,
        )
        if self.selection_mode == "weighted":
            total = (
                self.slow_down_pct + self.access_denied_pct + self.not_found_pct + self.service_unavailable_pct
                + self.internal_error_pct + self.bad_gateway_pct + self.gateway_timeout_pct + self.timeout_pct
                + self.connection_reset_pct + self.connection_stall_pct + self.slow_response_pct
                + self.truncated_body_pct + self.wrong_content_length_pct + self.checksum_mismatch_pct
                + self.metadata_corruption_pct + self.stale_list_pct + self.malformed_xml_pct
            )
            if total >= 100.0:
                warnings.warn("total error weights are >= 100; success responses may never occur", stacklevel=2)
        return self


class BlobStorageConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    max_object_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    default_content_type: str = "application/octet-stream"
    expose_s3_xml: bool = True


class ChaosBlobConfig(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    server: ServerConfig = Field(default_factory=lambda: ServerConfig(port=8300, workers=1))
    metrics: MetricsConfig = Field(default_factory=lambda: MetricsConfig(database=DEFAULT_MEMORY_DB))
    storage: BlobStorageConfig = Field(default_factory=BlobStorageConfig)
    latency: LatencyConfig = Field(default_factory=LatencyConfig)
    error_injection: BlobErrorInjectionConfig = Field(default_factory=BlobErrorInjectionConfig)
    allow_external_bind: bool = False
    preset_name: str | None = None

    @model_validator(mode="after")
    def _validate_server_safety(self) -> "ChaosBlobConfig":
        if self.server.host in DANGEROUS_BIND_HOSTS and not self.allow_external_bind:
            raise ValueError("binding to all interfaces requires allow_external_bind=true")
        if self.server.workers > 1 and self.metrics.is_in_memory():
            raise ValueError("workers > 1 requires a file-backed metrics database")
        return self


def _preset_dir() -> Path:
    return Path(__file__).parent / "presets"


def load_preset(name: str) -> dict[str, Any]:
    return _load_preset(name, _preset_dir())


def list_presets() -> list[str]:
    return _list_presets(_preset_dir())


def load_config(
    *,
    preset: str | None = None,
    config_file: str | Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> ChaosBlobConfig:
    return _load_config(
        config_model=ChaosBlobConfig,
        preset_dir=_preset_dir(),
        preset=preset,
        config_file=config_file,
        cli_overrides=cli_overrides,
    )
```

- [ ] **Step 4: Add preset YAML files**

Create `src/errorworks/blob/presets/silent.yaml`:

```yaml
server:
  port: 8300
  workers: 1
metrics:
  database: "file:chaosblob-metrics?mode=memory&cache=shared"
latency:
  base_ms: 10
  jitter_ms: 5
error_injection: {}
storage:
  max_object_bytes: 10485760
```

Create `src/errorworks/blob/presets/gentle.yaml` with `slow_down_pct: 1.0`, `not_found_pct: 0.5`, `base_ms: 50`, `jitter_ms: 20`.

Create `src/errorworks/blob/presets/realistic.yaml` with `slow_down_pct: 5.0`, `service_unavailable_pct: 2.0`, `internal_error_pct: 1.0`, `timeout_pct: 1.0`, `truncated_body_pct: 1.0`, `checksum_mismatch_pct: 1.0`, `stale_list_pct: 3.0`, burst enabled at `interval_sec: 60`, `duration_sec: 10`.

Create `src/errorworks/blob/presets/stress_storage.yaml` with `slow_down_pct: 15.0`, `service_unavailable_pct: 8.0`, `timeout_pct: 5.0`, `connection_reset_pct: 3.0`, `truncated_body_pct: 5.0`, `wrong_content_length_pct: 3.0`, `checksum_mismatch_pct: 4.0`, `metadata_corruption_pct: 3.0`, `stale_list_pct: 10.0`, `malformed_xml_pct: 2.0`, burst enabled at `interval_sec: 45`, `duration_sec: 12`.

Create `src/errorworks/blob/presets/stress_extreme.yaml` with every percentage field above set between `5.0` and `25.0`, burst enabled at `interval_sec: 30`, `duration_sec: 10`, and latency `base_ms: 500`, `jitter_ms: 250`.

- [ ] **Step 5: Run config tests**

Run: `uv run pytest tests/unit/blob/test_config.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/errorworks/blob/config.py src/errorworks/blob/presets tests/unit/blob
git commit -m "feat: add ChaosBlob configuration and presets"
```

---

## Task 2: Add In-Memory Blob Store

**Files:**
- Create: `src/errorworks/blob/store.py`
- Create: `tests/unit/blob/test_store.py`

- [ ] **Step 1: Write failing store tests**

Create `tests/unit/blob/test_store.py`:

```python
from __future__ import annotations

import pytest

from errorworks.blob.store import BlobObject, BlobStore, ObjectTooLargeError


def test_put_get_head_delete_round_trip() -> None:
    store = BlobStore(max_object_bytes=1024, default_content_type="application/octet-stream")
    stored = store.put("bucket", "a/b.txt", b"hello", {"content-type": "text/plain", "x-amz-meta-owner": "test"})

    assert stored.bucket == "bucket"
    assert stored.key == "a/b.txt"
    assert stored.body == b"hello"
    assert stored.size == 5
    assert stored.content_type == "text/plain"

    assert store.get("bucket", "a/b.txt") == stored
    assert store.head("bucket", "a/b.txt") == stored
    assert store.delete("bucket", "a/b.txt") is True
    assert store.get("bucket", "a/b.txt") is None


def test_put_rejects_large_object() -> None:
    store = BlobStore(max_object_bytes=3, default_content_type="application/octet-stream")
    with pytest.raises(ObjectTooLargeError):
        store.put("bucket", "too-big", b"abcd", {})


def test_list_filters_prefix_and_sorts_keys() -> None:
    store = BlobStore(max_object_bytes=1024, default_content_type="application/octet-stream")
    store.put("b", "logs/2.txt", b"2", {})
    store.put("b", "logs/1.txt", b"1", {})
    store.put("b", "images/1.png", b"x", {})

    page = store.list_objects("b", prefix="logs/", max_keys=10, continuation_token=None)
    assert [obj.key for obj in page.objects] == ["logs/1.txt", "logs/2.txt"]
    assert page.is_truncated is False
    assert page.next_continuation_token is None


def test_list_paginates_with_continuation_token() -> None:
    store = BlobStore(max_object_bytes=1024, default_content_type="application/octet-stream")
    for key in ["a", "b", "c"]:
        store.put("bucket", key, key.encode(), {})

    first = store.list_objects("bucket", prefix="", max_keys=2, continuation_token=None)
    second = store.list_objects("bucket", prefix="", max_keys=2, continuation_token=first.next_continuation_token)

    assert [obj.key for obj in first.objects] == ["a", "b"]
    assert first.is_truncated is True
    assert first.next_continuation_token == "2"
    assert [obj.key for obj in second.objects] == ["c"]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/blob/test_store.py -q`

Expected: import failure for `errorworks.blob.store`.

- [ ] **Step 3: Implement `src/errorworks/blob/store.py`**

Implement:

```python
"""Thread-safe in-memory object store for ChaosBlob."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from datetime import UTC, datetime


class ObjectTooLargeError(ValueError):
    """Raised when a PUT body exceeds the configured object size limit."""


@dataclass(frozen=True, slots=True)
class BlobObject:
    bucket: str
    key: str
    body: bytes
    content_type: str
    etag: str
    last_modified_utc: str
    metadata: dict[str, str]

    @property
    def size(self) -> int:
        return len(self.body)


@dataclass(frozen=True, slots=True)
class BlobListPage:
    objects: list[BlobObject]
    is_truncated: bool
    next_continuation_token: str | None


class BlobStore:
    """A small thread-safe object store with S3-like bucket/key addressing."""

    def __init__(self, *, max_object_bytes: int, default_content_type: str) -> None:
        self._max_object_bytes = max_object_bytes
        self._default_content_type = default_content_type
        self._objects: dict[tuple[str, str], BlobObject] = {}
        self._lock = threading.Lock()

    def put(self, bucket: str, key: str, body: bytes, headers: dict[str, str]) -> BlobObject:
        if len(body) > self._max_object_bytes:
            raise ObjectTooLargeError(f"object size {len(body)} exceeds max_object_bytes {self._max_object_bytes}")
        normalized = {name.lower(): value for name, value in headers.items()}
        content_type = normalized.get("content-type", self._default_content_type)
        metadata = {name: value for name, value in normalized.items() if name.startswith("x-amz-meta-")}
        etag = hashlib.md5(body, usedforsecurity=False).hexdigest()
        obj = BlobObject(
            bucket=bucket,
            key=key,
            body=body,
            content_type=content_type,
            etag=etag,
            last_modified_utc=datetime.now(UTC).isoformat(),
            metadata=metadata,
        )
        with self._lock:
            self._objects[(bucket, key)] = obj
        return obj

    def get(self, bucket: str, key: str) -> BlobObject | None:
        with self._lock:
            return self._objects.get((bucket, key))

    def head(self, bucket: str, key: str) -> BlobObject | None:
        return self.get(bucket, key)

    def delete(self, bucket: str, key: str) -> bool:
        with self._lock:
            return self._objects.pop((bucket, key), None) is not None

    def list_objects(
        self,
        bucket: str,
        *,
        prefix: str,
        max_keys: int,
        continuation_token: str | None,
    ) -> BlobListPage:
        start = int(continuation_token) if continuation_token else 0
        with self._lock:
            objects = sorted(
                (obj for (obj_bucket, _), obj in self._objects.items() if obj_bucket == bucket and obj.key.startswith(prefix)),
                key=lambda obj: obj.key,
            )
        page_objects = objects[start : start + max_keys]
        next_index = start + len(page_objects)
        is_truncated = next_index < len(objects)
        return BlobListPage(
            objects=page_objects,
            is_truncated=is_truncated,
            next_continuation_token=str(next_index) if is_truncated else None,
        )

    def reset(self) -> None:
        with self._lock:
            self._objects.clear()
```

- [ ] **Step 4: Run store tests**

Run: `uv run pytest tests/unit/blob/test_store.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/errorworks/blob/store.py tests/unit/blob/test_store.py
git commit -m "feat: add ChaosBlob in-memory object store"
```

---

## Task 3: Add S3 XML Helpers

**Files:**
- Create: `src/errorworks/blob/xml.py`
- Create: `tests/unit/blob/test_xml.py`

- [ ] **Step 1: Write failing XML tests**

Create `tests/unit/blob/test_xml.py`:

```python
from __future__ import annotations

from xml.etree import ElementTree

from errorworks.blob.store import BlobObject, BlobListPage
from errorworks.blob.xml import error_xml, list_objects_v2_xml


def test_error_xml_uses_s3_error_shape() -> None:
    body = error_xml("NoSuchKey", "The specified key does not exist.", resource="/bucket/key")
    root = ElementTree.fromstring(body)
    assert root.tag == "Error"
    assert root.findtext("Code") == "NoSuchKey"
    assert root.findtext("Message") == "The specified key does not exist."
    assert root.findtext("Resource") == "/bucket/key"


def test_list_objects_v2_xml_includes_object_metadata() -> None:
    obj = BlobObject(
        bucket="bucket",
        key="docs/a.txt",
        body=b"abc",
        content_type="text/plain",
        etag="900150983cd24fb0d6963f7d28e17f72",
        last_modified_utc="2026-05-24T00:00:00+00:00",
        metadata={},
    )
    xml = list_objects_v2_xml(
        bucket="bucket",
        prefix="docs/",
        max_keys=1000,
        continuation_token=None,
        page=BlobListPage(objects=[obj], is_truncated=False, next_continuation_token=None),
    )
    root = ElementTree.fromstring(xml)
    assert root.findtext("Name") == "bucket"
    assert root.findtext("Prefix") == "docs/"
    assert root.findtext("Contents/Key") == "docs/a.txt"
    assert root.findtext("Contents/Size") == "3"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/blob/test_xml.py -q`

Expected: import failure for `errorworks.blob.xml`.

- [ ] **Step 3: Implement XML helpers**

Implement `error_xml()` and `list_objects_v2_xml()` using `xml.etree.ElementTree`, not string concatenation. Use `ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)` and return `bytes`.

- [ ] **Step 4: Run XML tests**

Run: `uv run pytest tests/unit/blob/test_xml.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/errorworks/blob/xml.py tests/unit/blob/test_xml.py
git commit -m "feat: add ChaosBlob S3 XML helpers"
```

---

## Task 4: Add Blob Error Injector

**Files:**
- Create: `src/errorworks/blob/error_injector.py`
- Create: `tests/unit/blob/test_error_injector.py`

- [ ] **Step 1: Write failing injector tests**

Create tests for:

- `slow_down_pct=100.0` produces an HTTP error decision with status `503`, code `SlowDown`, and a Retry-After value.
- `truncated_body_pct=100.0` produces a body corruption decision.
- `stale_list_pct=100.0` only applies to list operations.
- Burst mode elevates `slow_down` and `service_unavailable`.
- `reset()` clears burst timing through the composed engine.

Use the same deterministic seeded `random.Random` style as `tests/unit/web/test_error_injector.py`.

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/blob/test_error_injector.py -q`

Expected: import failure for `errorworks.blob.error_injector`.

- [ ] **Step 3: Implement injector types**

Implement:

```python
from dataclasses import dataclass
from enum import StrEnum

class BlobOperation(StrEnum):
    PUT = "put"
    GET = "get"
    HEAD = "head"
    DELETE = "delete"
    LIST = "list"

class BlobErrorCategory(StrEnum):
    HTTP = "http"
    CONNECTION = "connection"
    BODY_CORRUPTION = "body_corruption"
    LIST_CORRUPTION = "list_corruption"
    METADATA_CORRUPTION = "metadata_corruption"

@dataclass(frozen=True, slots=True)
class BlobErrorDecision:
    error_type: str | None
    category: BlobErrorCategory | None
    status_code: int | None = None
    s3_code: str | None = None
    retry_after_sec: int | None = None
```

`BlobErrorInjector.decide(operation: BlobOperation) -> BlobErrorDecision | None` must build ordered `ErrorSpec` entries. Connection errors come first, then HTTP errors, then body/list/metadata corruption. Only include GET/HEAD body or metadata corruption for object reads. Only include `stale_list` and `malformed_xml` for list operations.

- [ ] **Step 4: Run injector tests**

Run: `uv run pytest tests/unit/blob/test_error_injector.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/errorworks/blob/error_injector.py tests/unit/blob/test_error_injector.py
git commit -m "feat: add ChaosBlob error injector"
```

---

## Task 5: Add Blob Metrics Recorder

**Files:**
- Create: `src/errorworks/blob/metrics.py`
- Create: `tests/unit/blob/test_metrics.py`

- [ ] **Step 1: Write failing metrics tests**

Create tests that record PUT, GET success, SlowDown, NoSuchKey, truncated body, checksum mismatch, stale list, and connection reset. Assert `get_stats()` exposes request totals, status-code counts, and timeseries buckets.

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/blob/test_metrics.py -q`

Expected: import failure for `errorworks.blob.metrics`.

- [ ] **Step 3: Implement metrics schema**

Use this request schema:

```python
BLOB_METRICS_SCHEMA = MetricsSchema(
    request_columns=(
        ColumnDef("request_id", SqlType.TEXT, nullable=False, primary_key=True),
        ColumnDef("timestamp_utc", SqlType.TEXT, nullable=False),
        ColumnDef("operation", SqlType.TEXT, nullable=False),
        ColumnDef("bucket", SqlType.TEXT, nullable=False),
        ColumnDef("object_key", SqlType.TEXT),
        ColumnDef("outcome", SqlType.TEXT, nullable=False),
        ColumnDef("status_code", SqlType.INTEGER),
        ColumnDef("error_type", SqlType.TEXT),
        ColumnDef("injection_type", SqlType.TEXT),
        ColumnDef("bytes_in", SqlType.INTEGER),
        ColumnDef("bytes_out", SqlType.INTEGER),
        ColumnDef("etag", SqlType.TEXT),
        ColumnDef("latency_ms", SqlType.REAL),
        ColumnDef("injected_delay_ms", SqlType.REAL),
    ),
    timeseries_columns=(
        ColumnDef("bucket_utc", SqlType.TEXT, nullable=False, primary_key=True),
        ColumnDef("requests_total", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_success", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_slow_down", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_not_found", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_access_denied", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_server_error", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_connection_error", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_corrupted", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("requests_stale_list", SqlType.INTEGER, nullable=False, default="0"),
        ColumnDef("avg_latency_ms", SqlType.REAL),
        ColumnDef("p99_latency_ms", SqlType.REAL),
    ),
    request_indexes=(
        ("idx_requests_timestamp", "timestamp_utc"),
        ("idx_requests_operation", "operation"),
        ("idx_requests_bucket_key", "bucket", "object_key"),
        ("idx_requests_outcome", "outcome"),
    ),
)
```

Classify `slow_down` separately from generic server errors because object stores expose throttling as `503 SlowDown`.

- [ ] **Step 4: Run metrics tests**

Run: `uv run pytest tests/unit/blob/test_metrics.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/errorworks/blob/metrics.py tests/unit/blob/test_metrics.py
git commit -m "feat: add ChaosBlob metrics recorder"
```

---

## Task 6: Add ChaosBlob ASGI Server

**Files:**
- Create: `src/errorworks/blob/server.py`
- Create: `tests/unit/blob/test_server.py`

- [ ] **Step 1: Write failing happy-path server tests**

In `tests/unit/blob/test_server.py`, use `starlette.testclient.TestClient` against:

```python
config = ChaosBlobConfig(
    metrics=MetricsConfig(database=str(tmp_path / "blob-metrics.db")),
    latency=LatencyConfig(base_ms=0, jitter_ms=0),
)
client = TestClient(create_app(config))
```

Cover:

- `GET /health`
- `PUT /bucket/key.txt`
- `GET /bucket/key.txt`
- `HEAD /bucket/key.txt`
- `DELETE /bucket/key.txt`
- `GET /bucket?list-type=2&prefix=logs/`
- `/admin/stats`
- `/admin/config` update for `slow_down_pct`
- `/admin/reset` clears metrics and store

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/blob/test_server.py -q`

Expected: import failure for `errorworks.blob.server`.

- [ ] **Step 3: Implement server skeleton and success paths**

`ChaosBlobServer` must mirror `ChaosWebServer`:

- Keep `_config_lock`.
- Compose `BlobErrorInjector`, `BlobStore`, `LatencySimulator`, and `BlobMetricsRecorder`.
- Reuse `errorworks.engine.admin` for `/admin/*`.
- Use routes in this order: `/health`, `/admin/config`, `/admin/stats`, `/admin/reset`, `/admin/export`, `/{bucket}`, `/{bucket}/{key:path}`.
- Treat `GET /{bucket}` with `list-type=2` as list; otherwise return `400 InvalidRequest`.
- Snapshot `error_injector`, `latency_simulator`, and config-derived references at request start.

Export:

```python
def create_app(config: ChaosBlobConfig | None = None) -> Starlette:
    server = ChaosBlobServer(config or ChaosBlobConfig())
    return server.app
```

- [ ] **Step 4: Add injected error handling tests**

Add tests for:

- `slow_down_pct=100.0` on GET returns `503`, XML body code `SlowDown`, and `Retry-After`.
- `access_denied_pct=100.0` returns `403 AccessDenied`.
- `not_found_pct=100.0` can force a `404 NoSuchKey`.
- `truncated_body_pct=100.0` returns HTTP 200 with a body shorter than the stored object.
- `checksum_mismatch_pct=100.0` returns an incorrect ETag.
- `wrong_content_length_pct=100.0` sets a mismatched `Content-Length`.
- `metadata_corruption_pct=100.0` drops at least one `x-amz-meta-*` header.
- `stale_list_pct=100.0` omits the newest object from list output.
- `malformed_xml_pct=100.0` returns unparseable XML for list.

- [ ] **Step 5: Implement injected behavior**

Implement S3-shaped errors with XML content type:

| Error type | Status | S3 code |
|---|---:|---|
| `slow_down` | 503 | `SlowDown` |
| `access_denied` | 403 | `AccessDenied` |
| `not_found` | 404 | `NoSuchKey` |
| `service_unavailable` | 503 | `ServiceUnavailable` |
| `internal_error` | 500 | `InternalError` |
| `bad_gateway` | 502 | `BadGateway` |
| `gateway_timeout` | 504 | `GatewayTimeout` |
| `timeout` | 504 | `RequestTimeout` |

For connection-level behaviors, follow the existing Web/LLM pattern: timeout sleeps then returns 504, reset/stall raise or return the closest Starlette-compatible simulated failure already used in current servers.

- [ ] **Step 6: Run server tests**

Run: `uv run pytest tests/unit/blob/test_server.py -q`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/errorworks/blob/server.py tests/unit/blob/test_server.py
git commit -m "feat: add ChaosBlob ASGI server"
```

---

## Task 7: Add CLI, Unified CLI, and Package Exports

**Files:**
- Create: `src/errorworks/blob/cli.py`
- Create: `src/errorworks/blob/__init__.py`
- Create: `tests/unit/blob/test_cli.py`
- Modify: `src/errorworks/engine/cli.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write failing CLI tests**

Create tests that mirror `tests/unit/web/test_cli.py`:

- `chaosblob presets` lists all five presets.
- `chaosblob show-config --preset=realistic --format=json` emits JSON.
- `chaosblob serve --preset=silent --port=9300` passes config to `uvicorn.run`.
- `chaosblob serve --workers=2` with in-memory DB exits with an error.
- `chaosengine blob presets` works through the unified CLI.

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/blob/test_cli.py -q`

Expected: import failure for `errorworks.blob.cli`.

- [ ] **Step 3: Implement CLI**

Mirror the Web CLI, using Blob-specific flags:

- `--slow-down-pct`
- `--access-denied-pct`
- `--not-found-pct`
- `--service-unavailable-pct`
- `--internal-error-pct`
- `--timeout-pct`
- `--truncated-body-pct`
- `--wrong-content-length-pct`
- `--checksum-mismatch-pct`
- `--metadata-corruption-pct`
- `--stale-list-pct`
- `--malformed-xml-pct`
- `--selection-mode`
- `--base-ms`
- `--jitter-ms`
- `--burst-enabled` / `--no-burst`
- `--burst-interval-sec`
- `--burst-duration-sec`
- `--max-object-bytes`

Add `[project.scripts] chaosblob = "errorworks.blob.cli:main"` and mount `blob_app` in `src/errorworks/engine/cli.py`.

- [ ] **Step 4: Run CLI tests**

Run: `uv run pytest tests/unit/blob/test_cli.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/errorworks/blob/__init__.py src/errorworks/blob/cli.py src/errorworks/engine/cli.py pyproject.toml tests/unit/blob/test_cli.py
git commit -m "feat: add ChaosBlob CLI"
```

---

## Task 8: Add Pytest Fixture and Integration Test

**Files:**
- Create: `tests/fixtures/chaosblob.py`
- Create: `tests/unit/blob/conftest.py`
- Create: `tests/unit/blob/test_fixture.py`
- Create: `tests/integration/test_blob_pipeline.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write failing fixture tests**

Create fixture tests for:

- `chaosblob.put_object("bucket", "key", b"data")`
- `chaosblob.get_object("bucket", "key")`
- `chaosblob.head_object("bucket", "key")`
- `chaosblob.list_objects("bucket", prefix="")`
- marker override: `@pytest.mark.chaosblob(preset="silent", slow_down_pct=100.0)`

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/blob/test_fixture.py tests/integration/test_blob_pipeline.py -q`

Expected: fixture import failure.

- [ ] **Step 3: Implement fixture**

`ChaosBlobFixture` should mirror the Web fixture and expose:

```python
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
```

Add `chaosblob: Configure ChaosBlob server for the test` to `tool.pytest.ini_options.markers`.

- [ ] **Step 4: Run fixture and integration tests**

Run: `uv run pytest tests/unit/blob/test_fixture.py tests/integration/test_blob_pipeline.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/chaosblob.py tests/unit/blob/conftest.py tests/unit/blob/test_fixture.py tests/integration/test_blob_pipeline.py pyproject.toml
git commit -m "test: add ChaosBlob pytest fixture"
```

---

## Task 9: Add Documentation

**Files:**
- Create: `docs/guide/chaosblob.md`
- Modify: `README.md`
- Modify: `docs/index.md`
- Modify: `docs/reference/api.md`
- Modify: `docs/reference/cli.md`
- Modify: `docs/reference/config-schema.md`
- Modify: `docs/guide/configuration.md`
- Modify: `docs/guide/presets.md`
- Modify: `docs/guide/testing-fixtures.md`
- Modify: `mkdocs.yml`

- [ ] **Step 1: Write the guide**

`docs/guide/chaosblob.md` must include:

- Quick start with `uv run chaosblob serve --preset=realistic`.
- Path-style S3 endpoints.
- Supported operations and explicit non-goals.
- Error injection table.
- Preset table.
- Example fixture test.

- [ ] **Step 2: Update reference docs**

Add ChaosBlob entries beside existing LLM/Web sections. Keep docs honest: call the API "S3-compatible-ish path-style object storage", not "full S3".

- [ ] **Step 3: Run docs-related checks**

Run: `uv run pytest tests/unit/blob -q`

Expected: all Blob unit tests pass.

Run: `uv run mkdocs build --strict`

Expected: docs build succeeds without broken nav warnings.

- [ ] **Step 4: Commit**

```bash
git add README.md docs mkdocs.yml
git commit -m "docs: document ChaosBlob"
```

---

## Task 10: Final Verification

**Files:**
- All files touched by Tasks 1-9.

- [ ] **Step 1: Run formatting and lint**

Run: `uv run ruff format src tests`

Expected: files formatted.

Run: `uv run ruff check src tests`

Expected: no lint errors.

- [ ] **Step 2: Run type checking**

Run: `uv run mypy src`

Expected: no type errors.

- [ ] **Step 3: Run focused and full tests**

Run: `uv run pytest tests/unit/blob tests/integration/test_blob_pipeline.py -q`

Expected: all Blob tests pass.

Run: `uv run pytest -q`

Expected: full suite passes.

- [ ] **Step 4: Update changelog**

Add to `CHANGELOG.md` under `[Unreleased]`:

```markdown
### Added

- **ChaosBlob**: S3-compatible-ish path-style object storage chaos server with
  PUT/GET/HEAD/DELETE/ListObjectsV2 support, blob-specific fault injection,
  metrics, CLI, presets, pytest fixture, and documentation.
```

- [ ] **Step 5: Commit final polish**

```bash
git add CHANGELOG.md
git commit -m "chore: record ChaosBlob changelog entry"
```

---

## Plan Self-Review

- Spec coverage: The plan covers config, presets, store, S3 XML, error injection, metrics, server, CLI, fixture, docs, and verification.
- Scope: The MVP intentionally avoids full S3 compatibility, auth validation, multipart upload, ACLs, versioning, and bucket management.
- Type consistency: The core names are stable across tasks: `ChaosBlobConfig`, `BlobStore`, `BlobErrorInjector`, `BlobMetricsRecorder`, `ChaosBlobServer`, and `ChaosBlobFixture`.
- Testability: Every implementation task starts with focused failing tests and ends with a targeted test command plus commit.
