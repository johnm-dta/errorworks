"""Tests for ChaosWeb metrics recorder."""

from __future__ import annotations

import threading
import time
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from errorworks.engine.metrics_store import _get_bucket_utc
from errorworks.engine.types import MetricsConfig
from errorworks.web.metrics import (
    WebMetricsRecorder,
    WebOutcomeClassification,
    _classify_web_outcome,
)


class TestGetBucketUtc:
    """Tests for _get_bucket_utc helper function."""

    def test_bucket_truncates_to_second(self) -> None:
        """Bucket truncates timestamp to second boundary."""
        timestamp = "2024-01-15T10:30:45.123+00:00"
        bucket = _get_bucket_utc(timestamp, bucket_sec=1)
        assert bucket.startswith("2024-01-15T10:30:45")

    def test_bucket_10_second(self) -> None:
        """10-second bucket truncates correctly."""
        timestamp = "2024-01-15T10:30:47+00:00"
        bucket = _get_bucket_utc(timestamp, bucket_sec=10)
        assert bucket.startswith("2024-01-15T10:30:40")

    def test_bucket_60_second(self) -> None:
        """60-second bucket truncates to minute boundary."""
        timestamp = "2024-01-15T10:30:47+00:00"
        bucket = _get_bucket_utc(timestamp, bucket_sec=60)
        assert bucket.startswith("2024-01-15T10:30:00")

    def test_bucket_handles_z_suffix(self) -> None:
        """Handles 'Z' timezone suffix."""
        timestamp = "2024-01-15T10:30:45Z"
        bucket = _get_bucket_utc(timestamp, bucket_sec=1)
        assert "2024-01-15T10:30:45" in bucket


class TestClassifyWebOutcome:
    """Tests for _classify_web_outcome helper function."""

    def test_returns_named_tuple(self) -> None:
        """Returns a WebOutcomeClassification NamedTuple."""
        result = _classify_web_outcome("success", 200, None)
        assert isinstance(result, WebOutcomeClassification)

    def test_success_outcome(self) -> None:
        """Success outcome is classified correctly."""
        result = _classify_web_outcome("success", 200, None)
        assert result.success is True
        assert result.rate_limited is False
        assert result.forbidden is False
        assert result.not_found is False
        assert result.server_error is False
        assert result.connection_error is False
        assert result.malformed is False
        assert result.redirect is False

    def test_rate_limited_429(self) -> None:
        """429 status code is classified as rate limited."""
        result = _classify_web_outcome("error_injected", 429, None)
        assert result.rate_limited is True

    def test_forbidden_403(self) -> None:
        """403 status code is classified as forbidden."""
        result = _classify_web_outcome("error_injected", 403, None)
        assert result.forbidden is True

    def test_not_found_404(self) -> None:
        """404 status code is classified as not_found."""
        result = _classify_web_outcome("error_injected", 404, None)
        assert result.not_found is True

    def test_server_error_500(self) -> None:
        """500 status code is classified as server error."""
        result = _classify_web_outcome("error_injected", 500, None)
        assert result.server_error is True

    def test_server_error_503(self) -> None:
        """503 status code is classified as server error."""
        result = _classify_web_outcome("error_injected", 503, None)
        assert result.server_error is True

    def test_connection_error_timeout(self) -> None:
        """Timeout error type with no status code is classified as connection error."""
        result = _classify_web_outcome("error_injected", None, "timeout")
        assert result.connection_error is True

    def test_connection_error_reset(self) -> None:
        """Connection reset error is classified as connection error."""
        result = _classify_web_outcome("error_injected", None, "connection_reset")
        assert result.connection_error is True

    def test_connection_error_stall(self) -> None:
        """Connection stall error is classified as connection error."""
        result = _classify_web_outcome("error_injected", None, "connection_stall")
        assert result.connection_error is True

    def test_connection_error_slow_response(self) -> None:
        """Slow response error is classified as connection error."""
        result = _classify_web_outcome("error_injected", None, "slow_response")
        assert result.connection_error is True

    def test_connection_error_incomplete_response(self) -> None:
        """Incomplete response error is classified as connection error."""
        result = _classify_web_outcome("error_injected", None, "incomplete_response")
        assert result.connection_error is True

    def test_connection_error_false_when_status_code_present(self) -> None:
        """Error type in connection list but with a status code should NOT be connection_error."""
        result = _classify_web_outcome("success", 200, "timeout")
        assert result.connection_error is False

    def test_malformed_outcome(self) -> None:
        """error_malformed outcome is classified correctly."""
        result = _classify_web_outcome("error_malformed", 200, None)
        assert result.malformed is True

    def test_redirect_outcome(self) -> None:
        """error_redirect outcome is classified correctly."""
        result = _classify_web_outcome("error_redirect", 301, None)
        assert result.redirect is True


