"""Structured application logging.

Every major operation logs the incident id, operation, status, duration and any
error. Secrets are never logged — callers must pass already-sanitised values, and
the formatter applies an extra scrub to be safe.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any

_SENSITIVE_KEYS = re.compile(
    r"(api[_-]?key|token|password|secret|authorization|cookie|jwt|"
    r"database[_-]?url|passwd|credential)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{6,}|ghp_[A-Za-z0-9]{20,}|rnd_[A-Za-z0-9]{20,}|"
    r"[A-Za-z0-9]{32,})"
)


def _scrub(obj: Any) -> Any:
    """Recursively scrub sensitive-looking values from a log payload."""
    if isinstance(obj, dict):
        return {
            k: (_scrub(v) if not _SENSITIVE_KEYS.search(str(k)) else "<REDACTED>")
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    if isinstance(obj, str):
        return _SENSITIVE_VALUE.sub("<REDACTED>", obj)
    return obj


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_obj: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "funcName": record.funcName,
            "lineno": record.lineno,
        }
        # Merge structured extras.
        extra = getattr(record, "extra", None)
        if isinstance(extra, dict):
            log_obj.update(_scrub(extra))
        if record.exc_info:
            log_obj["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers = [handler]

    for noisy in ("httpx", "httpcore", "urllib3", "docker", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_operation(
    logger: logging.Logger,
    incident_id: str,
    operation: str,
    status: str,
    duration: float | None = None,
    error: str | None = None,
    **extra: Any,
) -> None:
    """Log a structured operation record for an incident."""
    record: dict[str, Any] = {
        "incident_id": incident_id,
        "operation": operation,
        "status": status,
    }
    if duration is not None:
        record["duration_s"] = round(duration, 4)
    if error:
        record["error"] = error
    record.update(extra)
    level = logging.ERROR if status in ("failed", "error") else logging.INFO
    logger.log(level, operation, extra=record)
