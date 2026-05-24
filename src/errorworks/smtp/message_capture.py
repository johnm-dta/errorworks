"""Message capture helpers for ChaosSMTP."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from typing import NoReturn, TypeVar, overload

from errorworks.smtp.config import SMTPCaptureConfig

_SAFE_HEADERS = ("from", "to", "cc", "bcc", "subject", "message-id", "date")
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
    body: bytes | None
    truncated: bool


class MessageCapture:
    """Capture SMTP messages according to configured storage mode."""

    def __init__(self, config: SMTPCaptureConfig) -> None:
        self._config = config
        self._messages: list[CapturedMessage] = []
        self._lock = threading.Lock()

    @property
    def config(self) -> SMTPCaptureConfig:
        return self._config

    def capture(
        self,
        *,
        transaction_id: str,
        mail_from: str,
        rcpt_tos: list[str],
        data: bytes,
    ) -> CapturedMessage:
        parsed = BytesParser(policy=policy.default).parsebytes(data)
        safe_headers = {name: str(parsed[name]) for name in _SAFE_HEADERS if parsed[name] is not None}
        subject = safe_headers.get("subject")
        body: bytes | None = None
        truncated = False
        if self._config.mode == "full":
            limit = self._config.max_message_bytes
            body = data[:limit]
            truncated = len(data) > limit

        record = CapturedMessage(
            transaction_id=transaction_id,
            mail_from=mail_from,
            rcpt_tos=tuple(rcpt_tos),
            message_size_bytes=len(data),
            subject=subject if self._config.mode != "discard" else None,
            headers=_ImmutableHeaders(safe_headers if self._config.mode != "discard" else {}),
            body=body,
            truncated=truncated,
        )

        if self._config.mode != "discard":
            with self._lock:
                self._messages.append(record)
        return record

    def list_messages(self) -> list[CapturedMessage]:
        with self._lock:
            return list(self._messages)

    def reset(self) -> None:
        with self._lock:
            self._messages.clear()
