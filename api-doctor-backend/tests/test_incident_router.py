"""Regression tests for incident workflow API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx

from app.incidents.models import Incident, IncidentStatus
from app.incidents.store import incident_store
from app.main import app
from app.orchestrator import orchestrator


async def _request(method: str, path: str, headers: dict[str, str], **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=headers, **kwargs)


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


async def test_cancel_endpoint_rejects_when_orchestrator_returns_false(monkeypatch, auth_headers):
    inc = incident_store.create(Incident(status=IncidentStatus.CANCELLED))
    monkeypatch.setattr(orchestrator, "cancel_diagnosis", AsyncMock(return_value=False))

    response = await _request("POST", f"/api/incidents/{inc.id}/cancel", auth_headers)

    assert response.status_code == 409
    assert "no active diagnosis to cancel" in response.json()["detail"]


async def test_approve_file_read_calls_resume(monkeypatch, auth_headers):
    inc = incident_store.create(Incident(status=IncidentStatus.AWAITING_FILE_READ_APPROVAL))
    resume = AsyncMock(return_value=True)
    monkeypatch.setattr(orchestrator, "resume_file_read", resume)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/incidents/{inc.id}/approve-file-read",
            headers=auth_headers,
            json={"approved": True},
        )

    assert response.status_code == 200
    assert response.json() == {"incident_id": inc.id, "approved": True}
    resume.assert_awaited_once_with(inc.id)


async def test_approve_file_read_is_idempotent_after_resume(auth_headers):
    inc = incident_store.create(Incident(status=IncidentStatus.COLLECTING_CONTEXT))
    inc.add_activity("file_read_approval", "done", "User approved file reading")
    incident_store.update(inc)

    response = await _request(
        "POST", f"/api/incidents/{inc.id}/approve-file-read", auth_headers,
        json={"approved": True},
    )

    assert response.status_code == 200
    assert response.json()["already_processed"] is True


async def test_approve_fix_calls_resume(monkeypatch, auth_headers):
    inc = incident_store.create(Incident(status=IncidentStatus.AWAITING_FIX_APPROVAL))
    stage = AsyncMock(return_value={"applied": True, "files": ["main.py"]})
    resume = AsyncMock(return_value=True)
    monkeypatch.setattr(orchestrator, "stage_workspace_apply", stage)
    monkeypatch.setattr(orchestrator, "resume_fix", resume)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/incidents/{inc.id}/approve-fix",
            headers=auth_headers,
            json={"approved": True},
        )

    assert response.status_code == 200
    assert response.json() == {"incident_id": inc.id, "approved": True}
    stage.assert_awaited_once_with(inc.id)
    resume.assert_awaited_once_with(inc.id)


async def test_approve_fix_allows_explicit_read_only_demo_skip(
    monkeypatch, auth_headers
):
    inc = incident_store.create(Incident(status=IncidentStatus.AWAITING_FIX_APPROVAL))
    stage = AsyncMock(return_value={
        "applied": False,
        "skipped": True,
        "reason": "demo workspace is read-only",
    })
    resume = AsyncMock(return_value=True)
    monkeypatch.setattr(orchestrator, "stage_workspace_apply", stage)
    monkeypatch.setattr(orchestrator, "resume_fix", resume)

    response = await _request(
        "POST",
        f"/api/incidents/{inc.id}/approve-fix",
        auth_headers,
        json={"approved": True},
    )

    assert response.status_code == 200
    resume.assert_awaited_once_with(inc.id)


async def test_approve_fix_does_not_resume_when_workspace_apply_fails(
    monkeypatch, auth_headers
):
    inc = incident_store.create(Incident(status=IncidentStatus.AWAITING_FIX_APPROVAL))
    stage = AsyncMock(return_value={
        "applied": False,
        "reason": "File changed since diagnosis — patch refused for safety.",
    })
    resume = AsyncMock(return_value=True)
    monkeypatch.setattr(orchestrator, "stage_workspace_apply", stage)
    monkeypatch.setattr(orchestrator, "resume_fix", resume)

    response = await _request(
        "POST",
        f"/api/incidents/{inc.id}/approve-fix",
        auth_headers,
        json={"approved": True},
    )

    assert response.status_code == 409
    assert "File changed since diagnosis" in response.json()["detail"]
    resume.assert_not_awaited()


async def test_rediagnose_returns_fresh_incident(monkeypatch, auth_headers):
    original = incident_store.create(Incident(status=IncidentStatus.FIX_VERIFIED))
    fresh = Incident(project_id=original.project_id, status=IncidentStatus.RECEIVED)
    rediagnose = AsyncMock(return_value=fresh)
    monkeypatch.setattr(orchestrator, "rediagnose", rediagnose)

    response = await _request(
        "POST", f"/api/incidents/{original.id}/rediagnose", auth_headers
    )

    assert response.status_code == 200
    assert response.json()["incident_id"] == fresh.id
    assert response.json()["status"] == "RECEIVED"
    rediagnose.assert_awaited_once_with(original.id)

