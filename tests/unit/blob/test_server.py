from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import anyio
import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from errorworks.blob.config import BlobErrorInjectionConfig, BlobStorageConfig, ChaosBlobConfig
from errorworks.blob.error_injector import BlobErrorInjector
from errorworks.blob.server import create_app
from errorworks.engine.types import LatencyConfig, MetricsConfig


def _client_for(
    tmp_path: Path,
    *,
    error_injection: BlobErrorInjectionConfig | None = None,
    storage: BlobStorageConfig | None = None,
) -> TestClient:
    config = ChaosBlobConfig(
        metrics=MetricsConfig(database=str(tmp_path / "blob-metrics.db")),
        latency=LatencyConfig(base_ms=0, jitter_ms=0),
        error_injection=error_injection or BlobErrorInjectionConfig(),
        storage=storage or BlobStorageConfig(),
    )
    return TestClient(create_app(config))


def _app_for(
    tmp_path: Path,
    *,
    error_injection: BlobErrorInjectionConfig | None = None,
    storage: BlobStorageConfig | None = None,
) -> Starlette:
    config = ChaosBlobConfig(
        metrics=MetricsConfig(database=str(tmp_path / "blob-metrics.db")),
        latency=LatencyConfig(base_ms=0, jitter_ms=0),
        error_injection=error_injection or BlobErrorInjectionConfig(),
        storage=storage or BlobStorageConfig(),
    )
    return create_app(config)


def _admin_headers(client: TestClient) -> dict[str, str]:
    token = client.app.state.server.get_admin_token()
    return {"Authorization": f"Bearer {token}"}


def _xml_code(response) -> str | None:
    root = ElementTree.fromstring(response.content)
    return root.findtext("{*}Code")


def _list_keys(response) -> list[str]:
    root = ElementTree.fromstring(response.content)
    return [node.text or "" for node in root.findall("{*}Contents/{*}Key")]


def _exported_request(client: TestClient) -> dict:
    export = client.get("/admin/export", headers=_admin_headers(client))
    assert export.status_code == 200
    requests = export.json()["requests"]
    assert len(requests) == 1
    return requests[0]


def _capture_get_send_events(app: Starlette, path: str) -> tuple[list[dict[str, Any]], Exception | None]:
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    async def run() -> Exception | None:
        try:
            await app(
                {
                    "type": "http",
                    "asgi": {"version": "3.0"},
                    "http_version": "1.1",
                    "method": "GET",
                    "scheme": "http",
                    "path": path,
                    "raw_path": path.encode(),
                    "query_string": b"",
                    "headers": [],
                    "client": ("testclient", 50000),
                    "server": ("testserver", 80),
                    "root_path": "",
                },
                receive,
                send,
            )
        except Exception as exc:
            return exc
        return None

    error = anyio.run(run)
    return messages, error


def _capture_put_send_events(
    app: Starlette,
    path: str,
    *,
    headers: list[tuple[bytes, bytes]],
    chunks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], Exception | None]:
    messages: list[dict[str, Any]] = []
    pending = list(chunks)

    async def receive() -> dict[str, Any]:
        if not pending:
            raise AssertionError("request body reader consumed too many chunks")
        return pending.pop(0)

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    async def run() -> Exception | None:
        try:
            await app(
                {
                    "type": "http",
                    "asgi": {"version": "3.0"},
                    "http_version": "1.1",
                    "method": "PUT",
                    "scheme": "http",
                    "path": path,
                    "raw_path": path.encode(),
                    "query_string": b"",
                    "headers": headers,
                    "client": ("testclient", 50000),
                    "server": ("testserver", 80),
                    "root_path": "",
                },
                receive,
                send,
            )
        except Exception as exc:
            return exc
        return None

    error = anyio.run(run)
    return messages, error


def _header_from_start(start_message: dict[str, Any], name: bytes) -> bytes | None:
    for header_name, value in start_message["headers"]:
        if header_name.lower() == name:
            return value
    return None


