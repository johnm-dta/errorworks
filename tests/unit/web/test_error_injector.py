"""Tests for ChaosWeb error injector."""

from __future__ import annotations

import random
import threading

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from errorworks.web.config import WebBurstConfig, WebErrorInjectionConfig
from errorworks.web.error_injector import (
    SSRF_TARGETS,
    WEB_CONNECTION_ERRORS,
    WEB_HTTP_ERRORS,
    WEB_MALFORMED_TYPES,
    WEB_REDIRECT_TYPES,
    WebErrorCategory,
    WebErrorDecision,
    WebErrorInjector,
)


class FixedRandom(random.Random):
    """A Random instance that returns a fixed value for testing."""

    def __init__(self, value: float) -> None:
        super().__init__()
        self._fixed_value = value

    def random(self) -> float:
        return self._fixed_value


class TestWebErrorDecision:
    """Tests for WebErrorDecision dataclass."""

    def test_success_decision(self) -> None:
        """Success decision has no error type."""
        decision = WebErrorDecision.success()
        assert decision.error_type is None
        assert decision.status_code is None
        assert decision.should_inject is False
        assert decision.category is None

    def test_http_error_decision(self) -> None:
        """HTTP error decision has correct fields."""
        decision = WebErrorDecision.http_error("rate_limit", 429, retry_after_sec=5)
        assert decision.error_type == "rate_limit"
        assert decision.status_code == 429
        assert decision.retry_after_sec == 5
        assert decision.category == WebErrorCategory.HTTP
        assert decision.should_inject is True

    def test_http_error_without_retry_after(self) -> None:
        """HTTP error can omit retry_after_sec."""
        decision = WebErrorDecision.http_error("internal_error", 500)
        assert decision.error_type == "internal_error"
        assert decision.status_code == 500
        assert decision.retry_after_sec is None
        assert decision.should_inject is True

    def test_connection_error_decision(self) -> None:
        """Connection error decision has correct fields."""
        decision = WebErrorDecision.connection_error("timeout", delay_sec=30.5)
        assert decision.error_type == "timeout"
        assert decision.category == WebErrorCategory.CONNECTION
        assert decision.delay_sec == 30.5
        assert decision.status_code is None
        assert decision.should_inject is True

    def test_connection_error_without_delay(self) -> None:
        """Connection error can omit delay_sec."""
        decision = WebErrorDecision.connection_error("connection_reset")
        assert decision.error_type == "connection_reset"
        assert decision.delay_sec is None
        assert decision.should_inject is True

    def test_connection_error_with_incomplete_bytes(self) -> None:
        """Connection error can carry incomplete_bytes."""
        decision = WebErrorDecision.connection_error(
            "incomplete_response",
            incomplete_bytes=512,
        )
        assert decision.incomplete_bytes == 512

    def test_malformed_content_decision(self) -> None:
        """Malformed content decision has correct fields."""
        decision = WebErrorDecision.malformed_content("truncated_html")
        assert decision.error_type == "malformed"
        assert decision.status_code == 200  # Malformed still returns 200
        assert decision.category == WebErrorCategory.MALFORMED
        assert decision.malformed_type == "truncated_html"
        assert decision.should_inject is True

    def test_malformed_content_with_encoding(self) -> None:
        """Malformed content can carry encoding_actual."""
        decision = WebErrorDecision.malformed_content(
            "encoding_mismatch",
            encoding_actual="iso-8859-1",
        )
        assert decision.encoding_actual == "iso-8859-1"

    def test_redirect_decision(self) -> None:
        """Redirect decision has correct fields."""
        decision = WebErrorDecision.redirect(
            "ssrf_redirect",
            redirect_target="http://169.254.169.254/",
        )
        assert decision.error_type == "ssrf_redirect"
        assert decision.status_code == 301
        assert decision.category == WebErrorCategory.REDIRECT
        assert decision.redirect_target == "http://169.254.169.254/"
        assert decision.should_inject is True

    def test_redirect_loop_decision(self) -> None:
        """Redirect loop decision carries hop count."""
        decision = WebErrorDecision.redirect(
            "redirect_loop",
            redirect_hops=7,
        )
        assert decision.redirect_hops == 7
        assert decision.error_type == "redirect_loop"

    def test_is_connection_level_property(self) -> None:
        """is_connection_level returns True only for CONNECTION category."""
        assert WebErrorDecision.connection_error("timeout", delay_sec=5.0).is_connection_level is True
        assert WebErrorDecision.http_error("rate_limit", 429).is_connection_level is False
        assert WebErrorDecision.malformed_content("truncated_html").is_connection_level is False
        assert WebErrorDecision.redirect("ssrf_redirect", redirect_target="http://10.0.0.1/").is_connection_level is False
        assert WebErrorDecision.success().is_connection_level is False

    def test_is_malformed_property(self) -> None:
        """is_malformed returns True only for MALFORMED category."""
        assert WebErrorDecision.malformed_content("truncated_html").is_malformed is True
        assert WebErrorDecision.http_error("rate_limit", 429).is_malformed is False
        assert WebErrorDecision.connection_error("timeout").is_malformed is False
        assert WebErrorDecision.redirect("redirect_loop", redirect_hops=5).is_malformed is False
        assert WebErrorDecision.success().is_malformed is False

    def test_is_redirect_property(self) -> None:
        """is_redirect returns True only for REDIRECT category."""
        assert WebErrorDecision.redirect("ssrf_redirect", redirect_target="http://10.0.0.1/").is_redirect is True
        assert WebErrorDecision.redirect("redirect_loop", redirect_hops=5).is_redirect is True
        assert WebErrorDecision.http_error("rate_limit", 429).is_redirect is False
        assert WebErrorDecision.connection_error("timeout").is_redirect is False
        assert WebErrorDecision.malformed_content("truncated_html").is_redirect is False
        assert WebErrorDecision.success().is_redirect is False


