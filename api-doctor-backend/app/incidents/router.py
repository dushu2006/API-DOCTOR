"""Incident dashboard API endpoints."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.events.hub import event_hub
from app.incidents.models import Incident, IncidentStatus
from app.incidents.schemas import (
    ApproveRequest,
    ContextResponse,
    CreatePRRequest,
    DiagnoseRequest,
    DiagnoseResponse,
    DiffResponse,
    IncidentResponse,
    PRInfoResponse,
    SandboxResponse,
    StatusResponse,
)
from app.incidents.store import incident_store
from app.orchestrator import orchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/incidents", tags=["incidents"])

SCENARIOS = {
    "external_api": ("GET", "/api/v1/external/status", None),
    "config": ("GET", "/api/v1/config", None),
    "null_pointer": ("POST", "/api/v1/users/user_2/charge", {"amount": 100.0}),
    "schema": ("GET", "/api/v1/orders/order_2", None),
}


# ---------------------------------------------------------------------------
# Listing & retrieval
# ---------------------------------------------------------------------------
@router.get("", response_model=list[IncidentResponse])
async def list_incidents(project_id: str | None = None) -> list[IncidentResponse]:
    return [IncidentResponse.from_model(i) for i in incident_store.list_all(project_id)]


@router.get("/{incident_id}", response_model=IncidentResponse)
async def get_incident(incident_id: str) -> IncidentResponse:
    inc = _get_or_404(incident_id)
    return IncidentResponse.from_model(inc)


@router.get("/{incident_id}/status", response_model=StatusResponse)
async def get_status(incident_id: str) -> StatusResponse:
    return StatusResponse.from_model(_get_or_404(incident_id))


@router.get("/{incident_id}/context", response_model=ContextResponse)
async def get_context(incident_id: str) -> ContextResponse:
    inc = _get_or_404(incident_id)
    if not inc.context:
        raise HTTPException(409, "context not built yet")
    ctx = inc.context
    return ContextResponse(
        incident_id=incident_id,
        stack_trace=ctx.get("stack_trace", ""),
        implicated_files=ctx.get("affected_files", []),
        code_snippets=ctx.get("code_snippets", {}),
        git_log=ctx.get("git_log", ""),
    )


@router.get("/{incident_id}/diff", response_model=DiffResponse)
async def get_diff(incident_id: str) -> DiffResponse:
    inc = _get_or_404(incident_id)
    fix = inc.fix_proposal
    if not fix:
        return DiffResponse(incident_id=incident_id, present=False)
    return DiffResponse(
        incident_id=incident_id,
        present=True,
        summary=fix.get("summary"),
        diff=fix.get("diff"),
        files_changed=fix.get("files_changed", []),
        risk=fix.get("risk"),
        reason=fix.get("reason"),
    )


@router.get("/{incident_id}/sandbox", response_model=SandboxResponse)
async def get_sandbox(incident_id: str) -> SandboxResponse:
    inc = _get_or_404(incident_id)
    sb = inc.sandbox_result
    if not sb:
        return SandboxResponse(incident_id=incident_id, present=False)
    return SandboxResponse(
        incident_id=incident_id,
        present=True,
        passed=sb.get("passed"),
        steps=sb.get("steps", []),
        logs=sb.get("logs", ""),
        error=sb.get("error", ""),
    )


@router.get("/{incident_id}/pr", response_model=PRInfoResponse)
async def get_pr(incident_id: str) -> PRInfoResponse:
    inc = _get_or_404(incident_id)
    if not inc.pr_info:
        return PRInfoResponse(incident_id=incident_id, present=False)
    info = inc.pr_info
    return PRInfoResponse(
        incident_id=incident_id,
        present=True,
        pr_number=info.get("pr_number"),
        pr_url=info.get("pr_url"),
        branch=info.get("branch"),
        status=info.get("status"),
        checks=None,
    )


# ---------------------------------------------------------------------------
# Workflow triggers
# ---------------------------------------------------------------------------
@router.post("/trigger/{scenario}", response_model=DiagnoseResponse)
async def trigger_scenario(scenario: str) -> DiagnoseResponse:
    if scenario not in SCENARIOS:
        raise HTTPException(400, f"unknown scenario {scenario!r}; choose from {sorted(SCENARIOS)}")
    method, path, payload = SCENARIOS[scenario]
    incident = await orchestrator.detect_and_create(path, method, payload)
    orchestrator.start_diagnosis(incident.id)
    return DiagnoseResponse(incident_id=incident.id, status=incident.status)


@router.post("/{incident_id}/diagnose", response_model=DiagnoseResponse)
async def diagnose(incident_id: str, req: DiagnoseRequest | None = None) -> DiagnoseResponse:
    inc = _get_or_404(incident_id)
    orchestrator.start_diagnosis(incident_id)
    return DiagnoseResponse(incident_id=incident_id, status=incident.status)


@router.post("/{incident_id}/approve")
async def approve(incident_id: str, req: ApproveRequest) -> dict:
    inc = _get_or_404(incident_id)
    if not inc.fix_proposal:
        raise HTTPException(409, "no fix proposal to approve yet")
    inc.add_activity("human_review", "done", "approved" if req.approved else "rejected")
    incident_store.update(inc)
    if not req.approved:
        inc.status = IncidentStatus.REPAIR_LIMIT_REACHED
        incident_store.update(inc)
        return {"incident_id": incident_id, "approved": False}
    return {"incident_id": incident_id, "approved": True}


@router.post("/{incident_id}/create-pr")
async def create_pr(incident_id: str, req: CreatePRRequest | None = None) -> dict:
    inc = _get_or_404(incident_id)
    if not (req or CreatePRRequest()).approved:
        return {"incident_id": incident_id, "approved": False}
    try:
        pr_info = await orchestrator.create_pull_request(incident_id)
    except Exception as exc:
        raise HTTPException(502, f"PR creation failed: {exc}") from exc
    return {"incident_id": incident_id, **pr_info}


@router.get("/{incident_id}/pr-status")
async def pr_status(incident_id: str) -> dict:
    _get_or_404(incident_id)
    return await orchestrator.pr_status(incident_id)


# ---------------------------------------------------------------------------
# Live activity stream (SSE)
# ---------------------------------------------------------------------------
@router.get("/{incident_id}/stream")
async def stream_incident(incident_id: str, request: Request) -> StreamingResponse:
    _get_or_404(incident_id)
    queue = event_hub.subscribe(incident_id)

    async def gen():
        try:
            # Replay existing activity first so late subscribers catch up.
            inc = incident_store.get(incident_id)
            if inc:
                for ev in inc.activity:
                    yield _sse(ev.model_dump())
            yield _sse({"type": "connected"})
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield _sse(json.loads(payload))
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            event_hub.unsubscribe(incident_id, queue)

    return StreamingResponse(gen(), media_type="text/event-stream")


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _get_or_404(incident_id: str) -> Incident:
    inc = incident_store.get(incident_id)
    if not inc:
        raise HTTPException(404, f"incident {incident_id!r} not found")
    return inc
