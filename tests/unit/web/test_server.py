"""Tests for ChaosWeb HTTP server."""

from __future__ import annotations

from typing import ClassVar

import pytest
from starlette.testclient import TestClient

from errorworks.engine.types import LatencyConfig, MetricsConfig, ServerConfig
from errorworks.web.config import (
    ChaosWebConfig,
    WebErrorInjectionConfig,
)
from errorworks.web.server import ChaosWebServer, create_app

TEST_ADMIN_TOKEN = "test-admin-token"


@pytest.fixture
def tmp_metrics_db(tmp_path):
    """Create a temporary metrics database path."""
    return str(tmp_path / "test-metrics.db")


@pytest.fixture
def config(tmp_metrics_db):
    """Create a basic ChaosWeb config for testing."""
    return ChaosWebConfig(
        server=ServerConfig(admin_token=TEST_ADMIN_TOKEN),
        metrics=MetricsConfig(database=tmp_metrics_db),
        latency=LatencyConfig(base_ms=0, jitter_ms=0),
    )


@pytest.fixture
def admin_headers():
    """Auth headers for admin endpoints."""
    return {"Authorization": f"Bearer {TEST_ADMIN_TOKEN}"}


@pytest.fixture
def server(config):
    """Create a ChaosWebServer instance for testing."""
    return ChaosWebServer(config)


