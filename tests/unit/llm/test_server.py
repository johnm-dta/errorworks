# tests/testing/chaosllm/test_server.py
"""Tests for ChaosLLM HTTP server."""

import json
import sqlite3
import time
from typing import ClassVar

import pytest
from starlette.testclient import TestClient

from errorworks.engine.types import ServerConfig
from errorworks.llm.config import (
    ChaosLLMConfig,
    ErrorInjectionConfig,
    LatencyConfig,
    MetricsConfig,
    ResponseConfig,
)
from errorworks.llm.server import (
    ChaosLLMServer,
    create_app,
)

TEST_ADMIN_TOKEN = "test-admin-token"


@pytest.fixture
def tmp_metrics_db(tmp_path):
    """Create a temporary metrics database path."""
    return str(tmp_path / "test-metrics.db")


@pytest.fixture
def config(tmp_metrics_db):
    """Create a basic ChaosLLM config for testing."""
    return ChaosLLMConfig(
        server=ServerConfig(admin_token=TEST_ADMIN_TOKEN),
        metrics=MetricsConfig(database=tmp_metrics_db),
        latency=LatencyConfig(base_ms=0, jitter_ms=0),  # No latency for tests
    )


@pytest.fixture
def admin_headers():
    """Auth headers for admin endpoints."""
    return {"Authorization": f"Bearer {TEST_ADMIN_TOKEN}"}


@pytest.fixture
def client(config):
    """Create a test client for the ChaosLLM server."""
    app = create_app(config)
    return TestClient(app)