class TestWebMetricsRecorderBasic:
    """Basic tests for WebMetricsRecorder."""

    def test_init_creates_database(self, tmp_path: Path) -> None:
        """Initialization creates the database file."""
        db_path = tmp_path / "metrics.db"
        config = MetricsConfig(database=str(db_path))
        recorder = WebMetricsRecorder(config)

        assert db_path.exists()
        recorder.close()

    def test_generates_run_id(self, tmp_path: Path) -> None:
        """Generates a UUID run_id if not provided."""
        db_path = tmp_path / "metrics.db"
        config = MetricsConfig(database=str(db_path))
        recorder = WebMetricsRecorder(config)

        assert recorder.run_id is not None
        assert len(recorder.run_id) == 36  # UUID length
        recorder.close()

    def test_uses_provided_run_id(self, tmp_path: Path) -> None:
        """Uses the provided run_id if given."""
        db_path = tmp_path / "metrics.db"
        config = MetricsConfig(database=str(db_path))
        recorder = WebMetricsRecorder(config, run_id="custom-run-id")

        assert recorder.run_id == "custom-run-id"
        recorder.close()

    def test_records_started_utc(self, tmp_path: Path) -> None:
        """Records start time in UTC."""
        db_path = tmp_path / "metrics.db"
        config = MetricsConfig(database=str(db_path))

        before = datetime.now(UTC)
        recorder = WebMetricsRecorder(config)
        after = datetime.now(UTC)

        started = datetime.fromisoformat(recorder.started_utc)
        assert before <= started <= after
        recorder.close()


class TestRecordRequest:
    """Tests for record_request method."""

    @pytest.fixture
    def recorder(self, tmp_path: Path) -> Generator[WebMetricsRecorder, None, None]:
        """Create a fresh recorder for each test."""
        db_path = tmp_path / "metrics.db"
        config = MetricsConfig(database=str(db_path))
        recorder = WebMetricsRecorder(config)
        yield recorder
        recorder.close()

    def test_record_request_appears_in_stats(self, recorder: WebMetricsRecorder) -> None:
        """A recorded request appears in get_stats()."""
        recorder.record_request(
            request_id="req1",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            path="/test",
            outcome="success",
            status_code=200,
            latency_ms=50.0,
        )

        stats = recorder.get_stats()
        assert stats["total_requests"] == 1
        assert stats["requests_by_outcome"]["success"] == 1

    def test_record_multiple_requests(self, recorder: WebMetricsRecorder) -> None:
        """Multiple requests are counted correctly."""
        for i in range(10):
            recorder.record_request(
                request_id=f"req{i}",
                timestamp_utc=f"2024-01-15T10:30:{i:02d}+00:00",
                path="/test",
                outcome="success",
            )

        stats = recorder.get_stats()
        assert stats["total_requests"] == 10

    def test_record_with_web_specific_fields(self, recorder: WebMetricsRecorder) -> None:
        """Web-specific fields are recorded correctly."""
        recorder.record_request(
            request_id="req1",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            path="/test",
            outcome="error_redirect",
            status_code=301,
            error_type="ssrf_redirect",
            redirect_target="http://169.254.169.254/",
            redirect_hops=None,
        )

        requests = recorder.get_requests()
        assert len(requests) == 1
        assert requests[0]["redirect_target"] == "http://169.254.169.254/"

    def test_record_request_with_content_type(self, recorder: WebMetricsRecorder) -> None:
        """Content type and encoding fields are stored."""
        recorder.record_request(
            request_id="req1",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            path="/test",
            outcome="error_malformed",
            status_code=200,
            content_type_served="text/html; charset=utf-8",
            encoding_served="iso-8859-1",
        )

        requests = recorder.get_requests()
        assert requests[0]["content_type_served"] == "text/html; charset=utf-8"
        assert requests[0]["encoding_served"] == "iso-8859-1"


