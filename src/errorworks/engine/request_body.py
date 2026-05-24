"""Shared bounded request-body helpers."""

from __future__ import annotations

import json
from typing import Any

from starlette.requests import Request

MAX_JSON_BODY_BYTES = 1_048_576


class RequestBodyTooLarge(ValueError):
    """Raised when a request body exceeds the configured byte limit."""


class MalformedContentLength(ValueError):
    """Raised when the Content-Length header is present but not a valid non-negative integer.

    A non-integer or negative Content-Length is a client bug; we fail closed
    rather than silently disabling the up-front size guard and falling through
    to stream-and-enforce. Callers should map this to HTTP 400.

    Inherits from ``ValueError`` so existing handlers that catch
    ``ValueError`` for malformed JSON will also reject malformed
    Content-Length with a 400 response.
    """


async def read_limited_json(request: Request, *, max_bytes: int = MAX_JSON_BODY_BYTES) -> Any:
    """Read a JSON request body with a hard byte limit."""
    body = await read_limited_body(request, max_bytes=max_bytes)
    return json.loads(body)


async def read_limited_body(request: Request, *, max_bytes: int) -> bytes:
    """Read a request body with a hard byte limit.

    Raises:
        MalformedContentLength: Content-Length header is present but is not
            a valid non-negative integer.
        RequestBodyTooLarge: declared Content-Length, or streamed byte count,
            exceeds ``max_bytes``.
    """
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError as exc:
            raise MalformedContentLength(f"Content-Length header is not a valid integer: {content_length!r}") from exc
        if declared < 0:
            raise MalformedContentLength(f"Content-Length header is negative: {content_length!r}")
        if declared > max_bytes:
            raise RequestBodyTooLarge(f"Request body exceeds {max_bytes} bytes")

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise RequestBodyTooLarge(f"Request body exceeds {max_bytes} bytes")
        chunks.append(chunk)

    return b"".join(chunks)