class TestWebErrorInjectorBasic:
    """Basic tests for WebErrorInjector."""

    def test_no_errors_configured_always_succeeds(self) -> None:
        """With all error rates at 0, always succeeds."""
        config = WebErrorInjectionConfig()
        injector = WebErrorInjector(config)

        for _ in range(100):
            decision = injector.decide()
            assert decision.should_inject is False

    def test_hundred_percent_rate_limit_always_triggers(self) -> None:
        """100% rate_limit_pct always returns 429."""
        config = WebErrorInjectionConfig(rate_limit_pct=100.0)
        injector = WebErrorInjector(config)

        for _ in range(20):
            decision = injector.decide()
            assert decision.should_inject is True
            assert decision.error_type == "rate_limit"
            assert decision.status_code == 429

    def test_retry_after_in_range(self) -> None:
        """Retry-After is within configured range."""
        config = WebErrorInjectionConfig(
            rate_limit_pct=100.0,
            retry_after_sec=[3, 7],
        )
        injector = WebErrorInjector(config)

        values = set()
        for _ in range(50):
            decision = injector.decide()
            assert decision.retry_after_sec is not None
            values.add(decision.retry_after_sec)
            assert 3 <= decision.retry_after_sec <= 7

        assert len(values) > 1


class TestHTTPErrors:
    """Tests for HTTP-level error injection."""

    @pytest.mark.parametrize(
        "error_type,status_code,config_field",
        [
            ("rate_limit", 429, "rate_limit_pct"),
            ("forbidden", 403, "forbidden_pct"),
            ("not_found", 404, "not_found_pct"),
            ("gone", 410, "gone_pct"),
            ("payment_required", 402, "payment_required_pct"),
            ("unavailable_for_legal", 451, "unavailable_for_legal_pct"),
            ("service_unavailable", 503, "service_unavailable_pct"),
            ("bad_gateway", 502, "bad_gateway_pct"),
            ("gateway_timeout", 504, "gateway_timeout_pct"),
            ("internal_error", 500, "internal_error_pct"),
        ],
    )
    def test_http_error_types(
        self,
        error_type: str,
        status_code: int,
        config_field: str,
    ) -> None:
        """Each HTTP error type returns correct status code."""
        config = WebErrorInjectionConfig(**{config_field: 100.0})
        injector = WebErrorInjector(config)

        decision = injector.decide()
        assert decision.error_type == error_type
        assert decision.status_code == status_code
        assert decision.category == WebErrorCategory.HTTP

    def test_rate_limit_has_retry_after(self) -> None:
        """429 rate limit includes Retry-After."""
        config = WebErrorInjectionConfig(rate_limit_pct=100.0)
        injector = WebErrorInjector(config)

        decision = injector.decide()
        assert decision.retry_after_sec is not None

    def test_other_http_errors_no_retry_after(self) -> None:
        """Non-429 errors don't have Retry-After."""
        config = WebErrorInjectionConfig(internal_error_pct=100.0)
        injector = WebErrorInjector(config)

        decision = injector.decide()
        assert decision.retry_after_sec is None


