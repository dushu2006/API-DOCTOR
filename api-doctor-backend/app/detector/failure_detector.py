"""Failure detection and log ingestion pipeline.

Parses real production logs (Render, CI failures, manual logs) and HTTP responses
to detect and group failures into structured Incident detections.
"""

from __future__ import annotations

import logging
import re
import traceback
from datetime import datetime, timezone
from typing import Any, Literal

import httpx

from app.security.sanitizer import redact_text, sanitize

logger = logging.getLogger(__name__)

Method = Literal["GET", "POST", "PUT", "DELETE", "PATCH"]


class DetectionResult(dict):
    """Structured incident-ready detection payload."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_detection(
    *,
    status_code: int,
    error_message: str,
    stack_trace: str,
    method: Method | str = "GET",
    path: str = "",
    body: Any = None,
    headers: dict[str, str] | None = None,
    response_snapshot: dict[str, Any] | None = None,
    service: str = "production",
    source: str = "manual",
    raw_logs: str = "",
) -> DetectionResult:
    safe_error_message = redact_text(str(error_message or ""))
    safe_stack_trace = redact_text(str(stack_trace or ""))
    safe_raw_logs = redact_text(str(raw_logs or ""))
    return DetectionResult(
        error=True,
        status_code=status_code,
        error_message=safe_error_message,
        stack_trace=safe_stack_trace,
        endpoint=path,
        method=method,
        timestamp=_now_iso(),
        service=service,
        source=source,
        raw_logs=safe_raw_logs,
        request_snapshot=sanitize(
            {"method": method, "path": path, "body": body, "headers": headers}
        ),
        response_snapshot=sanitize(response_snapshot or {}),
    )


# Patterns to detect start of error blocks
_TRACEBACK_START = re.compile(r"Traceback \(most recent call last\):", re.IGNORECASE)
_HTTP_ERROR_LINE = re.compile(r"(?:HTTP\s+|status\s*=?\s*|code\s*=?\s*)([45]\d\d)|(5\d\d\s+Internal\s+Server\s+Error)", re.IGNORECASE)
_EXCEPTION_LINE = re.compile(r"(?:Exception|Error|FATAL|CRITICAL):\s*(.+)", re.IGNORECASE)


class FailureDetector:
    def __init__(self, service: str = "production") -> None:
        self.service = service

    def detect_from_logs(
        self,
        logs: list[dict] | str,
        service: str | None = None,
        source: str = "render",
    ) -> list[DetectionResult]:
        """Parse raw log lines and group related error lines into coherent incidents.

        Avoids treating every individual log line as an isolated incident.
        """
        svc = service or self.service
        raw_text_lines: list[str] = []

        if isinstance(logs, str):
            raw_text_lines = logs.splitlines()
        elif isinstance(logs, list):
            for entry in logs:
                if isinstance(entry, dict):
                    msg = entry.get("message") or entry.get("text") or entry.get("log", {}).get("message", "")
                    if msg:
                        raw_text_lines.append(str(msg))
                elif isinstance(entry, str):
                    raw_text_lines.append(entry)

        if not raw_text_lines:
            return []

        results: list[DetectionResult] = []
        i = 0
        n = len(raw_text_lines)

        while i < n:
            line = raw_text_lines[i]
            # 1. Detect Python traceback block
            if "Traceback (most recent call last):" in line:
                trace_lines = [line]
                i += 1
                while i < n:
                    curr = raw_text_lines[i]
                    trace_lines.append(curr)
                    # Python tracebacks end with the exception line (e.g. TypeError: ...)
                    if curr and not curr.startswith(" ") and not curr.startswith("\t") and ":" in curr:
                        break
                    i += 1
                full_trace = "\n".join(trace_lines)
                last_line = trace_lines[-1] if trace_lines else line
                results.append(
                    _build_detection(
                        status_code=500,
                        error_message=last_line.strip() or "Unhandled traceback exception",
                        stack_trace=full_trace,
                        service=svc,
                        source=source,
                        raw_logs=full_trace,
                    )
                )
                i += 1
                continue

            # 2. Detect JS / Node / Java stack trace block
            if any(marker in line for marker in ["TypeError:", "ReferenceError:", "SyntaxError:", "UnhandledPromiseRejection:", "Exception in thread", "NullPointerException"]):
                trace_lines = [line]
                i += 1
                while i < n and (raw_text_lines[i].strip().startswith("at ") or "Caused by:" in raw_text_lines[i]):
                    trace_lines.append(raw_text_lines[i])
                    i += 1
                full_trace = "\n".join(trace_lines)
                results.append(
                    _build_detection(
                        status_code=500,
                        error_message=line.strip(),
                        stack_trace=full_trace,
                        service=svc,
                        source=source,
                        raw_logs=full_trace,
                    )
                )
                continue

            # 3. Detect HTTP 5xx or 4xx failures in logs
            http_match = _HTTP_ERROR_LINE.search(line)
            if http_match:
                code_str = http_match.group(1) or "500"
                try:
                    code = int(code_str)
                except ValueError:
                    code = 500
                # Extract endpoint if present
                ep_match = re.search(r'(?:GET|POST|PUT|DELETE|PATCH)\s+([/\w\-._~:?#[\]@!$&\'()*+,;=]+)', line)
                endpoint = ep_match.group(1) if ep_match else ""
                method = ep_match.group(0).split()[0] if ep_match else "GET"

                results.append(
                    _build_detection(
                        status_code=code,
                        error_message=line.strip(),
                        stack_trace=line.strip(),
                        method=method,
                        path=endpoint,
                        service=svc,
                        source=source,
                        raw_logs=line.strip(),
                    )
                )
                i += 1
                continue

            # 4. Detect Database / Connection / Timeout errors
            if any(crit in line.lower() for crit in ["connectionrefusederror", "operationalerror", "timeout expired", "timed out", "failed to connect to database", "econnrefused"]):
                results.append(
                    _build_detection(
                        status_code=503,
                        error_message=line.strip(),
                        stack_trace=line.strip(),
                        service=svc,
                        source=source,
                        raw_logs=line.strip(),
                    )
                )
                i += 1
                continue

            i += 1

        return results

    async def detect_from_log(
        self,
        *,
        message: str,
        traceback: str,
        service: str,
        endpoint: str | None = None,
        status_code: int | None = None,
        timestamp: str | None = None,
        source: str = "manual",
        **extra: Any,
    ) -> DetectionResult:
        """Create a structured detection result from external/manual log parameters."""
        return DetectionResult(
            error=True,
            status_code=status_code or 500,
            error_message=message,
            stack_trace=traceback,
            endpoint=endpoint or "",
            method=extra.get("method") or "GET",
            timestamp=timestamp or _now_iso(),
            service=service,
            source=source,
            raw_logs=traceback or message,
            request_snapshot=sanitize(extra.get("request_snapshot") or {}),
            response_snapshot=sanitize(extra.get("response_snapshot") or {}),
        )

    # ------------------------------------------------------------------
    # Demo / Testing Trigger
    # ------------------------------------------------------------------
    async def trigger_diagnosis(
        self,
        endpoint: str,
        method: Method = "GET",
        payload: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> DetectionResult:
        """Exercise the demo API or in-process server for automated tests."""
        try:
            response = await self._call(endpoint, method, payload, headers)
        except Exception as exc:
            return _build_detection(
                status_code=0,
                error_message=str(exc),
                stack_trace=traceback.format_exc(),
                method=method,
                path=endpoint,
                body=payload,
                headers=headers,
                response_snapshot={"error": "transport failure"},
                service="demo-api",
                source="demo",
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
                service="demo-api",
                source="demo",
                request_snapshot=sanitize(
                    {"method": method, "path": endpoint, "body": payload}
                ),
                response_snapshot=sanitize(resp_json),
            )

        error_message = str(resp_json.get("detail") or resp_json.get("message") or "error")
        stack_trace = resp_json.get("traceback") or ""

        return _build_detection(
            status_code=status_code,
            error_message=error_message,
            stack_trace=stack_trace,
            method=method,
            path=endpoint,
            body=payload,
            headers=headers,
            response_snapshot={"status_code": status_code, "body": resp_json},
            service="demo-api",
            source="demo",
        )

    async def _call(
        self,
        endpoint: str,
        method: Method,
        payload: dict | None,
        headers: dict[str, str] | None,
    ) -> httpx.Response:
        from app.main import app

        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", timeout=30.0
        ) as client:
            request = client.build_request(method, endpoint, json=payload, headers=headers)
            return await client.send(request)
