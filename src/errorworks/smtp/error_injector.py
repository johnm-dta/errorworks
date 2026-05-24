"""Error injection logic for ChaosSMTP."""

from __future__ import annotations

import random as random_module
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from errorworks.engine.injection_engine import InjectionEngine
from errorworks.engine.types import BurstConfig as EngineBurstConfig
from errorworks.engine.types import ErrorSpec
from errorworks.smtp.config import SMTPErrorInjectionConfig


class SMTPStage(StrEnum):
    CONNECT = "connect"
    MAIL = "mail"
    RCPT = "rcpt"
    DATA = "data"
    ACCEPT = "accept"


class SMTPErrorCategory(StrEnum):
    COMMAND = "command"
    CONNECTION = "connection"
    MALFORMED = "malformed"


@dataclass(frozen=True, slots=True)
class SMTPErrorDecision:
    """Result of an SMTP error injection decision."""

    error_type: str | None
    stage: SMTPStage | None = None
    reply_code: int | None = None
    message: str | None = None
    category: SMTPErrorCategory | None = None
    delay_sec: float | None = None

    @classmethod
    def success(cls) -> SMTPErrorDecision:
        return cls(error_type=None)

    @property
    def should_inject(self) -> bool:
        return self.error_type is not None

    @property
    def reply_line(self) -> str:
        if self.reply_code is None or self.message is None:
            raise ValueError("SMTPErrorDecision has no reply line")
        return f"{self.reply_code} {self.message}"


_STAGE_TAGS: dict[SMTPStage, tuple[str, ...]] = {
    SMTPStage.CONNECT: ("banner_reject", "connection_reset", "connection_stall", "slow_response", "malformed_reply", "wrong_reply_code"),
    SMTPStage.MAIL: ("mail_from_tempfail", "mail_from_reject", "rate_limit", "connection_reset", "connection_stall", "slow_response"),
    SMTPStage.RCPT: ("rcpt_to_tempfail", "rcpt_to_reject", "rate_limit", "connection_reset", "connection_stall", "slow_response"),
    SMTPStage.DATA: (
        "data_tempfail",
        "data_reject",
        "connection_reset",
        "connection_stall",
        "slow_response",
        "malformed_reply",
        "wrong_reply_code",
    ),
    SMTPStage.ACCEPT: ("accept_then_drop",),
}


class SMTPErrorInjector:
    """Decides per-stage SMTP error injection behavior."""

    def __init__(
        self,
        config: SMTPErrorInjectionConfig,
        *,
        time_func: Callable[[], float] | None = None,
        rng: random_module.Random | None = None,
    ) -> None:
        self._config = config
        self._rng = rng if rng is not None else random_module.Random()
        self._engine = InjectionEngine(
            selection_mode=config.selection_mode,
            burst_config=EngineBurstConfig(
                enabled=config.burst.enabled,
                interval_sec=config.burst.interval_sec,
                duration_sec=config.burst.duration_sec,
            ),
            time_func=time_func,
            rng=self._rng,
        )

    @property
    def config(self) -> SMTPErrorInjectionConfig:
        return self._config

    def _pick_delay(self, value_range: tuple[int, int]) -> float:
        return self._rng.uniform(*value_range)

    def _build_specs(self, stage: SMTPStage) -> list[ErrorSpec]:
        in_burst = self._engine.is_in_burst()
        tempfail_pct = self._config.burst.tempfail_pct if in_burst else self._config.rcpt_to_tempfail_pct
        rate_limit_pct = self._config.burst.rate_limit_pct if in_burst else self._config.rate_limit_pct
        weights = {
            "rate_limit": rate_limit_pct,
            "mail_from_tempfail": self._config.mail_from_tempfail_pct,
            "mail_from_reject": self._config.mail_from_reject_pct,
            "rcpt_to_tempfail": tempfail_pct,
            "rcpt_to_reject": self._config.rcpt_to_reject_pct,
            "data_tempfail": self._config.data_tempfail_pct,
            "data_reject": self._config.data_reject_pct,
            "accept_then_drop": self._config.accept_then_drop_pct,
            "banner_reject": self._config.banner_reject_pct,
            "malformed_reply": self._config.malformed_reply_pct,
            "wrong_reply_code": self._config.wrong_reply_code_pct,
            "connection_reset": self._config.connection_reset_pct,
            "connection_stall": self._config.connection_stall_pct,
            "slow_response": self._config.slow_response_pct,
        }
        return [ErrorSpec(tag, weights[tag]) for tag in _STAGE_TAGS[stage]]

    def _build_decision(self, stage: SMTPStage, tag: str) -> SMTPErrorDecision:
        if tag == "rate_limit":
            return SMTPErrorDecision(
                tag, stage, 450, "4.7.0 Mailbox temporarily unavailable due to rate limiting", SMTPErrorCategory.COMMAND
            )
        if tag == "mail_from_tempfail":
            return SMTPErrorDecision(tag, stage, 451, "4.3.0 Temporary sender failure", SMTPErrorCategory.COMMAND)
        if tag == "mail_from_reject":
            return SMTPErrorDecision(tag, stage, 550, "5.1.0 Sender rejected", SMTPErrorCategory.COMMAND)
        if tag == "rcpt_to_tempfail":
            return SMTPErrorDecision(tag, stage, 451, "4.3.0 Temporary recipient failure", SMTPErrorCategory.COMMAND)
        if tag == "rcpt_to_reject":
            return SMTPErrorDecision(tag, stage, 550, "5.1.1 Recipient rejected", SMTPErrorCategory.COMMAND)
        if tag == "data_tempfail":
            return SMTPErrorDecision(tag, stage, 451, "4.3.0 Temporary message failure", SMTPErrorCategory.COMMAND)
        if tag == "data_reject":
            return SMTPErrorDecision(tag, stage, 554, "5.6.0 Message rejected", SMTPErrorCategory.COMMAND)
        if tag == "accept_then_drop":
            return SMTPErrorDecision(tag, stage, 250, "2.0.0 Accepted but dropped by chaos policy", SMTPErrorCategory.COMMAND)
        if tag == "banner_reject":
            return SMTPErrorDecision(tag, stage, 421, "4.3.2 Service not available", SMTPErrorCategory.COMMAND)
        if tag == "malformed_reply":
            return SMTPErrorDecision(tag, stage, 299, "malformed reply", SMTPErrorCategory.MALFORMED)
        if tag == "wrong_reply_code":
            return SMTPErrorDecision(tag, stage, 252, "2.5.2 Cannot VRFY user, accepting chaos path", SMTPErrorCategory.MALFORMED)
        if tag == "connection_reset":
            return SMTPErrorDecision(tag, stage, category=SMTPErrorCategory.CONNECTION)
        if tag == "connection_stall":
            return SMTPErrorDecision(
                tag,
                stage,
                category=SMTPErrorCategory.CONNECTION,
                delay_sec=self._pick_delay(self._config.connection_stall_sec),
            )
        if tag == "slow_response":
            return SMTPErrorDecision(
                tag,
                stage,
                category=SMTPErrorCategory.CONNECTION,
                delay_sec=self._pick_delay(self._config.slow_response_sec),
            )
        raise ValueError(f"Unknown SMTP error tag: {tag}")

    def decide(self, stage: SMTPStage) -> SMTPErrorDecision:
        selected = self._engine.select(self._build_specs(stage))
        if selected is None:
            return SMTPErrorDecision.success()
        return self._build_decision(stage, selected.tag)

    def reset(self) -> None:
        self._engine.reset()

    def is_in_burst(self) -> bool:
        return self._engine.is_in_burst()