class TestTimeseries:
    """Tests for time-series aggregation."""

    @pytest.fixture
    def recorder(self, tmp_path: Path) -> Generator[WebMetricsRecorder, None, None]:
        """Create a fresh recorder with 1-second buckets."""
        db_path = tmp_path / "metrics.db"
        config = MetricsConfig(database=str(db_path), timeseries_bucket_sec=1)
        recorder = WebMetricsRecorder(config)
        yield recorder
        recorder.close()

    def test_requests_in_same_bucket_aggregate(self, recorder: WebMetricsRecorder) -> None:
        """Requests in the same bucket are aggregated."""
        for i in range(5):
            recorder.record_request(
                request_id=f"req{i}",
                timestamp_utc="2024-01-15T10:30:00.100+00:00",
                path="/test",
                outcome="success",
                status_code=200,
            )

        timeseries = recorder.get_timeseries()
        assert len(timeseries) == 1
        assert timeseries[0]["requests_total"] == 5
        assert timeseries[0]["requests_success"] == 5

    def test_requests_in_different_buckets_separate(self, recorder: WebMetricsRecorder) -> None:
        """Requests in different buckets are tracked separately."""
        recorder.record_request(
            request_id="req1",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            path="/test",
            outcome="success",
            status_code=200,
        )
        recorder.record_request(
            request_id="req2",
            timestamp_utc="2024-01-15T10:30:01+00:00",
            path="/test",
            outcome="success",
            status_code=200,
        )

        timeseries = recorder.get_timeseries()
        assert len(timeseries) == 2

    def test_rate_limit_classification_in_timeseries(self, recorder: WebMetricsRecorder) -> None:
        """Rate limit (429) is classified correctly in timeseries."""
        recorder.record_request(
            request_id="req1",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            path="/test",
            outcome="error_injected",
            status_code=429,
        )

        timeseries = recorder.get_timeseries()
        assert timeseries[0]["requests_rate_limited"] == 1
        assert timeseries[0]["requests_success"] == 0

    def test_forbidden_classification_in_timeseries(self, recorder: WebMetricsRecorder) -> None:
        """Forbidden (403) is classified correctly in timeseries."""
        recorder.record_request(
            request_id="req1",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            path="/test",
            outcome="error_injected",
            status_code=403,
        )

        timeseries = recorder.get_timeseries()
        assert timeseries[0]["requests_forbidden"] == 1

    def test_not_found_classification_in_timeseries(self, recorder: WebMetricsRecorder) -> None:
        """Not found (404) is classified correctly in timeseries."""
        recorder.record_request(
            request_id="req1",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            path="/test",
            outcome="error_injected",
            status_code=404,
        )

        timeseries = recorder.get_timeseries()
        assert timeseries[0]["requests_not_found"] == 1

    def test_server_error_classification_in_timeseries(self, recorder: WebMetricsRecorder) -> None:
        """Server error (500) is classified correctly in timeseries."""
        recorder.record_request(
            request_id="req1",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            path="/test",
            outcome="error_injected",
            status_code=500,
        )

        timeseries = recorder.get_timeseries()
        assert timeseries[0]["requests_server_error"] == 1

    def test_connection_error_classification_in_timeseries(self, recorder: WebMetricsRecorder) -> None:
        """Connection error is classified correctly in timeseries."""
        recorder.record_request(
            request_id="req1",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            path="/test",
            outcome="error_injected",
            error_type="timeout",
        )

        timeseries = recorder.get_timeseries()
        assert timeseries[0]["requests_connection_error"] == 1

    def test_malformed_classification_in_timeseries(self, recorder: WebMetricsRecorder) -> None:
        """Malformed response is classified correctly in timeseries."""
        recorder.record_request(
            request_id="req1",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            path="/test",
            outcome="error_malformed",
            status_code=200,
        )

        timeseries = recorder.get_timeseries()
        assert timeseries[0]["requests_malformed"] == 1

    def test_redirect_classification_in_timeseries(self, recorder: WebMetricsRecorder) -> None:
        """Redirect is classified correctly in timeseries."""
        recorder.record_request(
            request_id="req1",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            path="/test",
            outcome="error_redirect",
            status_code=301,
        )

        timeseries = recorder.get_timeseries()
        assert timeseries[0]["requests_redirect"] == 1

    def test_timeseries_sorted_by_bucket(self, recorder: WebMetricsRecorder) -> None:
        """get_timeseries returns buckets sorted."""
        recorder.record_request(
            request_id="req1",
            timestamp_utc="2024-01-15T10:30:02+00:00",
            path="/test",
            outcome="success",
        )
        recorder.record_request(
            request_id="req2",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            path="/test",
            outcome="success",
        )

        timeseries = recorder.get_timeseries()
        assert len(timeseries) == 2
        # DESC order
        assert timeseries[0]["bucket_utc"] >= timeseries[1]["bucket_utc"]


