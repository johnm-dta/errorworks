"""Unit tests for read_limited_body / read_limited_json.

Focus: Content-Length header parsing discipline. A malformed
Content-Length must not silently disable the up-front size guard.
"""

from __future__ import annotations

from typing import Any

import anyio
import pytest
from starlette.requests import Request

from errorworks.engine.request_body import (
    MalformedContentLength,
    RequestBodyTooLarge,
    read_limited_body,
    read_limited_json,
)


def _make_request(
    *,
    headers: list[tuple[bytes, bytes]],
    chunks: list[bytes],
    method: str = "POST",
) -> Request:
    """Build a Starlette Request backed by a scripted receive() channel."""
    body_chunks: list[bytes] = list(chunks)

    async def receive() -> dict[str, Any]:
        if body_chunks:
            chunk = body_chunks.pop(0)
            more = bool(body_chunks)
            return {"type": "http.request", "body": chunk, "more_body": more}
        return {"type": "http.request", "body": b"", "more_body": False}

    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "root_path": "",
    }
    return Request(scope, receive)


def _run(coro: Any) -> Any:
    return anyio.run(lambda: coro)


# =============================================================================
# Malformed Content-Length: fail closed
# =============================================================================


def test_non_numeric_content_length_raises_malformed() -> None:
    request = _make_request(
        headers=[(b"content-length", b"abc")],
        chunks=[b"hi"],
    )
    with pytest.raises(MalformedContentLength):
        _run(read_limited_body(request, max_bytes=100))


def test_fractional_content_length_raises_malformed() -> None:
    request = _make_request(
        headers=[(b"content-length", b"1.5")],
        chunks=[b"hi"],
    )
    with pytest.raises(MalformedContentLength):
        _run(read_limited_body(request, max_bytes=100))


def test_negative_content_length_raises_malformed() -> None:
    request = _make_request(
        headers=[(b"content-length", b"-1")],
        chunks=[b"hi"],
    )
    with pytest.raises(MalformedContentLength):
        _run(read_limited_body(request, max_bytes=100))


def test_empty_content_length_raises_malformed() -> None:
    request = _make_request(
        headers=[(b"content-length", b"")],
        chunks=[b"hi"],
    )
    with pytest.raises(MalformedContentLength):
        _run(read_limited_body(request, max_bytes=100))


def test_malformed_content_length_is_value_error_subclass() -> None:
    """Existing callers that catch ValueError must still catch this."""
    assert issubclass(MalformedContentLength, ValueError)


# =============================================================================
# Up-front size guard still fires for huge declared sizes
# =============================================================================


def test_huge_content_length_rejected_up_front() -> None:
    request = _make_request(
        headers=[(b"content-length", b"9999999999")],
        chunks=[],  # body should not be read
    )
    with pytest.raises(RequestBodyTooLarge):
        _run(read_limited_body(request, max_bytes=100))


def test_content_length_exactly_at_limit_plus_one_rejected() -> None:
    request = _make_request(
        headers=[(b"content-length", b"101")],
        chunks=[],
    )
    with pytest.raises(RequestBodyTooLarge):
        _run(read_limited_body(request, max_bytes=100))


# =============================================================================
# Happy paths
# =============================================================================


def test_missing_content_length_falls_through_to_streaming() -> None:
    request = _make_request(
        headers=[],
        chunks=[b"hello"],
    )
    body = _run(read_limited_body(request, max_bytes=100))
    assert body == b"hello"


def test_missing_content_length_streaming_enforces_limit() -> None:
    request = _make_request(
        headers=[],
        chunks=[b"ab", b"cd", b"ef"],
    )
    with pytest.raises(RequestBodyTooLarge):
        _run(read_limited_body(request, max_bytes=3))


def test_valid_content_length_within_limit_returns_body() -> None:
    payload = b"x" * 100
    request = _make_request(
        headers=[(b"content-length", b"100")],
        chunks=[payload],
    )
    body = _run(read_limited_body(request, max_bytes=100))
    assert body == payload


def test_zero_content_length_returns_empty_body() -> None:
    request = _make_request(
        headers=[(b"content-length", b"0")],
        chunks=[],
    )
    body = _run(read_limited_body(request, max_bytes=100))
    assert body == b""


# =============================================================================
# read_limited_json delegates: malformed header bubbles up before json.loads
# =============================================================================


def test_read_limited_json_propagates_malformed_content_length() -> None:
    request = _make_request(
        headers=[(b"content-length", b"abc"), (b"content-type", b"application/json")],
        chunks=[b'{"x":1}'],
    )
    with pytest.raises(MalformedContentLength):
        _run(read_limited_json(request))


def test_read_limited_json_parses_valid_body() -> None:
    payload = b'{"hello": "world"}'
    request = _make_request(
        headers=[
            (b"content-length", str(len(payload)).encode()),
            (b"content-type", b"application/json"),
        ],
        chunks=[payload],
    )
    parsed = _run(read_limited_json(request))
    assert parsed == {"hello": "world"}