class TestConnectionErrors:
    """Tests for connection-level error injection."""

    def test_timeout_error(self) -> None:
        """Timeout error has delay and correct category."""
        config = WebErrorInjectionConfig(
            timeout_pct=100.0,
            timeout_sec=[10, 20],
        )
        injector = WebErrorInjector(config)

        decision = injector.decide()
        assert decision.error_type == "timeout"
        assert decision.category == WebErrorCategory.CONNECTION
        assert decision.delay_sec is not None
        assert 10.0 <= decision.delay_sec <= 20.0

    def test_connection_reset_error(self) -> None:
        """Connection reset error has correct type."""
        config = WebErrorInjectionConfig(connection_reset_pct=100.0)
        injector = WebErrorInjector(config)

        decision = injector.decide()
        assert decision.error_type == "connection_reset"
        assert decision.category == WebErrorCategory.CONNECTION
        assert decision.delay_sec is None

    def test_connection_stall_error(self) -> None:
        """Connection stall error has start and stall delays."""
        config = WebErrorInjectionConfig(
            connection_stall_pct=100.0,
            connection_stall_start_sec=[1, 2],
            connection_stall_sec=[10, 20],
        )
        injector = WebErrorInjector(config)

        decision = injector.decide()
        assert decision.error_type == "connection_stall"
        assert decision.category == WebErrorCategory.CONNECTION
        assert decision.start_delay_sec is not None
        assert decision.delay_sec is not None
        assert 1.0 <= decision.start_delay_sec <= 2.0
        assert 10.0 <= decision.delay_sec <= 20.0

    def test_slow_response_error(self) -> None:
        """Slow response error has delay and correct category."""
        config = WebErrorInjectionConfig(
            slow_response_pct=100.0,
            slow_response_sec=[5, 15],
        )
        injector = WebErrorInjector(config)

        decision = injector.decide()
        assert decision.error_type == "slow_response"
        assert decision.category == WebErrorCategory.CONNECTION
        assert decision.delay_sec is not None
        assert 5.0 <= decision.delay_sec <= 15.0

    def test_incomplete_response_error(self) -> None:
        """Incomplete response error has byte count and correct category."""
        config = WebErrorInjectionConfig(
            incomplete_response_pct=100.0,
            incomplete_response_bytes=[100, 500],
        )
        injector = WebErrorInjector(config)

        decision = injector.decide()
        assert decision.error_type == "incomplete_response"
        assert decision.category == WebErrorCategory.CONNECTION
        assert decision.incomplete_bytes is not None
        assert 100 <= decision.incomplete_bytes <= 500

    def test_connection_errors_take_priority(self) -> None:
        """Connection errors have priority over HTTP errors."""
        config = WebErrorInjectionConfig(
            timeout_pct=100.0,
            rate_limit_pct=100.0,
        )
        injector = WebErrorInjector(config)

        decision = injector.decide()
        assert decision.error_type == "timeout"
        assert decision.category == WebErrorCategory.CONNECTION


