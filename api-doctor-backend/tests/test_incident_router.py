"""Regression tests for incident workflow API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx

from app.incidents.models import Incident
from app.incidents.store import incident_store
from app.main import app
from app.orchestrator import orchestrator


async def _request(method: str, path: str, headers: dict[str, str]) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=headers)


async def test_diagnose_returns_incident_status(monkeypatch, auth_headers):
    inc = incident_store.create(Incident())
    monkeypatch.setattr(orchestrator, "start_diagnosis", lambda incident_id: True)

    response = await _request("POST", f"/api/incidents/{inc.id}/diagnose", auth_headers)

    assert response.status_code == 200
    assert response.json()["incident_id"] == inc.id
    assert response.json()["status"] == "DETECTED"


async def test_diagnose_rejects_duplicate_pipeline(monkeypatch, auth_headers):
    inc = incident_store.create(Incident())
    monkeypatch.setattr(orchestrator, "start_diagnosis", lambda incident_id: False)

    response = await _request("POST", f"/api/incidents/{inc.id}/diagnose", auth_headers)

    assert response.status_code == 409
    assert "already running" in response.json()["detail"]


async def test_cancel_endpoint_calls_orchestrator(monkeypatch, auth_headers):
    inc = incident_store.create(Incident())
    cancel = AsyncMock(return_value=True)
    monkeypatch.setattr(orchestrator, "cancel_diagnosis", cancel)

    response = await _request("POST", f"/api/incidents/{inc.id}/cancel", auth_headers)

    assert response.status_code == 200
    assert response.json() == {"incident_id": inc.id, "cancelled": True}
    cancel.assert_awaited_once_with(inc.id)


async def test_incident_response_exposes_root_cause(auth_headers):
    inc = Incident(
        root_cause={
            "root_cause": "missing null guard",
            "category": "CODE_BUG",
            "confidence": 0.87,
            "affected_files": ["app/demo_api/router.py"],
            "affected_functions": ["charge"],
            "safe_to_repair": True,
            "reason": "deterministic failure",
        }
    )
    incident_store.create(inc)

    response = await _request("GET", f"/api/incidents/{inc.id}", auth_headers)

    assert response.status_code == 200
    assert response.json()["root_cause"]["confidence"] == 0.87
    assert response.json()["root_cause"]["category"] == "CODE_BUG"
