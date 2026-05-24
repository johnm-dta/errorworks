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
    MAIL = "mail"
    RCPT = "rcpt"
    DATA = "data"
    ACCEPT = "accept"


class SMTPErrorCategory(StrEnum):
    COMMAND = "command"
    CONNECTION = "connection"
    MALFORMED = "malformed"


class SMTPErrorTag(StrEnum):
    RATE_LIMIT = "rate_limit"
    MAIL_FROM_TEMPFAIL = "mail_from_tempfail"
    MAIL_FROM_REJECT = "mail_from_reject"
    RCPT_TO_TEMPFAIL = "rcpt_to_tempfail"
    RCPT_TO_REJECT = "rcpt_to_reject"
    DATA_TEMPFAIL = "data_tempfail"
    DATA_REJECT = "data_reject"
    ACCEPT_THEN_DROP = "accept_then_drop"
    MALFORMED_REPLY = "malformed_reply"
    WRONG_REPLY_CODE = "wrong_reply_code"
    CONNECTION_RESET = "connection_reset"
    CONNECTION_STALL = "connection_stall"
    SLOW_RESPONSE = "slow_response"


@dataclass(frozen=True, slots=True)
class SMTPErrorDecision:
    """Result of an SMTP error injection decision."""

    error_type: SMTPErrorTag | None
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


_STAGE_TAGS: dict[SMTPStage, tuple[SMTPErrorTag, ...]] = {
    SMTPStage.MAIL: (
        SMTPErrorTag.MAIL_FROM_TEMPFAIL,
        SMTPErrorTag.MAIL_FROM_REJECT,
        SMTPErrorTag.RATE_LIMIT,
        SMTPErrorTag.CONNECTION_RESET,
        SMTPErrorTag.CONNECTION_STALL,
        SMTPErrorTag.SLOW_RESPONSE,
    ),
    SMTPStage.RCPT: (
        SMTPErrorTag.RCPT_TO_TEMPFAIL,
        SMTPErrorTag.RCPT_TO_REJECT,
        SMTPErrorTag.RATE_LIMIT,
        SMTPErrorTag.CONNECTION_RESET,
        SMTPErrorTag.CONNECTION_STALL,
        SMTPErrorTag.SLOW_RESPONSE,
    ),
    SMTPStage.DATA: (
        SMTPErrorTag.DATA_TEMPFAIL,
        SMTPErrorTag.DATA_REJECT,
        SMTPErrorTag.CONNECTION_RESET,
        SMTPErrorTag.CONNECTION_STALL,
        SMTPErrorTag.SLOW_RESPONSE,
        SMTPErrorTag.MALFORMED_REPLY,
        SMTPErrorTag.WRONG_REPLY_CODE,
    ),
    SMTPStage.ACCEPT: (SMTPErrorTag.ACCEPT_THEN_DROP,),
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
        tempfail_pct = self._config.burst.rcpt_to_tempfail_pct if in_burst else self._config.rcpt_to_tempfail_pct
        rate_limit_pct = self._config.burst.rate_limit_pct if in_burst else self._config.rate_limit_pct
        weights = {
            SMTPErrorTag.RATE_LIMIT: rate_limit_pct,
            SMTPErrorTag.MAIL_FROM_TEMPFAIL: self._config.mail_from_tempfail_pct,
            SMTPErrorTag.MAIL_FROM_REJECT: self._config.mail_from_reject_pct,
            SMTPErrorTag.RCPT_TO_TEMPFAIL: tempfail_pct,
            SMTPErrorTag.RCPT_TO_REJECT: self._config.rcpt_to_reject_pct,
            SMTPErrorTag.DATA_TEMPFAIL: self._config.data_tempfail_pct,
            SMTPErrorTag.DATA_REJECT: self._config.data_reject_pct,
            SMTPErrorTag.ACCEPT_THEN_DROP: self._config.accept_then_drop_pct,
            SMTPErrorTag.MALFORMED_REPLY: self._config.malformed_reply_pct,
            SMTPErrorTag.WRONG_REPLY_CODE: self._config.wrong_reply_code_pct,
            SMTPErrorTag.CONNECTION_RESET: self._config.connection_reset_pct,
            SMTPErrorTag.CONNECTION_STALL: self._config.connection_stall_pct,
            SMTPErrorTag.SLOW_RESPONSE: self._config.slow_response_pct,
        }
        return [ErrorSpec(tag.value, weights[tag]) for tag in _STAGE_TAGS[stage]]

    def _build_decision(self, stage: SMTPStage, tag: str) -> SMTPErrorDecision:
        error_tag = SMTPErrorTag(tag)
        if error_tag == SMTPErrorTag.RATE_LIMIT:
            return SMTPErrorDecision(
                error_tag, stage, 450, "4.7.0 Mailbox temporarily unavailable due to rate limiting", SMTPErrorCategory.COMMAND
            )
        if error_tag == SMTPErrorTag.MAIL_FROM_TEMPFAIL:
            return SMTPErrorDecision(error_tag, stage, 451, "4.3.0 Temporary sender failure", SMTPErrorCategory.COMMAND)
        if error_tag == SMTPErrorTag.MAIL_FROM_REJECT:
            return SMTPErrorDecision(error_tag, stage, 550, "5.1.0 Sender rejected", SMTPErrorCategory.COMMAND)
        if error_tag == SMTPErrorTag.RCPT_TO_TEMPFAIL:
            return SMTPErrorDecision(error_tag, stage, 451, "4.3.0 Temporary recipient failure", SMTPErrorCategory.COMMAND)
        if error_tag == SMTPErrorTag.RCPT_TO_REJECT:
            return SMTPErrorDecision(error_tag, stage, 550, "5.1.1 Recipient rejected", SMTPErrorCategory.COMMAND)
        if error_tag == SMTPErrorTag.DATA_TEMPFAIL:
            return SMTPErrorDecision(error_tag, stage, 451, "4.3.0 Temporary message failure", SMTPErrorCategory.COMMAND)
        if error_tag == SMTPErrorTag.DATA_REJECT:
            return SMTPErrorDecision(error_tag, stage, 554, "5.6.0 Message rejected", SMTPErrorCategory.COMMAND)
        if error_tag == SMTPErrorTag.ACCEPT_THEN_DROP:
            return SMTPErrorDecision(error_tag, stage, 250, "2.0.0 Accepted but dropped by chaos policy", SMTPErrorCategory.COMMAND)
        if error_tag == SMTPErrorTag.MALFORMED_REPLY:
            return SMTPErrorDecision(error_tag, stage, 299, "malformed reply", SMTPErrorCategory.MALFORMED)
        if error_tag == SMTPErrorTag.WRONG_REPLY_CODE:
            return SMTPErrorDecision(error_tag, stage, 252, "2.5.2 Cannot VRFY user, accepting chaos path", SMTPErrorCategory.MALFORMED)
        if error_tag == SMTPErrorTag.CONNECTION_RESET:
            return SMTPErrorDecision(error_tag, stage, category=SMTPErrorCategory.CONNECTION)
        if error_tag == SMTPErrorTag.CONNECTION_STALL:
            return SMTPErrorDecision(
                error_tag,
                stage,
                category=SMTPErrorCategory.CONNECTION,
                delay_sec=self._pick_delay(self._config.connection_stall_sec),
            )
        if error_tag == SMTPErrorTag.SLOW_RESPONSE:
            return SMTPErrorDecision(
                error_tag,
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
