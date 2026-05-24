"""Thread-safe in-memory object store for ChaosBlob."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from types import MappingProxyType


class ObjectTooLargeError(ValueError):
    """Raised when an object exceeds the configured in-memory size limit."""


class InvalidContinuationTokenError(ValueError):
    """Raised when an object-list continuation token is malformed."""


@dataclass(frozen=True, slots=True)
class BlobObject:
    """Stored object data and metadata."""

    bucket: str
    key: str
    body: bytes
    headers: Mapping[str, str]
    content_type: str
    metadata: Mapping[str, str]
    etag: str
    last_modified_utc: str

    @property
    def size(self) -> int:
        """Return object size in bytes."""
        return len(self.body)


@dataclass(frozen=True, slots=True)
class BlobListPage:
    """Single page of object-listing results."""

    objects: list[BlobObject]
    is_truncated: bool
    next_continuation_token: str | None


class BlobStore:
    """Thread-safe in-memory object store addressed by bucket and key."""

    def __init__(self, *, max_object_bytes: int, default_content_type: str) -> None:
        self._max_object_bytes = max_object_bytes
        self._default_content_type = default_content_type
        self._objects: dict[tuple[str, str], BlobObject] = {}
        self._lock = Lock()

    def put(self, bucket: str, key: str, body: bytes, headers: Mapping[str, str]) -> BlobObject:
        """Store an object and return its immutable snapshot."""
        if len(body) > self._max_object_bytes:
            raise ObjectTooLargeError(f"object size {len(body)} exceeds limit {self._max_object_bytes}")

        normalized_headers = {name.lower(): value for name, value in headers.items()}
        content_type = normalized_headers.get("content-type", self._default_content_type)
        metadata = {name: value for name, value in normalized_headers.items() if name.startswith("x-amz-meta-")}
        stored = BlobObject(
            bucket=bucket,
            key=key,
            body=body,
            headers=MappingProxyType(dict(normalized_headers)),
            content_type=content_type,
            metadata=MappingProxyType(dict(metadata)),
            etag=hashlib.md5(body, usedforsecurity=False).hexdigest(),
            last_modified_utc=datetime.now(UTC).isoformat(),
        )
        with self._lock:
            self._objects[(bucket, key)] = stored
        return stored

    def get(self, bucket: str, key: str) -> BlobObject | None:
        """Return an object snapshot by bucket and key, if present."""
        with self._lock:
            return self._objects.get((bucket, key))

    def head(self, bucket: str, key: str) -> BlobObject | None:
        """Return object metadata by bucket and key, if present."""
        return self.get(bucket, key)

    def delete(self, bucket: str, key: str) -> bool:
        """Delete an object by bucket and key."""
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
        """List objects in key order, starting at an integer continuation token."""
        start_index = self._parse_continuation_token(continuation_token)
        max_keys = max(max_keys, 0)

        with self._lock:
            objects = sorted(
                (
                    obj
                    for (stored_bucket, stored_key), obj in self._objects.items()
                    if stored_bucket == bucket and stored_key.startswith(prefix)
                ),
                key=lambda obj: obj.key,
            )

        page_objects = objects[start_index : start_index + max_keys]
        next_index = start_index + len(page_objects)
        is_truncated = next_index < len(objects)
        next_token = str(next_index) if is_truncated else None
        return BlobListPage(objects=page_objects, is_truncated=is_truncated, next_continuation_token=next_token)

    def reset(self) -> None:
        """Clear all stored objects."""
        with self._lock:
            self._objects.clear()

    def _parse_continuation_token(self, continuation_token: str | None) -> int:
        if continuation_token is None or continuation_token == "":
            return 0
        try:
            start_index = int(continuation_token)
        except ValueError as exc:
            raise InvalidContinuationTokenError(f"invalid continuation token: {continuation_token!r}") from exc
        if start_index < 0:
            raise InvalidContinuationTokenError(f"invalid continuation token: {continuation_token!r}")
        return start_index
