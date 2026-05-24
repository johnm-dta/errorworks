"""Tests for ChaosBlob metrics recorder."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from errorworks.blob.metrics import (
    BlobMetricsRecorder,
    BlobOutcomeClassification,
    BlobOutcomeCounter,
    _classify_blob_outcome,
)
from errorworks.engine.types import MetricsConfig


@pytest.fixture
def recorder(tmp_path: Path) -> Generator[BlobMetricsRecorder, None, None]:
    """Create a fresh recorder for each test."""
    db_path = tmp_path / "blob-metrics.db"
    recorder = BlobMetricsRecorder(MetricsConfig(database=str(db_path), timeseries_bucket_sec=60))
    yield recorder
    recorder.close()


class TestClassifyBlobOutcome:
    """Tests for blob outcome classification."""

    def test_returns_single_counter_classification(self) -> None:
        result = _classify_blob_outcome("success", 200, None)
        assert isinstance(result, BlobOutcomeClassification)
        assert isinstance(result.counter, BlobOutcomeCounter)

    def test_success_outcome(self) -> None:
        result = _classify_blob_outcome("success", 200, None)
        assert result.counter is BlobOutcomeCounter.SUCCESS

    def test_slow_down_is_not_generic_server_error(self) -> None:
        result = _classify_blob_outcome("error_injected", 503, "slow_down")
        assert result.counter is BlobOutcomeCounter.SLOW_DOWN

    def test_not_found_by_status_or_error_type(self) -> None:
        assert _classify_blob_outcome("error_injected", 404, "NoSuchKey").counter is BlobOutcomeCounter.NOT_FOUND
        assert _classify_blob_outcome("error_injected", None, "not_found").counter is BlobOutcomeCounter.NOT_FOUND

    def test_connection_error_is_not_generic_server_error(self) -> None:
        result = _classify_blob_outcome("error_injected", 504, "connection_reset")
        assert result.counter is BlobOutcomeCounter.CONNECTION_ERROR

    def test_corrupted_by_error_type_or_outcome(self) -> None:
        assert _classify_blob_outcome("error_injected", 200, "checksum_mismatch").counter is BlobOutcomeCounter.CORRUPTED
        assert _classify_blob_outcome("error_corrupted", 200, None).counter is BlobOutcomeCounter.CORRUPTED

    def test_stale_list(self) -> None:
        result = _classify_blob_outcome("error_injected", 200, "stale_list")
        assert result.counter is BlobOutcomeCounter.STALE_LIST

    def test_classification_is_mutually_exclusive(self) -> None:
        result = _classify_blob_outcome("error_corrupted", 503, "slow_down")
        assert result.counter is BlobOutcomeCounter.SLOW_DOWN


class TestBlobMetricsRecorder:
    """Tests for recording and exporting blob metrics."""

    def test_records_put_success(self, recorder: BlobMetricsRecorder) -> None:
        recorder.record_request(
            request_id="put-1",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            operation="put",
            bucket="photos",
            object_key="cat.jpg",
            outcome="success",
            status_code=200,
            bytes_in=512,
            bytes_out=0,
            etag='"abc"',
            latency_ms=12.5,
        )

        requests = recorder.get_requests()
        assert requests[0]["operation"] == "put"
        assert requests[0]["bucket"] == "photos"
        assert requests[0]["object_key"] == "cat.jpg"
        assert requests[0]["bytes_in"] == 512
        assert requests[0]["etag"] == '"abc"'

        stats = recorder.get_stats()
        assert stats["total_requests"] == 1
        assert stats["requests_by_status_code"][200] == 1

        timeseries = recorder.get_timeseries()
        assert timeseries[0]["requests_total"] == 1
        assert timeseries[0]["requests_success"] == 1
        assert timeseries[0]["avg_latency_ms"] == 12.5
        assert timeseries[0]["p99_latency_ms"] == 12.5

    def test_records_get_success(self, recorder: BlobMetricsRecorder) -> None:
        recorder.record_request(
            request_id="get-1",
            timestamp_utc="2024-01-15T10:30:01+00:00",
            operation="get",
            bucket="photos",
            object_key="cat.jpg",
            outcome="success",
            status_code=200,
            bytes_out=512,
            latency_ms=8.0,
        )

        request = recorder.get_requests()[0]
        assert request["operation"] == "get"
        assert request["bytes_out"] == 512
        assert recorder.get_timeseries()[0]["requests_success"] == 1

    @pytest.mark.parametrize(
        ("request_id", "status_code", "error_type", "counter"),
        [
            ("slow-down", 503, "slow_down", "requests_slow_down"),
            ("not-found", 404, "NoSuchKey", "requests_not_found"),
            ("truncated", 200, "truncated_body", "requests_corrupted"),
            ("checksum", 200, "checksum_mismatch", "requests_corrupted"),
            ("stale-list", 200, "stale_list", "requests_stale_list"),
            ("reset", None, "connection_reset", "requests_connection_error"),
        ],
    )
    def test_records_blob_error_counters(
        self,
        recorder: BlobMetricsRecorder,
        request_id: str,
        status_code: int | None,
        error_type: str,
        counter: str,
    ) -> None:
        recorder.record_request(
            request_id=request_id,
            timestamp_utc="2024-01-15T10:30:02+00:00",
            operation="get",
            bucket="photos",
            object_key="cat.jpg",
            outcome="error_corrupted" if error_type in {"truncated_body", "checksum_mismatch"} else "error_injected",
            status_code=status_code,
            error_type=error_type,
            injection_type=error_type,
            latency_ms=20.0,
            injected_delay_ms=5.0 if error_type == "slow_down" else None,
        )

        timeseries = recorder.get_timeseries()
        assert timeseries[0]["requests_total"] == 1
        assert timeseries[0][counter] == 1
        assert timeseries[0]["requests_success"] == 0

    def test_get_stats_exposes_totals_status_codes_and_timeseries(self, recorder: BlobMetricsRecorder) -> None:
        recorder.record_request(
            request_id="put-ok",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            operation="put",
            bucket="photos",
            object_key="cat.jpg",
            outcome="success",
            status_code=200,
            latency_ms=10.0,
        )
        recorder.record_request(
            request_id="get-missing",
            timestamp_utc="2024-01-15T10:30:10+00:00",
            operation="get",
            bucket="photos",
            object_key="missing.jpg",
            outcome="error_injected",
            status_code=404,
            error_type="NoSuchKey",
            latency_ms=30.0,
        )

        stats = recorder.get_stats()
        assert stats["total_requests"] == 2
        assert stats["requests_by_status_code"] == {200: 1, 404: 1}
        assert stats["timeseries"][0]["requests_total"] == 2
        assert stats["timeseries"][0]["requests_success"] == 1
        assert stats["timeseries"][0]["requests_not_found"] == 1

        timeseries = recorder.get_timeseries()
        assert len(timeseries) == 1
        assert timeseries[0]["requests_total"] == 2
        assert timeseries[0]["requests_success"] == 1
        assert timeseries[0]["requests_not_found"] == 1
        assert timeseries[0]["avg_latency_ms"] == 20.0

    def test_reset_and_export_smoke(self, recorder: BlobMetricsRecorder) -> None:
        started_before = datetime.fromisoformat(recorder.started_utc)
        recorder.save_run_info('{"service":"blob"}', preset_name="gentle")
        recorder.record_request(
            request_id="list-1",
            timestamp_utc="2024-01-15T10:30:00+00:00",
            operation="list",
            bucket="photos",
            object_key=None,
            outcome="success",
            status_code=200,
        )

        exported = recorder.export_data()
        assert len(exported["requests"]) == 1
        assert len(exported["timeseries"]) == 1

        old_run_id = recorder.run_id
        recorder.reset()

        assert recorder.run_id != old_run_id
        assert datetime.fromisoformat(recorder.started_utc) >= started_before.replace(tzinfo=UTC)
        assert recorder.get_stats()["total_requests"] == 0
        assert recorder.export_data()["requests"] == []