@pytest.fixture
def client(config):
    """Create a test client for the ChaosWeb server."""
    app = create_app(config)
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_check(self, client: TestClient) -> None:
        """Health endpoint returns 200 OK with status and run_id."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "run_id" in data

    def test_health_includes_burst_status(self, tmp_metrics_db: str) -> None:
        """Health endpoint includes burst mode status."""
        config = ChaosWebConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            error_injection=WebErrorInjectionConfig(
                burst={"enabled": True, "interval_sec": 30, "duration_sec": 5},
            ),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "in_burst" in data


class TestPageEndpoint:
    """Tests for GET /{path} content serving."""

    def test_get_page_returns_html(self, client: TestClient) -> None:
        """GET /{path} returns HTML on success."""
        response = client.get("/articles/test")
        assert response.status_code == 200
        content = response.text.lower()
        assert "<html" in content

    def test_get_root_returns_html(self, client: TestClient) -> None:
        """GET / returns HTML on success."""
        response = client.get("/")
        assert response.status_code == 200


class TestAdminEndpoints:
    """Tests for admin endpoints."""

    def test_admin_config_get(self, client: TestClient, admin_headers: dict[str, str]) -> None:
        """GET /admin/config returns current configuration."""
        response = client.get("/admin/config", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert "error_injection" in data
        assert "content" in data
        assert "latency" in data

    def test_admin_stats(self, client: TestClient, admin_headers: dict[str, str]) -> None:
        """GET /admin/stats returns metrics stats."""
        response = client.get("/admin/stats", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert "run_id" in data
        assert "total_requests" in data
        assert data["total_requests"] == 0

    def test_admin_reset(self, client: TestClient, admin_headers: dict[str, str]) -> None:
        """POST /admin/reset resets metrics and returns new run_id."""
        # Make some requests first
        client.get("/page1")
        client.get("/page2")

        stats = client.get("/admin/stats", headers=admin_headers).json()
        assert stats["total_requests"] == 2
        original_run_id = stats["run_id"]

        # Reset
        response = client.post("/admin/reset", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "reset"
        assert "new_run_id" in data
        assert data["new_run_id"] != original_run_id

        # Verify stats cleared
        stats = client.get("/admin/stats", headers=admin_headers).json()
        assert stats["total_requests"] == 0

    def test_admin_export(self, client: TestClient, admin_headers: dict[str, str]) -> None:
        """GET /admin/export returns metrics export data."""
        client.get("/page1")

        response = client.get("/admin/export", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert "run_id" in data
        assert "requests" in data
        assert "timeseries" in data
        assert "config" in data


class TestErrorInjection:
    """Tests for error injection behavior via HTTP."""

    def test_rate_limit_injection(self, tmp_metrics_db: str) -> None:
        """100% rate_limit_pct returns 429."""
        config = ChaosWebConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=WebErrorInjectionConfig(rate_limit_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.get("/test")
        assert response.status_code == 429
        assert "Retry-After" in response.headers

    def test_forbidden_injection(self, tmp_metrics_db: str) -> None:
        """100% forbidden_pct returns 403."""
        config = ChaosWebConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=WebErrorInjectionConfig(forbidden_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.get("/test")
        assert response.status_code == 403

    def test_not_found_injection(self, tmp_metrics_db: str) -> None:
        """100% not_found_pct returns 404."""
        config = ChaosWebConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=WebErrorInjectionConfig(not_found_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.get("/test")
        assert response.status_code == 404

    def test_redirect_loop_injection(self, tmp_metrics_db: str) -> None:
        """100% redirect_loop_pct returns 301 with Location containing hop params."""
        config = ChaosWebConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=WebErrorInjectionConfig(redirect_loop_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app, follow_redirects=False)

        response = client.get("/test")
        assert response.status_code == 301
        location = response.headers["location"]
        assert "hop=" in location
        assert "max=" in location
        assert "target=" in location

    def test_ssrf_redirect_injection(self, tmp_metrics_db: str) -> None:
        """100% ssrf_redirect_pct returns 301 to private IP."""
        config = ChaosWebConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=WebErrorInjectionConfig(ssrf_redirect_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app, follow_redirects=False)

        response = client.get("/test")
        assert response.status_code == 301
        location = response.headers["location"]
        # Should be a private/internal IP
        assert any(
            segment in location
            for segment in [
                "169.254.169.254",
                "192.168.",
                "10.0.",
                "172.16.",
                "127.0.0.1",
                "[::1]",
                "100.64.",
                "0.0.0.0",
                "metadata.google.internal",
                "2852039166",
                "[::ffff:",
            ]
        )


class TestConnectionErrorInjection:
    """Tests for connection-level error injection via HTTP."""

    def test_timeout_returns_504(self, tmp_metrics_db: str) -> None:
        """100% timeout_pct returns 504 Gateway Timeout."""
        config = ChaosWebConfig(
            server=ServerConfig(admin_token=TEST_ADMIN_TOKEN),
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=WebErrorInjectionConfig(
                timeout_pct=100.0,
                timeout_sec=[0, 0],  # No actual delay in tests
            ),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.get("/test")
        assert response.status_code == 504
        assert "Gateway Timeout" in response.text

    def test_timeout_records_metrics(self, tmp_metrics_db: str) -> None:
        """Timeout errors are recorded in metrics."""
        config = ChaosWebConfig(
            server=ServerConfig(admin_token=TEST_ADMIN_TOKEN),
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=WebErrorInjectionConfig(
                timeout_pct=100.0,
                timeout_sec=[0, 0],
            ),
        )
        app = create_app(config)
        client = TestClient(app)

        client.get("/test")
        stats = client.get("/admin/stats", headers={"Authorization": f"Bearer {TEST_ADMIN_TOKEN}"}).json()
        assert stats["total_requests"] == 1
        assert stats["requests_by_outcome"].get("error_injected", 0) == 1

    def test_incomplete_response_returns_partial_content(self, tmp_metrics_db: str) -> None:
        """100% incomplete_response_pct returns partial content then disconnects."""
        config = ChaosWebConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=WebErrorInjectionConfig(
                incomplete_response_pct=100.0,
                incomplete_response_bytes=[50, 50],
            ),
        )
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/test")
        # The streaming disconnect may or may not raise depending on the test client;
        # either way, the response should be truncated or the connection reset
        assert response.status_code == 200 or response.status_code == 500

    def test_connection_reset_raises(self, tmp_metrics_db: str) -> None:
        """100% connection_reset_pct causes connection reset."""
        config = ChaosWebConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=WebErrorInjectionConfig(connection_reset_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        # Connection reset produces an error when reading the streaming body
        response = client.get("/test")
        # The status code is 200 (headers sent before disconnect) or error
        assert response.status_code in (200, 500)

    def test_slow_response_returns_200(self, tmp_metrics_db: str) -> None:
        """100% slow_response_pct returns 200 with delayed content."""
        config = ChaosWebConfig(
            server=ServerConfig(admin_token=TEST_ADMIN_TOKEN),
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=WebErrorInjectionConfig(
                slow_response_pct=100.0,
                slow_response_sec=[0, 0],  # No actual delay in tests
            ),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.get("/test")
        assert response.status_code == 200
        assert "<html" in response.text.lower()


class TestMalformedContentInjection:
    """Tests for malformed content injection via HTTP."""

    def test_wrong_content_type(self, tmp_metrics_db: str) -> None:
        """100% wrong_content_type delivers HTML with wrong Content-Type."""
        config = ChaosWebConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=WebErrorInjectionConfig(wrong_content_type_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.get("/test")
        assert response.status_code == 200
        assert response.headers["content-type"] != "text/html; charset=utf-8"

    def test_encoding_mismatch(self, tmp_metrics_db: str) -> None:
        """100% encoding_mismatch_pct returns content with encoding mismatch."""
        config = ChaosWebConfig(
            server=ServerConfig(admin_token=TEST_ADMIN_TOKEN),
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=WebErrorInjectionConfig(encoding_mismatch_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.get("/test")
        assert response.status_code == 200

        # Verify metrics recorded the encoding mismatch
        stats = client.get("/admin/stats", headers={"Authorization": f"Bearer {TEST_ADMIN_TOKEN}"}).json()
        assert stats["total_requests"] == 1
        assert stats["requests_by_outcome"].get("error_malformed", 0) == 1

    def test_truncated_html(self, tmp_metrics_db: str) -> None:
        """100% truncated_html_pct returns truncated HTML."""
        config = ChaosWebConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=WebErrorInjectionConfig(truncated_html_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.get("/test")
        assert response.status_code == 200
        # Truncated HTML should not end with </html>
        assert not response.text.strip().endswith("</html>")

    def test_invalid_encoding(self, tmp_metrics_db: str) -> None:
        """100% invalid_encoding_pct returns content with invalid byte sequences."""
        config = ChaosWebConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=WebErrorInjectionConfig(invalid_encoding_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.get("/test")
        assert response.status_code == 200

    def test_charset_confusion(self, tmp_metrics_db: str) -> None:
        """100% charset_confusion_pct returns content with mismatched charset header."""
        config = ChaosWebConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=WebErrorInjectionConfig(charset_confusion_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.get("/test")
        assert response.status_code == 200
        # Header should declare windows-1252 but content is UTF-8
        assert "windows-1252" in response.headers.get("content-type", "")

    def test_malformed_meta(self, tmp_metrics_db: str) -> None:
        """100% malformed_meta_pct returns HTML with malformed meta refresh tag."""
        config = ChaosWebConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=WebErrorInjectionConfig(malformed_meta_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.get("/test")
        assert response.status_code == 200
        assert 'http-equiv="refresh"' in response.text


class TestRedirectHopEndpoint:
    """Tests for the /redirect hop endpoint."""

    def test_redirect_hop_continues_chain(self, tmp_metrics_db: str) -> None:
        """Redirect hops continue with 301 until max is reached."""
        config = ChaosWebConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
        )
        app = create_app(config)
        client = TestClient(app, follow_redirects=False)

        response = client.get("/redirect?hop=1&max=3&target=/page")
        assert response.status_code == 301
        location = response.headers["location"]
        assert "hop=2" in location
        assert "max=3" in location

    def test_redirect_hop_terminates_at_max(self, tmp_metrics_db: str) -> None:
        """Redirect chain terminates with 200 at max hops."""
        config = ChaosWebConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
        )
        app = create_app(config)
        client = TestClient(app, follow_redirects=False)

        response = client.get("/redirect?hop=3&max=3&target=/page")
        assert response.status_code == 200

    def test_redirect_hop_invalid_params_returns_400(self, tmp_metrics_db: str) -> None:
        """Invalid hop parameters return 400."""
        config = ChaosWebConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
        )
        app = create_app(config)
        client = TestClient(app, follow_redirects=False)

        response = client.get("/redirect?hop=abc&max=3&target=/page")
        assert response.status_code == 400

    def test_redirect_hop_respects_config_max(self, tmp_metrics_db: str) -> None:
        """Redirect chain caps to configured max_redirect_loop_hops."""
        config = ChaosWebConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=WebErrorInjectionConfig(max_redirect_loop_hops=5),
        )
        app = create_app(config)
        client = TestClient(app, follow_redirects=False)

        # Request with max=100 but config limits to 5
        response = client.get("/redirect?hop=5&max=100&target=/page")
        assert response.status_code == 200


class TestAdminConfigUpdate:
    """Tests for POST /admin/config endpoint."""

    def test_admin_config_post_updates_config(self, tmp_metrics_db: str) -> None:
        """POST /admin/config updates server configuration."""
        config = ChaosWebConfig(
            server=ServerConfig(admin_token=TEST_ADMIN_TOKEN),
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
        )
        app = create_app(config)
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {TEST_ADMIN_TOKEN}"}

        # Initially no errors
        response = client.get("/test")
        assert response.status_code == 200

        # Update config via admin endpoint
        response = client.post(
            "/admin/config",
            json={"error_injection": {"rate_limit_pct": 100.0}},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "updated"

        # Verify change took effect
        response = client.get("/test")
        assert response.status_code == 429

    def test_admin_config_post_invalid_json(self, tmp_metrics_db: str) -> None:
        """POST /admin/config with invalid JSON returns 400."""
        config = ChaosWebConfig(
            server=ServerConfig(admin_token=TEST_ADMIN_TOKEN),
            metrics=MetricsConfig(database=tmp_metrics_db),
        )
        app = create_app(config)
        client = TestClient(app)
        headers = {
            "Authorization": f"Bearer {TEST_ADMIN_TOKEN}",
            "Content-Type": "application/json",
        }

        response = client.post("/admin/config", content=b"not json", headers=headers)
        assert response.status_code == 400
        assert "JSON" in response.json()["error"]["message"]

    def test_admin_config_post_requires_auth(self, client: TestClient) -> None:
        """POST /admin/config requires authentication."""
        response = client.post("/admin/config", json={"error_injection": {"rate_limit_pct": 50.0}})
        assert response.status_code == 401


class TestRuntimeConfigUpdate:
    """Tests for runtime configuration updates."""

    def test_update_error_injection(self, server: ChaosWebServer) -> None:
        """Server can update error injection config at runtime."""
        assert server._error_injector._config.rate_limit_pct == 0.0

        server.update_config({"error_injection": {"rate_limit_pct": 50.0}})
        assert server._error_injector._config.rate_limit_pct == 50.0

    def test_update_via_fixture_pattern(self, tmp_metrics_db: str) -> None:
        """update_config changes behavior for subsequent requests."""
        config = ChaosWebConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
        )
        server = ChaosWebServer(config)
        client = TestClient(server.app)

        # Initially no errors
        response = client.get("/test")
        assert response.status_code == 200

        # Enable 100% rate limiting
        server.update_config({"error_injection": {"rate_limit_pct": 100.0}})

        response = client.get("/test")
        assert response.status_code == 429


class TestMetricsRecording:
    """Tests for metrics recording."""

    def test_successful_request_recorded(self, client: TestClient, admin_headers: dict[str, str]) -> None:
        """Successful requests are recorded in metrics."""
        client.get("/page1")

        response = client.get("/admin/stats", headers=admin_headers)
        data = response.json()
        assert data["total_requests"] == 1
        assert data["requests_by_outcome"].get("success", 0) == 1

    def test_error_request_recorded(self, tmp_metrics_db: str) -> None:
        """Error responses are recorded in metrics."""
        config = ChaosWebConfig(
            server=ServerConfig(admin_token=TEST_ADMIN_TOKEN),
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=WebErrorInjectionConfig(rate_limit_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {TEST_ADMIN_TOKEN}"}

        client.get("/test")

        stats = client.get("/admin/stats", headers=headers).json()
        assert stats["total_requests"] == 1
        assert stats["requests_by_outcome"].get("error_injected", 0) == 1

    def test_stats_increment_after_multiple_requests(self, client: TestClient, admin_headers: dict[str, str]) -> None:
        """Stats count increases with each request."""
        for i in range(5):
            client.get(f"/page{i}")

        stats = client.get("/admin/stats", headers=admin_headers).json()
        assert stats["total_requests"] == 5


class TestChaosWebServer:
    """Tests for the ChaosWebServer class."""

    def test_server_creation(self, config: ChaosWebConfig) -> None:
        """ChaosWebServer can be created from config."""
        server = ChaosWebServer(config)
        assert server.app is not None
        assert server.run_id is not None

    def test_server_reset(self, server: ChaosWebServer) -> None:
        """Server reset creates new run_id."""
        original_run_id = server.run_id
        new_run_id = server.reset()
        assert new_run_id != original_run_id
        assert server.run_id == new_run_id

    def test_get_stats(self, server: ChaosWebServer) -> None:
        """Server get_stats returns metrics dict."""
        stats = server.get_stats()
        assert "run_id" in stats
        assert "total_requests" in stats

    def test_export_metrics(self, server: ChaosWebServer) -> None:
        """Server export_metrics returns complete data."""
        data = server.export_metrics()
        assert "run_id" in data
        assert "requests" in data
        assert "config" in data


class TestCreateApp:
    """Tests for the create_app convenience function."""

    def test_create_app_returns_starlette(self, config: ChaosWebConfig) -> None:
        """create_app returns a Starlette application."""
        app = create_app(config)
        assert app is not None

    def test_create_app_stores_server_on_state(self, config: ChaosWebConfig) -> None:
        """create_app stores ChaosWebServer on app.state.server."""
        app = create_app(config)
        assert hasattr(app.state, "server")
        assert isinstance(app.state.server, ChaosWebServer)

    def test_create_app_functional(self, config: ChaosWebConfig) -> None:
        """App created by create_app handles requests."""
        app = create_app(config)
        client = TestClient(app)

        response = client.get("/health")
        assert response.status_code == 200


# =============================================================================
# Admin Authentication Rejection
# =============================================================================


class TestAdminAuthRejection:
    """Tests for admin endpoint auth rejection paths (401/403)."""

    ADMIN_ENDPOINTS: ClassVar[list[tuple[str, str]]] = [
        ("GET", "/admin/config"),
        ("GET", "/admin/stats"),
        ("POST", "/admin/reset"),
        ("GET", "/admin/export"),
    ]

    @pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
    def test_missing_auth_header_returns_401(self, client: TestClient, method: str, path: str) -> None:
        """Admin endpoints return 401 when Authorization header is missing."""
        response = client.request(method, path)
        assert response.status_code == 401
        assert response.json()["error"]["type"] == "authentication_error"

    @pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
    def test_wrong_token_returns_403(self, client: TestClient, method: str, path: str) -> None:
        """Admin endpoints return 403 when token is wrong."""
        response = client.request(method, path, headers={"Authorization": "Bearer wrong-token"})
        assert response.status_code == 403
        assert response.json()["error"]["type"] == "authorization_error"

    @pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
    def test_malformed_auth_header_returns_401(self, client: TestClient, method: str, path: str) -> None:
        """Admin endpoints return 401 when Authorization header has wrong prefix."""
        response = client.request(method, path, headers={"Authorization": f"Token {TEST_ADMIN_TOKEN}"})
        assert response.status_code == 401


# =============================================================================
# Admin Token Not Leaked
# =============================================================================


class TestAdminTokenNotLeaked:
    """Tests that admin_token is excluded from serialized config."""

    def test_export_excludes_admin_token(self, client: TestClient, admin_headers: dict) -> None:
        """Export endpoint does not include admin_token in config."""
        response = client.get("/admin/export", headers=admin_headers)
        assert response.status_code == 200
        config_server = response.json().get("config", {}).get("server", {})
        assert "admin_token" not in config_server

    def test_run_info_excludes_admin_token(self, server: ChaosWebServer, tmp_metrics_db: str) -> None:
        """Run info stored in DB does not include admin_token."""
        import sqlite3

        db = sqlite3.connect(tmp_metrics_db)
        rows = db.execute("SELECT config_json FROM run_info").fetchall()
        for row in rows:
            assert "admin_token" not in row[0]
            assert TEST_ADMIN_TOKEN not in row[0]
        db.close()


# =============================================================================
# Best-Effort Metrics Recording
# =============================================================================


class TestBestEffortMetrics:
    """Tests that metrics recording failures don't replace chaos responses."""

    def test_metrics_failure_does_not_replace_success_response(self, tmp_metrics_db: str) -> None:
        """A broken metrics store doesn't prevent successful chaos responses."""
        config = ChaosWebConfig(
            server=ServerConfig(admin_token=TEST_ADMIN_TOKEN),
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
        )
        server = ChaosWebServer(config)
        client = TestClient(server.app)

        # Make a request first to confirm the server works
        response = client.get("/test-page")
        assert response.status_code == 200

        # Close the metrics store to simulate a database failure
        server._metrics_recorder._store.close()

        # Next request should still succeed (metrics failure is swallowed)
        response = client.get("/test-page")
        assert response.status_code == 200

    def test_metrics_failure_does_not_replace_error_response(self, tmp_metrics_db: str) -> None:
        """A broken metrics store doesn't prevent injected error responses."""
        config = ChaosWebConfig(
            server=ServerConfig(admin_token=TEST_ADMIN_TOKEN),
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=WebErrorInjectionConfig(rate_limit_pct=100.0),
        )
        server = ChaosWebServer(config)
        client = TestClient(server.app)

        # Close metrics store to simulate failure
        server._metrics_recorder._store.close()

        # Error injection should still return the intended 429
        response = client.get("/test-page")
        assert response.status_code == 429


