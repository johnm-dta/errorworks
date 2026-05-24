"""Integration tests for the ChaosBlob pipeline: fixture -> object workflow -> metrics."""

from __future__ import annotations

from xml.etree import ElementTree

import pytest

from tests.fixtures.chaosblob import chaosblob as _chaosblob  # noqa: F401


def _xml_code(response) -> str | None:
    root = ElementTree.fromstring(response.content)
    return root.findtext("{*}Code")


def _list_keys(response) -> list[str]:
    root = ElementTree.fromstring(response.content)
    return [node.text or "" for node in root.findall("{*}Contents/{*}Key")]


@pytest.mark.integration
def test_blob_pipeline_retries_forced_slow_down_and_records_metrics(_chaosblob) -> None:  # noqa: F811
    """A realistic blob pipeline can retry object-store throttling and inspect metrics."""
    first = _chaosblob.put_object("bucket", "incoming/first.json", b'{"id": 1}', headers={"content-type": "application/json"})
    second = _chaosblob.put_object("bucket", "incoming/second.json", b'{"id": 2}', headers={"content-type": "application/json"})
    _chaosblob.put_object("bucket", "archive/old.json", b'{"id": 0}', headers={"content-type": "application/json"})
    assert first.status_code == 200
    assert second.status_code == 200

    listing = _chaosblob.list_objects("bucket", prefix="incoming/")
    assert listing.status_code == 200
    keys = _list_keys(listing)
    assert keys == ["incoming/first.json", "incoming/second.json"]

    _chaosblob.update_config(updates={"error_injection": {"retry_after_sec": (0, 0)}}, slow_down_pct=100.0)
    retry_after_values: list[str] = []
    payloads: list[dict[str, int]] = []
    for key in keys:
        while True:
            response = _chaosblob.get_object("bucket", key)
            if response.status_code == 503:
                assert _xml_code(response) == "SlowDown"
                retry_after_values.append(response.headers["retry-after"])
                _chaosblob.update_config(slow_down_pct=0.0)
                continue

            assert response.status_code == 200
            payloads.append(response.json())
            break

    assert retry_after_values == ["0"]
    assert payloads == [{"id": 1}, {"id": 2}]

    stats = _chaosblob.get_stats()
    assert stats["total_requests"] == 7
    assert stats["requests_by_status_code"][200] == 6
    assert stats["requests_by_status_code"][503] == 1
    assert stats["timeseries"][0]["requests_slow_down"] == 1

    exported = _chaosblob.export_metrics()
    assert [request["operation"] for request in exported["requests"]] == ["put", "put", "put", "list", "get", "get", "get"]
    assert exported["requests"][4]["error_type"] == "slow_down"
