"""Starlette ASGI application for ChaosBlob fake object storage."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from errorworks.blob.config import BlobErrorInjectionConfig, BlobStorageConfig, ChaosBlobConfig
from errorworks.blob.error_injector import BlobErrorCategory, BlobErrorDecision, BlobErrorInjector, BlobOperation
from errorworks.blob.metrics import BlobMetricsRecorder
from errorworks.blob.store import BlobListPage, BlobObject, BlobStore, InvalidContinuationTokenError, ObjectTooLargeError
from errorworks.blob.xml import error_xml, list_objects_v2_xml
from errorworks.engine import admin
from errorworks.engine.config_loader import deep_merge
from errorworks.engine.latency import LatencySimulator
from errorworks.engine.request_body import RequestBodyTooLarge, read_limited_body
from errorworks.engine.types import LatencyConfig

logger = structlog.get_logger(__name__)

_XML_MEDIA_TYPE = "application/xml"

_S3_MESSAGES: dict[str, str] = {
    "SlowDown": "Please reduce your request rate.",
    "AccessDenied": "Access Denied.",
    "NoSuchKey": "The specified key does not exist.",
    "ServiceUnavailable": "Service Unavailable.",
    "InternalError": "We encountered an internal error. Please try again.",
    "BadGateway": "Bad Gateway.",
    "GatewayTimeout": "Gateway Timeout.",
    "RequestTimeout": "Your socket connection to the server was not read from or written to within the timeout period.",
    "InvalidRequest": "The request is invalid.",
    "InvalidArgument": "Invalid argument.",
    "EntityTooLarge": "Your proposed upload exceeds the maximum allowed object size.",
}


class ChaosBlobServer:
    """Main ChaosBlob server class."""

    def __init__(self, config: ChaosBlobConfig) -> None:
        self._config = config
        self._config_lock = threading.Lock()
        self._error_injector = BlobErrorInjector(config.error_injection)
        self._storage_config = config.storage
        self._store = BlobStore(
            max_object_bytes=config.storage.max_object_bytes,
            default_content_type=config.storage.default_content_type,
        )
        self._latency_simulator = LatencySimulator(config.latency)
        self._metrics_recorder = BlobMetricsRecorder(config.metrics)
        self._record_run_info()
        self._app = self._create_app()

    def _create_app(self) -> Starlette:
        routes = [
            Route("/health", self._health_endpoint, methods=["GET"]),
            Route("/admin/config", self._admin_config_endpoint, methods=["GET", "POST"]),
            Route("/admin/stats", self._admin_stats_endpoint, methods=["GET"]),
            Route("/admin/reset", self._admin_reset_endpoint, methods=["POST"]),
            Route("/admin/export", self._admin_export_endpoint, methods=["GET"]),
            Route("/{bucket}", self._bucket_endpoint, methods=["GET"]),
            Route("/{bucket}/{key:path}", self._object_endpoint, methods=["PUT", "GET", "HEAD", "DELETE"]),
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

    def get_admin_token(self) -> str:
        """Return the admin token for authentication."""
        return self._config.server.admin_token

    def get_stats(self) -> dict[str, Any]:
        """Get current metrics statistics."""
        return self._metrics_recorder.get_stats()

    def reset(self) -> str:
        """Reset metrics, store contents, and injector state."""
        self._error_injector.reset()
        self._store.reset()
        self._metrics_recorder.reset()
        self._record_run_info()
        return self._metrics_recorder.run_id

    def export_metrics(self) -> dict[str, Any]:
        """Export raw metrics data."""
        data = self._metrics_recorder.export_data()
        data["config"] = {
            "server": self._config.server.model_dump(exclude={"admin_token"}),
            "metrics": self._config.metrics.model_dump(),
            **self.get_current_config(),
        }
        return data

    def close(self) -> None:
        """Close server-owned resources."""
        self._metrics_recorder.close()

    def update_config(self, updates: dict[str, Any]) -> None:
        """Update runtime configuration by rebuilding affected components and swapping atomically."""
        new_error: BlobErrorInjector | None = None
        new_storage_config: BlobStorageConfig | None = None
        new_store: BlobStore | None = None
        new_latency: LatencySimulator | None = None

        if "error_injection" in updates:
            current = self._error_injector.config.model_dump()
            merged = deep_merge(current, updates["error_injection"])
            new_error = BlobErrorInjector(BlobErrorInjectionConfig(**merged))

        if "storage" in updates:
            current_storage = self._storage_config.model_dump()
            merged_storage = deep_merge(current_storage, updates["storage"])
            new_storage_config = BlobStorageConfig(**merged_storage)
            new_store = BlobStore(
                max_object_bytes=new_storage_config.max_object_bytes,
                default_content_type=new_storage_config.default_content_type,
            )

        if "latency" in updates:
            current_latency = self._latency_simulator.config.model_dump()
            merged_latency = deep_merge(current_latency, updates["latency"])
            new_latency = LatencySimulator(LatencyConfig(**merged_latency))

        with self._config_lock:
            if new_error is not None:
                self._error_injector = new_error
            if new_storage_config is not None and new_store is not None:
                self._storage_config = new_storage_config
                self._store = new_store
            if new_latency is not None:
                self._latency_simulator = new_latency

    def get_current_config(self) -> dict[str, Any]:
        """Get current runtime configuration as a dictionary."""
        with self._config_lock:
            return {
                "error_injection": self._error_injector.config.model_dump(),
                "storage": self._storage_config.model_dump(),
                "latency": self._latency_simulator.config.model_dump(),
            }

    def _record_run_info(self) -> None:
        config_json = json.dumps(
            {
                "server": self._config.server.model_dump(exclude={"admin_token"}),
                "metrics": self._config.metrics.model_dump(),
                **self.get_current_config(),
            },
            sort_keys=True,
        )
        self._metrics_recorder.save_run_info(config_json=config_json, preset_name=self._config.preset_name)

    async def _health_endpoint(self, request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "healthy",
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

    async def _bucket_endpoint(self, request: Request) -> Response:
        request_id, timestamp_utc, start_time = self._request_context()
        bucket = request.path_params["bucket"]
        if request.query_params.get("list-type") != "2":
            error_body = self._s3_error_body(code="InvalidRequest", resource=f"/{bucket}", request_id=request_id)
            self._record_request(
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                operation=BlobOperation.LIST.value,
                bucket=bucket,
                outcome="error_injected",
                status_code=400,
                error_type="InvalidRequest",
                bytes_out=len(error_body),
                latency_ms=self._elapsed_ms(start_time),
            )
            return self._s3_error_response(body=error_body, status_code=400)
        return await self._handle_list(request, bucket=bucket)

    async def _object_endpoint(self, request: Request) -> Response:
        bucket = request.path_params["bucket"]
        key = request.path_params["key"]
        if request.method == "PUT":
            return await self._handle_put(request, bucket=bucket, key=key)
        if request.method == "GET":
            return await self._handle_get_or_head(request, bucket=bucket, key=key, operation=BlobOperation.GET)
        if request.method == "HEAD":
            return await self._handle_get_or_head(request, bucket=bucket, key=key, operation=BlobOperation.HEAD)
        if request.method == "DELETE":
            return await self._handle_delete(request, bucket=bucket, key=key)
        return self._s3_error(code="InvalidRequest", status_code=400, resource=f"/{bucket}/{key}", request_id=str(uuid.uuid4()))

    async def _handle_put(self, request: Request, *, bucket: str, key: str) -> Response:
        request_id, timestamp_utc, start_time = self._request_context()
        with self._config_lock:
            error_injector = self._error_injector
            store = self._store
            storage_config = self._storage_config
            latency_simulator = self._latency_simulator

        decision = error_injector.decide(BlobOperation.PUT)
        if decision is not None:
            return await self._handle_injected_decision(
                decision=decision,
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                operation=BlobOperation.PUT,
                bucket=bucket,
                key=key,
                start_time=start_time,
                latency_simulator=latency_simulator,
                error_injector=error_injector,
            )

        try:
            body = await read_limited_body(request, max_bytes=storage_config.max_object_bytes)
        except RequestBodyTooLarge:
            error_body = self._s3_error_body(code="EntityTooLarge", resource=f"/{bucket}/{key}", request_id=request_id)
            elapsed_ms = self._elapsed_ms(start_time)
            self._record_request(
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                operation=BlobOperation.PUT.value,
                bucket=bucket,
                object_key=key,
                outcome="error_injected",
                status_code=413,
                error_type="EntityTooLarge",
                bytes_out=len(error_body),
                latency_ms=elapsed_ms,
            )
            return self._s3_error_response(body=error_body, status_code=413)

        delay = latency_simulator.simulate()
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            stored = store.put(bucket, key, body, request.headers)
        except ObjectTooLargeError:
            error_body = self._s3_error_body(code="EntityTooLarge", resource=f"/{bucket}/{key}", request_id=request_id)
            elapsed_ms = self._elapsed_ms(start_time)
            self._record_request(
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                operation=BlobOperation.PUT.value,
                bucket=bucket,
                object_key=key,
                outcome="error_injected",
                status_code=413,
                error_type="EntityTooLarge",
                bytes_in=len(body),
                bytes_out=len(error_body),
                latency_ms=elapsed_ms,
                injected_delay_ms=self._delay_ms(delay),
            )
            return self._s3_error_response(body=error_body, status_code=413)

        etag = self._quoted_etag(stored.etag)
        elapsed_ms = self._elapsed_ms(start_time)
        self._record_request(
            request_id=request_id,
            timestamp_utc=timestamp_utc,
            operation=BlobOperation.PUT.value,
            bucket=bucket,
            object_key=key,
            outcome="success",
            status_code=200,
            bytes_in=len(body),
            bytes_out=0,
            etag=etag,
            latency_ms=elapsed_ms,
            injected_delay_ms=self._delay_ms(delay),
        )
        return Response(content=b"", status_code=200, headers={"ETag": etag})

    async def _handle_get_or_head(self, request: Request, *, bucket: str, key: str, operation: BlobOperation) -> Response:
        request_id, timestamp_utc, start_time = self._request_context()
        with self._config_lock:
            error_injector = self._error_injector
            store = self._store
            latency_simulator = self._latency_simulator

        decision = error_injector.decide(operation)
        if decision is not None and decision.category in {BlobErrorCategory.HTTP, BlobErrorCategory.CONNECTION}:
            return await self._handle_injected_decision(
                decision=decision,
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                operation=operation,
                bucket=bucket,
                key=key,
                start_time=start_time,
                latency_simulator=latency_simulator,
                error_injector=error_injector,
            )

        stored = store.get(bucket, key)
        if stored is None:
            error_body = self._s3_error_body(code="NoSuchKey", resource=f"/{bucket}/{key}", request_id=request_id)
            error_type = decision.error_type if decision is not None else "NoSuchKey"
            elapsed_ms = self._elapsed_ms(start_time)
            self._record_request(
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                operation=operation.value,
                bucket=bucket,
                object_key=key,
                outcome="error_injected",
                status_code=404,
                error_type=error_type,
                injection_type=decision.error_type if decision is not None else None,
                bytes_out=self._response_bytes_out(operation, error_body),
                latency_ms=elapsed_ms,
            )
            return self._s3_error_response(body=error_body, status_code=404)

        delay = latency_simulator.simulate()
        if delay > 0:
            await asyncio.sleep(delay)

        if decision is not None and decision.error_type == "wrong_content_length":
            return self._handle_wrong_content_length(
                stored=stored,
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                operation=operation,
                bucket=bucket,
                key=key,
                start_time=start_time,
                injected_delay_sec=delay,
            )

        body, headers, outcome, error_type = self._build_object_response(
            stored, decision=decision, include_body=operation is BlobOperation.GET
        )
        elapsed_ms = self._elapsed_ms(start_time)
        self._record_request(
            request_id=request_id,
            timestamp_utc=timestamp_utc,
            operation=operation.value,
            bucket=bucket,
            object_key=key,
            outcome=outcome,
            status_code=200,
            error_type=error_type,
            injection_type=error_type,
            bytes_out=len(body) if operation is BlobOperation.GET else 0,
            etag=headers.get("ETag"),
            latency_ms=elapsed_ms,
            injected_delay_ms=self._delay_ms(delay),
        )
        return Response(content=body, status_code=200, headers=headers)

    async def _handle_delete(self, request: Request, *, bucket: str, key: str) -> Response:
        request_id, timestamp_utc, start_time = self._request_context()
        with self._config_lock:
            error_injector = self._error_injector
            store = self._store
            latency_simulator = self._latency_simulator

        decision = error_injector.decide(BlobOperation.DELETE)
        if decision is not None:
            return await self._handle_injected_decision(
                decision=decision,
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                operation=BlobOperation.DELETE,
                bucket=bucket,
                key=key,
                start_time=start_time,
                latency_simulator=latency_simulator,
                error_injector=error_injector,
            )

        delay = latency_simulator.simulate()
        if delay > 0:
            await asyncio.sleep(delay)
        store.delete(bucket, key)
        elapsed_ms = self._elapsed_ms(start_time)
        self._record_request(
            request_id=request_id,
            timestamp_utc=timestamp_utc,
            operation=BlobOperation.DELETE.value,
            bucket=bucket,
            object_key=key,
            outcome="success",
            status_code=204,
            bytes_out=0,
            latency_ms=elapsed_ms,
            injected_delay_ms=self._delay_ms(delay),
        )
        return Response(status_code=204)

    async def _handle_list(self, request: Request, *, bucket: str) -> Response:
        request_id, timestamp_utc, start_time = self._request_context()
        prefix = request.query_params.get("prefix", "")
        continuation_token = request.query_params.get("continuation-token")
        try:
            max_keys = self._parse_max_keys(request.query_params.get("max-keys"))
        except InvalidContinuationTokenError:
            error_body = self._s3_error_body(code="InvalidArgument", resource=f"/{bucket}", request_id=request_id)
            elapsed_ms = self._elapsed_ms(start_time)
            self._record_request(
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                operation=BlobOperation.LIST.value,
                bucket=bucket,
                outcome="error_injected",
                status_code=400,
                error_type="InvalidArgument",
                bytes_out=len(error_body),
                latency_ms=elapsed_ms,
            )
            return self._s3_error_response(body=error_body, status_code=400)

        with self._config_lock:
            error_injector = self._error_injector
            store = self._store
            latency_simulator = self._latency_simulator

        decision = error_injector.decide(BlobOperation.LIST)
        if decision is not None and decision.category in {BlobErrorCategory.HTTP, BlobErrorCategory.CONNECTION}:
            return await self._handle_injected_decision(
                decision=decision,
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                operation=BlobOperation.LIST,
                bucket=bucket,
                key=None,
                start_time=start_time,
                latency_simulator=latency_simulator,
                error_injector=error_injector,
            )

        delay = latency_simulator.simulate()
        if delay > 0:
            await asyncio.sleep(delay)

        try:
            page = store.list_objects(bucket, prefix=prefix, max_keys=max_keys, continuation_token=continuation_token)
        except InvalidContinuationTokenError:
            error_body = self._s3_error_body(code="InvalidArgument", resource=f"/{bucket}", request_id=request_id)
            elapsed_ms = self._elapsed_ms(start_time)
            self._record_request(
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                operation=BlobOperation.LIST.value,
                bucket=bucket,
                outcome="error_injected",
                status_code=400,
                error_type="InvalidArgument",
                bytes_out=len(error_body),
                latency_ms=elapsed_ms,
                injected_delay_ms=self._delay_ms(delay),
            )
            return self._s3_error_response(body=error_body, status_code=400)

        page, content, outcome, error_type = self._build_list_response(
            bucket=bucket,
            prefix=prefix,
            max_keys=max_keys,
            continuation_token=continuation_token,
            page=page,
            decision=decision,
        )
        elapsed_ms = self._elapsed_ms(start_time)
        self._record_request(
            request_id=request_id,
            timestamp_utc=timestamp_utc,
            operation=BlobOperation.LIST.value,
            bucket=bucket,
            outcome=outcome,
            status_code=200,
            error_type=error_type,
            injection_type=error_type,
            bytes_out=len(content),
            latency_ms=elapsed_ms,
            injected_delay_ms=self._delay_ms(delay),
        )
        return Response(content=content, status_code=200, media_type=_XML_MEDIA_TYPE)

    async def _handle_injected_decision(
        self,
        *,
        decision: BlobErrorDecision,
        request_id: str,
        timestamp_utc: str,
        operation: BlobOperation,
        bucket: str,
        key: str | None,
        start_time: float,
        latency_simulator: LatencySimulator,
        error_injector: BlobErrorInjector,
    ) -> Response:
        if decision.category == BlobErrorCategory.CONNECTION:
            return await self._handle_connection_error(
                decision=decision,
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                operation=operation,
                bucket=bucket,
                key=key,
                start_time=start_time,
                error_injector=error_injector,
            )

        delay = latency_simulator.simulate()
        if delay > 0:
            await asyncio.sleep(delay)
        assert decision.status_code is not None and decision.s3_code is not None
        error_body = self._s3_error_body(code=decision.s3_code, resource=self._resource(bucket, key), request_id=request_id)
        elapsed_ms = self._elapsed_ms(start_time)
        self._record_request(
            request_id=request_id,
            timestamp_utc=timestamp_utc,
            operation=operation.value,
            bucket=bucket,
            object_key=key,
            outcome="error_injected",
            status_code=decision.status_code,
            error_type=decision.error_type,
            injection_type=decision.error_type,
            bytes_out=self._response_bytes_out(operation, error_body),
            latency_ms=elapsed_ms,
            injected_delay_ms=self._delay_ms(delay),
        )
        headers = {"Retry-After": str(decision.retry_after_sec)} if decision.retry_after_sec is not None else None
        return self._s3_error_response(body=error_body, status_code=decision.status_code, headers=headers)

    async def _handle_connection_error(
        self,
        *,
        decision: BlobErrorDecision,
        request_id: str,
        timestamp_utc: str,
        operation: BlobOperation,
        bucket: str,
        key: str | None,
        start_time: float,
        error_injector: BlobErrorInjector,
    ) -> Response:
        error_type = decision.error_type
        if error_type == "timeout":
            delay = error_injector.pick_delay(error_injector.config.timeout_sec)
            if delay > 0:
                await asyncio.sleep(delay)
            error_body = self._s3_error_body(code="RequestTimeout", resource=self._resource(bucket, key), request_id=request_id)
            elapsed_ms = self._elapsed_ms(start_time)
            self._record_request(
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                operation=operation.value,
                bucket=bucket,
                object_key=key,
                outcome="error_injected",
                status_code=504,
                error_type="timeout",
                injection_type="timeout",
                bytes_out=self._response_bytes_out(operation, error_body),
                latency_ms=elapsed_ms,
                injected_delay_ms=self._delay_ms(delay),
            )
            return self._s3_error_response(body=error_body, status_code=504)

        if error_type == "slow_response":
            delay = error_injector.pick_delay(error_injector.config.slow_response_sec)
            if delay > 0:
                await asyncio.sleep(delay)
            error_body = self._s3_error_body(code="SlowDown", resource=self._resource(bucket, key), request_id=request_id)
            elapsed_ms = self._elapsed_ms(start_time)
            self._record_request(
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                operation=operation.value,
                bucket=bucket,
                object_key=key,
                outcome="error_injected",
                status_code=503,
                error_type="slow_response",
                injection_type="slow_response",
                bytes_out=self._response_bytes_out(operation, error_body),
                latency_ms=elapsed_ms,
                injected_delay_ms=self._delay_ms(delay),
            )
            return self._s3_error_response(body=error_body, status_code=503)

        if error_type in {"connection_reset", "connection_stall"}:
            start_delay = 0.0
            stall_delay = 0.0
            if error_type == "connection_stall":
                start_delay = error_injector.pick_delay(error_injector.config.connection_stall_start_sec)
                stall_delay = error_injector.pick_delay(error_injector.config.connection_stall_sec)
                if start_delay > 0:
                    await asyncio.sleep(start_delay)
                if stall_delay > 0:
                    await asyncio.sleep(stall_delay)

            elapsed_ms = self._elapsed_ms(start_time)
            injected_delay_ms = self._delay_ms(start_delay + stall_delay)
            self._record_request(
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                operation=operation.value,
                bucket=bucket,
                object_key=key,
                outcome="error_injected",
                status_code=200,
                error_type=error_type,
                injection_type=error_type,
                bytes_out=0,
                latency_ms=elapsed_ms,
                injected_delay_ms=injected_delay_ms,
            )

            async def _disconnect_body() -> Any:
                yield b""
                raise ConnectionResetError(f"{error_type} injected by ChaosBlob")

            return _StreamingDisconnect(content=_disconnect_body(), status_code=200, media_type=_XML_MEDIA_TYPE)

        elapsed_ms = self._elapsed_ms(start_time)
        self._record_request(
            request_id=request_id,
            timestamp_utc=timestamp_utc,
            operation=operation.value,
            bucket=bucket,
            object_key=key,
            outcome="error_injected",
            error_type=error_type,
            injection_type=error_type,
            latency_ms=elapsed_ms,
        )
        raise ConnectionResetError(f"{error_type} injected by ChaosBlob")

    def _handle_wrong_content_length(
        self,
        *,
        stored: BlobObject,
        request_id: str,
        timestamp_utc: str,
        operation: BlobOperation,
        bucket: str,
        key: str,
        start_time: float,
        injected_delay_sec: float,
    ) -> Response:
        partial = stored.body[: max(0, len(stored.body) // 2)]
        headers = {
            "Content-Type": stored.content_type,
            "Content-Length": str(stored.size),
            "ETag": self._quoted_etag(stored.etag),
        }
        headers.update(dict(stored.metadata))
        self._record_request(
            request_id=request_id,
            timestamp_utc=timestamp_utc,
            operation=operation.value,
            bucket=bucket,
            object_key=key,
            outcome="error_corrupted",
            status_code=200,
            error_type="wrong_content_length",
            injection_type="wrong_content_length",
            bytes_out=len(partial),
            etag=headers["ETag"],
            latency_ms=self._elapsed_ms(start_time),
            injected_delay_ms=self._delay_ms(injected_delay_sec),
        )

        async def _partial_body() -> Any:
            yield partial
            raise ConnectionResetError("wrong_content_length injected by ChaosBlob")

        return _StreamingDisconnect(content=_partial_body(), status_code=200, headers=headers)

    def _build_object_response(
        self,
        stored: BlobObject,
        *,
        decision: BlobErrorDecision | None,
        include_body: bool,
    ) -> tuple[bytes, dict[str, str], str, str | None]:
        body = stored.body if include_body else b""
        headers = {
            "Content-Type": stored.content_type,
            "Content-Length": str(stored.size),
            "ETag": self._quoted_etag(stored.etag),
        }
        headers.update(dict(stored.metadata))
        outcome = "success"
        error_type: str | None = None

        if decision is None:
            return body, headers, outcome, error_type

        error_type = decision.error_type
        if decision.category in {BlobErrorCategory.BODY_CORRUPTION, BlobErrorCategory.METADATA_CORRUPTION}:
            outcome = "error_corrupted"

        if decision.error_type == "truncated_body":
            body = body[: max(0, len(body) // 2)]
            headers["Content-Length"] = str(len(body))
        elif decision.error_type == "checksum_mismatch":
            headers["ETag"] = '"00000000000000000000000000000000"'
        elif decision.error_type == "metadata_corruption":
            for name in sorted(name for name in headers if name.lower().startswith("x-amz-meta-"))[:1]:
                headers.pop(name, None)

        return body, headers, outcome, error_type

    def _build_list_response(
        self,
        *,
        bucket: str,
        prefix: str,
        max_keys: int,
        continuation_token: str | None,
        page: BlobListPage,
        decision: BlobErrorDecision | None,
    ) -> tuple[BlobListPage, bytes, str, str | None]:
        outcome = "success"
        error_type: str | None = None
        response_page = page
        if decision is not None and decision.category == BlobErrorCategory.LIST_CORRUPTION:
            outcome = "error_corrupted"
            error_type = decision.error_type
            if decision.error_type == "stale_list" and page.objects:
                newest = max(page.objects, key=lambda obj: obj.last_modified_utc)
                objects = tuple(obj for obj in page.objects if obj is not newest)
                response_page = BlobListPage(
                    objects=objects,
                    is_truncated=page.is_truncated,
                    next_continuation_token=page.next_continuation_token,
                )
            elif decision.error_type == "malformed_xml":
                return response_page, b"<ListBucketResult><Contents>", outcome, error_type

        content = list_objects_v2_xml(bucket, prefix, max_keys, continuation_token, response_page)
        return response_page, content, outcome, error_type

    def _s3_error(
        self,
        *,
        code: str,
        status_code: int,
        resource: str,
        request_id: str,
        headers: dict[str, str] | None = None,
    ) -> Response:
        body = self._s3_error_body(code=code, resource=resource, request_id=request_id)
        return self._s3_error_response(body=body, status_code=status_code, headers=headers)

    def _s3_error_body(self, *, code: str, resource: str, request_id: str) -> bytes:
        return error_xml(code, _S3_MESSAGES[code], resource=resource, request_id=request_id)

    def _s3_error_response(
        self,
        *,
        body: bytes,
        status_code: int,
        headers: dict[str, str] | None = None,
    ) -> Response:
        return Response(content=body, status_code=status_code, media_type=_XML_MEDIA_TYPE, headers=headers)

    def _record_request(
        self,
        *,
        request_id: str,
        timestamp_utc: str,
        operation: str,
        bucket: str,
        outcome: str,
        object_key: str | None = None,
        status_code: int | None = None,
        error_type: str | None = None,
        injection_type: str | None = None,
        bytes_in: int | None = None,
        bytes_out: int | None = None,
        etag: str | None = None,
        latency_ms: float | None = None,
        injected_delay_ms: float | None = None,
    ) -> None:
        try:
            self._metrics_recorder.record_request(
                request_id=request_id,
                timestamp_utc=timestamp_utc,
                operation=operation,
                bucket=bucket,
                object_key=object_key,
                outcome=outcome,
                status_code=status_code,
                error_type=error_type,
                injection_type=injection_type,
                bytes_in=bytes_in,
                bytes_out=bytes_out,
                etag=etag,
                latency_ms=latency_ms,
                injected_delay_ms=injected_delay_ms,
            )
        except sqlite3.Error:
            logger.warning("metrics_recording_failed", request_id=request_id, bucket=bucket, outcome=outcome, exc_info=True)
        except (ValueError, TypeError):
            logger.error("metrics_recording_unexpected_error", request_id=request_id, bucket=bucket, outcome=outcome, exc_info=True)
            raise

    @staticmethod
    def _request_context() -> tuple[str, str, float]:
        return str(uuid.uuid4()), datetime.now(UTC).isoformat(), time.monotonic()

    @staticmethod
    def _elapsed_ms(start_time: float) -> float:
        return (time.monotonic() - start_time) * 1000

    @staticmethod
    def _delay_ms(delay_sec: float) -> float | None:
        return delay_sec * 1000 if delay_sec > 0 else None

    @staticmethod
    def _quoted_etag(etag: str) -> str:
        return f'"{etag}"'

    @staticmethod
    def _resource(bucket: str, key: str | None) -> str:
        return f"/{bucket}/{key}" if key is not None else f"/{bucket}"

    @staticmethod
    def _response_bytes_out(operation: BlobOperation, body: bytes) -> int:
        return 0 if operation is BlobOperation.HEAD else len(body)

    @staticmethod
    def _parse_max_keys(value: str | None) -> int:
        if value is None or value == "":
            return 1000
        try:
            max_keys = int(value)
        except ValueError:
            raise InvalidContinuationTokenError(f"invalid max-keys: {value!r}") from None
        if max_keys <= 0:
            raise InvalidContinuationTokenError(f"invalid max-keys: {value!r}")
        return min(max_keys, 1000)


class _StreamingDisconnect(Response):
    """A streaming response that disconnects before a normal end-of-message."""

    body_iterator: Any

    def __init__(
        self,
        content: Any,
        status_code: int = 200,
        media_type: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.body_iterator = content
        self.status_code = status_code
        self.media_type = media_type
        self._extra_headers = headers or {}
        self.background = None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        raw_headers = [(name.lower().encode(), value.encode()) for name, value in self._extra_headers.items()]
        if self.media_type is not None and not any(name == b"content-type" for name, _value in raw_headers):
            raw_headers.append((b"content-type", self.media_type.encode()))
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": raw_headers,
            }
        )
        async for chunk in self.body_iterator:
            await send({"type": "http.response.body", "body": chunk, "more_body": True})


def create_app(config: ChaosBlobConfig | None = None) -> Starlette:
    """Create a Starlette ASGI application from config."""
    server = ChaosBlobServer(config or ChaosBlobConfig())
    server.app.state.server = server
    return server.app