class _RangeRandom:
    def __init__(self, uniform_values: list[float]) -> None:
        self._uniform_values = uniform_values

    def random(self) -> float:
        return 0.0

    def randint(self, min_value: int, _max_value: int) -> int:
        return min_value

    def uniform(self, _min_value: float, _max_value: float) -> float:
        if not self._uniform_values:
            raise AssertionError("unexpected uniform call")
        return self._uniform_values.pop(0)


def test_health_returns_run_information(tmp_path: Path) -> None:
    client = _client_for(tmp_path)

    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "run_id" in data
    assert "started_utc" in data
    assert "in_burst" in data


def test_put_get_head_delete_object_round_trip(tmp_path: Path) -> None:
    client = _client_for(tmp_path)

    put = client.put("/bucket/key.txt", content=b"hello blob", headers={"content-type": "text/plain", "x-amz-meta-owner": "tests"})
    assert put.status_code == 200
    assert put.headers["etag"]

    get = client.get("/bucket/key.txt")
    assert get.status_code == 200
    assert get.content == b"hello blob"
    assert get.headers["content-type"].startswith("text/plain")
    assert get.headers["x-amz-meta-owner"] == "tests"
    assert get.headers["etag"] == put.headers["etag"]

    head = client.head("/bucket/key.txt")
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == str(len(b"hello blob"))
    assert head.headers["etag"] == put.headers["etag"]

    delete = client.delete("/bucket/key.txt")
    assert delete.status_code == 204

    missing = client.get("/bucket/key.txt")
    assert missing.status_code == 404
    assert _xml_code(missing) == "NoSuchKey"


