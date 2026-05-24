"""Tests for the ChaosBlob pytest fixture."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

import pytest

from errorworks.blob.config import ChaosBlobConfig
from errorworks.blob.server import ChaosBlobServer
from tests.fixtures.chaosblob import _build_config_from_marker


def _xml_code(response) -> str | None:
    root = ElementTree.fromstring(response.content)
    return root.findtext("{*}Code")


def _list_keys(response) -> list[str]:
    root = ElementTree.fromstring(response.content)
    return [node.text or "" for node in root.findall("{*}Contents/{*}Key")]


@dataclass
class _Marker:
    kwargs: dict[str, object]


class TestChaosBlobFixtureBasics:
    """Basic fixture functionality tests."""

    def test_fixture_provides_client(self, chaosblob) -> None:
        """Fixture provides a working test client."""
        response = chaosblob.client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_fixture_provides_server(self, chaosblob) -> None:
        """Fixture provides server access."""
        assert chaosblob.server is not None
        assert chaosblob.server.run_id is not None

    def test_base_url_property(self, chaosblob) -> None:
        """base_url property returns testserver URL."""
        assert chaosblob.base_url == "http://testserver"

    def test_admin_url_property(self, chaosblob) -> None:
        """Admin URL property returns correct path."""
        assert chaosblob.admin_url == "http://testserver/admin"

    def test_metrics_db_property(self, chaosblob) -> None:
        """Metrics DB property returns path."""
        assert chaosblob.metrics_db.exists()

    def test_run_id_property(self, chaosblob) -> None:
        """Run ID property returns server run_id."""
        assert chaosblob.run_id == chaosblob.server.run_id


class TestChaosBlobFixtureLifecycle:
    """Tests for fixture lifecycle support."""

    def test_server_close_closes_metrics_recorder(self, monkeypatch) -> None:
        """Server exposes a close method for fixture teardown."""
        server = ChaosBlobServer(ChaosBlobConfig())
        closed = False

        def close_metrics() -> None:
            nonlocal closed
            closed = True

        monkeypatch.setattr(server._metrics_recorder, "close", close_metrics)

        server.close()

        assert closed is True


class TestChaosBlobFixtureConvenienceMethods:
    """Tests for convenience methods on the fixture."""

    def test_put_get_head_and_list_objects(self, chaosblob) -> None:
        """Convenience methods exercise core object operations."""
        put = chaosblob.put_object("bucket", "logs/1.txt", b"data", headers={"content-type": "text/plain"})
        assert put.status_code == 200
        assert put.headers["etag"]

        get = chaosblob.get_object("bucket", "logs/1.txt")
        assert get.status_code == 200
        assert get.content == b"data"
        assert get.headers["content-type"].startswith("text/plain")
        assert get.headers["etag"] == put.headers["etag"]

        head = chaosblob.head_object("bucket", "logs/1.txt")
        assert head.status_code == 200
        assert head.content == b""
        assert head.headers["content-length"] == str(len(b"data"))

        listing = chaosblob.list_objects("bucket", prefix="")
        assert listing.status_code == 200
        assert _list_keys(listing) == ["logs/1.txt"]

    def test_delete_object(self, chaosblob) -> None:
        """delete_object removes the object."""
        chaosblob.put_object("bucket", "key", b"data")

        delete = chaosblob.delete_object("bucket", "key")

        assert delete.status_code == 204
        missing = chaosblob.get_object("bucket", "key")
        assert missing.status_code == 404
        assert _xml_code(missing) == "NoSuchKey"

    def test_get_stats(self, chaosblob) -> None:
        """get_stats returns metrics."""
        stats = chaosblob.get_stats()
        assert "run_id" in stats
        assert "total_requests" in stats
        assert stats["total_requests"] == 0

    def test_get_stats_after_request(self, chaosblob) -> None:
        """get_stats reflects requests made."""
        chaosblob.put_object("bucket", "key", b"data")
        stats = chaosblob.get_stats()
        assert stats["total_requests"] == 1

    def test_export_metrics(self, chaosblob) -> None:
        """export_metrics includes raw request rows."""
        chaosblob.put_object("bucket", "key", b"data")

        exported = chaosblob.export_metrics()

        assert len(exported["requests"]) == 1
        assert exported["requests"][0]["operation"] == "put"

    def test_reset(self, chaosblob) -> None:
        """reset clears metrics and stored objects, and returns new run_id."""
        chaosblob.put_object("bucket", "key", b"data")
        old_run_id = chaosblob.run_id

        new_run_id = chaosblob.reset()

        assert new_run_id != old_run_id
        assert chaosblob.run_id == new_run_id
        assert chaosblob.get_stats()["total_requests"] == 0
        assert chaosblob.get_object("bucket", "key").status_code == 404

    def test_wait_for_requests(self, chaosblob) -> None:
        """wait_for_requests returns True when count reached."""
        chaosblob.put_object("bucket", "one", b"1")
        chaosblob.put_object("bucket", "two", b"2")

        result = chaosblob.wait_for_requests(2, timeout=1.0)
        assert result is True

    def test_wait_for_requests_timeout(self, chaosblob) -> None:
        """wait_for_requests returns False on timeout."""
        result = chaosblob.wait_for_requests(100, timeout=0.1)
        assert result is False


class TestChaosBlobFixtureUpdateConfig:
    """Tests for runtime configuration updates."""

    def test_update_config_error_rate(self, chaosblob) -> None:
        """update_config can change error rates."""
        chaosblob.put_object("bucket", "key", b"data")
        response = chaosblob.get_object("bucket", "key")
        assert response.status_code == 200

        chaosblob.update_config(slow_down_pct=100.0)

        response = chaosblob.get_object("bucket", "key")
        assert response.status_code == 503
        assert _xml_code(response) == "SlowDown"

    def test_update_config_multiple_fields(self, chaosblob) -> None:
        """update_config can change multiple fields."""
        chaosblob.update_config(
            slow_down_pct=50.0,
            selection_mode="weighted",
            base_ms=0,
            max_object_bytes=1024,
        )

        current = chaosblob.server.get_current_config()
        assert current["error_injection"]["slow_down_pct"] == 50.0
        assert current["error_injection"]["selection_mode"] == "weighted"
        assert current["storage"]["max_object_bytes"] == 1024

    def test_update_config_accepts_raw_updates_for_unsupported_fields(self, chaosblob) -> None:
        """update_config raw updates provide an escape hatch for less common fields."""
        chaosblob.update_config(updates={"storage": {"default_content_type": "text/plain"}})

        chaosblob.put_object("bucket", "key", b"data")
        response = chaosblob.get_object("bucket", "key")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")


class TestChaosBlobMarkerIntegration:
    """Tests for the @pytest.mark.chaosblob marker."""

    def test_default_config_no_marker(self, chaosblob) -> None:
        """Without marker, uses default config with no injected errors."""
        chaosblob.put_object("bucket", "key", b"data")
        response = chaosblob.get_object("bucket", "key")
        assert response.status_code == 200

    @pytest.mark.chaosblob(preset="silent", slow_down_pct=100.0)
    def test_marker_override_forces_slow_down(self, chaosblob) -> None:
        """Marker can set preset and error-injection overrides."""
        response = chaosblob.put_object("bucket", "key", b"data")
        assert response.status_code == 503
        assert _xml_code(response) == "SlowDown"

    @pytest.mark.chaosblob(preset="silent", max_object_bytes=3)
    def test_marker_storage_override(self, chaosblob) -> None:
        """Marker can set storage overrides."""
        response = chaosblob.put_object("bucket", "key", b"data")
        assert response.status_code == 413
        assert _xml_code(response) == "EntityTooLarge"

    def test_marker_rejects_unknown_kwargs(self, tmp_path: Path) -> None:
        """Marker builder should fail fast on misspelled options."""
        with pytest.raises(ValueError, match=r"Unknown chaosblob marker kwargs.*slow_dwon_pct.*slow_down_pct"):
            _build_config_from_marker(_Marker({"slow_dwon_pct": 100.0}), tmp_path)  # type: ignore[arg-type]


class TestChaosBlobFixtureIsolation:
    """Tests for fixture isolation between tests."""

    def test_first_request(self, chaosblob) -> None:
        """First test makes a request."""
        chaosblob.put_object("bucket", "key", b"data")
        assert chaosblob.get_stats()["total_requests"] == 1

    def test_second_request_isolated(self, chaosblob) -> None:
        """Second test should have fresh state."""
        assert chaosblob.get_stats()["total_requests"] == 0

    @pytest.mark.chaosblob(slow_down_pct=100.0)
    def test_marker_in_first(self, chaosblob) -> None:
        """Test with marker affecting config."""
        response = chaosblob.put_object("bucket", "key", b"data")
        assert response.status_code == 503

    def test_no_marker_after_marker(self, chaosblob) -> None:
        """Test without marker should not inherit previous config."""
        response = chaosblob.put_object("bucket", "key", b"data")
        assert response.status_code == 200
