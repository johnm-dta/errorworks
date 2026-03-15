"""Unit tests for shared admin endpoint logic.

Tests check_admin_auth, handle_admin_config, handle_admin_stats,
handle_admin_reset, handle_admin_export, and ChaosServer protocol
conformance — all in isolation from specific chaos plugins.
"""

from __future__ import annotations

import sqlite3
from typing import Any
from unittest.mock import MagicMock

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from errorworks.engine.admin import (
    ChaosServer,
    handle_admin_config,
    handle_admin_export,
    handle_admin_reset,
    handle_admin_stats,
)

# =============================================================================
# Helpers
# =============================================================================


def _make_mock_server(
    *,
    token: str = "test-token",
    config: dict[str, Any] | None = None,
    stats: dict[str, Any] | None = None,
    export: dict[str, Any] | None = None,
    run_id: str = "run-001",
) -> MagicMock:
    """Create a mock that satisfies the ChaosServer protocol."""
    server = MagicMock()
    server.get_admin_token.return_value = token
    server.get_current_config.return_value = config or {"mode": "random"}
    server.get_stats.return_value = stats or {"total_requests": 0}
    server.export_metrics.return_value = export or {"requests": []}
    server.reset.return_value = run_id
    return server


def _make_app(server: MagicMock) -> TestClient:
    """Build a minimal Starlette app wired to admin handlers for testing."""
    from starlette.applications import Starlette
    from starlette.routing import Route

    async def config_handler(r: Request) -> JSONResponse:
        return await handle_admin_config(r, server)

    async def stats_handler(r: Request) -> JSONResponse:
        return await handle_admin_stats(r, server)

    async def reset_handler(r: Request) -> JSONResponse:
        return await handle_admin_reset(r, server)

    async def export_handler(r: Request) -> JSONResponse:
        return await handle_admin_export(r, server)

    app = Starlette(
        routes=[
            Route("/admin/config", config_handler, methods=["GET", "POST"]),
            Route("/admin/stats", stats_handler, methods=["GET"]),
            Route("/admin/reset", reset_handler, methods=["POST"]),
            Route("/admin/export", export_handler, methods=["GET"]),
        ]
    )
    return TestClient(app)


# =============================================================================
# Protocol Conformance
# =============================================================================


class TestChaosServerProtocol:
    """ChaosServer protocol structural checks."""

    def test_protocol_defines_expected_methods(self) -> None:
        """ChaosServer protocol defines the expected method set."""
        import inspect

        protocol_methods = {name for name, _ in inspect.getmembers(ChaosServer, predicate=inspect.isfunction) if not name.startswith("__")}
        expected = {"get_admin_token", "get_current_config", "update_config", "reset", "export_metrics", "get_stats"}
        assert protocol_methods == expected

    def test_real_llm_server_satisfies_protocol(self) -> None:
        """ChaosLLMServer satisfies the ChaosServer protocol."""
        from errorworks.llm.server import ChaosLLMServer

        assert issubclass(ChaosLLMServer, ChaosServer)

    def test_real_web_server_satisfies_protocol(self) -> None:
        """ChaosWebServer satisfies the ChaosServer protocol."""
        from errorworks.web.server import ChaosWebServer

        assert issubclass(ChaosWebServer, ChaosServer)


# =============================================================================
# check_admin_auth
# =============================================================================


