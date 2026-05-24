"""Shared admin endpoint logic for chaos servers.

Provides free functions for admin authentication and endpoint handling,
composed by both ChaosLLM and ChaosWeb servers via the ChaosServer protocol.
"""

from __future__ import annotations

import hmac
import json
import sqlite3
from typing import Any, Protocol, runtime_checkable

import jinja2
import pydantic
import structlog
from starlette.requests import Request
from starlette.responses import JSONResponse

from errorworks.engine.request_body import RequestBodyTooLarge, read_limited_json

logger = structlog.get_logger(__name__)


@runtime_checkable
class ChaosServer(Protocol):
    """Minimal interface for admin endpoint handlers.

    Both ChaosLLMServer and ChaosWebServer satisfy this protocol.
    """

    def get_admin_token(self) -> str: ...
    def get_current_config(self) -> dict[str, Any]: ...
    def update_config(self, updates: dict[str, Any]) -> None: ...
    def reset(self) -> str: ...
    def export_metrics(self) -> dict[str, Any]: ...
    def get_stats(self) -> dict[str, Any]: ...


def check_admin_auth(request: Request, token: str) -> JSONResponse | None:
    """Check admin authentication.

    Returns None if auth passes, or a 401/403 JSONResponse if it fails.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(
            {"error": {"type": "authentication_error", "message": "Missing Authorization: Bearer <token> header"}},
            status_code=401,
        )
    try:
        valid_token = hmac.compare_digest(auth_header[7:], token)
    except TypeError:
        valid_token = False
    if not valid_token:
        return JSONResponse(
            {"error": {"type": "authorization_error", "message": "Invalid admin token"}},
            status_code=403,
        )
    return None


async def handle_admin_config(request: Request, server: ChaosServer) -> JSONResponse:
    """Handle GET/POST /admin/config."""
    if (denied := check_admin_auth(request, server.get_admin_token())) is not None:
        return denied
    if request.method == "GET":
        return JSONResponse(server.get_current_config())
    try:
        body = await read_limited_json(request)
    except RequestBodyTooLarge:
        return JSONResponse(
            {"error": {"type": "request_too_large", "message": "Request body exceeds maximum size"}},
            status_code=413,
        )
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return JSONResponse(
            {"error": {"type": "invalid_request_error", "message": "Request body must be valid JSON"}},
            status_code=400,
        )
    if not isinstance(body, dict):
        return JSONResponse(
            {"error": {"type": "invalid_request_error", "message": "Request body must be a JSON object"}},
            status_code=400,
        )
    # Validate shape before handing to update_config: each top-level key must be
    # a known config section (matches a key in get_current_config()) and its
    # value must be a dict. Without this, an unknown key silently no-ops and
    # a null section value raises an uncaught AttributeError inside deep_merge.
    current_config = server.get_current_config()
    allowed_sections = set(current_config.keys())
    for section, value in body.items():
        if section not in allowed_sections:
            return JSONResponse(
                {
                    "error": {
                        "type": "invalid_request_error",
                        "message": f"Unknown config section: {section!r}. Allowed: {sorted(allowed_sections)}",
                    }
                },
                status_code=400,
            )
        if not isinstance(value, dict):
            return JSONResponse(
                {
                    "error": {
                        "type": "invalid_request_error",
                        "message": f"Config section {section!r} must be a JSON object",
                    }
                },
                status_code=400,
            )
    try:
        server.update_config(body)
    except (FileNotFoundError, ValueError, TypeError, jinja2.TemplateError, pydantic.ValidationError) as e:
        return JSONResponse(
            {"error": {"type": "validation_error", "message": str(e)}},
            status_code=422,
        )
    return JSONResponse({"status": "updated", "config": server.get_current_config()})


async def handle_admin_stats(request: Request, server: ChaosServer) -> JSONResponse:
    """Handle GET /admin/stats."""
    if (denied := check_admin_auth(request, server.get_admin_token())) is not None:
        return denied
    try:
        return JSONResponse(server.get_stats())
    except sqlite3.Error:
        logger.exception("admin_stats_database_error")
        return JSONResponse(
            {"error": {"type": "database_error", "message": "Failed to retrieve stats due to a database error"}},
            status_code=503,
        )


async def handle_admin_reset(request: Request, server: ChaosServer) -> JSONResponse:
    """Handle POST /admin/reset."""
    if (denied := check_admin_auth(request, server.get_admin_token())) is not None:
        return denied
    try:
        new_run_id = server.reset()
    except sqlite3.Error:
        logger.exception("admin_reset_database_error")
        return JSONResponse(
            {"error": {"type": "database_error", "message": "Failed to reset metrics due to a database error"}},
            status_code=503,
        )
    return JSONResponse({"status": "reset", "new_run_id": new_run_id})


async def handle_admin_export(request: Request, server: ChaosServer) -> JSONResponse:
    """Handle GET /admin/export."""
    if (denied := check_admin_auth(request, server.get_admin_token())) is not None:
        return denied
    try:
        return JSONResponse(server.export_metrics())
    except sqlite3.Error:
        logger.exception("admin_export_database_error")
        return JSONResponse(
            {"error": {"type": "database_error", "message": "Failed to export metrics due to a database error"}},
            status_code=503,
        )
