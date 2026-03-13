"""Starlette ASGI application for ChaosWeb fake web server.

Provides multi-path HTTP serving with configurable error injection,
content malformations, redirect loops, and SSRF injection for testing
web scraping pipeline resilience.

Usage:
    from errorworks.web.server import create_app, ChaosWebServer
    from errorworks.web.config import ChaosWebConfig

    config = ChaosWebConfig()
    app = create_app(config)

    # Or use the server class for more control
    server = ChaosWebServer(config)
    app = server.app
"""

import asyncio
import hmac
import json
import sqlite3
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import structlog
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from errorworks.engine.config_loader import deep_merge
from errorworks.engine.latency import LatencySimulator
from errorworks.engine.types import LatencyConfig
from errorworks.web.config import (
    ChaosWebConfig,
    WebContentConfig,
    WebErrorInjectionConfig,
)
from errorworks.web.content_generator import (
    ContentGenerator,
    generate_wrong_content_type,
    inject_charset_confusion,
    inject_encoding_mismatch,
    inject_invalid_encoding,
    inject_malformed_meta,
    truncate_html,
)
from errorworks.web.error_injector import (
    WebErrorCategory,
    WebErrorDecision,
    WebErrorInjector,
)
from errorworks.web.metrics import WebMetricsRecorder

logger = structlog.get_logger(__name__)

# Web error type to human-readable message mapping.
_WEB_ERROR_MESSAGES: dict[str, str] = {
    "rate_limit": "429 Too Many Requests — You are being rate limited.",
    "forbidden": "403 Forbidden — Access denied.",
    "not_found": "404 Not Found — The requested page does not exist.",
    "gone": "410 Gone — This resource has been permanently removed.",
    "payment_required": "402 Payment Required — Premium content requires a subscription.",
    "unavailable_for_legal": "451 Unavailable For Legal Reasons — This content is not available in your region.",
    "service_unavailable": "503 Service Unavailable — Please try again later.",
    "bad_gateway": "502 Bad Gateway — The upstream server returned an invalid response.",
    "gateway_timeout": "504 Gateway Timeout — The upstream server did not respond in time.",
    "internal_error": "500 Internal Server Error — Something went wrong on our end.",
}