class TestCheckAdminAuth:
    """Tests for the check_admin_auth helper."""

    def test_valid_token_returns_none(self) -> None:
        """Correct Bearer token passes authentication."""
        client = _make_app(_make_mock_server(token="secret"))
        resp = client.get("/admin/stats", headers={"Authorization": "Bearer secret"})
        assert resp.status_code == 200

    def test_missing_header_returns_401(self) -> None:
        """Missing Authorization header returns 401."""
        client = _make_app(_make_mock_server())
        resp = client.get("/admin/stats")
        assert resp.status_code == 401
        assert resp.json()["error"]["type"] == "authentication_error"

    def test_wrong_prefix_returns_401(self) -> None:
        """Non-Bearer authorization returns 401."""
        client = _make_app(_make_mock_server())
        resp = client.get("/admin/stats", headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert resp.status_code == 401

    def test_wrong_token_returns_403(self) -> None:
        """Wrong token returns 403."""
        client = _make_app(_make_mock_server(token="correct"))
        resp = client.get("/admin/stats", headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 403
        assert resp.json()["error"]["type"] == "authorization_error"

    def test_empty_bearer_returns_403(self) -> None:
        """Empty Bearer value returns 403."""
        client = _make_app(_make_mock_server(token="secret"))
        resp = client.get("/admin/stats", headers={"Authorization": "Bearer "})
        assert resp.status_code == 403


# =============================================================================
# handle_admin_config
# =============================================================================


class TestHandleAdminConfig:
    """Tests for GET/POST /admin/config."""

    def _headers(self, token: str = "test-token") -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_get_returns_current_config(self) -> None:
        """GET returns the server's current config dict."""
        server = _make_mock_server(config={"mode": "template"})
        client = _make_app(server)
        resp = client.get("/admin/config", headers=self._headers())
        assert resp.status_code == 200
        assert resp.json() == {"mode": "template"}

    def test_post_valid_update(self) -> None:
        """POST with valid JSON calls update_config and returns updated config."""
        server = _make_mock_server()
        client = _make_app(server)
        resp = client.post("/admin/config", json={"mode": "echo"}, headers=self._headers())
        assert resp.status_code == 200
        assert resp.json()["status"] == "updated"
        server.update_config.assert_called_once_with({"mode": "echo"})

    def test_post_invalid_json_returns_400(self) -> None:
        """POST with malformed JSON returns 400."""
        server = _make_mock_server()
        client = _make_app(server)
        resp = client.post(
            "/admin/config",
            content=b"not json",
            headers={**self._headers(), "content-type": "application/json"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["type"] == "invalid_request_error"

    def test_post_validation_error_returns_422(self) -> None:
        """POST that triggers a ValidationError returns 422."""
        server = _make_mock_server()
        server.update_config.side_effect = ValueError("invalid mode")
        client = _make_app(server)
        resp = client.post("/admin/config", json={"mode": "bogus"}, headers=self._headers())
        assert resp.status_code == 422
        assert "invalid mode" in resp.json()["error"]["message"]

    def test_post_list_body_returns_400(self) -> None:
        """POST with a JSON array instead of object returns 400."""
        server = _make_mock_server()
        client = _make_app(server)
        resp = client.post("/admin/config", json=[1, 2, 3], headers=self._headers())
        assert resp.status_code == 400
        assert resp.json()["error"]["type"] == "invalid_request_error"
        assert "JSON object" in resp.json()["error"]["message"]
        server.update_config.assert_not_called()

    def test_post_string_body_returns_400(self) -> None:
        """POST with a JSON string instead of object returns 400."""
        server = _make_mock_server()
        client = _make_app(server)
        resp = client.post("/admin/config", json="hello", headers=self._headers())
        assert resp.status_code == 400
        assert resp.json()["error"]["type"] == "invalid_request_error"
        server.update_config.assert_not_called()


# =============================================================================
# handle_admin_stats
# =============================================================================


class TestHandleAdminStats:
    """Tests for GET /admin/stats."""

    def _headers(self, token: str = "test-token") -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_returns_stats(self) -> None:
        """Successful stats call returns server stats as JSON."""
        server = _make_mock_server(stats={"total_requests": 42})
        client = _make_app(server)
        resp = client.get("/admin/stats", headers=self._headers())
        assert resp.status_code == 200
        assert resp.json() == {"total_requests": 42}

    def test_sqlite_error_returns_503(self) -> None:
        """sqlite3.Error from get_stats returns 503 with structured error."""
        server = _make_mock_server()
        server.get_stats.side_effect = sqlite3.OperationalError("database is locked")
        client = _make_app(server)
        resp = client.get("/admin/stats", headers=self._headers())
        assert resp.status_code == 503
        assert resp.json()["error"]["type"] == "database_error"


# =============================================================================
# handle_admin_reset
# =============================================================================


class TestHandleAdminReset:
    """Tests for POST /admin/reset."""

    def _headers(self, token: str = "test-token") -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_reset_returns_new_run_id(self) -> None:
        """Successful reset returns the new run_id."""
        server = _make_mock_server(run_id="run-new")
        client = _make_app(server)
        resp = client.post("/admin/reset", headers=self._headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "reset"
        assert body["new_run_id"] == "run-new"
        server.reset.assert_called_once()

    def test_sqlite_error_returns_503(self) -> None:
        """sqlite3.Error from reset returns 503 with structured error."""
        server = _make_mock_server()
        server.reset.side_effect = sqlite3.OperationalError("disk I/O error")
        client = _make_app(server)
        resp = client.post("/admin/reset", headers=self._headers())
        assert resp.status_code == 503
        assert resp.json()["error"]["type"] == "database_error"
        assert "disk I/O error" in resp.json()["error"]["message"]

    def test_auth_required(self) -> None:
        """Reset without auth returns 401."""
        client = _make_app(_make_mock_server())
        resp = client.post("/admin/reset")
        assert resp.status_code == 401


# =============================================================================
# handle_admin_export
# =============================================================================


class TestHandleAdminExport:
    """Tests for GET /admin/export."""

    def _headers(self, token: str = "test-token") -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_returns_export_data(self) -> None:
        """Successful export returns metrics data."""
        server = _make_mock_server(export={"requests": [{"id": 1}]})
        client = _make_app(server)
        resp = client.get("/admin/export", headers=self._headers())
        assert resp.status_code == 200
        assert resp.json() == {"requests": [{"id": 1}]}

    def test_sqlite_error_returns_503(self) -> None:
        """sqlite3.Error from export_metrics returns 503."""
        server = _make_mock_server()
        server.export_metrics.side_effect = sqlite3.DatabaseError("corrupted")
        client = _make_app(server)
        resp = client.get("/admin/export", headers=self._headers())
        assert resp.status_code == 503
        assert resp.json()["error"]["type"] == "database_error"
