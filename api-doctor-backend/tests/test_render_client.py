"""Tests for the Render client (HTTP mocked)."""

from __future__ import annotations

import re

import pytest

from app.render.client import (
    RenderAuthError,
    RenderClient,
    RenderError,
    RenderNetworkError,
    RenderNotFoundError,
    RenderRateLimitError,
    normalize_log_entry,
)

SERVICE_URL = re.compile(r"^https://api\.render\.com/v1/services/srv_test(?:\?.*)?$")
LOGS_URL = re.compile(r"^https://api\.render\.com/v1/logs(?:\?.*)?$")
DEPLOYS_URL = re.compile(r"^https://api\.render\.com/v1/services/srv_test/deploys(?:\?.*)?$")
OLD_LOGS_URL = re.compile(r"^https://api\.render\.com/v1/services/srv_test/logs")


def _render_client(**overrides) -> RenderClient:
    """Build a client with explicit project-scoped test credentials."""
    config = {
        "api_key": "test-render-key",
        "service_id": "srv_test",
        "owner_id": "tea_owner",
    }
    config.update(overrides)
    return RenderClient(**config)


def _service_payload() -> dict:
    return {"id": "srv_test", "name": "demo", "ownerId": "tea_owner"}


def _logs_payload(messages: list[str], has_more: bool = False) -> dict:
    return {
        "hasMore": has_more,
        "nextStartTime": "2026-08-12T07:00:00Z" if has_more else None,
        "nextEndTime": "2026-08-12T08:00:00Z" if has_more else None,
        "logs": [
            {
                "id": f"log-{i}",
                "message": msg,
                "timestamp": "2026-08-12T08:00:00Z",
                "labels": [{"name": "resource", "value": "srv_test"}, {"name": "type", "value": "app"}],
            }
            for i, msg in enumerate(messages)
        ],
    }


async def test_get_service(httpx_mock):
    client = _render_client()
    httpx_mock.add_response(url=SERVICE_URL, method="GET", json=_service_payload())
    service = await client.get_service()
    assert service["name"] == "demo"
    assert service["ownerId"] == "tea_owner"


async def test_list_deployments_unwraps_cursor_items(httpx_mock):
    client = _render_client()
    httpx_mock.add_response(
        url=DEPLOYS_URL,
        method="GET",
        json=[{"deploy": {"id": "dep1", "status": "live"}, "cursor": "abc"}],
    )
    deploys = await client.list_deployments()
    assert deploys[0]["status"] == "live"


async def test_get_deployment_status(httpx_mock):
    client = _render_client()
    httpx_mock.add_response(
        url=DEPLOYS_URL,
        method="GET",
        json=[{"id": "dep1", "status": "live", "createdAt": "2026-01-01"}],
    )
    status = await client.get_deployment_status()
    assert status["present"] is True
    assert status["status"] == "live"


async def test_missing_key_raises():
    client = RenderClient(api_key="")
    with pytest.raises(RenderError):
        await client.get_service()


async def test_error_raises(httpx_mock):
    client = _render_client()
    httpx_mock.add_response(url=SERVICE_URL, method="GET", status_code=500, json={})
    with pytest.raises(RenderError):
        await client.get_service()


async def test_get_logs_uses_official_logs_endpoint(httpx_mock):
    client = _render_client()
    httpx_mock.add_response(url=SERVICE_URL, method="GET", json=_service_payload())
    httpx_mock.add_response(
        url=LOGS_URL,
        method="GET",
        json=_logs_payload(["Traceback (most recent call last):", "ValueError: boom"]),
    )
    logs = await client.get_logs()
    assert len(logs) == 2
    assert logs[0]["message"].startswith("Traceback")
    requests = httpx_mock.get_requests()
    log_requests = [r for r in requests if "/logs" in str(r.url) and "/services/" not in str(r.url)]
    assert log_requests, "expected GET /v1/logs"
    assert "ownerId=tea_owner" in str(log_requests[0].url)
    assert "resource=srv_test" in str(log_requests[0].url)
    assert not any("/services/srv_test/logs" in str(r.url) for r in requests)


async def test_get_logs_does_not_swallow_404(httpx_mock):
    client = _render_client()
    httpx_mock.add_response(url=SERVICE_URL, method="GET", json=_service_payload())
    httpx_mock.add_response(url=LOGS_URL, method="GET", status_code=404, text="not found")
    with pytest.raises(RenderNotFoundError):
        await client.get_logs()


async def test_get_logs_auth_error(httpx_mock):
    client = _render_client()
    httpx_mock.add_response(url=SERVICE_URL, method="GET", status_code=401, text="unauthorized")
    with pytest.raises(RenderAuthError):
        await client.get_logs()


async def test_get_logs_forbidden(httpx_mock):
    client = _render_client()
    httpx_mock.add_response(url=SERVICE_URL, method="GET", status_code=403, text="forbidden")
    with pytest.raises(RenderAuthError) as exc:
        await client.get_logs()
    assert exc.value.status_code == 403


async def test_get_logs_rate_limit(httpx_mock):
    client = _render_client()
    httpx_mock.add_response(url=SERVICE_URL, method="GET", json=_service_payload())
    httpx_mock.add_response(url=LOGS_URL, method="GET", status_code=429, text="slow down")
    httpx_mock.add_response(url=LOGS_URL, method="GET", status_code=429, text="slow down")
    with pytest.raises(RenderRateLimitError):
        await client.get_logs()


async def test_get_logs_empty_success(httpx_mock):
    client = _render_client()
    httpx_mock.add_response(url=SERVICE_URL, method="GET", json=_service_payload())
    httpx_mock.add_response(url=LOGS_URL, method="GET", json=_logs_payload([]))
    httpx_mock.add_response(url=LOGS_URL, method="GET", json=_logs_payload([]))
    result = await client.fetch_runtime_logs()
    assert result.status == "success"
    assert result.logs == []
    assert result.log_count == 0


async def test_get_logs_paginates(httpx_mock):
    client = _render_client()
    httpx_mock.add_response(url=SERVICE_URL, method="GET", json=_service_payload())
    httpx_mock.add_response(url=LOGS_URL, method="GET", json=_logs_payload(["line-1"], has_more=True))
    httpx_mock.add_response(url=LOGS_URL, method="GET", json=_logs_payload(["line-2"], has_more=False))
    logs = await client.get_logs(limit=50)
    assert [entry["message"] for entry in logs] == ["line-1", "line-2"]


async def test_get_logs_invalid_service(httpx_mock):
    client = _render_client()
    httpx_mock.add_response(url=SERVICE_URL, method="GET", status_code=404, text="missing")
    with pytest.raises(RenderNotFoundError):
        await client.get_logs()


async def test_normalize_log_entry_from_labels():
    entry = normalize_log_entry(
        {
            "id": "1",
            "message": "GET /checkout 500",
            "timestamp": "2026-08-12T00:00:00Z",
            "labels": [
                {"name": "statusCode", "value": "500"},
                {"name": "method", "value": "GET"},
                {"name": "path", "value": "/checkout"},
            ],
        }
    )
    assert entry["statusCode"] == "500"
    assert entry["path"] == "/checkout"
    assert entry["message"] == "GET /checkout 500"


async def test_unexpected_logs_payload_raises(httpx_mock):
    client = _render_client()
    httpx_mock.add_response(url=SERVICE_URL, method="GET", json=_service_payload())
    httpx_mock.add_response(url=LOGS_URL, method="GET", json={"unexpected": True})
    with pytest.raises(RenderError, match="unexpected payload"):
        await client.get_logs()