class ChaosWebServer:
    """Main ChaosWeb server class.

    Encapsulates all server state and provides methods for runtime
    configuration updates and metrics access.
    """

    def __init__(self, config: ChaosWebConfig) -> None:
        self._config = config
        self._config_lock = threading.Lock()
        self._error_injector = WebErrorInjector(config.error_injection)
        self._content_generator = ContentGenerator(config.content)
        self._latency_simulator = LatencySimulator(config.latency)
        self._metrics_recorder = WebMetricsRecorder(config.metrics)
        self._record_run_info()
        self._app = self._create_app()

    def _create_app(self) -> Starlette:
        """Create the Starlette application with all routes."""
        routes = [
            Route("/health", self._health_endpoint, methods=["GET"]),
            # Admin endpoints
            Route("/admin/config", self._admin_config_endpoint, methods=["GET", "POST"]),
            Route("/admin/stats", self._admin_stats_endpoint, methods=["GET"]),
            Route("/admin/reset", self._admin_reset_endpoint, methods=["POST"]),
            Route("/admin/export", self._admin_export_endpoint, methods=["GET"]),
            # Redirect loop handler — must be before catch-all
            Route("/redirect", self._redirect_hop_endpoint, methods=["GET"]),
            # Catch-all content route — must be last
            Route("/{path:path}", self._page_endpoint, methods=["GET"]),
        ]
        return Starlette(debug=False, routes=routes)

    @property
    def app(self) -> Starlette:
        """Get the Starlette ASGI application."""
        return self._app

    @property
    def run_id(self) -> str:
        """Get the current run ID."""
        return self._metrics_recorder.run_id

    def get_stats(self) -> dict[str, Any]:
        """Get current metrics statistics."""
        return self._metrics_recorder.get_stats()

    def reset(self) -> str:
        """Reset metrics and start a new run."""
        self._error_injector.reset()
        self._content_generator.reset()
        self._metrics_recorder.reset()
        self._record_run_info()
        return self._metrics_recorder.run_id

    def export_metrics(self) -> dict[str, Any]:
        """Export raw metrics data."""
        data = self._metrics_recorder.export_data()
        data["config"] = {
            "server": self._config.server.model_dump(exclude={"admin_token"}),
            "metrics": self._config.metrics.model_dump(),
            **self._get_current_config(),
        }
        return data

    def update_config(self, updates: dict[str, Any]) -> None:
        """Update server configuration at runtime.

        Uses deep_merge so partial nested updates preserve existing fields.
        Components are built outside the lock (validation may be expensive),
        then swapped atomically under _config_lock to prevent concurrent
        request handlers from seeing a half-updated configuration.
        """
        # Build new components outside the lock
        new_error: WebErrorInjector | None = None
        new_content: ContentGenerator | None = None
        new_latency: LatencySimulator | None = None

        if "error_injection" in updates:
            current = self._error_injector.config.model_dump()
            merged = deep_merge(current, updates["error_injection"])
            new_error = WebErrorInjector(WebErrorInjectionConfig(**merged))

        if "content" in updates:
            current = self._content_generator.config.model_dump()
            merged = deep_merge(current, updates["content"])
            new_content = ContentGenerator(WebContentConfig(**merged))

        if "latency" in updates:
            current = self._latency_simulator.config.model_dump()
            merged = deep_merge(current, updates["latency"])
            new_latency = LatencySimulator(LatencyConfig(**merged))

        # Swap atomically under lock
        with self._config_lock:
            if new_error is not None:
                self._error_injector = new_error
            if new_content is not None:
                self._content_generator = new_content
            if new_latency is not None:
                self._latency_simulator = new_latency

    def _get_current_config(self) -> dict[str, Any]:
        """Get current configuration as dict."""
        with self._config_lock:
            return {
                "error_injection": self._error_injector.config.model_dump(),
                "content": self._content_generator.config.model_dump(),
                "latency": self._latency_simulator.config.model_dump(),
            }

    def _record_run_info(self) -> None:
        """Persist run info for the current metrics run."""
        config_json = json.dumps(
            {
                "server": self._config.server.model_dump(exclude={"admin_token"}),
                "metrics": self._config.metrics.model_dump(),
                **self._get_current_config(),
            },
            sort_keys=True,
        )
        self._metrics_recorder.save_run_info(
            config_json=config_json,
            preset_name=self._config.preset_name,
        )

    # === Endpoint handlers ===

    async def _health_endpoint(self, request: Request) -> JSONResponse:
        """Handle GET /health."""
        return JSONResponse(
            {
                "status": "healthy",
                "run_id": self._metrics_recorder.run_id,
                "started_utc": self._metrics_recorder.started_utc,
                "in_burst": self._error_injector.is_in_burst(),
            }
        )

    def _check_admin_auth(self, request: Request) -> JSONResponse | None:
        """Check admin authentication.

        Returns None if auth passes, or a 401/403 JSONResponse if it fails.
        """
        token = self._config.server.admin_token
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                {"error": {"type": "authentication_error", "message": "Missing Authorization: Bearer <token> header"}},
                status_code=401,
            )
        if not hmac.compare_digest(auth_header[7:], token):
            return JSONResponse(
                {"error": {"type": "authorization_error", "message": "Invalid admin token"}},
                status_code=403,
            )
        return None

    async def _admin_config_endpoint(self, request: Request) -> JSONResponse:
        """Handle GET/POST /admin/config."""
        if (denied := self._check_admin_auth(request)) is not None:
            return denied
        if request.method == "GET":
            return JSONResponse(self._get_current_config())
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
            return JSONResponse(
                {"error": {"type": "invalid_request_error", "message": "Request body must be valid JSON"}},
                status_code=400,
            )
        try:
            self.update_config(body)
        except (ValueError, TypeError) as e:
            return JSONResponse(
                {"error": {"type": "validation_error", "message": str(e)}},
                status_code=422,
            )
        return JSONResponse({"status": "updated", "config": self._get_current_config()})

    async def _admin_stats_endpoint(self, request: Request) -> JSONResponse:
        """Handle GET /admin/stats."""
        if (denied := self._check_admin_auth(request)) is not None:
            return denied
        return JSONResponse(self._metrics_recorder.get_stats())

    async def _admin_reset_endpoint(self, request: Request) -> JSONResponse:
        """Handle POST /admin/reset."""
        if (denied := self._check_admin_auth(request)) is not None:
            return denied
        new_run_id = self.reset()
        return JSONResponse({"status": "reset", "new_run_id": new_run_id})

    async def _admin_export_endpoint(self, request: Request) -> JSONResponse:
        """Handle GET /admin/export."""
        if (denied := self._check_admin_auth(request)) is not None:
            return denied
        return JSONResponse(self.export_metrics())

    async def _redirect_hop_endpoint(self, request: Request) -> Response:
        """Handle GET /redirect — enforce redirect loop hop limits.

        Each hop increments the counter until max is reached, then terminates
        with a 200 response. Without this handler, redirect URLs would fall
        through to the catch-all route and the hop/max params would be ignored.
        """
        try:
            hop = max(1, int(request.query_params.get("hop", "1")))
            max_hops = max(1, int(request.query_params.get("max", "10")))
        except (ValueError, OverflowError):
            return HTMLResponse("<html><body><p>Invalid redirect parameters.</p></body></html>", status_code=400)

        # Snapshot components under lock (config snapshot pattern)
        with self._config_lock:
            error_injector = self._error_injector
            latency_simulator = self._latency_simulator

        # Cap to the configured maximum to prevent resource exhaustion
        config_max = error_injector.config.max_redirect_loop_hops
        max_hops = min(max_hops, config_max)
        target = request.query_params.get("target", "/")

        request_id = str(uuid.uuid4())
        timestamp_utc = datetime.now(UTC).isoformat()
        start_time = time.monotonic()

        # Simulate latency on each hop (same as initial redirect)
        delay = latency_simulator.simulate()
        if delay > 0:
            await asyncio.sleep(delay)

        elapsed_ms = (time.monotonic() - start_time) * 1000

        if hop < max_hops:
            # Continue the redirect chain
            next_url = f"/redirect?hop={hop + 1}&max={max_hops}&target={quote(target, safe='/')}"
            self._record_request(
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                path="/redirect",
                outcome="error_redirect",
                status_code=301,
                error_type="redirect_loop",
                injection_type="redirect_loop",
                latency_ms=elapsed_ms,
                redirect_hops=hop,
            )
            return Response(
                status_code=301,
                headers={"Location": next_url},
            )

        # Loop terminated — return 200 at final hop
        self._record_request(
            request_id=request_id,
            timestamp_utc=timestamp_utc,
            path="/redirect",
            outcome="redirect_loop_terminated",
            status_code=200,
            error_type="redirect_loop",
            injection_type="redirect_loop",
            latency_ms=elapsed_ms,
            redirect_hops=hop,
        )
        return HTMLResponse(f"<html><body><p>Redirect loop terminated after {hop} hops.</p></body></html>")

    async def _page_endpoint(self, request: Request) -> Response:
        """Handle GET /{path} — main content serving with error injection.

        Request flow:
        1. Extract per-request header overrides (if config allows)
        2. Error injector decides outcome
        3. Route to appropriate handler: redirect, connection error, HTTP error,
           malformed content, or success
        4. Apply latency simulation
        5. Record metrics
        6. Return response
        """
        request_id = str(uuid.uuid4())
        start_time = time.monotonic()
        timestamp_utc = datetime.now(UTC).isoformat()
        path = "/" + request.path_params["path"]

        # Snapshot components under lock so a concurrent update_config()
        # cannot produce a half-updated view during request processing.
        with self._config_lock:
            error_injector = self._error_injector
            content_generator = self._content_generator
            latency_simulator = self._latency_simulator

        # Extract header overrides if allowed
        mode_override: str | None = None
        if content_generator.config.allow_header_overrides:
            mode_override = request.headers.get("X-Fake-Content-Mode")

        # Capture request headers for content generation (template/echo modes)
        request_headers = dict(request.headers)

        # Error injector decides
        decision = error_injector.decide()

        if decision.error_type is not None:
            # Handle injected error
            if decision.category == WebErrorCategory.REDIRECT:
                return await self._handle_redirect(
                    decision=decision,
                    request_id=request_id,
                    timestamp_utc=timestamp_utc,
                    path=path,
                    start_time=start_time,
                    latency_simulator=latency_simulator,
                )
            if decision.category == WebErrorCategory.CONNECTION:
                if decision.error_type == "slow_response":
                    return await self._handle_slow_response(
                        decision=decision,
                        request_id=request_id,
                        timestamp_utc=timestamp_utc,
                        path=path,
                        mode_override=mode_override,
                        headers=request_headers,
                        start_time=start_time,
                        content_generator=content_generator,
                        latency_simulator=latency_simulator,
                    )
                return await self._handle_connection_error(
                    decision=decision,
                    request_id=request_id,
                    timestamp_utc=timestamp_utc,
                    path=path,
                    mode_override=mode_override,
                    headers=request_headers,
                    start_time=start_time,
                    content_generator=content_generator,
                )
            if decision.category == WebErrorCategory.MALFORMED:
                return await self._handle_malformed_content(
                    decision=decision,
                    request_id=request_id,
                    timestamp_utc=timestamp_utc,
                    path=path,
                    mode_override=mode_override,
                    headers=request_headers,
                    start_time=start_time,
                    content_generator=content_generator,
                    latency_simulator=latency_simulator,
                )
            # HTTP-level error
            return await self._handle_http_error(
                decision=decision,
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                path=path,
                start_time=start_time,
                latency_simulator=latency_simulator,
            )

        # Success — generate HTML page
        return await self._handle_success(
            request_id=request_id,
            timestamp_utc=timestamp_utc,
            path=path,
            mode_override=mode_override,
            headers=request_headers,
            start_time=start_time,
            content_generator=content_generator,
            latency_simulator=latency_simulator,
        )

    # === Error Handlers ===

    async def _handle_redirect(
        self,
        decision: WebErrorDecision,
        request_id: str,
        timestamp_utc: str,
        path: str,
        start_time: float,
        latency_simulator: LatencySimulator,
    ) -> Response:
        """Handle redirect injection (loops and SSRF)."""
        # Add base latency before redirect
        delay = latency_simulator.simulate()
        if delay > 0:
            await asyncio.sleep(delay)

        elapsed_ms = (time.monotonic() - start_time) * 1000

        if decision.error_type == "ssrf_redirect":
            # Redirect to private IP (SSRF injection)
            target = decision.redirect_target
            self._record_request(
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                path=path,
                outcome="error_redirect",
                status_code=301,
                error_type="ssrf_redirect",
                injection_type="ssrf_redirect",
                latency_ms=elapsed_ms,
                redirect_target=target,
            )
            return Response(
                status_code=301,
                headers={"Location": target or "http://169.254.169.254/"},
            )

        # Redirect loop — stateless query-parameter approach
        hops = decision.redirect_hops or 10
        self._record_request(
            request_id=request_id,
            timestamp_utc=timestamp_utc,
            path=path,
            outcome="error_redirect",
            status_code=301,
            error_type="redirect_loop",
            injection_type="redirect_loop",
            latency_ms=elapsed_ms,
            redirect_hops=hops,
        )
        # Build redirect URL with hop counter
        redirect_url = f"/redirect?hop=1&max={hops}&target={path}"
        return Response(
            status_code=301,
            headers={"Location": redirect_url},
        )

    async def _handle_connection_error(
        self,
        decision: WebErrorDecision,
        request_id: str,
        timestamp_utc: str,
        path: str,
        mode_override: str | None,
        headers: dict[str, str] | None,
        start_time: float,
        content_generator: ContentGenerator,
    ) -> Response:
        """Handle connection-level errors (timeout, reset, stall, incomplete)."""
        error_type = decision.error_type

        if error_type == "timeout":
            delay = decision.delay_sec if decision.delay_sec is not None else 60.0
            await asyncio.sleep(delay)
            elapsed_ms = (time.monotonic() - start_time) * 1000
            self._record_request(
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                path=path,
                outcome="error_injected",
                status_code=504,
                error_type="timeout",
                injection_type="timeout",
                latency_ms=elapsed_ms,
                injected_delay_ms=delay * 1000,
            )
            return HTMLResponse(
                "<html><body><h1>504 Gateway Timeout</h1></body></html>",
                status_code=504,
            )

        if error_type == "connection_reset":
            elapsed_ms = (time.monotonic() - start_time) * 1000
            self._record_request(
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                path=path,
                outcome="error_injected",
                error_type="connection_reset",
                injection_type="connection_reset",
                latency_ms=elapsed_ms,
            )

            async def _reset_body() -> Any:
                yield b""
                raise ConnectionResetError("Connection reset by server")

            return _StreamingDisconnect(content=_reset_body(), status_code=200)

        if error_type == "connection_stall":
            start_delay = decision.start_delay_sec if decision.start_delay_sec is not None else 0.0
            stall_delay = decision.delay_sec if decision.delay_sec is not None else 60.0
            if start_delay > 0:
                await asyncio.sleep(start_delay)
            await asyncio.sleep(stall_delay)
            elapsed_ms = (time.monotonic() - start_time) * 1000
            injected_ms = (start_delay + stall_delay) * 1000
            self._record_request(
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                path=path,
                outcome="error_injected",
                error_type="connection_stall",
                injection_type="connection_stall",
                latency_ms=elapsed_ms,
                injected_delay_ms=injected_ms if injected_ms > 0 else None,
            )

            async def _stall_body() -> Any:
                yield b""
                raise ConnectionResetError("Connection stalled and was closed by server")

            return _StreamingDisconnect(content=_stall_body(), status_code=200)

        if error_type == "incomplete_response":
            # Send headers + partial body, then close connection
            incomplete_bytes = decision.incomplete_bytes if decision.incomplete_bytes is not None else 500
            # Generate full HTML then truncate
            web_response = content_generator.generate(
                path=path,
                headers=headers,
                mode_override=mode_override,
            )
            content = web_response.content
            if isinstance(content, str):
                content = content.encode("utf-8")
            partial = content[:incomplete_bytes]
            elapsed_ms = (time.monotonic() - start_time) * 1000
            self._record_request(
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                path=path,
                outcome="error_injected",
                status_code=200,
                error_type="incomplete_response",
                injection_type="incomplete_response",
                latency_ms=elapsed_ms,
                content_type_served=web_response.content_type,
            )

            async def _stream_partial() -> Any:
                yield partial
                raise ConnectionResetError("Connection closed mid-response")

            return _StreamingDisconnect(
                content=_stream_partial(),
                status_code=200,
                media_type=web_response.content_type,
            )

        raise ValueError(f"Unknown connection error type: {error_type}")

    async def _handle_http_error(
        self,
        decision: WebErrorDecision,
        request_id: str,
        timestamp_utc: str,
        path: str,
        start_time: float,
        latency_simulator: LatencySimulator,
    ) -> Response:
        """Handle HTTP-level errors (4xx, 5xx)."""
        status_code = decision.status_code
        error_type = decision.error_type

        if status_code is None or error_type is None:
            raise ValueError("HTTP error decision must have status_code and error_type")

        # Add latency
        delay = latency_simulator.simulate()
        if delay > 0:
            await asyncio.sleep(delay)

        headers: dict[str, str] = {}
        if decision.retry_after_sec is not None:
            headers["Retry-After"] = str(decision.retry_after_sec)

        message = _WEB_ERROR_MESSAGES.get(error_type, f"{status_code} Error")
        body = f"<html><body><h1>{message}</h1></body></html>"

        elapsed_ms = (time.monotonic() - start_time) * 1000
        self._record_request(
            request_id=request_id,
            timestamp_utc=timestamp_utc,
            path=path,
            outcome="error_injected",
            status_code=status_code,
            error_type=error_type,
            injection_type=error_type,
            latency_ms=elapsed_ms,
        )

        return HTMLResponse(body, status_code=status_code, headers=headers)

    async def _handle_malformed_content(
        self,
        decision: WebErrorDecision,
        request_id: str,
        timestamp_utc: str,
        path: str,
        mode_override: str | None,
        headers: dict[str, str] | None,
        start_time: float,
        content_generator: ContentGenerator,
        latency_simulator: LatencySimulator,
    ) -> Response:
        """Handle malformed content responses (200 with corrupted content)."""
        malformed_type = decision.malformed_type

        # Add latency
        delay = latency_simulator.simulate()
        if delay > 0:
            await asyncio.sleep(delay)

        # Generate base HTML then corrupt it
        web_response = content_generator.generate(
            path=path,
            headers=headers,
            mode_override=mode_override,
        )

        # Corruption helpers expect str input. ContentGenerator.generate() always
        # returns str for normal HTML; bytes only for already-corrupted content.
        html_content: str = (
            web_response.content if isinstance(web_response.content, str) else web_response.content.decode("utf-8", errors="replace")
        )

        elapsed_ms = (time.monotonic() - start_time) * 1000

        if malformed_type == "wrong_content_type":
            wrong_ct = generate_wrong_content_type(rng=content_generator._rng)
            self._record_request(
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                path=path,
                outcome="error_malformed",
                status_code=200,
                error_type=f"malformed_{malformed_type}",
                injection_type=f"malformed_{malformed_type}",
                latency_ms=elapsed_ms,
                content_type_served=wrong_ct,
            )
            content = web_response.content
            if isinstance(content, str):
                content = content.encode("utf-8")
            return Response(content=content, status_code=200, media_type=wrong_ct)

        if malformed_type == "encoding_mismatch":
            corrupted = inject_encoding_mismatch(html_content)
            self._record_request(
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                path=path,
                outcome="error_malformed",
                status_code=200,
                error_type=f"malformed_{malformed_type}",
                injection_type=f"malformed_{malformed_type}",
                latency_ms=elapsed_ms,
                content_type_served="text/html; charset=utf-8",
                encoding_served="iso-8859-1",
            )
            return Response(
                content=corrupted,
                status_code=200,
                headers={"Content-Type": "text/html; charset=utf-8"},
            )

        if malformed_type == "truncated_html":
            truncated = truncate_html(html_content)
            self._record_request(
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                path=path,
                outcome="error_malformed",
                status_code=200,
                error_type=f"malformed_{malformed_type}",
                injection_type=f"malformed_{malformed_type}",
                latency_ms=elapsed_ms,
                content_type_served=web_response.content_type,
            )
            return Response(content=truncated, status_code=200, media_type=web_response.content_type)

        if malformed_type == "invalid_encoding":
            invalid = inject_invalid_encoding(html_content)
            self._record_request(
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                path=path,
                outcome="error_malformed",
                status_code=200,
                error_type=f"malformed_{malformed_type}",
                injection_type=f"malformed_{malformed_type}",
                latency_ms=elapsed_ms,
                content_type_served="text/html; charset=utf-8",
            )
            return Response(
                content=invalid,
                status_code=200,
                headers={"Content-Type": "text/html; charset=utf-8"},
            )

        if malformed_type == "charset_confusion":
            confused = inject_charset_confusion(html_content)
            self._record_request(
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                path=path,
                outcome="error_malformed",
                status_code=200,
                error_type=f"malformed_{malformed_type}",
                injection_type=f"malformed_{malformed_type}",
                latency_ms=elapsed_ms,
                content_type_served="text/html; charset=windows-1252",
            )
            return Response(
                content=confused.encode("utf-8"),
                status_code=200,
                headers={"Content-Type": "text/html; charset=windows-1252"},
            )

        if malformed_type == "malformed_meta":
            malformed = inject_malformed_meta(html_content)
            self._record_request(
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                path=path,
                outcome="error_malformed",
                status_code=200,
                error_type=f"malformed_{malformed_type}",
                injection_type=f"malformed_{malformed_type}",
                latency_ms=elapsed_ms,
                content_type_served=web_response.content_type,
            )
            return Response(content=malformed.encode("utf-8"), status_code=200, media_type=web_response.content_type)

        raise ValueError(f"Unknown malformed content type: {malformed_type}")

    async def _handle_slow_response(
        self,
        decision: WebErrorDecision,
        request_id: str,
        timestamp_utc: str,
        path: str,
        mode_override: str | None,
        headers: dict[str, str] | None,
        start_time: float,
        content_generator: ContentGenerator,
        latency_simulator: LatencySimulator,
    ) -> Response:
        """Handle a slow response that eventually succeeds."""
        delay = decision.delay_sec if decision.delay_sec is not None else 15.0
        return await self._handle_success(
            request_id=request_id,
            timestamp_utc=timestamp_utc,
            path=path,
            mode_override=mode_override,
            headers=headers,
            start_time=start_time,
            extra_delay_sec=delay,
            injection_type="slow_response",
            content_generator=content_generator,
            latency_simulator=latency_simulator,
        )

    async def _handle_success(
        self,
        request_id: str,
        timestamp_utc: str,
        path: str,
        mode_override: str | None,
        start_time: float,
        content_generator: ContentGenerator,
        latency_simulator: LatencySimulator,
        headers: dict[str, str] | None = None,
        extra_delay_sec: float | None = None,
        injection_type: str | None = None,
    ) -> Response:
        """Handle a successful page response with latency simulation."""
        # Latency
        delay = latency_simulator.simulate()
        total_delay = delay + (extra_delay_sec if extra_delay_sec is not None else 0.0)
        if total_delay > 0:
            await asyncio.sleep(total_delay)

        # Generate HTML
        web_response = content_generator.generate(
            path=path,
            headers=headers,
            mode_override=mode_override,
        )

        # Record metrics
        elapsed_ms = (time.monotonic() - start_time) * 1000
        self._record_request(
            request_id=request_id,
            timestamp_utc=timestamp_utc,
            path=path,
            outcome="success",
            status_code=200,
            latency_ms=elapsed_ms,
            injected_delay_ms=total_delay * 1000 if total_delay > 0 else None,
            content_type_served=web_response.content_type,
            injection_type=injection_type,
        )

        content = web_response.content
        if isinstance(content, str):
            content = content.encode("utf-8")

        headers = dict(web_response.headers) if web_response.headers else {}
        return Response(
            content=content,
            status_code=200,
            media_type=web_response.content_type,
            headers=headers,
        )

    def _record_request(
        self,
        *,
        request_id: str,
        timestamp_utc: str,
        path: str,
        outcome: str,
        status_code: int | None = None,
        error_type: str | None = None,
        injection_type: str | None = None,
        latency_ms: float | None = None,
        injected_delay_ms: float | None = None,
        content_type_served: str | None = None,
        encoding_served: str | None = None,
        redirect_target: str | None = None,
        redirect_hops: int | None = None,
    ) -> None:
        """Record a request to metrics.

        Metrics recording is best-effort: failures are logged but never
        propagated to the caller, because a metrics side-effect must not
        replace the intended chaos response with an unintended real 500.
        """
        try:
            self._metrics_recorder.record_request(
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                path=path,
                outcome=outcome,
                status_code=status_code,
                error_type=error_type,
                injection_type=injection_type,
                latency_ms=latency_ms,
                injected_delay_ms=injected_delay_ms,
                content_type_served=content_type_served,
                encoding_served=encoding_served,
                redirect_target=redirect_target,
                redirect_hops=redirect_hops,
            )
        except sqlite3.Error:
            logger.warning(
                "metrics_recording_failed",
                request_id=request_id,
                path=path,
                outcome=outcome,
                exc_info=True,
            )
        except Exception:
            logger.error(
                "metrics_recording_unexpected_error",
                request_id=request_id,
                path=path,
                outcome=outcome,
                exc_info=True,
            )


class _StreamingDisconnect(Response):
    """A streaming response that disconnects mid-transfer.

    Used for incomplete_response error injection — sends partial body
    then raises ConnectionResetError to simulate a dropped connection.
    """

    body_iterator: Any

    def __init__(
        self,
        content: Any,
        status_code: int = 200,
        media_type: str | None = None,
    ) -> None:
        self.body_iterator = content
        self.status_code = status_code
        self.media_type = media_type
        self.background = None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": [
                    [b"content-type", (self.media_type or "text/html").encode()],
                ],
            }
        )
        async for chunk in self.body_iterator:
            await send({"type": "http.response.body", "body": chunk, "more_body": True})


def create_app(config: ChaosWebConfig) -> Starlette:
    """Create a Starlette ASGI application from config.

    Convenience function for simple use cases. For more control
    (runtime config updates, metrics access), use ChaosWebServer directly.
    """
    server = ChaosWebServer(config)
    server.app.state.server = server
    return server.app