def test_list_objects_v2_filters_by_prefix(tmp_path: Path) -> None:
    client = _client_for(tmp_path)
    client.put("/bucket/logs/2.txt", content=b"2")
    client.put("/bucket/logs/1.txt", content=b"1")
    client.put("/bucket/images/1.png", content=b"x")

    response = client.get("/bucket?list-type=2&prefix=logs/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert _list_keys(response) == ["logs/1.txt", "logs/2.txt"]


def test_list_objects_v2_rejects_zero_max_keys(tmp_path: Path) -> None:
    client = _client_for(tmp_path)
    client.put("/bucket/logs/1.txt", content=b"1")

    response = client.get("/bucket?list-type=2&max-keys=0")

    assert response.status_code == 400
    assert _xml_code(response) == "InvalidArgument"


def test_list_objects_v2_caps_max_keys_at_s3_limit(tmp_path: Path) -> None:
    client = _client_for(tmp_path)
    client.put("/bucket/a.txt", content=b"a")

    response = client.get("/bucket?list-type=2&max-keys=5000")

    assert response.status_code == 200
    root = ElementTree.fromstring(response.content)
    assert root.findtext("{*}MaxKeys") == "1000"


def test_list_objects_v2_continuation_token_starts_after_last_key_when_store_mutates(tmp_path: Path) -> None:
    client = _client_for(tmp_path)
    for key in ["a", "b", "c"]:
        client.put(f"/bucket/{key}", content=key.encode())

    first = client.get("/bucket?list-type=2&max-keys=2")
    root = ElementTree.fromstring(first.content)
    token = root.findtext("{*}NextContinuationToken")
    assert token
    assert _list_keys(first) == ["a", "b"]

    client.put("/bucket/aa", content=b"aa")
    second = client.get(f"/bucket?list-type=2&max-keys=2&continuation-token={token}")

    assert second.status_code == 200
    assert _list_keys(second) == ["c"]


def test_list_without_list_type_v2_returns_invalid_request(tmp_path: Path) -> None:
    client = _client_for(tmp_path)

    response = client.get("/bucket")

    assert response.status_code == 400
    assert _xml_code(response) == "InvalidRequest"


def test_list_without_list_type_v2_records_invalid_request_metrics(tmp_path: Path) -> None:
    client = _client_for(tmp_path)

    response = client.get("/bucket")

    request = _exported_request(client)
    assert request["operation"] == "list"
    assert request["bucket"] == "bucket"
    assert request["object_key"] is None
    assert request["status_code"] == 400
    assert request["error_type"] == "InvalidRequest"
    assert request["bytes_out"] == len(response.content)
    assert request["bytes_out"] > 0


def test_admin_stats_config_update_and_reset_clear_metrics_and_store(tmp_path: Path) -> None:
    client = _client_for(tmp_path)
    headers = _admin_headers(client)

    client.put("/bucket/key.txt", content=b"hello")
    assert client.get("/admin/stats", headers=headers).json()["total_requests"] == 1

    update = client.post("/admin/config", headers=headers, json={"error_injection": {"slow_down_pct": 100.0}})
    assert update.status_code == 200
    assert update.json()["config"]["error_injection"]["slow_down_pct"] == 100.0
    client.post("/admin/config", headers=headers, json={"error_injection": {"slow_down_pct": 0.0}})

    reset = client.post("/admin/reset", headers=headers)
    assert reset.status_code == 200
    assert reset.json()["status"] == "reset"
    assert client.get("/admin/stats", headers=headers).json()["total_requests"] == 0

    missing = client.get("/bucket/key.txt")
    assert missing.status_code == 404
    assert _xml_code(missing) == "NoSuchKey"


def test_storage_config_update_clears_existing_objects(tmp_path: Path) -> None:
    client = _client_for(tmp_path)
    headers = _admin_headers(client)
    client.put("/bucket/key.txt", content=b"hello")

    update = client.post("/admin/config", headers=headers, json={"storage": {"max_object_bytes": 1024}})

    assert update.status_code == 200
    missing = client.get("/bucket/key.txt")
    assert missing.status_code == 404
    assert _xml_code(missing) == "NoSuchKey"


def test_admin_config_rejects_storage_content_type_header_injection(tmp_path: Path) -> None:
    client = _client_for(tmp_path)
    headers = _admin_headers(client)

    response = client.post(
        "/admin/config",
        headers=headers,
        json={"storage": {"default_content_type": "text/plain\r\nx-evil: 1"}},
    )

    assert response.status_code == 422


def test_slow_down_injection_returns_s3_error_with_retry_after(tmp_path: Path) -> None:
    client = _client_for(tmp_path, error_injection=BlobErrorInjectionConfig(slow_down_pct=100.0, retry_after_sec=(3, 3)))
    client.put("/bucket/key.txt", content=b"hello")

    response = client.get("/bucket/key.txt")

    assert response.status_code == 503
    assert response.headers["retry-after"] == "3"
    assert _xml_code(response) == "SlowDown"


def test_access_denied_injection_returns_s3_error(tmp_path: Path) -> None:
    client = _client_for(tmp_path, error_injection=BlobErrorInjectionConfig(access_denied_pct=100.0))

    response = client.get("/bucket/key.txt")

    assert response.status_code == 403
    assert _xml_code(response) == "AccessDenied"


def test_access_denied_injection_records_error_response_size(tmp_path: Path) -> None:
    client = _client_for(tmp_path, error_injection=BlobErrorInjectionConfig(access_denied_pct=100.0))

    response = client.get("/bucket/key.txt")

    request = _exported_request(client)
    assert isinstance(request["bytes_out"], int)
    assert request["bytes_out"] == len(response.content)
    assert request["bytes_out"] > 0


def test_not_found_injection_can_force_no_such_key(tmp_path: Path) -> None:
    client = _client_for(tmp_path, error_injection=BlobErrorInjectionConfig(not_found_pct=100.0))
    client.put("/bucket/key.txt", content=b"hello")

    response = client.get("/bucket/key.txt")

    assert response.status_code == 404
    assert _xml_code(response) == "NoSuchKey"


def test_truncated_body_injection_returns_short_success_body(tmp_path: Path) -> None:
    client = _client_for(tmp_path, error_injection=BlobErrorInjectionConfig(truncated_body_pct=100.0))
    body = b"0123456789"
    client.put("/bucket/key.txt", content=body)

    response = client.get("/bucket/key.txt")

    assert response.status_code == 200
    assert 0 <= len(response.content) < len(body)


def test_checksum_mismatch_injection_returns_incorrect_etag(tmp_path: Path) -> None:
    client = _client_for(tmp_path, error_injection=BlobErrorInjectionConfig(checksum_mismatch_pct=100.0))
    put = client.put("/bucket/key.txt", content=b"hello")

    response = client.get("/bucket/key.txt")

    assert response.status_code == 200
    assert response.headers["etag"] != put.headers["etag"]


def test_streaming_disconnect_exposes_response_body_and_headers_attributes(tmp_path: Path) -> None:
    """_StreamingDisconnect must call super().__init__() so middleware that touches
    response.body / response.headers does not AttributeError."""
    from errorworks.blob.server import _StreamingDisconnect

    async def _gen() -> Any:
        yield b""

    response = _StreamingDisconnect(content=_gen(), status_code=200, media_type="application/xml")

    # Concrete Response attributes that middleware commonly inspects.
    assert response.body == b""
    # raw_headers is what Starlette uses internally; headers is the user-facing API.
    assert response.raw_headers is not None
    # The MutableHeaders accessor should not raise.
    _ = response.headers


def test_wrong_content_length_injection_disconnects_after_partial_body(tmp_path: Path) -> None:
    app = _app_for(tmp_path, error_injection=BlobErrorInjectionConfig(wrong_content_length_pct=100.0))
    client = TestClient(app)
    client.put("/bucket/key.txt", content=b"hello")

    messages, error = _capture_get_send_events(app, "/bucket/key.txt")

    # The injected ConnectionResetError must be swallowed inside the ASGI app
    # so uvicorn does not log "Exception in ASGI application" for a deliberate
    # disconnection. The wire effect is the same — no terminal more_body:False.
    assert error is None
    start = messages[0]
    body_event = messages[1]
    assert start["type"] == "http.response.start"
    assert start["status"] == 200
    assert int(_header_from_start(start, b"content-length") or b"0") == len(b"hello")
    assert body_event == {"type": "http.response.body", "body": b"he", "more_body": True}
    # No terminal http.response.body with more_body:False — modeling a dropped TCP connection.
    assert all(msg.get("more_body") is not False for msg in messages if msg["type"] == "http.response.body")
    request = client.get("/admin/export", headers=_admin_headers(client)).json()["requests"][-1]
    assert request["outcome"] == "error_corrupted"
    assert request["error_type"] == "wrong_content_length"
    assert request["bytes_out"] == len(body_event["body"])


def test_connection_reset_does_not_leak_exception_out_of_asgi_app(tmp_path: Path) -> None:
    """The injected ConnectionResetError must be swallowed inside _StreamingDisconnect.__call__
    so uvicorn does not log "Exception in ASGI application" for a deliberate disconnection."""
    app = _app_for(tmp_path, error_injection=BlobErrorInjectionConfig(connection_reset_pct=100.0))

    messages, error = _capture_get_send_events(app, "/bucket/key.txt")

    assert error is None
    assert messages[0]["type"] == "http.response.start"
    assert messages[0]["status"] == 200


def test_connection_reset_streams_disconnect_instead_of_http_500(tmp_path: Path) -> None:
    app = _app_for(tmp_path, error_injection=BlobErrorInjectionConfig(connection_reset_pct=100.0))
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/bucket/key.txt")

    assert response.status_code == 200
    request = _exported_request(client)
    assert request["error_type"] == "connection_reset"
    assert request["status_code"] == 200
    assert request["bytes_out"] == 0
    assert client.get("/admin/stats", headers=_admin_headers(client)).json()["timeseries"][0]["requests_connection_error"] == 1


def test_connection_stall_streams_disconnect_instead_of_http_500(tmp_path: Path) -> None:
    app = _app_for(
        tmp_path,
        error_injection=BlobErrorInjectionConfig(
            connection_stall_pct=100.0,
            connection_stall_start_sec=(0, 0),
            connection_stall_sec=(0, 0),
        ),
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/bucket/key.txt")

    assert response.status_code == 200
    request = _exported_request(client)
    assert request["error_type"] == "connection_stall"
    assert request["status_code"] == 200
    assert request["bytes_out"] == 0
    assert client.get("/admin/stats", headers=_admin_headers(client)).json()["timeseries"][0]["requests_connection_error"] == 1


def test_connection_stall_uses_random_delay_from_configured_ranges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = ChaosBlobConfig(
        metrics=MetricsConfig(database=str(tmp_path / "blob-metrics.db")),
        latency=LatencyConfig(base_ms=0, jitter_ms=0),
        error_injection=BlobErrorInjectionConfig(
            connection_stall_pct=100.0,
            connection_stall_start_sec=(1, 2),
            connection_stall_sec=(3, 4),
        ),
    )
    app = create_app(config)
    app.state.server._error_injector = BlobErrorInjector(config.error_injection, rng=_RangeRandom([1.25, 3.5]))
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("errorworks.blob.server.asyncio.sleep", fake_sleep)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/bucket/key.txt")

    assert response.status_code == 200
    assert sleeps == [1.25, 3.5]


def test_slow_response_uses_random_delay_from_configured_range(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = ChaosBlobConfig(
        metrics=MetricsConfig(database=str(tmp_path / "blob-metrics.db")),
        latency=LatencyConfig(base_ms=0, jitter_ms=0),
        error_injection=BlobErrorInjectionConfig(slow_response_pct=100.0, slow_response_sec=(1, 3)),
    )
    app = create_app(config)
    app.state.server._error_injector = BlobErrorInjector(config.error_injection, rng=_RangeRandom([1.5]))
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("errorworks.blob.server.asyncio.sleep", fake_sleep)
    client = TestClient(app)

    response = client.get("/bucket/key.txt")

    assert response.status_code == 503
    assert _xml_code(response) == "SlowDown"
    assert sleeps == [1.5]


def test_metadata_corruption_drops_amz_metadata_header(tmp_path: Path) -> None:
    client = _client_for(tmp_path, error_injection=BlobErrorInjectionConfig(metadata_corruption_pct=100.0))
    client.put("/bucket/key.txt", content=b"hello", headers={"x-amz-meta-owner": "tests"})

    response = client.get("/bucket/key.txt")

    assert response.status_code == 200
    assert "x-amz-meta-owner" not in response.headers


def test_get_missing_key_records_injected_latency_consistently_with_hit_path(tmp_path: Path) -> None:
    """Latency simulation runs before store.get() so 404 misses record the same
    injected_delay_ms field as a successful hit, instead of recording None."""
    config = ChaosBlobConfig(
        metrics=MetricsConfig(database=str(tmp_path / "blob-metrics.db")),
        latency=LatencyConfig(base_ms=50, jitter_ms=0),
        error_injection=BlobErrorInjectionConfig(),
        storage=BlobStorageConfig(),
    )
    app = create_app(config)
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    import errorworks.blob.server as blob_server

    original = blob_server.asyncio.sleep
    blob_server.asyncio.sleep = fake_sleep  # type: ignore[assignment]
    try:
        client = TestClient(app)
        response = client.get("/bucket/missing.txt")
    finally:
        blob_server.asyncio.sleep = original  # type: ignore[assignment]

    assert response.status_code == 404
    assert sleeps == [0.050]
    request = _exported_request(client)
    assert request["injected_delay_ms"] == 50.0


def test_corruption_decision_on_missing_object_records_actual_not_found_outcome(tmp_path: Path) -> None:
    """A body/metadata corruption decision cannot apply to a non-existent object.
    The metrics row must reflect the real outcome (NoSuchKey) instead of being
    mislabelled with a phantom corruption tag — the injection was wasted, that
    is fine, but we must not lie about what happened."""
    client = _client_for(tmp_path, error_injection=BlobErrorInjectionConfig(metadata_corruption_pct=100.0))

    response = client.get("/bucket/missing.txt")

    assert response.status_code == 404
    request = _exported_request(client)
    assert request["error_type"] == "NoSuchKey"
    assert request["injection_type"] is None


def test_truncated_body_decision_on_missing_object_records_actual_not_found_outcome(tmp_path: Path) -> None:
    """Same as above but for the truncated_body category — must not record a
    phantom body-corruption tag against a real 404."""
    client = _client_for(tmp_path, error_injection=BlobErrorInjectionConfig(truncated_body_pct=100.0))

    response = client.get("/bucket/missing.txt")

    assert response.status_code == 404
    request = _exported_request(client)
    assert request["error_type"] == "NoSuchKey"
    assert request["injection_type"] is None


def test_stale_list_omits_newest_object(tmp_path: Path) -> None:
    client = _client_for(tmp_path, error_injection=BlobErrorInjectionConfig(stale_list_pct=100.0))
    client.put("/bucket/logs/1.txt", content=b"1")
    client.put("/bucket/logs/2.txt", content=b"2")

    response = client.get("/bucket?list-type=2&prefix=logs/")

    assert response.status_code == 200
    assert _list_keys(response) == ["logs/1.txt"]


def test_malformed_xml_injection_returns_unparseable_list_xml(tmp_path: Path) -> None:
    client = _client_for(tmp_path, error_injection=BlobErrorInjectionConfig(malformed_xml_pct=100.0))

    response = client.get("/bucket?list-type=2")

    assert response.status_code == 200
    try:
        ElementTree.fromstring(response.content)
    except ElementTree.ParseError:
        pass
    else:
        raise AssertionError("expected malformed XML")


def test_invalid_continuation_token_returns_controlled_s3_client_error(tmp_path: Path) -> None:
    client = _client_for(tmp_path)

    response = client.get("/bucket?list-type=2&continuation-token=not-a-token")

    assert response.status_code == 400
    assert _xml_code(response) == "InvalidArgument"


def test_invalid_continuation_token_records_error_response_size(tmp_path: Path) -> None:
    client = _client_for(tmp_path)

    response = client.get("/bucket?list-type=2&continuation-token=not-a-token")

    request = _exported_request(client)
    assert isinstance(request["bytes_out"], int)
    assert request["bytes_out"] == len(response.content)
    assert request["bytes_out"] > 0


def test_timeout_injection_records_error_response_size(tmp_path: Path) -> None:
    client = _client_for(tmp_path, error_injection=BlobErrorInjectionConfig(timeout_pct=100.0, timeout_sec=(0, 0)))

    response = client.get("/bucket/key.txt")

    request = _exported_request(client)
    assert response.status_code == 504
    assert isinstance(request["bytes_out"], int)
    assert request["bytes_out"] == len(response.content)
    assert request["bytes_out"] > 0


def test_put_object_too_large_returns_entity_too_large(tmp_path: Path) -> None:
    client = _client_for(tmp_path, storage=BlobStorageConfig(max_object_bytes=3))

    response = client.put("/bucket/key.txt", content=b"toolarge")

    assert response.status_code == 413
    assert _xml_code(response) == "EntityTooLarge"


def test_put_rejects_content_length_over_limit_without_reading_body(tmp_path: Path) -> None:
    app = _app_for(tmp_path, storage=BlobStorageConfig(max_object_bytes=3))

    messages, error = _capture_put_send_events(
        app,
        "/bucket/key.txt",
        headers=[(b"content-length", b"4")],
        chunks=[{"type": "http.request", "body": b"this should not be read", "more_body": False}],
    )

    assert error is None
    assert messages[0]["status"] == 413


def test_put_stops_streaming_when_body_exceeds_limit(tmp_path: Path) -> None:
    app = _app_for(tmp_path, storage=BlobStorageConfig(max_object_bytes=3))

    messages, error = _capture_put_send_events(
        app,
        "/bucket/key.txt",
        headers=[],
        chunks=[
            {"type": "http.request", "body": b"ab", "more_body": True},
            {"type": "http.request", "body": b"cd", "more_body": True},
        ],
    )

    assert error is None
    assert messages[0]["status"] == 413


def test_unhandled_connection_error_tag_raises_assertion_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If BLOB_CONNECTION_ERRORS gains a tag without a handler branch, fail loudly
    in tests with an AssertionError instead of leaking a generic ConnectionResetError
    that surfaces as a noisy ASGI traceback in production."""
    import errorworks.blob.error_injector as injector_module
    from errorworks.blob.error_injector import BlobErrorCategory, BlobErrorDecision, BlobOperation

    app = _app_for(tmp_path, error_injection=BlobErrorInjectionConfig(connection_reset_pct=100.0))
    server = app.state.server

    # Force the injector to return an unknown connection tag (simulating a future
    # tag added to BLOB_CONNECTION_ERRORS without a matching handler branch).
    monkeypatch.setattr(injector_module, "BLOB_CONNECTION_ERRORS", {"timeout", "connection_reset", "connection_stall", "slow_response", "future_tag"})

    def fake_decide(_op: BlobOperation) -> BlobErrorDecision:
        return BlobErrorDecision(
            category=BlobErrorCategory.CONNECTION,
            error_type="future_tag",
            status_code=None,
            s3_code=None,
            retry_after_sec=None,
        )

    monkeypatch.setattr(server._error_injector, "decide", fake_decide)
    client = TestClient(app, raise_server_exceptions=True)

    with pytest.raises(AssertionError, match="unhandled connection error tag 'future_tag'"):
        client.get("/bucket/key.txt")


def test_blob_metrics_sqlite_error_logged_at_error_level_with_row_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sqlite3.Error during metrics recording silently desyncs the time-series.
    Surface it at error level (not warning) and include the row payload so the
    metric can be replayed manually."""
    import sqlite3

    import errorworks.blob.server as blob_server

    app = _app_for(tmp_path)
    server = app.state.server

    def raise_sqlite(**_kwargs: Any) -> None:
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(server._metrics_recorder, "record_request", raise_sqlite)

    log_calls: list[tuple[str, str, dict[str, Any]]] = []

    class _StubLogger:
        def warning(self, event: str, **kwargs: Any) -> None:
            log_calls.append(("warning", event, kwargs))

        def error(self, event: str, **kwargs: Any) -> None:
            log_calls.append(("error", event, kwargs))

    monkeypatch.setattr(blob_server, "logger", _StubLogger())
    client = TestClient(app)

    response = client.put("/bucket/key.txt", content=b"hello")

    assert response.status_code == 200
    error_calls = [call for call in log_calls if call[0] == "error" and call[1] == "metrics_recording_failed"]
    assert error_calls, f"sqlite3.Error must be logged at ERROR level (got {log_calls!r})"
    # The full row payload must be in the log so operators can replay the lost metric.
    payload = error_calls[0][2]
    assert payload["bucket"] == "bucket"
    assert payload["object_key"] == "key.txt"
    assert payload["operation"] == "put"
    assert payload["bytes_in"] == 5
    assert payload["outcome"] == "success"
    # Must NOT be logged at warning level.
    assert not [call for call in log_calls if call[0] == "warning"], "sqlite3.Error must not be logged at WARNING"


def test_blob_metrics_unexpected_exception_does_not_crash_committed_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """OSError / MemoryError / RuntimeError from the recorder must not propagate
    out of the handler — the response is already committed and an unhandled ASGI
    exception would mask the actual outcome. Widening the catch to Exception
    keeps the recorder honest about lost metrics without breaking the wire."""
    app = _app_for(tmp_path)
    server = app.state.server

    def raise_runtime(**_kwargs: Any) -> None:
        raise RuntimeError("recorder is wedged")

    monkeypatch.setattr(server._metrics_recorder, "record_request", raise_runtime)
    client = TestClient(app)

    response = client.put("/bucket/key.txt", content=b"hello")

    assert response.status_code == 200


def test_blob_metrics_type_errors_do_not_replace_success_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app_for(tmp_path)
    server = app.state.server

    def raise_type_error(**_kwargs: Any) -> None:
        raise TypeError("schema mismatch")

    monkeypatch.setattr(server._metrics_recorder, "record_request", raise_type_error)
    client = TestClient(app)

    response = client.put("/bucket/key.txt", content=b"hello")

    assert response.status_code == 200


def test_blob_metrics_type_errors_do_not_replace_error_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app_for(tmp_path, error_injection=BlobErrorInjectionConfig(access_denied_pct=100.0))
    server = app.state.server

    def raise_type_error(**_kwargs: Any) -> None:
        raise TypeError("schema mismatch")

    monkeypatch.setattr(server._metrics_recorder, "record_request", raise_type_error)
    client = TestClient(app)

    response = client.get("/bucket/key.txt")

    assert response.status_code == 403
    assert _xml_code(response) == "AccessDenied"