class TestRedirectInjection:
    """Tests for redirect injection."""

    def test_ssrf_redirect(self) -> None:
        """SSRF redirect produces redirect to private IP."""
        config = WebErrorInjectionConfig(ssrf_redirect_pct=100.0)
        injector = WebErrorInjector(config)

        decision = injector.decide()
        assert decision.error_type == "ssrf_redirect"
        assert decision.category == WebErrorCategory.REDIRECT
        assert decision.status_code == 301
        assert decision.redirect_target is not None
        assert decision.redirect_target in SSRF_TARGETS

    def test_redirect_loop(self) -> None:
        """Redirect loop produces redirect with hop count."""
        config = WebErrorInjectionConfig(
            redirect_loop_pct=100.0,
            max_redirect_loop_hops=10,
        )
        injector = WebErrorInjector(config)

        decision = injector.decide()
        assert decision.error_type == "redirect_loop"
        assert decision.category == WebErrorCategory.REDIRECT
        assert decision.status_code == 301
        assert decision.redirect_hops is not None
        assert 3 <= decision.redirect_hops <= 10

    def test_redirect_priority_over_http(self) -> None:
        """Redirect errors have priority over HTTP errors."""
        config = WebErrorInjectionConfig(
            ssrf_redirect_pct=100.0,
            rate_limit_pct=100.0,
        )
        injector = WebErrorInjector(config)

        decision = injector.decide()
        assert decision.error_type == "ssrf_redirect"
        assert decision.category == WebErrorCategory.REDIRECT


class TestMalformedContentInjection:
    """Tests for content malformation injection."""

    @pytest.mark.parametrize(
        "malformed_type,config_field",
        [
            ("wrong_content_type", "wrong_content_type_pct"),
            ("encoding_mismatch", "encoding_mismatch_pct"),
            ("truncated_html", "truncated_html_pct"),
            ("invalid_encoding", "invalid_encoding_pct"),
            ("charset_confusion", "charset_confusion_pct"),
            ("malformed_meta", "malformed_meta_pct"),
        ],
    )
    def test_malformed_response_types(
        self,
        malformed_type: str,
        config_field: str,
    ) -> None:
        """Each malformed type is correctly identified."""
        config = WebErrorInjectionConfig(**{config_field: 100.0})
        injector = WebErrorInjector(config)

        decision = injector.decide()
        assert decision.error_type == "malformed"
        assert decision.malformed_type == malformed_type
        assert decision.category == WebErrorCategory.MALFORMED
        assert decision.status_code == 200

    def test_encoding_mismatch_has_actual_encoding(self) -> None:
        """Encoding mismatch carries the actual encoding."""
        config = WebErrorInjectionConfig(encoding_mismatch_pct=100.0)
        injector = WebErrorInjector(config)

        decision = injector.decide()
        assert decision.encoding_actual == "iso-8859-1"

    def test_http_errors_take_priority_over_malformed(self) -> None:
        """HTTP errors have priority over malformed responses."""
        config = WebErrorInjectionConfig(
            rate_limit_pct=100.0,
            truncated_html_pct=100.0,
        )
        injector = WebErrorInjector(config)

        decision = injector.decide()
        assert decision.error_type == "rate_limit"
        assert decision.category == WebErrorCategory.HTTP


class TestErrorPriority:
    """Tests for error priority ordering."""

    def test_connection_before_redirect_before_http_before_malformed(self) -> None:
        """Priority: connection > redirect > HTTP > malformed."""
        config = WebErrorInjectionConfig(
            timeout_pct=100.0,
            ssrf_redirect_pct=100.0,
            rate_limit_pct=100.0,
            truncated_html_pct=100.0,
        )
        injector = WebErrorInjector(config)

        # Should always get timeout (highest priority)
        for _ in range(10):
            decision = injector.decide()
            assert decision.error_type == "timeout"