class TestReset:
    """Tests for reset method."""

    @pytest.fixture
    def recorder(self, tmp_path: Path) -> Generator[WebMetricsRecorder, None, None]:
        """Create a fresh recorder for each test."""
        db_path = tmp_path / "metrics.db"
        config = MetricsConfig(database=str(db_path))
        recorder = WebMetricsRecorder(config)
        yield recorder
        recorder.close()

    def test_reset_clears_all_data(self, recorder: WebMetricsRecorder) -> None:
        """Reset clears requests and timeseries."""
        recorder.record_request(
            request_id="req1",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            path="/test",
            outcome="success",
        )

        assert len(recorder.get_requests()) == 1
        assert len(recorder.get_timeseries()) == 1

        recorder.reset()

        assert len(recorder.get_requests()) == 0
        assert len(recorder.get_timeseries()) == 0

    def test_reset_returns_new_run_id(self, recorder: WebMetricsRecorder) -> None:
        """Reset generates a new run ID."""
        old_run_id = recorder.run_id
        recorder.reset()
        assert recorder.run_id != old_run_id

    def test_reset_updates_started_utc(self, recorder: WebMetricsRecorder) -> None:
        """Reset updates the start time."""
        old_started = recorder.started_utc
        time.sleep(0.01)
        recorder.reset()
        assert recorder.started_utc != old_started


class TestGetStats:
    """Tests for get_stats method."""

    @pytest.fixture
    def recorder(self, tmp_path: Path) -> Generator[WebMetricsRecorder, None, None]:
        """Create a fresh recorder for each test."""
        db_path = tmp_path / "metrics.db"
        config = MetricsConfig(database=str(db_path))
        recorder = WebMetricsRecorder(config)
        yield recorder
        recorder.close()

    def test_stats_empty_database(self, recorder: WebMetricsRecorder) -> None:
        """Stats work on empty database."""
        stats = recorder.get_stats()
        assert stats["run_id"] == recorder.run_id
        assert stats["started_utc"] == recorder.started_utc
        assert stats["total_requests"] == 0
        assert stats["requests_by_outcome"] == {}
        assert stats["error_rate"] == 0.0

    def test_stats_error_rate(self, recorder: WebMetricsRecorder) -> None:
        """Stats reports error rate percentage."""
        for i in range(3):
            recorder.record_request(
                request_id=f"success{i}",
                timestamp_utc="2024-01-15T10:30:00+00:00",
                path="/test",
                outcome="success",
            )
        for i in range(2):
            recorder.record_request(
                request_id=f"error{i}",
                timestamp_utc="2024-01-15T10:30:01+00:00",
                path="/test",
                outcome="error_injected",
            )

        stats = recorder.get_stats()
        assert stats["error_rate"] == 40.0

    def test_stats_latency_statistics(self, recorder: WebMetricsRecorder) -> None:
        """Stats reports latency statistics."""
        latencies = [100.0, 150.0, 200.0, 250.0, 300.0]
        for i, lat in enumerate(latencies):
            recorder.record_request(
                request_id=f"req{i}",
                timestamp_utc="2024-01-15T10:30:00+00:00",
                path="/test",
                outcome="success",
                latency_ms=lat,
            )

        stats = recorder.get_stats()
        latency_stats = stats["latency_stats"]
        assert latency_stats["avg_ms"] == 200.0
        assert latency_stats["max_ms"] == 300.0

    def test_stats_by_status_code(self, recorder: WebMetricsRecorder) -> None:
        """Stats reports requests grouped by status code."""
        recorder.record_request(
            request_id="req1",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            path="/test",
            outcome="success",
            status_code=200,
        )
        recorder.record_request(
            request_id="req2",
            timestamp_utc="2024-01-15T10:30:01+00:00",
            path="/test",
            outcome="error_injected",
            status_code=429,
        )
        recorder.record_request(
            request_id="req3",
            timestamp_utc="2024-01-15T10:30:02+00:00",
            path="/test",
            outcome="error_injected",
            status_code=429,
        )

        stats = recorder.get_stats()
        assert stats["requests_by_status_code"][200] == 1
        assert stats["requests_by_status_code"][429] == 2


