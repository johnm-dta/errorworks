"""Tests for the ChaosWeb pytest fixture."""

import pytest


class TestChaosWebFixtureBasics:
    """Basic fixture functionality tests."""

    def test_fixture_provides_client(self, chaosweb_server) -> None:
        """Fixture provides a working test client."""
        response = chaosweb_server.client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_fixture_provides_server(self, chaosweb_server) -> None:
        """Fixture provides server access."""
        assert chaosweb_server.server is not None
        assert chaosweb_server.server.run_id is not None

    def test_base_url_property(self, chaosweb_server) -> None:
        """base_url property returns testserver URL."""
        assert chaosweb_server.base_url == "http://testserver"

    def test_admin_url_property(self, chaosweb_server) -> None:
        """Admin URL property returns correct path."""
        assert chaosweb_server.admin_url == "http://testserver/admin"

    def test_metrics_db_property(self, chaosweb_server) -> None:
        """Metrics DB property returns path."""
        assert chaosweb_server.metrics_db.exists()

    def test_run_id_property(self, chaosweb_server) -> None:
        """Run ID property returns server run_id."""
        assert chaosweb_server.run_id == chaosweb_server.server.run_id


class TestChaosWebFixtureConvenienceMethods:
    """Tests for convenience methods on the fixture."""

    def test_fetch_page(self, chaosweb_server) -> None:
        """fetch_page sends a GET request."""
        response = chaosweb_server.fetch_page("/articles/test")
        assert response.status_code == 200

    def test_fetch_page_with_headers(self, chaosweb_server) -> None:
        """fetch_page accepts custom headers."""
        response = chaosweb_server.fetch_page("/", headers={"Accept": "text/html"})
        assert response.status_code == 200

    def test_get_stats(self, chaosweb_server) -> None:
        """get_stats returns metrics."""
        stats = chaosweb_server.get_stats()
        assert "run_id" in stats
        assert "total_requests" in stats
        assert stats["total_requests"] == 0

    def test_get_stats_after_request(self, chaosweb_server) -> None:
        """get_stats reflects requests made."""
        chaosweb_server.fetch_page("/")
        stats = chaosweb_server.get_stats()
        assert stats["total_requests"] == 1

    def test_reset(self, chaosweb_server) -> None:
        """reset clears metrics and returns new run_id."""
        chaosweb_server.fetch_page("/")
        old_run_id = chaosweb_server.run_id

        new_run_id = chaosweb_server.reset()

        assert new_run_id != old_run_id
        assert chaosweb_server.run_id == new_run_id
        assert chaosweb_server.get_stats()["total_requests"] == 0

    def test_wait_for_requests(self, chaosweb_server) -> None:
        """wait_for_requests returns True when count reached."""
        chaosweb_server.fetch_page("/")
        chaosweb_server.fetch_page("/")

        result = chaosweb_server.wait_for_requests(2, timeout=1.0)
        assert result is True

    def test_wait_for_requests_timeout(self, chaosweb_server) -> None:
        """wait_for_requests returns False on timeout."""
        result = chaosweb_server.wait_for_requests(100, timeout=0.1)
        assert result is False


class TestChaosWebFixtureUpdateConfig:
    """Tests for runtime configuration updates."""

    def test_update_config_error_rate(self, chaosweb_server) -> None:
        """update_config can change error rates."""
        response = chaosweb_server.fetch_page("/")
        assert response.status_code == 200

        chaosweb_server.update_config(rate_limit_pct=100.0)

        response = chaosweb_server.fetch_page("/")
        assert response.status_code == 429

    def test_update_config_multiple_fields(self, chaosweb_server) -> None:
        """update_config can change multiple fields."""
        chaosweb_server.update_config(
            rate_limit_pct=50.0,
            base_ms=100,
        )

    def test_update_config_content_mode(self, chaosweb_server) -> None:
        """update_config can change content mode."""
        chaosweb_server.update_config(content_mode="echo")

        response = chaosweb_server.fetch_page("/test")
        assert response.status_code == 200


class TestChaosWebMarkerIntegration:
    """Tests for the @pytest.mark.chaosweb marker."""

    def test_default_config_no_marker(self, chaosweb_server) -> None:
        """Without marker, uses default config (no errors)."""
        response = chaosweb_server.fetch_page("/")
        assert response.status_code == 200

    @pytest.mark.chaosweb(rate_limit_pct=100.0)
    def test_marker_error_rate(self, chaosweb_server) -> None:
        """Marker can set error rate."""
        response = chaosweb_server.fetch_page("/")
        assert response.status_code == 429

    @pytest.mark.chaosweb(internal_error_pct=100.0)
    def test_marker_internal_error(self, chaosweb_server) -> None:
        """Marker can set different error types."""
        response = chaosweb_server.fetch_page("/")
        assert response.status_code == 500

    @pytest.mark.chaosweb(content_mode="echo")
    def test_marker_content_mode(self, chaosweb_server) -> None:
        """Marker can set content mode."""
        response = chaosweb_server.fetch_page("/test")
        assert response.status_code == 200


class TestChaosWebFixtureIsolation:
    """Tests for fixture isolation between tests."""

    def test_first_request(self, chaosweb_server) -> None:
        """First test makes a request."""
        chaosweb_server.fetch_page("/")
        assert chaosweb_server.get_stats()["total_requests"] == 1

    def test_second_request_isolated(self, chaosweb_server) -> None:
        """Second test should have fresh state."""
        assert chaosweb_server.get_stats()["total_requests"] == 0

    @pytest.mark.chaosweb(rate_limit_pct=100.0)
    def test_marker_in_first(self, chaosweb_server) -> None:
        """Test with marker affecting config."""
        response = chaosweb_server.fetch_page("/")
        assert response.status_code == 429

    def test_no_marker_after_marker(self, chaosweb_server) -> None:
        """Test without marker should not inherit previous config."""
        response = chaosweb_server.fetch_page("/")
        assert response.status_code == 200


class TestChaosWebErrorTypes:
    """Test various error injection types via the fixture."""

    @pytest.mark.chaosweb(service_unavailable_pct=100.0)
    def test_service_unavailable(self, chaosweb_server) -> None:
        """503 service unavailable injection."""
        response = chaosweb_server.fetch_page("/")
        assert response.status_code == 503

    @pytest.mark.chaosweb(forbidden_pct=100.0)
    def test_forbidden(self, chaosweb_server) -> None:
        """403 forbidden injection."""
        response = chaosweb_server.fetch_page("/")
        assert response.status_code == 403

    @pytest.mark.chaosweb(not_found_pct=100.0)
    def test_not_found(self, chaosweb_server) -> None:
        """404 not found injection."""
        response = chaosweb_server.fetch_page("/")
        assert response.status_code == 404
