"""Tests for ChaosSMTP error injection."""

import random

from errorworks.smtp.config import SMTPErrorInjectionConfig
from errorworks.smtp.error_injector import SMTPErrorCategory, SMTPErrorInjector, SMTPStage


def test_success_when_no_percentages_enabled() -> None:
    injector = SMTPErrorInjector(SMTPErrorInjectionConfig(), rng=random.Random(1))
    decision = injector.decide(SMTPStage.RCPT)
    assert decision.error_type is None
    assert decision.reply_code is None


def test_rcpt_tempfail_maps_to_451() -> None:
    injector = SMTPErrorInjector(SMTPErrorInjectionConfig(rcpt_to_tempfail_pct=100.0), rng=random.Random(1))
    decision = injector.decide(SMTPStage.RCPT)
    assert decision.error_type == "rcpt_to_tempfail"
    assert decision.reply_code == 451
    assert decision.category == SMTPErrorCategory.COMMAND


def test_rcpt_reject_maps_to_550() -> None:
    injector = SMTPErrorInjector(SMTPErrorInjectionConfig(rcpt_to_reject_pct=100.0), rng=random.Random(1))
    decision = injector.decide(SMTPStage.RCPT)
    assert decision.error_type == "rcpt_to_reject"
    assert decision.reply_code == 550


def test_data_reject_maps_to_554() -> None:
    injector = SMTPErrorInjector(SMTPErrorInjectionConfig(data_reject_pct=100.0), rng=random.Random(1))
    decision = injector.decide(SMTPStage.DATA)
    assert decision.error_type == "data_reject"
    assert decision.reply_code == 554


def test_stage_filters_unrelated_errors() -> None:
    injector = SMTPErrorInjector(SMTPErrorInjectionConfig(data_reject_pct=100.0), rng=random.Random(1))
    decision = injector.decide(SMTPStage.RCPT)
    assert decision.error_type is None


def test_connect_stage_is_not_exposed_without_listener_hook() -> None:
    assert "connect" not in {stage.value for stage in SMTPStage}


def test_burst_overrides_tempfail_rates() -> None:
    calls = iter([0.0, 1.0])
    injector = SMTPErrorInjector(
        SMTPErrorInjectionConfig(
            burst={"enabled": True, "interval_sec": 30, "duration_sec": 5, "rcpt_to_tempfail_pct": 100.0},
        ),
        rng=random.Random(1),
        time_func=lambda: next(calls),
    )
    decision = injector.decide(SMTPStage.RCPT)
    assert decision.error_type == "rcpt_to_tempfail"


def test_reset_clears_burst_state() -> None:
    injector = SMTPErrorInjector(SMTPErrorInjectionConfig(burst={"enabled": True}), rng=random.Random(1))
    injector.is_in_burst()
    injector.reset()
    assert isinstance(injector.is_in_burst(), bool)