@pytest.fixture
def server(config):
    """Create a ChaosLLMServer instance for testing."""
    return ChaosLLMServer(config)


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_check(self, client):
        """Health endpoint returns 200 OK."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "run_id" in data

    def test_health_check_includes_burst_status(self, tmp_metrics_db):
        """Health endpoint includes burst mode status."""
        config = ChaosLLMConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            error_injection=ErrorInjectionConfig(burst={"enabled": True, "interval_sec": 30, "duration_sec": 5}),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "in_burst" in data


class TestOpenAICompletionsEndpoint:
    """Tests for POST /v1/chat/completions (OpenAI format)."""

    def test_basic_completion(self, client):
        """Basic completion request returns valid response."""
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert response.status_code == 200
        data = response.json()

        # Verify OpenAI response format
        assert "id" in data
        assert data["id"].startswith("fake-")
        assert data["object"] == "chat.completion"
        assert "created" in data
        assert data["model"] == "gpt-4"
        assert "choices" in data
        assert len(data["choices"]) == 1
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert "content" in data["choices"][0]["message"]
        assert data["choices"][0]["finish_reason"] == "stop"
        assert "usage" in data

    def test_completion_with_temperature(self, client):
        """Completion request with temperature parameter."""
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
                "temperature": 0.7,
            },
        )
        assert response.status_code == 200

    def test_completion_with_max_tokens(self, client):
        """Completion request with max_tokens parameter."""
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 100,
            },
        )
        assert response.status_code == 200


class TestAzureCompletionsEndpoint:
    """Tests for POST /openai/deployments/{deployment}/chat/completions (Azure format)."""

    def test_azure_completion(self, client):
        """Azure completion request returns valid response."""
        response = client.post(
            "/openai/deployments/my-gpt4-deployment/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert response.status_code == 200
        data = response.json()

        # Verify OpenAI response format
        assert "id" in data
        assert data["object"] == "chat.completion"
        assert "choices" in data
        assert "usage" in data

    def test_azure_completion_with_api_version(self, client):
        """Azure endpoint accepts api-version query parameter."""
        response = client.post(
            "/openai/deployments/my-deployment/chat/completions?api-version=2024-02-01",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert response.status_code == 200

    def test_azure_completion_extracts_deployment(self, client):
        """Azure endpoint extracts deployment name from path."""
        response = client.post(
            "/openai/deployments/custom-deployment-name/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert response.status_code == 200


class TestErrorInjection:
    """Tests for error injection behavior."""

    def test_rate_limit_error(self, tmp_metrics_db):
        """100% rate limit returns 429."""
        config = ChaosLLMConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=ErrorInjectionConfig(rate_limit_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )
        assert response.status_code == 429
        assert "Retry-After" in response.headers

    def test_capacity_529_error(self, tmp_metrics_db):
        """100% capacity error returns 529."""
        config = ChaosLLMConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=ErrorInjectionConfig(capacity_529_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )
        assert response.status_code == 529
        assert "Retry-After" in response.headers

    def test_internal_error(self, tmp_metrics_db):
        """100% internal error returns 500."""
        config = ChaosLLMConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=ErrorInjectionConfig(internal_error_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )
        assert response.status_code == 500

    def test_service_unavailable_error(self, tmp_metrics_db):
        """100% service unavailable returns 503."""
        config = ChaosLLMConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=ErrorInjectionConfig(service_unavailable_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )
        assert response.status_code == 503

    def test_slow_response_returns_success(self, tmp_metrics_db):
        """Slow response delays but still returns a successful response."""
        config = ChaosLLMConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=ErrorInjectionConfig(
                slow_response_pct=100.0,
                slow_response_sec=(0, 0),
            ),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "chat.completion"


class TestMalformedResponses:
    """Tests for malformed response injection."""

    def test_invalid_json_response(self, tmp_metrics_db):
        """100% invalid JSON returns malformed JSON body."""
        config = ChaosLLMConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=ErrorInjectionConfig(invalid_json_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )
        assert response.status_code == 200

        # Should NOT be valid JSON
        with pytest.raises(json.JSONDecodeError):
            response.json()

    def test_empty_body_response(self, tmp_metrics_db):
        """100% empty body returns empty response."""
        config = ChaosLLMConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=ErrorInjectionConfig(empty_body_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )
        assert response.status_code == 200
        assert response.content == b""

    def test_missing_fields_response(self, tmp_metrics_db):
        """100% missing fields returns JSON without choices/usage."""
        config = ChaosLLMConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=ErrorInjectionConfig(missing_fields_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )
        assert response.status_code == 200
        data = response.json()

        # Should be missing choices or usage
        assert "choices" not in data or "usage" not in data

    def test_wrong_content_type_response(self, tmp_metrics_db):
        """100% wrong content type returns text/html."""
        config = ChaosLLMConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=ErrorInjectionConfig(wrong_content_type_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_truncated_response(self, tmp_metrics_db):
        """100% truncated returns cut-off JSON."""
        config = ChaosLLMConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=ErrorInjectionConfig(truncated_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )
        assert response.status_code == 200

        # Should NOT be valid JSON due to truncation
        with pytest.raises(json.JSONDecodeError):
            response.json()


class TestResponseModeOverrides:
    """Tests for per-request response mode overrides via headers."""

    def test_mode_override_header(self, tmp_metrics_db):
        """X-Fake-Response-Mode header overrides configured mode."""
        config = ChaosLLMConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            response=ResponseConfig(mode="random"),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Test message"}],
            },
            headers={"X-Fake-Response-Mode": "echo"},
        )
        assert response.status_code == 200
        data = response.json()

        # Echo mode should return the last user message
        content = data["choices"][0]["message"]["content"]
        assert content == "Echo: Test message"

    def test_template_override_header(self, tmp_metrics_db):
        """X-Fake-Template header overrides configured template."""
        config = ChaosLLMConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            response=ResponseConfig(mode="template"),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
            headers={
                "X-Fake-Response-Mode": "template",
                "X-Fake-Template": "Custom template: {{ model }}",
            },
        )
        assert response.status_code == 200
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        assert content == "Custom template: gpt-4"


class TestAdminConfigEndpoint:
    """Tests for /admin/config endpoint."""

    def test_get_config(self, client, admin_headers):
        """GET /admin/config returns current configuration."""
        response = client.get("/admin/config", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()

        # Should have all config sections
        assert "error_injection" in data
        assert "response" in data
        assert "latency" in data

    def test_post_config_updates_error_injection(self, client, admin_headers):
        """POST /admin/config updates error injection settings."""
        # First verify current state
        response = client.get("/admin/config", headers=admin_headers)
        original = response.json()
        assert original["error_injection"]["rate_limit_pct"] == 0.0

        # Update config
        response = client.post(
            "/admin/config",
            json={"error_injection": {"rate_limit_pct": 50.0}},
            headers=admin_headers,
        )
        assert response.status_code == 200

        # Verify update
        response = client.get("/admin/config", headers=admin_headers)
        updated = response.json()
        assert updated["error_injection"]["rate_limit_pct"] == 50.0


class TestAdminStatsEndpoint:
    """Tests for /admin/stats endpoint."""

    def test_get_stats_empty(self, client, admin_headers):
        """GET /admin/stats returns stats even when empty."""
        response = client.get("/admin/stats", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()

        assert "run_id" in data
        assert "started_utc" in data
        assert "total_requests" in data
        assert data["total_requests"] == 0

    def test_stats_increment_after_request(self, client, admin_headers):
        """Stats increment after successful request."""
        # Make a request
        client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )

        # Check stats
        response = client.get("/admin/stats", headers=admin_headers)
        data = response.json()
        assert data["total_requests"] == 1


class TestAdminResetEndpoint:
    """Tests for /admin/reset endpoint."""

    def test_reset_clears_stats(self, client, admin_headers):
        """POST /admin/reset clears metrics and starts new run."""
        # Make some requests
        for _ in range(3):
            client.post(
                "/v1/chat/completions",
                json={"model": "gpt-4", "messages": []},
            )

        # Verify we have stats
        response = client.get("/admin/stats", headers=admin_headers)
        assert response.json()["total_requests"] == 3

        # Get original run_id
        original_run_id = response.json()["run_id"]

        # Reset
        response = client.post("/admin/reset", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "reset"
        assert "new_run_id" in data
        assert data["new_run_id"] != original_run_id

        # Verify stats are cleared
        response = client.get("/admin/stats", headers=admin_headers)
        assert response.json()["total_requests"] == 0

    def test_reset_records_run_info(self, tmp_metrics_db):
        """POST /admin/reset persists run_info for new run."""
        config = ChaosLLMConfig(
            server=ServerConfig(admin_token=TEST_ADMIN_TOKEN),
            metrics=MetricsConfig(database=tmp_metrics_db),
            preset_name="gentle",
        )
        app = create_app(config)
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {TEST_ADMIN_TOKEN}"}

        # Initial run info should be recorded on startup
        stats = client.get("/admin/stats", headers=headers).json()
        run_id = stats["run_id"]
        with sqlite3.connect(tmp_metrics_db) as conn:
            row = conn.execute("SELECT run_id, preset_name, config_json FROM run_info").fetchone()
        assert row is not None
        assert row[0] == run_id
        assert row[1] == "gentle"
        assert row[2]

        # Reset should replace run_info with new run
        reset = client.post("/admin/reset", headers=headers).json()
        new_run_id = reset["new_run_id"]
        assert new_run_id != run_id
        with sqlite3.connect(tmp_metrics_db) as conn:
            rows = conn.execute("SELECT run_id, preset_name FROM run_info").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == new_run_id
        assert rows[0][1] == "gentle"


class TestMetricsRecording:
    """Tests for metrics recording behavior."""

    def test_successful_request_recorded(self, client, admin_headers):
        """Successful requests are recorded in metrics."""
        client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )

        response = client.get("/admin/stats", headers=admin_headers)
        data = response.json()
        assert data["total_requests"] == 1
        assert data["requests_by_outcome"].get("success", 0) == 1

    def test_error_request_recorded(self, tmp_metrics_db):
        """Error responses are recorded in metrics."""
        config = ChaosLLMConfig(
            server=ServerConfig(admin_token=TEST_ADMIN_TOKEN),
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=ErrorInjectionConfig(rate_limit_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app)
        headers = {"Authorization": f"Bearer {TEST_ADMIN_TOKEN}"}

        client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )

        response = client.get("/admin/stats", headers=headers)
        data = response.json()
        assert data["total_requests"] == 1
        # Should be recorded as error
        assert data["requests_by_outcome"].get("error_injected", 0) == 1


class TestLatencySimulation:
    """Tests for latency simulation."""

    def test_latency_applied_to_requests(self, tmp_metrics_db):
        """Latency is applied to successful requests."""
        config = ChaosLLMConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=100, jitter_ms=0),  # Fixed 100ms latency
        )
        app = create_app(config)
        client = TestClient(app)

        start = time.monotonic()
        client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )
        elapsed_ms = (time.monotonic() - start) * 1000

        # Should take at least 100ms (allowing some margin)
        assert elapsed_ms >= 90


class TestChaosLLMServer:
    """Tests for the ChaosLLMServer class."""

    def test_server_creation(self, config):
        """ChaosLLMServer can be created from config."""
        server = ChaosLLMServer(config)
        assert server.app is not None
        assert server.run_id is not None

    def test_server_reset(self, server):
        """Server reset creates new run_id."""
        original_run_id = server.run_id
        server.reset()
        assert server.run_id != original_run_id

    def test_get_stats(self, server):
        """Server get_stats returns metrics."""
        stats = server.get_stats()
        assert "run_id" in stats
        assert "total_requests" in stats

    def test_update_config(self, server):
        """Server can update error injection config."""
        original_rate = server._error_injector._config.rate_limit_pct
        assert original_rate == 0.0

        server.update_config({"error_injection": {"rate_limit_pct": 25.0}})
        assert server._error_injector._config.rate_limit_pct == 25.0


class TestErrorResponseBodies:
    """Tests for error response body format."""

    def test_rate_limit_error_body(self, tmp_metrics_db):
        """429 error has OpenAI-compatible error body."""
        config = ChaosLLMConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=ErrorInjectionConfig(rate_limit_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )
        data = response.json()

        assert "error" in data
        assert data["error"]["type"] == "rate_limit_error"
        assert "message" in data["error"]

    def test_server_error_body(self, tmp_metrics_db):
        """500 error has OpenAI-compatible error body."""
        config = ChaosLLMConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=ErrorInjectionConfig(internal_error_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )
        data = response.json()

        assert "error" in data
        assert data["error"]["type"] == "server_error"


class TestContentTypeHeaders:
    """Tests for Content-Type headers."""

    def test_success_response_content_type(self, client):
        """Successful response has application/json content type."""
        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )
        assert "application/json" in response.headers["content-type"]

    def test_error_response_content_type(self, tmp_metrics_db):
        """Error response has application/json content type."""
        config = ChaosLLMConfig(
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=ErrorInjectionConfig(rate_limit_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app)

        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )
        assert "application/json" in response.headers["content-type"]


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

    def test_run_info_excludes_admin_token(self, server: ChaosLLMServer, tmp_metrics_db: str) -> None:
        """Run info stored in DB does not include admin_token."""
        db = sqlite3.connect(tmp_metrics_db)
        rows = db.execute("SELECT config_json FROM run_info").fetchall()
        for row in rows:
            assert "admin_token" not in row[0]
            assert TEST_ADMIN_TOKEN not in row[0]
        db.close()


# =============================================================================
# Connection-Level Error Injection
# =============================================================================


class TestConnectionErrors:
    """Tests for connection-level error injection (timeout, reset, stall, failed)."""

    def test_connection_reset_raises(self, tmp_metrics_db):
        """100% connection_reset raises ConnectionResetError."""
        config = ChaosLLMConfig(
            server=ServerConfig(admin_token=TEST_ADMIN_TOKEN),
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=ErrorInjectionConfig(connection_reset_pct=100.0),
        )
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )
        assert response.status_code == 500

    def test_connection_reset_records_metrics(self, tmp_metrics_db):
        """Connection reset records metrics before raising."""
        config = ChaosLLMConfig(
            server=ServerConfig(admin_token=TEST_ADMIN_TOKEN),
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=ErrorInjectionConfig(connection_reset_pct=100.0),
        )
        server = ChaosLLMServer(config)
        client = TestClient(server.app, raise_server_exceptions=False)
        headers = {"Authorization": f"Bearer {TEST_ADMIN_TOKEN}"}

        client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )

        stats = client.get("/admin/stats", headers=headers).json()
        assert stats["total_requests"] == 1
        assert stats["requests_by_outcome"].get("error_injected", 0) == 1

    def test_connection_failed_raises(self, tmp_metrics_db):
        """100% connection_failed raises ConnectionResetError."""
        config = ChaosLLMConfig(
            server=ServerConfig(admin_token=TEST_ADMIN_TOKEN),
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=ErrorInjectionConfig(
                connection_failed_pct=100.0,
                connection_failed_lead_sec=(0, 0),
            ),
        )
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )
        assert response.status_code == 500

    def test_timeout_returns_504_or_raises(self, tmp_metrics_db):
        """100% timeout with zero delay produces 504 or connection reset."""
        config = ChaosLLMConfig(
            server=ServerConfig(admin_token=TEST_ADMIN_TOKEN),
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=ErrorInjectionConfig(
                timeout_pct=100.0,
                timeout_sec=(0, 0),
            ),
        )
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )
        # Timeout either returns 504 (50%) or drops connection (50% -> 500 in TestClient)
        assert response.status_code in {500, 504}

    def test_connection_stall_raises(self, tmp_metrics_db):
        """100% connection_stall with zero delays raises ConnectionResetError."""
        config = ChaosLLMConfig(
            server=ServerConfig(admin_token=TEST_ADMIN_TOKEN),
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=ErrorInjectionConfig(
                connection_stall_pct=100.0,
                connection_stall_start_sec=(0, 0),
                connection_stall_sec=(0, 0),
            ),
        )
        app = create_app(config)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )
        assert response.status_code == 500


# =============================================================================
# Malformed Request Handling
# =============================================================================


class TestMalformedRequestHandling:
    """Tests for invalid request body handling."""

    def test_non_json_body_returns_400(self, client):
        """POST /v1/chat/completions with non-JSON body returns 400."""
        response = client.post(
            "/v1/chat/completions",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["type"] == "invalid_request_error"

    def test_admin_config_post_invalid_values_returns_422(self, client, admin_headers):
        """POST /admin/config with invalid config values returns 422."""
        response = client.post(
            "/admin/config",
            json={"error_injection": {"rate_limit_pct": 200.0}},
            headers=admin_headers,
        )
        assert response.status_code == 422
        assert response.json()["error"]["type"] == "validation_error"

    def test_admin_config_post_non_json_returns_400(self, client, admin_headers):
        """POST /admin/config with non-JSON body returns 400."""
        response = client.post(
            "/admin/config",
            content=b"not json",
            headers={**admin_headers, "content-type": "application/json"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["type"] == "invalid_request_error"


# =============================================================================
# Best-Effort Metrics Recording
# =============================================================================


class TestBestEffortMetrics:
    """Tests that metrics recording failures don't replace chaos responses."""

    def test_metrics_failure_does_not_replace_success_response(self, tmp_metrics_db):
        """A broken metrics store doesn't prevent successful chaos responses."""
        config = ChaosLLMConfig(
            server=ServerConfig(admin_token=TEST_ADMIN_TOKEN),
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
        )
        server = ChaosLLMServer(config)
        client = TestClient(server.app)

        # Make a successful request first to confirm the server works
        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 200

        # Now close the metrics store to simulate a database failure
        server._metrics_recorder._store.close()

        # The next request should still succeed (metrics failure is swallowed)
        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 200
        assert "choices" in response.json()

    def test_metrics_failure_does_not_replace_error_response(self, tmp_metrics_db):
        """A broken metrics store doesn't prevent injected error responses."""
        config = ChaosLLMConfig(
            server=ServerConfig(admin_token=TEST_ADMIN_TOKEN),
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
            error_injection=ErrorInjectionConfig(rate_limit_pct=100.0),
        )
        server = ChaosLLMServer(config)
        client = TestClient(server.app)

        # Close metrics store to simulate failure
        server._metrics_recorder._store.close()

        # Error injection should still return the intended 429
        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": []},
        )
        assert response.status_code == 429


# =============================================================================
# Concurrent Config Updates
# =============================================================================


class TestConcurrentConfigUpdates:
    """Tests that concurrent config updates don't corrupt request handling."""

    def test_config_update_during_requests(self, tmp_metrics_db):
        """Requests use a consistent config snapshot even during updates."""
        import threading

        config = ChaosLLMConfig(
            server=ServerConfig(admin_token=TEST_ADMIN_TOKEN),
            metrics=MetricsConfig(database=tmp_metrics_db),
            latency=LatencyConfig(base_ms=0, jitter_ms=0),
        )
        server = ChaosLLMServer(config)
        client = TestClient(server.app)
        errors: list[str] = []

        def make_requests() -> None:
            for _ in range(20):
                try:
                    resp = client.post(
                        "/v1/chat/completions",
                        json={"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]},
                    )
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
