"""Regression tests for run workflow API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx

from app.runs.models import Run, RunStatus
from app.runs.store import run_store
from app.main import app
from app.orchestrator import orchestrator


async def _request(method: str, path: str, headers: dict[str, str], **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=headers, **kwargs)


async def test_current_endpoint_has_no_history(authenticated_user):
    user, headers = authenticated_user
    first = run_store.create(Run(owner_id=user.id))
    second = run_store.create(Run(owner_id=user.id))

    current = await _request("GET", "/api/diagnosis/current", headers)
    assert current.status_code == 200
    assert current.json()["id"] == second.id
    assert run_store.get(first.id) is None

    cleared = await _request("DELETE", "/api/diagnosis/current", headers)
    assert cleared.status_code == 200
    assert cleared.json()["cleared"] is True
    assert run_store.get(second.id) is None
    assert (await _request("GET", "/api/diagnosis/current", headers)).json() is None


async def test_diagnose_returns_run_status(monkeypatch, auth_headers):
    run = run_store.create(Run())
    monkeypatch.setattr(orchestrator, "start_diagnosis", lambda run_id: True)

    response = await _request("POST", f"/api/diagnosis/{run.id}/diagnose", auth_headers)

    assert response.status_code == 200
    assert response.json()["run_id"] == run.id
    assert response.json()["status"] == "DETECTED"


async def test_diagnose_rejects_duplicate_pipeline(monkeypatch, auth_headers):
    run = run_store.create(Run())
    monkeypatch.setattr(orchestrator, "start_diagnosis", lambda run_id: False)

    response = await _request("POST", f"/api/diagnosis/{run.id}/diagnose", auth_headers)

    assert response.status_code == 409
    assert "already running" in response.json()["detail"]


async def test_cancel_endpoint_calls_orchestrator(monkeypatch, auth_headers):
    run = run_store.create(Run())
    cancel = AsyncMock(return_value=True)
    monkeypatch.setattr(orchestrator, "cancel_diagnosis", cancel)

    response = await _request("POST", f"/api/diagnosis/{run.id}/cancel", auth_headers)

    assert response.status_code == 200
    assert response.json() == {"run_id": run.id, "cancelled": True}
    cancel.assert_awaited_once_with(run.id)


async def test_run_response_exposes_root_cause(auth_headers):
    run = Run(
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
    run_store.create(run)

    response = await _request("GET", f"/api/diagnosis/{run.id}", auth_headers)

    assert response.status_code == 200
    assert response.json()["root_cause"]["confidence"] == 0.87
    assert response.json()["root_cause"]["category"] == "CODE_BUG"


async def test_cancel_endpoint_rejects_when_orchestrator_returns_false(monkeypatch, auth_headers):
    run = run_store.create(Run(status=RunStatus.CANCELLED))
    monkeypatch.setattr(orchestrator, "cancel_diagnosis", AsyncMock(return_value=False))

    response = await _request("POST", f"/api/diagnosis/{run.id}/cancel", auth_headers)

    assert response.status_code == 409
    assert "no active diagnosis to cancel" in response.json()["detail"]


async def test_approve_file_read_calls_resume(monkeypatch, auth_headers):
    run = run_store.create(Run(status=RunStatus.AWAITING_FILE_READ_APPROVAL))
    resume = AsyncMock(return_value=True)
    monkeypatch.setattr(orchestrator, "resume_file_read", resume)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/diagnosis/{run.id}/approve-file-read",
            headers=auth_headers,
            json={"approved": True},
        )

    assert response.status_code == 200
    assert response.json() == {"run_id": run.id, "approved": True}
    resume.assert_awaited_once_with(run.id)


async def test_approve_file_read_is_idempotent_after_resume(auth_headers):
    run = run_store.create(Run(status=RunStatus.COLLECTING_CONTEXT))
    run.add_activity("file_read_approval", "done", "User approved file reading")
    run_store.update(run)

    response = await _request(
        "POST", f"/api/diagnosis/{run.id}/approve-file-read", auth_headers,
        json={"approved": True},
    )

    assert response.status_code == 200
    assert response.json()["already_processed"] is True


async def test_approve_fix_calls_resume(monkeypatch, auth_headers):
    run = run_store.create(Run(status=RunStatus.AWAITING_FIX_APPROVAL))
    stage = AsyncMock(return_value={"applied": True, "files": ["main.py"]})
    resume = AsyncMock(return_value=True)
    monkeypatch.setattr(orchestrator, "stage_workspace_apply", stage)
    monkeypatch.setattr(orchestrator, "resume_fix", resume)

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/diagnosis/{run.id}/approve-fix",
            headers=auth_headers,
            json={"approved": True},
        )

    assert response.status_code == 200
    assert response.json() == {"run_id": run.id, "approved": True}
    stage.assert_awaited_once_with(run.id)
    resume.assert_awaited_once_with(run.id)


async def test_approve_fix_does_not_resume_when_workspace_apply_fails(
    monkeypatch, auth_headers
):
    run = run_store.create(Run(status=RunStatus.AWAITING_FIX_APPROVAL))
    stage = AsyncMock(return_value={
        "applied": False,
        "reason": "File changed since diagnosis — patch refused for safety.",
    })
    resume = AsyncMock(return_value=True)
    monkeypatch.setattr(orchestrator, "stage_workspace_apply", stage)
    monkeypatch.setattr(orchestrator, "resume_fix", resume)

    response = await _request(
        "POST",
        f"/api/diagnosis/{run.id}/approve-fix",
        auth_headers,
        json={"approved": True},
    )

    assert response.status_code == 409
    assert "File changed since diagnosis" in response.json()["detail"]
    resume.assert_not_awaited()


async def test_restart_returns_fresh_run(monkeypatch, auth_headers):
    original = run_store.create(Run(status=RunStatus.FIX_VERIFIED))
    fresh = Run(project_id=original.project_id, status=RunStatus.RECEIVED)
    restart = AsyncMock(return_value=fresh)
    monkeypatch.setattr(orchestrator, "restart", restart)

    response = await _request(
        "POST", f"/api/diagnosis/{original.id}/restart", auth_headers
    )

    assert response.status_code == 200
    assert response.json()["run_id"] == fresh.id
    assert response.json()["status"] == "RECEIVED"
    restart.assert_awaited_once_with(original.id)