class TestExportData:
    """Tests for export_data method."""

    @pytest.fixture
    def recorder(self, tmp_path: Path) -> Generator[WebMetricsRecorder, None, None]:
        """Create a fresh recorder for each test."""
        db_path = tmp_path / "metrics.db"
        config = MetricsConfig(database=str(db_path))
        recorder = WebMetricsRecorder(config)
        yield recorder
        recorder.close()

    def test_export_data_structure(self, recorder: WebMetricsRecorder) -> None:
        """export_data returns expected structure."""
        recorder.record_request(
            request_id="req1",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            path="/test",
            outcome="success",
            status_code=200,
        )

        data = recorder.export_data()
        assert "run_id" in data
        assert "started_utc" in data
        assert "requests" in data
        assert "timeseries" in data
        assert len(data["requests"]) == 1
        assert len(data["timeseries"]) >= 1


class TestGetRequests:
    """Tests for get_requests method."""

    @pytest.fixture
    def recorder(self, tmp_path: Path) -> Generator[WebMetricsRecorder, None, None]:
        """Create a fresh recorder for each test."""
        db_path = tmp_path / "metrics.db"
        config = MetricsConfig(database=str(db_path))
        recorder = WebMetricsRecorder(config)
        yield recorder
        recorder.close()

    def test_filter_by_outcome(self, recorder: WebMetricsRecorder) -> None:
        """Can filter requests by outcome."""
        recorder.record_request(
            request_id="req1",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            path="/test",
            outcome="success",
        )
        recorder.record_request(
            request_id="req2",
            timestamp_utc="2024-01-15T10:30:01+00:00",
            path="/test",
            outcome="error_injected",
        )

        success_reqs = recorder.get_requests(outcome="success")
        error_reqs = recorder.get_requests(outcome="error_injected")

        assert len(success_reqs) == 1
        assert success_reqs[0]["request_id"] == "req1"
        assert len(error_reqs) == 1
        assert error_reqs[0]["request_id"] == "req2"

    def test_pagination(self, recorder: WebMetricsRecorder) -> None:
        """Pagination with limit and offset works."""
        for i in range(20):
            recorder.record_request(
                request_id=f"req{i:02d}",
                timestamp_utc=f"2024-01-15T10:30:{i:02d}+00:00",
                path="/test",
                outcome="success",
            )

        page1 = recorder.get_requests(limit=10, offset=0)
        page2 = recorder.get_requests(limit=10, offset=10)

        assert len(page1) == 10
        assert len(page2) == 10

        ids1 = {r["request_id"] for r in page1}
        ids2 = {r["request_id"] for r in page2}
        assert ids1.isdisjoint(ids2)


class TestClose:
    """Tests for close method."""

    def test_close_shuts_down_connections(self, tmp_path: Path) -> None:
        """close() shuts down database connections."""
        db_path = tmp_path / "metrics.db"
        config = MetricsConfig(database=str(db_path))
        recorder = WebMetricsRecorder(config)

        # Record something to ensure connection is active
        recorder.record_request(
            request_id="req1",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            path="/test",
            outcome="success",
        )

        recorder.close()

        # Connections list should be cleared
        assert len(recorder._store._connections) == 0


class TestThreadSafety:
    """Tests for thread-safe operation."""

    def test_concurrent_record_requests(self, tmp_path: Path) -> None:
        """Multiple threads can record requests safely."""
        db_path = tmp_path / "metrics.db"
        config = MetricsConfig(database=str(db_path))
        recorder = WebMetricsRecorder(config)

        errors: list[Exception] = []
        lock = threading.Lock()

        def worker(thread_id: int) -> None:
            try:
                for i in range(50):
                    recorder.record_request(
                        request_id=f"t{thread_id}_req{i}",
                        timestamp_utc=f"2024-01-15T10:30:{i % 60:02d}+00:00",
                        path=f"/test/{thread_id}",
                        outcome="success",
                        status_code=200,
                        latency_ms=float(100 + i),
                    )
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        recorder.close()
        assert not errors, f"Errors occurred: {errors}"

    def test_concurrent_get_stats(self, tmp_path: Path) -> None:
        """Multiple threads can call get_stats safely."""
        db_path = tmp_path / "metrics.db"
        config = MetricsConfig(database=str(db_path))
        recorder = WebMetricsRecorder(config)

        for i in range(100):
            recorder.record_request(
                request_id=f"req{i}",
                timestamp_utc="2024-01-15T10:30:00+00:00",
                path="/test",
                outcome="success",
            )

        errors: list[Exception] = []
        lock = threading.Lock()

        def worker() -> None:
            try:
                for _ in range(50):
                    stats = recorder.get_stats()
                    assert stats["total_requests"] == 100
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        recorder.close()
        assert not errors, f"Errors occurred: {errors}"
