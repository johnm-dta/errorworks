"""Tests for ChaosBlob metrics recorder."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from errorworks.blob.metrics import (
    BLOB_METRICS_SCHEMA,
    BlobMetricsRecorder,
    BlobOutcomeCounter,
    BlobRequestRecord,
    _classify_blob_outcome,
)
from errorworks.engine.types import MetricsConfig


def _valid_record(**overrides: object) -> BlobRequestRecord:
    """Build a BlobRequestRecord with sensible defaults; tests override fields they care about."""
    defaults: dict[str, object] = {
        "request_id": "r-1",
        "timestamp_utc": "2024-01-15T10:30:00+00:00",
        "operation": "get",
        "bucket": "photos",
        "outcome": "success",
        "object_key": "cat.jpg",
        "status_code": 200,
        "error_type": None,
        "injection_type": None,
        "bytes_in": None,
        "bytes_out": None,
        "etag": None,
        "latency_ms": None,
        "injected_delay_ms": None,
    }
    defaults.update(overrides)
    return BlobRequestRecord(**defaults)  # type: ignore[arg-type]


class TestBlobRequestRecordInvariants:
    """BlobRequestRecord guards cross-field invariants that primitive kwargs let drift."""

    def test_success_outcome_requires_2xx_3xx_status_and_no_error_type(self) -> None:
        # success + 200 + error_type=None — fine.
        _valid_record(outcome="success", status_code=200, error_type=None)

    def test_success_outcome_rejects_error_type(self) -> None:
        with pytest.raises(ValueError, match="success"):
            _valid_record(outcome="success", status_code=200, error_type="checksum_mismatch")

    def test_success_outcome_rejects_4xx_status(self) -> None:
        with pytest.raises(ValueError, match="success"):
            _valid_record(outcome="success", status_code=404, error_type=None)

    def test_success_outcome_rejects_5xx_status(self) -> None:
        with pytest.raises(ValueError, match="success"):
            _valid_record(outcome="success", status_code=503, error_type=None)

    def test_error_injected_requires_error_type_or_4xx_5xx_status(self) -> None:
        # error_type set, status 200 — allowed (connection_reset emits 200 stream then aborts).
        _valid_record(outcome="error_injected", status_code=200, error_type="connection_reset")
        # status 4xx, no error_type — allowed (e.g. an emitted 404 without a tag).
        _valid_record(outcome="error_injected", status_code=404, error_type=None)

    def test_error_injected_rejects_2xx_status_with_no_error_type(self) -> None:
        with pytest.raises(ValueError, match="error_injected"):
            _valid_record(outcome="error_injected", status_code=200, error_type=None)

    def test_error_corrupted_requires_error_type_or_4xx_5xx_status(self) -> None:
        _valid_record(outcome="error_corrupted", status_code=200, error_type="truncated_body")

    def test_error_corrupted_rejects_2xx_status_with_no_error_type(self) -> None:
        with pytest.raises(ValueError, match="error_corrupted"):
            _valid_record(outcome="error_corrupted", status_code=200, error_type=None)

    def test_record_is_frozen(self) -> None:
        record = _valid_record()
        with pytest.raises((AttributeError, TypeError)):
            record.bucket = "other"  # type: ignore[misc]


class TestSchemaEnumConsistency:
    """The BlobOutcomeCounter enum must stay aligned with timeseries schema columns."""

    def test_every_counter_has_a_schema_column(self) -> None:
        column_names = {col.name for col in BLOB_METRICS_SCHEMA.timeseries_columns}
        counter_values = {c.value for c in BlobOutcomeCounter}
        missing = counter_values - column_names
        assert not missing, f"BlobOutcomeCounter values without schema columns: {missing}"


@pytest.fixture
def recorder(tmp_path: Path) -> Generator[BlobMetricsRecorder, None, None]:
    """Create a fresh recorder for each test."""
    db_path = tmp_path / "blob-metrics.db"
    recorder = BlobMetricsRecorder(MetricsConfig(database=str(db_path), timeseries_bucket_sec=60))
    yield recorder
    recorder.close()


class TestClassifyBlobOutcome:
    """Tests for blob outcome classification."""

    def test_returns_counter_directly(self) -> None:
        # _classify_blob_outcome now returns a BlobOutcomeCounter directly,
        # not a single-field wrapper. The wrapper was vacuous and added a
        # `.counter` indirection at every call site for no information gain.
        result = _classify_blob_outcome("success", 200, None)
        assert isinstance(result, BlobOutcomeCounter)

    def test_success_outcome(self) -> None:
        assert _classify_blob_outcome("success", 200, None) is BlobOutcomeCounter.SUCCESS

    def test_slow_down_is_not_generic_server_error(self) -> None:
        assert _classify_blob_outcome("error_injected", 503, "slow_down") is BlobOutcomeCounter.SLOW_DOWN

    def test_not_found_by_status_or_error_type(self) -> None:
        assert _classify_blob_outcome("error_injected", 404, "NoSuchKey") is BlobOutcomeCounter.NOT_FOUND
        assert _classify_blob_outcome("error_injected", None, "not_found") is BlobOutcomeCounter.NOT_FOUND

    def test_connection_error_is_not_generic_server_error(self) -> None:
        assert _classify_blob_outcome("error_injected", 504, "connection_reset") is BlobOutcomeCounter.CONNECTION_ERROR

    def test_corrupted_by_error_type_or_outcome(self) -> None:
        assert _classify_blob_outcome("error_injected", 200, "checksum_mismatch") is BlobOutcomeCounter.CORRUPTED
        assert _classify_blob_outcome("error_corrupted", 200, None) is BlobOutcomeCounter.CORRUPTED

    def test_not_found_status_takes_precedence_over_corruption_error_type(self) -> None:
        assert _classify_blob_outcome("error_injected", 404, "checksum_mismatch") is BlobOutcomeCounter.NOT_FOUND

    def test_stale_list(self) -> None:
        assert _classify_blob_outcome("error_injected", 200, "stale_list") is BlobOutcomeCounter.STALE_LIST

    def test_classification_is_mutually_exclusive(self) -> None:
        assert _classify_blob_outcome("error_corrupted", 503, "slow_down") is BlobOutcomeCounter.SLOW_DOWN

    def test_unclassified_outcome_is_bucketed_not_dropped(self) -> None:
        # An outcome with no recognised tag/status (e.g. a future code path that
        # forgets to extend _classify_blob_outcome) used to fall through to a
        # None counter and become invisible in the time-series. It must now be
        # recorded in a dedicated bucket so the drift is loud.
        assert _classify_blob_outcome("error_injected", 418, "teapot") is BlobOutcomeCounter.UNCLASSIFIED

    def test_unclassified_outcome_logs_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import errorworks.blob.metrics as metrics_module

        log_calls: list[tuple[str, dict[str, object]]] = []

        class _StubLogger:
            def warning(self, event: str, **kwargs: object) -> None:
                log_calls.append((event, kwargs))

        monkeypatch.setattr(metrics_module, "logger", _StubLogger())
        _classify_blob_outcome("error_injected", 418, "teapot")
        # Drift should surface immediately, not require a metrics scan to detect.
        assert log_calls, "fall-through case must log a warning"
        event, payload = log_calls[0]
        assert event == "blob_outcome_unclassified"
        assert payload["outcome"] == "error_injected"
        assert payload["status_code"] == 418
        assert payload["error_type"] == "teapot"


class TestBlobMetricsRecorder:
    """Tests for recording and exporting blob metrics."""

    def test_records_put_success(self, recorder: BlobMetricsRecorder) -> None:
        recorder.record_request(
            _valid_record(
                request_id="put-1",
                operation="put",
                object_key="cat.jpg",
                bytes_in=512,
                bytes_out=0,
                etag='"abc"',
                latency_ms=12.5,
            )
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
            _valid_record(
                request_id="get-1",
                timestamp_utc="2024-01-15T10:30:01+00:00",
                operation="get",
                bytes_out=512,
                latency_ms=8.0,
            )
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
            _valid_record(
                request_id=request_id,
                timestamp_utc="2024-01-15T10:30:02+00:00",
                operation="get",
                outcome="error_corrupted" if error_type in {"truncated_body", "checksum_mismatch"} else "error_injected",
                status_code=status_code,
                error_type=error_type,
                injection_type=error_type,
                latency_ms=20.0,
                injected_delay_ms=5.0 if error_type == "slow_down" else None,
            )
        )

        timeseries = recorder.get_timeseries()
        assert timeseries[0]["requests_total"] == 1
        assert timeseries[0][counter] == 1
        assert timeseries[0]["requests_success"] == 0

    def test_unclassified_outcomes_increment_dedicated_counter(self, recorder: BlobMetricsRecorder) -> None:
        recorder.record_request(
            _valid_record(
                request_id="weird-1",
                timestamp_utc="2024-01-15T10:30:02+00:00",
                operation="get",
                outcome="error_injected",
                status_code=418,
                error_type="teapot",
                latency_ms=20.0,
            )
        )
        timeseries = recorder.get_timeseries()
        assert timeseries[0]["requests_total"] == 1
        assert timeseries[0]["requests_unclassified"] == 1
        assert timeseries[0]["requests_success"] == 0

    def test_get_stats_exposes_totals_status_codes_and_timeseries(self, recorder: BlobMetricsRecorder) -> None:
        recorder.record_request(
            _valid_record(
                request_id="put-ok",
                operation="put",
                latency_ms=10.0,
            )
        )
        recorder.record_request(
            _valid_record(
                request_id="get-missing",
                timestamp_utc="2024-01-15T10:30:10+00:00",
                operation="get",
                object_key="missing.jpg",
                outcome="error_injected",
                status_code=404,
                error_type="NoSuchKey",
                latency_ms=30.0,
            )
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
            _valid_record(
                request_id="list-1",
                operation="list",
                object_key=None,
            )
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
