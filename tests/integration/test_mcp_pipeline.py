"""Integration tests for MCP analysis tools against a real metrics database.

Tests verify that ChaosLLMAnalyzer produces correct results when pointed at
a database populated by MetricsRecorder, exercising the full write-then-read
pipeline without mocks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from errorworks.engine.types import MetricsConfig
from errorworks.llm.metrics import MetricsRecorder
from errorworks.llm_mcp.server import ChaosLLMAnalyzer

ENDPOINT = "/v1/chat/completions"


def _db_config(tmp_path: Path) -> MetricsConfig:
    """Create a MetricsConfig pointing at a temporary database file."""
    return MetricsConfig(database=str(tmp_path / "metrics.db"))


def _record_mixed_requests(
    recorder: MetricsRecorder,
    *,
    success_count: int = 18,
    error_count: int = 2,
) -> None:
    """Record a batch of requests with a known success/error distribution."""
    for i in range(success_count):
        recorder.record_request(
            request_id=str(uuid4()),
            timestamp_utc=datetime.now(UTC).isoformat(),
            endpoint=ENDPOINT,
            outcome="success",
            status_code=200,
            latency_ms=50.0 + i,
        )

    for _ in range(error_count):
        recorder.record_request(
            request_id=str(uuid4()),
            timestamp_utc=datetime.now(UTC).isoformat(),
            endpoint=ENDPOINT,
            outcome="error_injected",
            status_code=429,
            error_type="rate_limit",
            latency_ms=10.0,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_analyze_with_real_metrics_db(tmp_path: Path) -> None:
    """Diagnose returns a populated dict after recording mixed requests."""
    config = _db_config(tmp_path)
    recorder = MetricsRecorder(config)

    _record_mixed_requests(recorder, success_count=18, error_count=2)

    analyzer = ChaosLLMAnalyzer(database_path=str(tmp_path / "metrics.db"))
    try:
        result = analyzer.diagnose()

        assert isinstance(result, dict)
        assert result.get("status") != "NO_DATA"
        assert result["total_requests"] == 20
        assert result["success_rate_pct"] == 90.0
        assert "summary" in result
    finally:
        analyzer.close()
        recorder.close()


@pytest.mark.integration
def test_error_rate_tool_matches_recorded(tmp_path: Path) -> None:
    """analyze_errors reflects the exact error distribution we inserted."""
    config = _db_config(tmp_path)
    recorder = MetricsRecorder(config)

    _record_mixed_requests(recorder, success_count=18, error_count=2)

    analyzer = ChaosLLMAnalyzer(database_path=str(tmp_path / "metrics.db"))
    try:
        result = analyzer.analyze_errors()

        assert isinstance(result, dict)
        assert result["total_requests"] == 20
        assert result["total_errors"] == 2
        assert result["error_rate_pct"] == 10.0

        # The only error type we recorded is "rate_limit"
        by_type = result["by_error_type"]
        assert len(by_type) == 1
        assert by_type[0]["type"] == "rate_limit"
        assert by_type[0]["count"] == 2

        # Status-code breakdown should include 429
        status_codes = {entry["status_code"] for entry in result["by_status_code"]}
        assert 429 in status_codes
    finally:
        analyzer.close()
        recorder.close()


@pytest.mark.integration
def test_empty_database_returns_no_data(tmp_path: Path) -> None:
    """Analyzer handles an empty database gracefully without crashing."""
    config = _db_config(tmp_path)
    # Create the recorder so the schema exists, but insert nothing.
    recorder = MetricsRecorder(config)

    analyzer = ChaosLLMAnalyzer(database_path=str(tmp_path / "metrics.db"))
    try:
        result = analyzer.diagnose()

        assert isinstance(result, dict)
        assert result["status"] == "NO_DATA"
    finally:
        analyzer.close()
        recorder.close()


@pytest.mark.integration
def test_time_series_present_after_requests(tmp_path: Path) -> None:
    """After recording requests the timeseries table is populated and visible to the analyzer."""
    config = _db_config(tmp_path)
    recorder = MetricsRecorder(config)

    _record_mixed_requests(recorder, success_count=18, error_count=2)

    analyzer = ChaosLLMAnalyzer(database_path=str(tmp_path / "metrics.db"))
    try:
        rows = analyzer.query("SELECT * FROM timeseries")

        assert len(rows) >= 1
        # The bucket should aggregate exactly 20 requests total
        total_requests = sum(row["requests_total"] for row in rows)
        assert total_requests == 20

        total_success = sum(row["requests_success"] for row in rows)
        assert total_success == 18

        total_rate_limited = sum(row["requests_rate_limited"] for row in rows)
        assert total_rate_limited == 2
    finally:
        analyzer.close()
        recorder.close()
