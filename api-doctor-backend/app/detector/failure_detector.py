"""Failure detection.

The detector watches the "patient" demo API and, on a failed request, emits a
structured :class:`DetectionResult`. The shape is provider-agnostic so a Render
log source (or Sentry/CloudWatch) can produce the exact same incident format
later.

Two transports are supported:
    * ``in-process`` (default): calls the FastAPI app over an ASGI transport so
      the demo is fully self-contained and deterministic.
    * ``http``: calls ``settings.DEMO_API_BASE_URL`` (e.g. a deployed Render
      service). The served app must expose tracebacks on 5xx for this to work.
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Literal

import httpx

from app.core.config import settings
from app.security.sanitizer import sanitize

logger = logging.getLogger(__name__)

Method = Literal["GET", "POST", "PUT", "DELETE", "PATCH"]


class DetectionResult(dict):
    """Structured incident-ready detection payload.

    Used as a plain dict but typed for clarity. Fields follow the spec:
    HTTP status, error message, traceback, endpoint, timestamp, service,
    request information, relevant response information.
    """


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_detection(
    *,
    status_code: int,
    error_message: str,
    stack_trace: str,
    method: Method,
    path: str,
    body: Any,
    headers: dict[str, str] | None,
    response_snapshot: dict[str, Any],
    service: str,
) -> DetectionResult:
    return DetectionResult(
        error=True,
        status_code=status_code,
        error_message=error_message,
        stack_trace=stack_trace,
        endpoint=path,
        method=method,
        timestamp=_now_iso(),
        service=service,
        request_snapshot=sanitize(
            {"method": method, "path": path, "body": body, "headers": headers}
        ),
        response_snapshot=sanitize(response_snapshot),
    )


class FailureDetector:
    def __init__(self) -> None:
        self.service = "demo-api"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def trigger_diagnosis(
        self,
        endpoint: str,
        method: Method = "GET",
        payload: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> DetectionResult:
        """Exercise the demo API and capture the failure (if any)."""
        try:
            response = await self._call(endpoint, method, payload, headers)
        except Exception as exc:  # transport-level failure
            return _build_detection(
                status_code=0,
                error_message=str(exc),
                stack_trace=traceback.format_exc(),
                method=method,
                path=endpoint,
                body=payload,
                headers=headers,
                response_snapshot={"error": "transport failure"},
                service=self.service,
            )

        status_code = response.status_code
        try:
            resp_json = response.json()
        except Exception:
            resp_json = {"body": response.text}

        if status_code < 400:
            return DetectionResult(
                error=False,
                status_code=status_code,
                endpoint=endpoint,
                method=method,
                timestamp=_now_iso(),
                service=self.service,
                request_snapshot=sanitize(
                    {"method": method, "path": endpoint, "body": payload}
                ),
                response_snapshot=sanitize(resp_json),
            )

        error_message = str(resp_json.get("detail") or resp_json.get("message") or "error")
        stack_trace = resp_json.get("traceback") or ""

        # Fallback: if the served app didn't return a traceback, try to
        # reconstruct one from the current stack (in-process mode always
        # returns one via the app's exception handler).
        if not stack_trace:
            logger.warning(
                "No traceback returned for %s %s (status=%s). Provide a log-source "
                "traceback or enable debug tracebacks on the served app.",
                method, endpoint, status_code,
            )

        return _build_detection(
            status_code=status_code,
            error_message=error_message,
            stack_trace=stack_trace,
            method=method,
            path=endpoint,
            body=payload,
            headers=headers,
            response_snapshot={"status_code": status_code, "body": resp_json},
            service=self.service,
        )

    async def detect_from_log(
        self,
        *,
        message: str,
        traceback: str,
        service: str,
        endpoint: str | None = None,
        status_code: int | None = None,
        timestamp: str | None = None,
        **extra: Any,
    ) -> DetectionResult:
        """Adapter: build an identical incident from an external log source.

        This is the seam where a Render log source (or Sentry / CloudWatch)
        plugs in later.
        """
        return DetectionResult(
            error=True,
            status_code=status_code or 500,
            error_message=message,
            stack_trace=traceback,
            endpoint=endpoint or "",
            method="GET",
            timestamp=timestamp or _now_iso(),
            service=service,
            request_snapshot=sanitize(extra.get("request_snapshot") or {}),
            response_snapshot=sanitize(extra.get("response_snapshot") or {}),
        )

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    async def _call(
        self,
        endpoint: str,
        method: Method,
        payload: dict | None,
        headers: dict[str, str] | None,
    ) -> httpx.Response:
        if settings.DEMO_API_BASE_URL:
            return await self._call_http(endpoint, method, payload, headers)
        return await self._call_inprocess(endpoint, method, payload, headers)

    async def _call_http(
        self,
        endpoint: str,
        method: Method,
        payload: dict | None,
        headers: dict[str, str] | None,
    ) -> httpx.Response:
        url = settings.DEMO_API_BASE_URL.rstrip("/") + endpoint
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            request = client.build_request(method, url, json=payload, headers=headers)
            return await client.send(request)

    async def _call_inprocess(
        self,
        endpoint: str,
        method: Method,
        payload: dict | None,
        headers: dict[str, str] | None,
    ) -> httpx.Response:
        from app.main import app  # lazy import to avoid circular imports

        # raise_app_exceptions=False so the app's 500 (with traceback) is returned
        # to us as a normal response rather than re-raised by the transport.
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", timeout=30.0
        ) as client:
            request = client.build_request(method, endpoint, json=payload, headers=headers)
            return await client.send(request)