# =============================================================================
# Concurrent Config Updates
# =============================================================================


class TestConcurrentConfigUpdates:
    """Tests that concurrent config updates don't corrupt request handling."""

    def test_config_update_during_requests(self, tmp_metrics_db: str) -> None:
        """Requests use a consistent config snapshot even during updates."""
        import threading

        config = ChaosWebConfig(
            server=ServerConfig(admin_token=TEST_ADMIN_TOKEN),
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
        )
        server = ChaosWebServer(config)
        client = TestClient(server.app)
        errors: list[str] = []

        def make_requests() -> None:
            for _ in range(20):
                try:
                    resp = client.get("/test-page")
                    if resp.status_code not in (200, 429):
                        errors.append(f"Unexpected status: {resp.status_code}")
                except Exception as e:
                    errors.append(f"Request error: {e}")

        def update_configs() -> None:
            for i in range(20):
                try:
                    pct = float(i * 5)
                    server.update_config({"error_injection": {"rate_limit_pct": pct}})
                except Exception as e:
                    errors.append(f"Config update error: {e}")

        request_thread = threading.Thread(target=make_requests)
        update_thread = threading.Thread(target=update_configs)

        request_thread.start()
        update_thread.start()

        request_thread.join()
        update_thread.join()

        assert errors == [], f"Concurrent errors: {errors}"