class TestBurstStateMachine:
    """Tests for burst mode state machine."""

    def test_burst_disabled_by_default(self) -> None:
        """Burst mode is disabled by default."""
        config = WebErrorInjectionConfig()
        injector = WebErrorInjector(config)
        assert injector.is_in_burst() is False

    def test_burst_enabled_at_start(self) -> None:
        """When enabled, burst starts at time 0."""
        burst = WebBurstConfig(
            enabled=True,
            interval_sec=30,
            duration_sec=5,
        )
        config = WebErrorInjectionConfig(burst=burst)

        current_time = 0.0
        injector = WebErrorInjector(config, time_func=lambda: current_time)

        assert injector.is_in_burst() is True

    def test_burst_cycle(self) -> None:
        """Burst cycles through on/off periods."""
        burst = WebBurstConfig(
            enabled=True,
            interval_sec=10,
            duration_sec=3,
        )
        config = WebErrorInjectionConfig(burst=burst)

        current_time = [0.0]
        injector = WebErrorInjector(config, time_func=lambda: current_time[0])

        # t=0: start of burst
        assert injector.is_in_burst() is True

        # t=2: still in burst
        current_time[0] = 2.0
        assert injector.is_in_burst() is True

        # t=3: exited burst
        current_time[0] = 3.0
        assert injector.is_in_burst() is False

        # t=9: still not in burst
        current_time[0] = 9.0
        assert injector.is_in_burst() is False

        # t=10: new burst started
        current_time[0] = 10.0
        assert injector.is_in_burst() is True

        # t=13: exited burst
        current_time[0] = 13.0
        assert injector.is_in_burst() is False

    def test_burst_elevates_rate_limit(self) -> None:
        """Burst mode uses elevated rate_limit_pct."""
        burst = WebBurstConfig(
            enabled=True,
            interval_sec=10,
            duration_sec=5,
            rate_limit_pct=100.0,
        )
        config = WebErrorInjectionConfig(
            rate_limit_pct=0.0,
            burst=burst,
        )

        current_time = [0.0]
        injector = WebErrorInjector(config, time_func=lambda: current_time[0])

        # During burst: should always trigger rate limit
        for _ in range(10):
            decision = injector.decide()
            assert decision.error_type == "rate_limit"

        # Outside burst: should never trigger
        current_time[0] = 6.0
        for _ in range(10):
            decision = injector.decide()
            assert decision.should_inject is False

    def test_burst_elevates_forbidden(self) -> None:
        """Burst mode uses elevated forbidden_pct."""
        burst = WebBurstConfig(
            enabled=True,
            interval_sec=10,
            duration_sec=5,
            rate_limit_pct=0.0,
            forbidden_pct=100.0,
        )
        config = WebErrorInjectionConfig(
            rate_limit_pct=0.0,
            forbidden_pct=0.0,
            burst=burst,
        )

        current_time = [0.0]
        injector = WebErrorInjector(config, time_func=lambda: current_time[0])

        # During burst: should always trigger forbidden
        for _ in range(10):
            decision = injector.decide()
            assert decision.error_type == "forbidden"
            assert decision.status_code == 403

        # Outside burst: should never trigger
        current_time[0] = 6.0
        for _ in range(10):
            decision = injector.decide()
            assert decision.should_inject is False


class TestRandomDecisions:
    """Tests for random decision logic."""

    def test_deterministic_with_fixed_random(self) -> None:
        """FixedRandom at 0.3 triggers 50% threshold."""
        config = WebErrorInjectionConfig(rate_limit_pct=50.0)

        # 0.3 * 100 = 30 < 50 threshold, so should trigger
        injector = WebErrorInjector(config, rng=FixedRandom(0.3))
        assert injector.decide().should_inject is True

        # 0.6 * 100 = 60 >= 50 threshold, so should NOT trigger
        injector = WebErrorInjector(config, rng=FixedRandom(0.6))
        assert injector.decide().should_inject is False

    def test_zero_percent_never_triggers(self) -> None:
        """0% error rate never triggers."""
        config = WebErrorInjectionConfig(rate_limit_pct=0.0)
        injector = WebErrorInjector(config)

        for _ in range(100):
            assert injector.decide().should_inject is False

    def test_fifty_percent_roughly_half(self) -> None:
        """50% error rate triggers roughly half the time."""
        config = WebErrorInjectionConfig(rate_limit_pct=50.0)
        injector = WebErrorInjector(config)

        errors = sum(1 for _ in range(1000) if injector.decide().should_inject)
        assert 400 <= errors <= 600


class TestWeightedSelection:
    """Tests for weighted error selection."""

    def test_weighted_mix_selects_multiple_types(self) -> None:
        """Weighted mode mixes error types instead of strict priority."""
        config = WebErrorInjectionConfig(
            rate_limit_pct=50.0,
            forbidden_pct=50.0,
            selection_mode="weighted",
        )
        injector = WebErrorInjector(config, rng=random.Random(123))

        decisions = [injector.decide().error_type for _ in range(100)]
        assert "rate_limit" in decisions
        assert "forbidden" in decisions


