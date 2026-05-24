from __future__ import annotations

import pytest

from errorworks.blob.store import BlobStore, ObjectTooLargeError


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
