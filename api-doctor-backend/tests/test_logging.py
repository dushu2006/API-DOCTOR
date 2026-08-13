"""Structured operation logs must include run id, status and error."""

from __future__ import annotations

import json
import logging

from app.core.logging_config import JsonFormatter, log_operation


def _emit(logger: logging.Logger, **kwargs) -> dict:
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        log_operation(logger, "run-123", "root_cause", **kwargs)
    finally:
        logger.removeHandler(handler)

    assert records, "expected a log record"
    return json.loads(handler.format(records[0]))


def test_failed_operation_includes_error_in_json():
    payload = _emit(
        logging.getLogger("test.logging.fail"),
        status="failed",
        error="root cause analysis failed: content is None",
        duration=68.02,
    )
    assert payload["message"] == "root_cause"
    assert payload["level"] == "ERROR"
    assert payload["run_id"] == "run-123"
    assert payload["operation"] == "root_cause"
    assert payload["status"] == "failed"
    assert payload["error"] == "root cause analysis failed: content is None"
    assert payload["duration_s"] == 68.02


def test_ok_operation_is_info_without_error_field():
    payload = _emit(
        logging.getLogger("test.logging.ok"),
        status="ok",
        duration=1.25,
    )
    assert payload["level"] == "INFO"
    assert payload["status"] == "ok"
    assert "error" not in payload