class TestThreadSafety:
    """Tests for thread-safe operation."""

    def test_concurrent_decide_calls(self) -> None:
        """Multiple threads can call decide() safely."""
        config = WebErrorInjectionConfig(rate_limit_pct=50.0)
        injector = WebErrorInjector(config)

        results: list[bool] = []
        lock = threading.Lock()

        def worker() -> None:
            for _ in range(100):
                decision = injector.decide()
                with lock:
                    results.append(decision.should_inject)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 1000
        assert any(r for r in results)
        assert any(not r for r in results)

    def test_burst_state_thread_safe(self) -> None:
        """Burst state tracking is thread-safe."""
        burst = WebBurstConfig(
            enabled=True,
            interval_sec=100,
            duration_sec=50,
        )
        config = WebErrorInjectionConfig(burst=burst)
        injector = WebErrorInjector(config)

        results: list[bool] = []
        lock = threading.Lock()

        def worker() -> None:
            for _ in range(100):
                is_burst = injector.is_in_burst()
                with lock:
                    results.append(is_burst)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 1000
        assert all(r for r in results)


class TestReset:
    """Tests for injector reset functionality."""

    def test_reset_clears_burst_timing(self) -> None:
        """Reset clears the start time for burst calculations."""
        burst = WebBurstConfig(
            enabled=True,
            interval_sec=10,
            duration_sec=3,
        )
        config = WebErrorInjectionConfig(burst=burst)

        current_time = [0.0]
        injector = WebErrorInjector(config, time_func=lambda: current_time[0])

        # Initialize at time 0 (in burst)
        injector.decide()
        assert injector.is_in_burst() is True

        # Move to outside burst period
        current_time[0] = 5.0
        assert injector.is_in_burst() is False

        # Reset at time 15 — elapsed resets to 0
        current_time[0] = 15.0
        injector.reset()
        # Now is_in_burst() re-establishes start_time as 15
        # elapsed = 15 - 15 = 0 -> in burst
        assert injector.is_in_burst() is True


class TestConstants:
    """Tests for module constants."""

    def test_web_http_errors_mapping(self) -> None:
        """WEB_HTTP_ERRORS contains all expected error types."""
        expected = {
            "rate_limit": 429,
            "forbidden": 403,
            "not_found": 404,
            "gone": 410,
            "payment_required": 402,
            "unavailable_for_legal": 451,
            "service_unavailable": 503,
            "bad_gateway": 502,
            "gateway_timeout": 504,
            "internal_error": 500,
        }
        assert expected == WEB_HTTP_ERRORS

    def test_web_connection_errors_set(self) -> None:
        """WEB_CONNECTION_ERRORS contains all expected types."""
        expected = {
            "timeout",
            "connection_reset",
            "connection_stall",
            "slow_response",
            "incomplete_response",
        }
        assert expected == WEB_CONNECTION_ERRORS

    def test_web_malformed_types_set(self) -> None:
        """WEB_MALFORMED_TYPES contains all expected types."""
        expected = {
            "wrong_content_type",
            "encoding_mismatch",
            "truncated_html",
            "invalid_encoding",
            "charset_confusion",
            "malformed_meta",
        }
        assert expected == WEB_MALFORMED_TYPES

    def test_web_redirect_types_set(self) -> None:
        """WEB_REDIRECT_TYPES contains all expected types."""
        expected = {"redirect_loop", "ssrf_redirect"}
        assert expected == WEB_REDIRECT_TYPES

    def test_ssrf_targets_not_empty(self) -> None:
        """SSRF_TARGETS has entries."""
        assert len(SSRF_TARGETS) > 0
        for target in SSRF_TARGETS:
            assert target.startswith("http")


# ---------------------------------------------------------------------------
# Property-based tests for error rate accuracy
# ---------------------------------------------------------------------------

@settings(max_examples=200)
@given(rate=st.floats(min_value=5.0, max_value=95.0))
def test_web_error_rate_accuracy_property(rate: float) -> None:
    """Observed injection rate should approximate configured rate."""
    config = WebErrorInjectionConfig(rate_limit_pct=rate)
    injector = WebErrorInjector(config)
    n = 2000
    injected = sum(1 for _ in range(n) if injector.decide().should_inject)
    observed_pct = (injected / n) * 100
    assert abs(observed_pct - rate) < 5.0, f"Configured {rate}%, observed {observed_pct}%"
