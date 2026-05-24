"""Shared bounded request-body helpers."""

from __future__ import annotations

import json
from typing import Any

from starlette.requests import Request

MAX_JSON_BODY_BYTES = 1_048_576


class RequestBodyTooLarge(ValueError):
    """Raised when a request body exceeds the configured byte limit."""


async def read_limited_json(request: Request, *, max_bytes: int = MAX_JSON_BODY_BYTES) -> Any:
    """Read a JSON request body with a hard byte limit."""
    body = await read_limited_body(request, max_bytes=max_bytes)
    return json.loads(body)


async def read_limited_body(request: Request, *, max_bytes: int) -> bytes:
    """Read a request body with a hard byte limit."""
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > max_bytes:
                raise RequestBodyTooLarge(f"Request body exceeds {max_bytes} bytes")
        except ValueError as exc:
            if isinstance(exc, RequestBodyTooLarge):
                raise

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise RequestBodyTooLarge(f"Request body exceeds {max_bytes} bytes")
        chunks.append(chunk)

    return b"".join(chunks)
