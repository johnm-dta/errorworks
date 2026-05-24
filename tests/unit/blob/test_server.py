from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

from starlette.testclient import TestClient

from errorworks.blob.config import BlobErrorInjectionConfig, BlobStorageConfig, ChaosBlobConfig
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


def _admin_headers(client: TestClient) -> dict[str, str]:
    token = client.app.state.server.get_admin_token()
    return {"Authorization": f"Bearer {token}"}


def _xml_code(response) -> str | None:
    root = ElementTree.fromstring(response.content)
    return root.findtext("Code")


def _list_keys(response) -> list[str]:
    root = ElementTree.fromstring(response.content)
    return [node.text or "" for node in root.findall("Contents/Key")]


def _exported_request(client: TestClient) -> dict:
    export = client.get("/admin/export", headers=_admin_headers(client))
    assert export.status_code == 200
    requests = export.json()["requests"]
    assert len(requests) == 1
    return requests[0]


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


def test_list_without_list_type_v2_returns_invalid_request(tmp_path: Path) -> None:
    client = _client_for(tmp_path)

    response = client.get("/bucket")

    assert response.status_code == 400
    assert _xml_code(response) == "InvalidRequest"


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


def test_wrong_content_length_injection_exposes_mismatched_header(tmp_path: Path) -> None:
    client = _client_for(tmp_path, error_injection=BlobErrorInjectionConfig(wrong_content_length_pct=100.0))
    client.put("/bucket/key.txt", content=b"hello")

    response = client.get("/bucket/key.txt")

    assert response.status_code == 200
    assert response.headers["content-length"] != str(len(response.content))


def test_metadata_corruption_drops_amz_metadata_header(tmp_path: Path) -> None:
    client = _client_for(tmp_path, error_injection=BlobErrorInjectionConfig(metadata_corruption_pct=100.0))
    client.put("/bucket/key.txt", content=b"hello", headers={"x-amz-meta-owner": "tests"})

    response = client.get("/bucket/key.txt")

    assert response.status_code == 200
    assert "x-amz-meta-owner" not in response.headers


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
