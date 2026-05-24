"""SMTP listener and admin sidecar for ChaosSMTP."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from socket import create_connection
from typing import Any, cast

import structlog
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import Envelope, Session
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from errorworks.engine import admin
from errorworks.engine.config_loader import deep_merge
from errorworks.engine.latency import LatencySimulator
from errorworks.engine.types import LatencyConfig
from errorworks.smtp.config import ChaosSMTPConfig, SMTPCaptureConfig, SMTPErrorInjectionConfig
from errorworks.smtp.error_injector import SMTPErrorCategory, SMTPErrorDecision, SMTPErrorInjector, SMTPStage
from errorworks.smtp.message_capture import CapturedMessage, MessageCapture
from errorworks.smtp.metrics import SMTPMetricsRecorder

logger = structlog.get_logger(__name__)


class _EphemeralPortController(Controller):
    """Controller that can self-trigger after binding to port 0."""

    def _trigger_server(self) -> None:
        if self.server is None:
            raise RuntimeError("SMTP server did not expose a bound socket")

        sockets = _server_sockets(self.server)
        if not sockets:
            raise RuntimeError("SMTP server did not expose a bound socket")
        host = self.hostname or self._localhost
        port = self.port if self.port != 0 else int(sockets[0].getsockname()[1])
        with create_connection((host, port), 1.0) as sock:
            sock.recv(1024)


class _ChaosSMTPHandler:
    """aiosmtpd handler that delegates SMTP stages to ChaosSMTPServer."""

    def __init__(self, owner: ChaosSMTPServer) -> None:
        self._owner = owner

    async def handle_MAIL(self, server: Any, session: Session, envelope: Envelope, address: str, mail_options: list[str]) -> str:
        decision = await self._owner.handle_stage(SMTPStage.MAIL, session=session, smtp_server=server, mail_from=address)
        if _is_failure_decision(decision):
            return _reply_for_decision(decision)
        envelope.mail_from = address
        envelope.mail_options.extend(mail_options)
        return "250 2.1.0 OK"

    async def handle_RCPT(self, server: Any, session: Session, envelope: Envelope, address: str, rcpt_options: list[str]) -> str:
        decision = await self._owner.handle_stage(SMTPStage.RCPT, session=session, smtp_server=server, rcpt_to=address)
        if _is_failure_decision(decision):
            return _reply_for_decision(decision)
        envelope.rcpt_tos.append(address)
        envelope.rcpt_options.extend(rcpt_options)
        return "250 2.1.5 OK"

    async def handle_DATA(self, server: Any, session: Session, envelope: Envelope) -> str:
        return await self._owner.handle_data(session=session, smtp_server=server, envelope=envelope)


class ChaosSMTPServer:
    """Main ChaosSMTP server class."""

    def __init__(self, config: ChaosSMTPConfig) -> None:
        self._config = config
        self._config_lock = threading.Lock()
        self._error_injector = SMTPErrorInjector(config.error_injection)
        self._capture = MessageCapture(config.capture)
        self._latency_simulator = LatencySimulator(config.latency)
        self._metrics_recorder = SMTPMetricsRecorder(config.metrics)
        self._controller: Controller | None = None
        self._record_run_info()
        self._admin_app = create_admin_app(self)

    @property
    def admin_app(self) -> Starlette:
        return self._admin_app

    @property
    def run_id(self) -> str:
        return self._metrics_recorder.run_id

    @property
    def smtp_host(self) -> str:
        return self._config.smtp.host

    @property
    def smtp_port(self) -> int:
        if self._controller is not None and self._controller.server is not None:
            sockets = _server_sockets(self._controller.server)
            if sockets:
                return int(sockets[0].getsockname()[1])
        return self._config.smtp.port

    @property
    def smtp_running(self) -> bool:
        return self._controller is not None and self._controller.server is not None and bool(_server_sockets(self._controller.server))

    def start(self) -> None:
        if self.smtp_running:
            return
        controller = _EphemeralPortController(
            _ChaosSMTPHandler(self),
            hostname=self._config.smtp.host,
            port=self._config.smtp.port,
            ready_timeout=5.0,
            server_hostname=self._config.smtp.hostname,
            data_size_limit=self._config.smtp.data_size_limit,
            enable_SMTPUTF8=self._config.smtp.enable_smtputf8,
            require_starttls=self._config.smtp.require_starttls,
        )
        try:
            controller.start()
        except Exception:
            try:
                controller.stop(no_assert=True)
            except Exception:
                logger.warning("smtp_controller_cleanup_failed", exc_info=True)
            raise
        self._controller = controller

    def stop(self) -> None:
        try:
            if self._controller is not None:
                controller = self._controller
                self._controller = None
                controller.stop()
        finally:
            self._metrics_recorder.close()

    def get_admin_token(self) -> str:
        return self._config.admin.admin_token

    def get_stats(self) -> dict[str, Any]:
        return self._metrics_recorder.get_stats()

    def export_metrics(self) -> dict[str, Any]:
        data = self._metrics_recorder.export_data()
        data["messages"] = [asdict(message) for message in self._capture.list_messages()]
        data["config"] = {
            "smtp": self._config.smtp.model_dump(),
            "admin": self._config.admin.model_dump(exclude={"admin_token"}),
            "metrics": self._config.metrics.model_dump(),
            **self.get_current_config(),
        }
        return data

    def list_messages(self) -> list[CapturedMessage]:
        return self._capture.list_messages()

    def reset(self) -> str:
        self._error_injector.reset()
        self._capture.reset()
        self._metrics_recorder.reset(config_json=self._config_json(), preset_name=self._config.preset_name)
        return self._metrics_recorder.run_id

    def update_config(self, updates: dict[str, Any]) -> None:
        new_error: SMTPErrorInjector | None = None
        new_capture_config: SMTPCaptureConfig | None = None
        new_latency: LatencySimulator | None = None

        if "error_injection" in updates:
            current = self._error_injector.config.model_dump()
            merged = deep_merge(current, updates["error_injection"])
            new_error = SMTPErrorInjector(SMTPErrorInjectionConfig(**merged))

        if "capture" in updates:
            current = self._capture.config.model_dump()
            merged = deep_merge(current, updates["capture"])
            new_capture_config = SMTPCaptureConfig(**merged)

        if "latency" in updates:
            current = self._latency_simulator.config.model_dump()
            merged = deep_merge(current, updates["latency"])
            new_latency = LatencySimulator(LatencyConfig(**merged))

        with self._config_lock:
            if new_error is not None:
                self._error_injector = new_error
            if new_capture_config is not None:
                self._capture.update_config(new_capture_config)
            if new_latency is not None:
                self._latency_simulator = new_latency

    def get_current_config(self) -> dict[str, Any]:
        with self._config_lock:
            return {
                "error_injection": self._error_injector.config.model_dump(),
                "capture": self._capture.config.model_dump(),
                "latency": self._latency_simulator.config.model_dump(),
            }

    async def _health_endpoint(self, request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "healthy",
                "smtp_running": self.smtp_running,
                "run_id": self._metrics_recorder.run_id,
                "started_utc": self._metrics_recorder.started_utc,
                "in_burst": self._error_injector.is_in_burst(),
            }
        )

    async def _admin_config_endpoint(self, request: Request) -> JSONResponse:
        return await admin.handle_admin_config(request, self)

    async def _admin_stats_endpoint(self, request: Request) -> JSONResponse:
        return await admin.handle_admin_stats(request, self)

    async def _admin_reset_endpoint(self, request: Request) -> JSONResponse:
        return await admin.handle_admin_reset(request, self)

    async def _admin_export_endpoint(self, request: Request) -> JSONResponse:
        return await admin.handle_admin_export(request, self)

    async def handle_stage(
        self,
        stage: SMTPStage,
        *,
        session: Session,
        smtp_server: Any,
        mail_from: str | None = None,
        rcpt_to: str | None = None,
    ) -> SMTPErrorDecision:
        with self._config_lock:
            error_injector = self._error_injector
            latency_simulator = self._latency_simulator
            capture_mode = self._capture.config.mode
        decision = error_injector.decide(stage)
        delay = latency_simulator.simulate()
        if decision.delay_sec is not None:
            delay += decision.delay_sec
        if delay > 0:
            await asyncio.sleep(delay)
        if _is_failure_decision(decision):
            self._record_transaction(
                session=session,
                outcome=_outcome_for_decision(decision),
                stage=stage,
                decision=decision,
                mail_from=mail_from,
                rcpt_count=1 if rcpt_to else None,
                rcpt_tos=[rcpt_to] if rcpt_to else None,
                capture_mode=capture_mode,
                latency_ms=delay * 1000,
                injected_delay_ms=decision.delay_sec * 1000 if decision.delay_sec else None,
            )
            _apply_protocol_failure(smtp_server, decision)
        return decision

    async def handle_data(self, *, session: Session, smtp_server: Any, envelope: Envelope) -> str:
        start = time.monotonic()
        with self._config_lock:
            error_injector = self._error_injector
            capture = self._capture
            latency_simulator = self._latency_simulator
            capture_config = capture.config
            capture_mode = capture_config.mode
        decision = error_injector.decide(SMTPStage.DATA)
        delay = latency_simulator.simulate()
        if decision.delay_sec is not None:
            delay += decision.delay_sec
        if delay > 0:
            await asyncio.sleep(delay)
        elapsed_ms = (time.monotonic() - start) * 1000
        content = envelope.content if isinstance(envelope.content, bytes) else b""
        if _is_failure_decision(decision):
            self._record_transaction(
                session=session,
                outcome=_outcome_for_decision(decision),
                stage=SMTPStage.DATA,
                decision=decision,
                mail_from=envelope.mail_from,
                rcpt_count=len(envelope.rcpt_tos),
                rcpt_tos=list(envelope.rcpt_tos),
                message_size_bytes=len(content),
                capture_mode=capture_mode,
                latency_ms=elapsed_ms,
                injected_delay_ms=decision.delay_sec * 1000 if decision.delay_sec else None,
            )
            _apply_protocol_failure(smtp_server, decision)
            return _reply_for_decision(decision)
        accept_decision = error_injector.decide(SMTPStage.ACCEPT)
        if accept_decision.should_inject:
            self._record_transaction(
                session=session,
                outcome=_outcome_for_decision(accept_decision),
                stage=SMTPStage.ACCEPT,
                decision=accept_decision,
                mail_from=envelope.mail_from,
                rcpt_count=len(envelope.rcpt_tos),
                rcpt_tos=list(envelope.rcpt_tos),
                message_size_bytes=len(content),
                reply_code=250,
                capture_mode=capture_mode,
                latency_ms=elapsed_ms,
            )
            return "250 2.0.0 OK"
        transaction_id = str(uuid.uuid4())
        captured = capture.capture(
            transaction_id=transaction_id,
            mail_from=envelope.mail_from or "",
            rcpt_tos=list(envelope.rcpt_tos),
            data=content,
            config=capture_config,
        )
        self._record_transaction(
            session=session,
            outcome="success",
            stage=SMTPStage.DATA,
            transaction_id=transaction_id,
            mail_from=envelope.mail_from,
            rcpt_count=len(envelope.rcpt_tos),
            rcpt_tos=list(envelope.rcpt_tos),
            message_size_bytes=captured.message_size_bytes,
            subject=captured.subject,
            reply_code=250,
            capture_mode=capture_mode,
            latency_ms=elapsed_ms,
        )
        return "250 2.0.0 OK"

    def _record_run_info(self) -> None:
        self._metrics_recorder.save_run_info(
            config_json=self._config_json(),
            preset_name=self._config.preset_name,
        )

    def _config_json(self) -> str:
        return json.dumps(
            {
                "smtp": self._config.smtp.model_dump(),
                "admin": self._config.admin.model_dump(exclude={"admin_token"}),
                "metrics": self._config.metrics.model_dump(),
                **self.get_current_config(),
            },
            sort_keys=True,
        )

    def _record_transaction(
        self,
        *,
        session: Session,
        outcome: str,
        stage: SMTPStage,
        transaction_id: str | None = None,
        decision: SMTPErrorDecision | None = None,
        mail_from: str | None = None,
        rcpt_count: int | None = None,
        rcpt_tos: list[str] | None = None,
        message_size_bytes: int | None = None,
        subject: str | None = None,
        reply_code: int | None = None,
        capture_mode: str | None = None,
        latency_ms: float | None = None,
        injected_delay_ms: float | None = None,
    ) -> None:
        transaction_id = transaction_id or str(uuid.uuid4())
        if decision is not None:
            reply_code = decision.reply_code
        timestamp_utc = datetime.now(UTC).isoformat()
        try:
            self._metrics_recorder.record_transaction(
                transaction_id=transaction_id,
                session_id=str(id(session)),
                timestamp_utc=timestamp_utc,
                client_addr=_client_addr(session),
                mail_from=mail_from,
                rcpt_count=rcpt_count,
                rcpt_domains=_rcpt_domains(rcpt_tos),
                message_size_bytes=message_size_bytes,
                subject=subject,
                outcome=outcome,
                smtp_stage=stage.value,
                reply_code=reply_code,
                enhanced_status_code=_enhanced_status_code(decision.message) if decision is not None else None,
                error_type=decision.error_type if decision is not None else None,
                injection_type=decision.error_type if decision is not None else None,
                latency_ms=latency_ms,
                injected_delay_ms=injected_delay_ms,
                capture_mode=capture_mode,
                tls_used=bool(getattr(session, "ssl", None)),
                auth_username=_auth_username(session),
            )
        except sqlite3.Error:
            logger.warning("smtp_metrics_recording_failed", transaction_id=transaction_id, outcome=outcome, exc_info=True)
        except (ValueError, TypeError):
            logger.error("smtp_metrics_recording_unexpected_error", transaction_id=transaction_id, outcome=outcome, exc_info=True)


def create_admin_app(server: ChaosSMTPServer) -> Starlette:
    routes = [
        Route("/health", server._health_endpoint, methods=["GET"]),
        Route("/admin/config", server._admin_config_endpoint, methods=["GET", "POST"]),
        Route("/admin/stats", server._admin_stats_endpoint, methods=["GET"]),
        Route("/admin/reset", server._admin_reset_endpoint, methods=["POST"]),
        Route("/admin/export", server._admin_export_endpoint, methods=["GET"]),
    ]
    app = Starlette(debug=False, routes=routes)
    app.state.server = server
    return app


def _server_sockets(server: Any) -> list[Any]:
    return list(cast(Any, server).sockets or [])


def _outcome_for_decision(decision: SMTPErrorDecision) -> str:
    if decision.category == SMTPErrorCategory.CONNECTION:
        return "connection_error"
    if decision.category == SMTPErrorCategory.MALFORMED:
        return "malformed_protocol"
    if decision.error_type == "accept_then_drop":
        return "accepted_then_dropped"
    if decision.reply_code is not None and 400 <= decision.reply_code < 500:
        return "tempfailed"
    if decision.reply_code is not None and 500 <= decision.reply_code < 600:
        return "permfailed"
    return "error_injected"


def _is_failure_decision(decision: SMTPErrorDecision) -> bool:
    return decision.should_inject and decision.error_type != "slow_response"


def _transport_from_smtp(smtp_server: Any) -> Any:
    transport = getattr(smtp_server, "transport", None)
    if transport is not None:
        return transport
    writer = getattr(smtp_server, "_writer", None)
    if writer is not None:
        return getattr(writer, "transport", None)
    return None


def _close_smtp_transport(smtp_server: Any) -> None:
    transport = _transport_from_smtp(smtp_server)
    if transport is not None:
        transport.close()


def _write_raw_smtp_reply(smtp_server: Any, payload: bytes) -> None:
    transport = _transport_from_smtp(smtp_server)
    if transport is not None:
        transport.write(payload)


def _apply_protocol_failure(smtp_server: Any, decision: SMTPErrorDecision) -> None:
    if decision.error_type in {"connection_reset", "connection_stall"}:
        _close_smtp_transport(smtp_server)
    elif decision.error_type == "malformed_reply":
        _write_raw_smtp_reply(smtp_server, b"299-Malformed SMTP reply\r\n")
        _close_smtp_transport(smtp_server)


def _reply_for_decision(decision: SMTPErrorDecision) -> str:
    if decision.reply_code is not None and decision.message is not None:
        return decision.reply_line
    if decision.error_type == "malformed_reply":
        return "451 4.3.0 Malformed reply injected"
    if decision.error_type in {"connection_reset", "connection_stall"}:
        return "421 4.3.0 Connection closed by chaos policy"
    if decision.reply_code is None or decision.message is None:
        return "451 4.3.0 Chaos SMTP failure"
    return decision.reply_line


def _client_addr(session: Session) -> str | None:
    peer = getattr(session, "peer", None)
    if isinstance(peer, tuple) and peer:
        return str(peer[0])
    if peer is not None:
        return str(peer)
    return None


def _rcpt_domains(rcpt_tos: list[str] | None) -> str | None:
    if not rcpt_tos:
        return None
    domains = sorted({address.rsplit("@", 1)[1].lower() for address in rcpt_tos if "@" in address})
    return json.dumps(domains)


def _enhanced_status_code(message: str | None) -> str | None:
    if message is None:
        return None
    first = message.split(" ", 1)[0]
    if first.count(".") == 2:
        return first
    return None


def _auth_username(session: Session) -> str | None:
    auth_data = getattr(session, "auth_data", None)
    login = getattr(auth_data, "login", None)
    if login is not None:
        return str(login)
    return None
