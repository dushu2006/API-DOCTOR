"""Tests for the Render client (HTTP mocked)."""

from __future__ import annotations

import pytest

from app.render.client import RenderClient, RenderError


async def test_get_service(httpx_mock):
    client = RenderClient()
    httpx_mock.add_response(
        url="https://api.render.com/v1/services/srv_test", method="GET",
        json={"id": "srv_test", "name": "demo"},
    )
    service = await client.get_service()
    assert service["name"] == "demo"


async def test_list_deployments(httpx_mock):
    client = RenderClient()
    httpx_mock.add_response(
        url="https://api.render.com/v1/services/srv_test/deploys?limit=10", method="GET",
        json=[{"id": "dep1", "status": "live"}],
    )
    deploys = await client.list_deployments()
    assert deploys[0]["status"] == "live"


async def test_get_deployment_status(httpx_mock):
    client = RenderClient()
    httpx_mock.add_response(
        url="https://api.render.com/v1/services/srv_test/deploys?limit=1", method="GET",
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
    client = RenderClient()
    httpx_mock.add_response(
        url="https://api.render.com/v1/services/srv_test", method="GET", status_code=500, json={}
    )
    with pytest.raises(RenderError):
        await client.get_service()
