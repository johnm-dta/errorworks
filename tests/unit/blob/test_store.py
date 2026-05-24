from __future__ import annotations

import pytest

from errorworks.blob.store import BlobListPage, BlobObject, BlobStore, InvalidContinuationTokenError, ObjectTooLargeError


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
    deleted = store.delete("bucket", "a/b.txt")
    assert deleted is True
    assert store.get("bucket", "a/b.txt") is None


def test_put_rejects_large_object() -> None:
    store = BlobStore(max_object_bytes=3, default_content_type="application/octet-stream")
    with pytest.raises(ObjectTooLargeError):
        store.put("bucket", "too-big", b"abcd", {})


def test_returned_metadata_is_immutable() -> None:
    store = BlobStore(max_object_bytes=1024, default_content_type="application/octet-stream")
    stored = store.put("bucket", "key", b"body", {"x-amz-meta-owner": "test"})

    with pytest.raises(TypeError):
        stored.metadata["x-amz-meta-owner"] = "mutated"

    reloaded = store.get("bucket", "key")
    assert reloaded is not None
    assert reloaded.metadata["x-amz-meta-owner"] == "test"


def test_direct_blob_object_wraps_headers_and_metadata_as_immutable() -> None:
    stored = BlobObject(
        bucket="bucket",
        key="key",
        body=b"body",
        headers={"content-type": "text/plain"},
        content_type="text/plain",
        metadata={"x-amz-meta-owner": "test"},
        etag="etag",
        last_modified_utc="2026-05-24T00:00:00+00:00",
    )

    with pytest.raises(TypeError):
        stored.headers["content-type"] = "application/json"
    with pytest.raises(TypeError):
        stored.metadata["x-amz-meta-owner"] = "mutated"


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
    assert first.next_continuation_token is not None
    assert [obj.key for obj in second.objects] == ["c"]


def test_list_continuation_token_starts_after_key_when_objects_mutate() -> None:
    store = BlobStore(max_object_bytes=1024, default_content_type="application/octet-stream")
    for key in ["a", "b", "c"]:
        store.put("bucket", key, key.encode(), {})

    first = store.list_objects("bucket", prefix="", max_keys=2, continuation_token=None)
    store.put("bucket", "aa", b"aa", {})
    second = store.list_objects("bucket", prefix="", max_keys=2, continuation_token=first.next_continuation_token)

    assert [obj.key for obj in first.objects] == ["a", "b"]
    assert [obj.key for obj in second.objects] == ["c"]


def test_blob_list_page_objects_are_immutable_tuple() -> None:
    page = BlobListPage(objects=[], is_truncated=False, next_continuation_token=None)

    assert page.objects == ()


@pytest.mark.parametrize("continuation_token", ["abc", "-1"])
def test_list_rejects_invalid_continuation_token(continuation_token: str) -> None:
    store = BlobStore(max_object_bytes=1024, default_content_type="application/octet-stream")

    with pytest.raises(InvalidContinuationTokenError):
        store.list_objects("bucket", prefix="", max_keys=10, continuation_token=continuation_token)


def test_list_treats_empty_continuation_token_as_no_token() -> None:
    store = BlobStore(max_object_bytes=1024, default_content_type="application/octet-stream")
    for key in ["a", "b"]:
        store.put("bucket", key, key.encode(), {})

    page = store.list_objects("bucket", prefix="", max_keys=10, continuation_token="")

    assert [obj.key for obj in page.objects] == ["a", "b"]
    assert page.is_truncated is False
    assert page.next_continuation_token is None
