"""Tests for demo API failures and the failure detector."""

from __future__ import annotations

import pytest

from app.detector.failure_detector import FailureDetector


@pytest.mark.asyncio
async def test_healthy_endpoint_returns_no_error():
    det = FailureDetector()
    result = await det.trigger_diagnosis("/api/v1/health", "GET", None)
    assert result.get("error") is False
    assert result.get("status_code") == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint,method,payload",
    [
        ("/api/v1/external/status", "GET", None),          # external API failure
        ("/api/v1/config", "GET", None),                    # config/env failure
        ("/api/v1/users/user_2/charge", "POST", {"amount": 100}),  # runtime
        ("/api/v1/orders/order_2", "GET", None),            # schema mismatch
    ],
)
async def test_bug_scenarios_produce_detection(endpoint, method, payload):
    det = FailureDetector()
    result = await det.trigger_diagnosis(endpoint, method, payload)
    assert result.get("error") is True
    assert result.get("status_code") == 500
    assert result.get("endpoint") == endpoint
    assert result.get("method") == method
    assert result.get("service") == "demo-api"
    assert result.get("timestamp")
    # Public HTTP responses deliberately omit server tracebacks. Production
    # diagnosis gets details from connected provider logs instead.
    assert result.get("stack_trace") == ""
    assert result.get("error_message") == "Internal server error"
    assert result.get("request_snapshot", {}).get("path") == endpoint


@pytest.mark.asyncio
async def test_null_pointer_detection_does_not_leak_traceback_to_http_clients():
    det = FailureDetector()
    result = await det.trigger_diagnosis("/api/v1/users/user_2/charge", "POST", {"amount": 100})
    assert result.get("status_code") == 500
    assert result.get("stack_trace") == ""
    assert result.get("error_message") == "Internal server error"


@pytest.mark.asyncio
async def test_detect_from_log_adapter():
    det = FailureDetector()
    result = await det.detect_from_log(
        message="boom",
        traceback="Traceback ...\nValueError: boom",
        service="render-demo",
        endpoint="/x",
        status_code=500,
        request_snapshot={"method": "GET"},
    )
    assert result["error"] is True
    assert result["service"] == "render-demo"
    assert result["status_code"] == 500
    assert result["stack_trace"] == "Traceback ...\nValueError: boom"
