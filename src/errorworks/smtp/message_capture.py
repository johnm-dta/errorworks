"""Message capture helpers for ChaosSMTP."""

from __future__ import annotations

import asyncio
import base64
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from email import policy
from email.errors import MessageError
from email.parser import BytesParser
from typing import NoReturn, TypeVar, overload

from errorworks.smtp.config import SMTPCaptureConfig

_SAFE_HEADERS = ("from", "to", "cc", "bcc", "subject", "message-id", "date")


def _parse_message_bytes(data: bytes) -> dict[str, str]:
    """Parse raw SMTP DATA bytes and return safe headers.

    Returns an empty dict on any parse failure — chaos clients deliberately
    send malformed input, and the caller decides whether to log.
    """
    try:
        parsed = BytesParser(policy=policy.default).parsebytes(data)
        return {name: str(parsed[name]) for name in _SAFE_HEADERS if parsed[name] is not None}
    except (MessageError, ValueError, UnicodeDecodeError):
        return {}


_T = TypeVar("_T")


class _ImmutableHeaders(dict[str, str]):
    """Dict-compatible headers that reject caller mutation."""

    def _readonly(self) -> NoReturn:
        raise TypeError("captured message headers are immutable")

    def __setitem__(self, key: str, value: str) -> NoReturn:
        self._readonly()

    def __delitem__(self, key: str) -> NoReturn:
        self._readonly()

    def __ior__(self, other: Mapping[str, str]) -> NoReturn:  # type: ignore[misc, override]
        self._readonly()

    def clear(self) -> NoReturn:
        self._readonly()

    @overload
    def pop(self, key: str, /) -> str: ...

    @overload
    def pop(self, key: str, default: str, /) -> str: ...

    @overload
    def pop(self, key: str, default: _T, /) -> str | _T: ...

    def pop(self, key: str, default: object = None, /) -> NoReturn:
        self._readonly()

    def popitem(self) -> NoReturn:
        self._readonly()

    def setdefault(self, key: str, default: str = "") -> NoReturn:
        self._readonly()

    def update(self, *args: Mapping[str, str], **kwargs: str) -> NoReturn:  # type: ignore[override]
        self._readonly()


@dataclass(frozen=True, slots=True)
class CapturedMessage:
    """Captured SMTP message data."""

    transaction_id: str
    mail_from: str
    rcpt_tos: tuple[str, ...]
    message_size_bytes: int
    subject: str | None
    headers: Mapping[str, str]
    body: str | None
    body_encoding: str | None
    truncated: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "rcpt_tos", tuple(self.rcpt_tos))
        object.__setattr__(self, "headers", _ImmutableHeaders(dict(self.headers)))


class MessageCapture:
    """Capture SMTP messages according to configured storage mode."""

    def __init__(self, config: SMTPCaptureConfig) -> None:
        self._config = config
        self._messages: list[CapturedMessage] = []
        self._lock = threading.Lock()

    @property
    def config(self) -> SMTPCaptureConfig:
        with self._lock:
            return self._config

    def update_config(self, config: SMTPCaptureConfig) -> None:
        with self._lock:
            self._config = config
            self._trim_locked(config.max_messages)

    async def capture(
        self,
        *,
        transaction_id: str,
        mail_from: str,
        rcpt_tos: list[str],
        data: bytes,
        config: SMTPCaptureConfig | None = None,
    ) -> CapturedMessage:
        if config is None:
            with self._lock:
                config = self._config

        safe_headers = await asyncio.to_thread(_parse_message_bytes, data)
        subject = safe_headers.get("subject")
        body: str | None = None
        body_encoding: str | None = None
        truncated = False
        if config.mode == "full":
            limit = config.max_message_bytes
            body = base64.b64encode(data[:limit]).decode("ascii")
            body_encoding = "base64"
            truncated = len(data) > limit

        record = CapturedMessage(
            transaction_id=transaction_id,
            mail_from=mail_from,
            rcpt_tos=tuple(rcpt_tos),
            message_size_bytes=len(data),
            subject=subject if config.mode != "discard" else None,
            headers=safe_headers if config.mode != "discard" else {},
            body=body,
            body_encoding=body_encoding,
            truncated=truncated,
        )

        if config.mode != "discard":
            with self._lock:
                self._messages.append(record)
                self._trim_locked(config.max_messages)
        return record

    def list_messages(self) -> list[CapturedMessage]:
        with self._lock:
            return list(self._messages)

    def reset(self) -> None:
        with self._lock:
            self._messages.clear()

    def _trim_locked(self, max_messages: int) -> None:
        overflow = len(self._messages) - max_messages
        if overflow > 0:
            del self._messages[:overflow]
