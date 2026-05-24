"""Integration tests for the ChaosBlob pipeline: fixture -> object workflow -> metrics."""

from __future__ import annotations

from xml.etree import ElementTree

import pytest

from tests.fixtures.chaosblob import chaosblob as _chaosblob  # noqa: F401


def _xml_code(response) -> str | None:
    root = ElementTree.fromstring(response.content)
    return root.findtext("Code")


def _list_keys(response) -> list[str]:
    root = ElementTree.fromstring(response.content)
    return [node.text or "" for node in root.findall("Contents/Key")]


@pytest.mark.integration
def test_blob_pipeline_put_list_get_forced_slow_down_and_metrics(_chaosblob) -> None:  # noqa: F811
    """A realistic blob pipeline can handle normal object IO, storage throttling, and metrics."""
    first = _chaosblob.put_object("bucket", "incoming/first.json", b'{"id": 1}', headers={"content-type": "application/json"})
    second = _chaosblob.put_object("bucket", "incoming/second.json", b'{"id": 2}', headers={"content-type": "application/json"})
    _chaosblob.put_object("bucket", "archive/old.json", b'{"id": 0}', headers={"content-type": "application/json"})
    assert first.status_code == 200
    assert second.status_code == 200

    listing = _chaosblob.list_objects("bucket", prefix="incoming/")
    assert listing.status_code == 200
    assert _list_keys(listing) == ["incoming/first.json", "incoming/second.json"]

    fetched = _chaosblob.get_object("bucket", "incoming/first.json")
    assert fetched.status_code == 200
    assert fetched.json() == {"id": 1}

    _chaosblob.update_config(slow_down_pct=100.0)
    throttled = _chaosblob.get_object("bucket", "incoming/second.json")
    assert throttled.status_code == 503
    assert _xml_code(throttled) == "SlowDown"
    assert "retry-after" in throttled.headers

    stats = _chaosblob.get_stats()
    assert stats["total_requests"] == 6
    assert stats["requests_by_status_code"][200] == 5
    assert stats["requests_by_status_code"][503] == 1
    assert stats["timeseries"][0]["requests_slow_down"] == 1

    exported = _chaosblob.export_metrics()
    assert [request["operation"] for request in exported["requests"]] == ["put", "put", "put", "list", "get", "get"]
    assert exported["requests"][-1]["error_type"] == "slow_down"
