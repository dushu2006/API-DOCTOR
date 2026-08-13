"""Incident dashboard and ingestion API endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.auth.dependencies import require_authenticated_user
from app.auth.schemas import UserResponse
from app.context_builder.context_builder import ContextBuilder
from app.core.config import settings
from app.detector.failure_detector import FailureDetector
from app.events.hub import event_hub
from app.incidents.models import Incident, IncidentStatus
from app.incidents.schemas import (
    ApproveRequest,
    ContextResponse,
    CreatePRRequest,
    DiagnoseRequest,
    DiagnoseResponse,
    DiffFilePreview,
    DiffResponse,
    IncidentResponse,
    IngestIncidentRequest,
    PRInfoResponse,
    SandboxResponse,
    StatusResponse,
)
from app.incidents.store import incident_store
from app.integrations.factory import get_log_provider
from app.orchestrator import orchestrator
from app.projects.store import project_store
from app.render.client import RenderError
from app.security.sanitizer import redact_text, sanitize

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/incidents", tags=["incidents"], dependencies=[Depends(require_authenticated_user)])

SCENARIOS = {
    "external_api": ("GET", "/api/v1/external/status", None),
    "config": ("GET", "/api/v1/config", None),
    "null_pointer": ("POST", "/api/v1/users/user_2/charge", {"amount": 100.0}),
    "schema": ("GET", "/api/v1/orders/order_2", None),
}


def _resolved_project_id(project_id: str | None = None, user_id: str | None = None) -> str | None:
    if project_id:
        return project_id
    current = project_store.get_current(user_id)
    return current.id if current else None


def _require_project_for_user(user: UserResponse, project_id: str | None = None):
    """Resolve the selected project and ensure it belongs to the caller."""
    project = project_store.get(project_id, user.id) if project_id else project_store.get_current(user.id)
    if not project:
        raise HTTPException(404, "No project is configured.")
    return project


def _safe_render_logs(logs: Any) -> list[dict[str, Any]]:
    """Sanitize provider output before it crosses the browser boundary."""
    if not isinstance(logs, list):
        return []
    safe_logs = sanitize(logs)
    return [entry for entry in safe_logs if isinstance(entry, dict)]


# ---------------------------------------------------------------------------
# Listing & retrieval
# ---------------------------------------------------------------------------
@router.get("", response_model=list[IncidentResponse])
async def list_incidents(
    project_id: str | None = None,
    user: UserResponse = Depends(require_authenticated_user),
) -> list[IncidentResponse]:
    if project_id:
        _require_project_for_user(user, project_id)
    resolved = _resolved_project_id(project_id, user.id)
    return [IncidentResponse.from_model(i) for i in incident_store.list_all(resolved)]


@router.get("/render-logs")
async def get_render_logs(
    project_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=800),
    user: UserResponse = Depends(require_authenticated_user),
) -> dict[str, Any]:
    """Retrieve sanitized Render log entries without running incident detection.

    This endpoint exists separately from ``sync-render`` so a connected project
    can inspect its runtime logs even when no failure is detected. It must stay
    above ``/{incident_id}`` because FastAPI matches routes in declaration order.
    """
    project = _require_project_for_user(user, project_id)
    render = project_store.resolve_render(project.id)
    if not render.get("api_key") or not render.get("service_id"):
        raise HTTPException(409, "Render integration is not configured for the selected project.")

    provider = get_log_provider(project.id, "render")
    try:
        payload = await provider.get_logs(
            service_id=render.get("service_id"),
            owner_id=render.get("owner_id"),
            limit=limit,
        )
    except RenderError as exc:
        logger.warning("Render log retrieval failed for project %s: %s", project.id, exc)
        raise HTTPException(502, f"Unable to retrieve Render logs: {exc}") from exc

    logs = _safe_render_logs(payload.get("logs"))
    return {
        "status": payload.get("status") or "success",
        "project_id": project.id,
        "provider": payload.get("provider") or "render",
        "logs": logs,
        "logs_retrieved": len(logs),
        "message": payload.get("message") or f"Retrieved {len(logs)} Render log entries.",
        "service_id": payload.get("service_id"),
        "service_name": payload.get("service_name"),
        "owner_id": payload.get("owner_id"),
    }


@router.get("/{incident_id}", response_model=IncidentResponse)
async def get_incident(incident_id: str) -> IncidentResponse:
    return IncidentResponse.from_model(_get_or_404(incident_id))


@router.get("/{incident_id}/status", response_model=StatusResponse)
async def get_status(incident_id: str) -> StatusResponse:
    return StatusResponse.from_model(_get_or_404(incident_id))


@router.get("/{incident_id}/context", response_model=ContextResponse)
async def get_context(incident_id: str) -> ContextResponse:
    inc = _get_or_404(incident_id)
    if inc.context:
        ctx = inc.context
    else:
        # Build context on demand when the pipeline hasn't finished saving it.
        project = project_store.get(inc.project_id)
        workspace_path = (
            project.workspace_path
            if project and project.workspace_path and Path(project.workspace_path).is_dir()
            else settings.INTERNAL_REPO_ROOT
        )

        def _build() -> dict:
            builder = ContextBuilder(repo_root=workspace_path)
            return builder.build_incident_payload(inc)

        ctx = await asyncio.to_thread(_build)
    # Saved context uses "affected_files"; dynamic payload uses "implicated_files".
    if "implicated_files" in ctx:
        implicated_files = ctx["implicated_files"]
    else:
        implicated_files = ctx.get("affected_files", [])
    return ContextResponse(
        incident_id=incident_id,
        stack_trace=ctx.get("stack_trace", ""),
        implicated_files=implicated_files,
        code_snippets=ctx.get("code_snippets", {}),
        git_log=ctx.get("git_log", ""),
    )


@router.get("/{incident_id}/diff", response_model=DiffResponse)
async def get_diff(incident_id: str) -> DiffResponse:
    inc = _get_or_404(incident_id)
    fix = inc.fix_proposal
    if not fix:
        return DiffResponse(incident_id=incident_id, present=False)

    # Compute real before/after content per file so the frontend can render a
    # proper side-by-side diff editor (and later the applied normal code).
    previews: list[DiffFilePreview] = []
    diff_text = fix.get("diff") or ""
    if diff_text.strip():
        project = project_store.get(inc.project_id) or project_store.get_current()
        workspace_path = (
            project.workspace_path
            if project and project.workspace_path and Path(project.workspace_path).is_dir()
            else settings.INTERNAL_REPO_ROOT
        )
        try:
            from app.sandbox.patch_utils import preview_patch

            for entry in preview_patch(diff_text, Path(workspace_path)):
                previews.append(
                    DiffFilePreview(
                        path=entry["path"],
                        original=entry["original"],
                        proposed=entry["proposed"],
                        error=entry.get("error"),
                    )
                )

            # Once the patch has been applied to the workspace the "before"
            # state no longer exists on disk. Show the current (fixed) content
            # on both sides instead of a stale context-mismatch error.
            if fix.get("applied_files") and previews:
                from app.sandbox.workspace_manager import WorkspaceManager

                wm = WorkspaceManager(repo_root=Path(workspace_path))
                for preview in previews:
                    current = wm.read_relative(None, preview.path)
                    if current is not None:
                        preview.original = current
                        preview.proposed = current
                        preview.error = None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Diff preview failed for incident %s: %s", incident_id, exc)

    return DiffResponse(
        incident_id=incident_id,
        present=True,
        summary=fix.get("summary"),
        diff=diff_text,
        files_changed=fix.get("files_changed", []),
        risk=fix.get("risk"),
        reason=fix.get("reason"),
        applied=bool(fix.get("applied_files")),
        applied_files=fix.get("applied_files") or [],
        files=previews,
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
# Real Incident Ingestion Endpoints
# ---------------------------------------------------------------------------
@router.post("/ingest", response_model=DiagnoseResponse)
async def ingest_incident(req: IngestIncidentRequest) -> DiagnoseResponse:
    trace = req.stack_trace or req.log_text or req.raw_logs or req.message or ""
    if not trace.strip():
        raise HTTPException(400, "Log text, stack trace, or error message is required.")

    project_id = req.project_id or _resolved_project_id() or "default"
    incident = await orchestrator.ingest_incident(
        source=req.source,
        raw_logs=req.raw_logs or req.log_text or trace,
        stack_trace=trace,
        message=req.message or "",
        endpoint=req.endpoint or "",
        method=req.method or "GET",
        status_code=req.status_code or 500,
        service_id=req.service_id or "",
        project_id=project_id,
    )

    if req.auto_diagnose:
        orchestrator.start_diagnosis(incident.id)

    return DiagnoseResponse(
        incident_id=incident.id,
        status=incident.status,
        message=f"Incident ingested from {req.source} and diagnosis started.",
    )


def _render_error_payload(exc: RenderError, service_id: str | None = None) -> dict[str, Any]:
    return {
        "status": "error",
        "message": str(exc),
        "error_type": exc.error_type,
        "http_status": exc.status_code,
        "service_id": service_id,
        "incidents_created": [],
        "logs_retrieved": 0,
        "logs": [],
    }


@router.post("/sync-render")
async def sync_render_logs(
    service_id: str | None = None,
    auto_diagnose: bool = True,
    project_id: str | None = None,
    user: UserResponse = Depends(require_authenticated_user),
) -> dict[str, Any]:
    try:
        project = _require_project_for_user(user, project_id)
    except HTTPException:
        return {
            "status": "error",
            "message": "No project is configured.",
            "error_type": "unconfigured",
            "incidents_created": [],
            "logs_retrieved": 0,
            "logs": [],
        }

    render = project_store.resolve_render(project.id)
    if service_id:
        render["service_id"] = service_id
    if not render.get("api_key"):
        return {
            "status": "error",
            "message": "Render integration is not configured for the selected project.",
            "error_type": "unconfigured",
            "incidents_created": [],
            "logs_retrieved": 0,
            "logs": [],
        }
    if not render.get("service_id"):
        return {
            "status": "error",
            "message": "Render service is not configured for the selected project.",
            "error_type": "unconfigured",
            "incidents_created": [],
            "logs_retrieved": 0,
            "logs": [],
        }

    provider = get_log_provider(project.id, "render")
    try:
        payload = await provider.get_logs(
            service_id=render.get("service_id"),
            owner_id=render.get("owner_id"),
            limit=200,
        )
    except RenderError as exc:
        logger.warning("Render log retrieval failed: %s", exc)
        return _render_error_payload(exc, render.get("service_id"))

    logs = payload.get("logs") or []
    safe_logs = _safe_render_logs(logs)
    if not logs:
        return {
            "status": "success",
            "message": payload.get("message") or "No production errors were found in the selected time range.",
            "project_id": project.id,
            "logs_retrieved": 0,
            "logs": [],
            "incidents_created": [],
            "service_id": payload.get("service_id"),
            "owner_id": payload.get("owner_id"),
            "service_name": payload.get("service_name"),
        }

    # Keep a small, redacted sample in the application logs while validating a
    # provider's log format. This makes a zero-detection result auditable without
    # sending potentially sensitive production text to the browser or logger.
    sample_entries = [
        redact_text(str(entry.get("message") or entry.get("text") or ""))[:200]
        if isinstance(entry, dict)
        else redact_text(str(entry))[:200]
        for entry in logs[:10]
    ]
    logger.info("Sample Render log entries: %s", sample_entries)

    detector = FailureDetector(service=render.get("service_id") or "render")
    detections = detector.detect_from_logs(logs, service=render.get("service_id") or "render", source="render")

    created_ids: list[str] = []
    for det in detections:
        inc = await orchestrator.ingest_incident(
            source="render",
            raw_logs=det.get("raw_logs", ""),
            stack_trace=det.get("stack_trace", ""),
            message=det.get("error_message", ""),
            endpoint=det.get("endpoint", ""),
            method=det.get("method", "GET"),
            status_code=det.get("status_code", 500),
            service_id=render.get("service_id", ""),
            project_id=project.id,
        )
        created_ids.append(inc.id)

    diagnosed = False
    if auto_diagnose and created_ids and project.is_connected:
        diagnosed = bool(orchestrator.start_diagnosis(created_ids[0]))

    return {
        "status": "success",
        "message": f"Retrieved {len(logs)} Render log entries; {len(detections)} incident(s) detected.",
        "project_id": project.id,
        "logs_retrieved": len(logs),
        "logs": safe_logs,
        "incidents_detected": len(detections),
        "incidents_created": created_ids,
        "diagnosis_started": diagnosed,
        "service_id": payload.get("service_id"),
        "owner_id": payload.get("owner_id"),
        "service_name": payload.get("service_name"),
    }


# ---------------------------------------------------------------------------
# Workflow triggers
# ---------------------------------------------------------------------------
@router.post("/trigger/{scenario}", response_model=DiagnoseResponse)
async def trigger_scenario(scenario: str) -> DiagnoseResponse:
    if not settings.DEMO_MODE:
        raise HTTPException(404, "Demo scenarios are disabled when DEMO_MODE=false.")
    if scenario not in SCENARIOS:
        raise HTTPException(400, f"unknown scenario {scenario!r}; choose from {sorted(SCENARIOS)}")
    method, path, payload = SCENARIOS[scenario]
    incident = await orchestrator.detect_and_create(path, method, payload)
    if not orchestrator.start_diagnosis(incident.id):
        raise HTTPException(409, "diagnosis could not be started")
    return DiagnoseResponse(incident_id=incident.id, status=incident.status)


@router.post("/{incident_id}/diagnose", response_model=DiagnoseResponse)
async def diagnose(incident_id: str, req: DiagnoseRequest | None = None) -> DiagnoseResponse:
    inc = _get_or_404(incident_id)
    if not orchestrator.start_diagnosis(incident_id):
        raise HTTPException(
            409,
            f"diagnosis is already running or cannot start from status {inc.status.value}",
        )
    return DiagnoseResponse(incident_id=incident_id, status=inc.status)


@router.post("/{incident_id}/rediagnose", response_model=DiagnoseResponse)
async def rediagnose(incident_id: str) -> DiagnoseResponse:
    """Start a new diagnosis from this incident using a fresh source snapshot."""
    _get_or_404(incident_id)
    try:
        fresh = await orchestrator.rediagnose(incident_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return DiagnoseResponse(
        incident_id=fresh.id,
        status=fresh.status,
        message="Fresh diagnosis started from the current workspace state.",
    )


@router.post("/{incident_id}/cancel")
async def cancel_diagnosis(incident_id: str) -> dict:
    inc = _get_or_404(incident_id)
    if not await orchestrator.cancel_diagnosis(incident_id):
        raise HTTPException(
            409,
            f"no active diagnosis to cancel (status={inc.status.value})",
        )
    return {"incident_id": incident_id, "cancelled": True}


@router.post("/{incident_id}/approve")
async def approve(incident_id: str, req: ApproveRequest) -> dict:
    inc = _get_or_404(incident_id)
    if not inc.fix_proposal:
        raise HTTPException(409, "no fix proposal to approve yet")
    inc.add_activity("human_review", "done", "approved" if req.approved else "rejected")
    incident_store.update(inc)
    if not req.approved:
        inc.status = IncidentStatus.REQUIRES_HUMAN_REVIEW
        incident_store.update(inc)
        return {"incident_id": incident_id, "approved": False}
    return {"incident_id": incident_id, "approved": True}


@router.post("/{incident_id}/approve-file-read")
async def approve_file_read(incident_id: str, req: ApproveRequest) -> dict:
    """Resume pipeline after user approves file reading."""
    inc = _get_or_404(incident_id)
    if inc.status != IncidentStatus.AWAITING_FILE_READ_APPROVAL:
        # Approval changes the status before the resumed background task starts.
        # A double-click (or a delayed browser retry) can therefore legitimately
        # arrive while the incident is already COLLECTING_CONTEXT.  Treat that
        # exact completed approval as idempotent rather than reporting a false
        # conflict to the user.
        already_approved = any(
            event.step == "file_read_approval" and event.status == "done"
            for event in inc.activity
        )
        if req.approved and already_approved and inc.status in {
            IncidentStatus.COLLECTING_CONTEXT,
            IncidentStatus.INVESTIGATING,
            IncidentStatus.ROOT_CAUSE_FOUND,
            IncidentStatus.AWAITING_FIX_APPROVAL,
            IncidentStatus.SANDBOX_RUNNING,
            IncidentStatus.SANDBOX_TESTING,
            IncidentStatus.TESTING,
            IncidentStatus.VERIFYING,
            IncidentStatus.FIX_VERIFIED,
        }:
            return {"incident_id": incident_id, "approved": True, "already_processed": True}
        raise HTTPException(
            409,
            f"Cannot approve file read: incident is in {inc.status.value} state, not AWAITING_FILE_READ_APPROVAL"
        )
    if not req.approved:
        inc.status = IncidentStatus.REQUIRES_HUMAN_REVIEW
        inc.add_activity("file_read_approval", "failed", "rejected by user")
        incident_store.update(inc)
        return {"incident_id": incident_id, "approved": False}
    
    success = await orchestrator.resume_file_read(incident_id)
    if not success:
        raise HTTPException(500, "Failed to resume file reading")
    return {"incident_id": incident_id, "approved": True}


@router.post("/{incident_id}/approve-fix")
async def approve_fix(incident_id: str, req: ApproveRequest) -> dict:
    """Keep Changes / resume pipeline after the user approves the proposed fix.

    Approving applies the patch to the real project workspace first (a
    pre-apply snapshot is kept), then verification runs against the snapshot.
    If verification fails, the workspace is rolled back automatically.
    """
    inc = _get_or_404(incident_id)
    if inc.status != IncidentStatus.AWAITING_FIX_APPROVAL:
        raise HTTPException(
            409,
            f"Cannot approve fix: incident is in {inc.status.value} state, not AWAITING_FIX_APPROVAL"
        )
    if not req.approved:
        inc.status = IncidentStatus.REQUIRES_HUMAN_REVIEW
        inc.add_activity("fix_approval", "failed", "rejected by user")
        incident_store.update(inc)
        await event_hub.publish(incident_id, {"type": "progress", "step": "fix_rejected", "status": "done", "message": "Patch rejected — workspace untouched"})
        return {"incident_id": incident_id, "approved": False}

    # Keep Changes: apply to the real workspace, then resume into sandbox
    # verification (which runs against the pre-apply snapshot). Never approve
    # after an unexpected workspace failure; the only exception is the
    # explicit read-only demo skip, which remains sandbox-only by design.
    outcome = await orchestrator.stage_workspace_apply(incident_id)
    if not outcome.get("applied") and not outcome.get("skipped"):
        raise HTTPException(409, outcome.get("reason") or "Patch could not be applied.")

    success = await orchestrator.resume_fix(incident_id)
    if not success:
        raise HTTPException(500, "Failed to resume fix")
    return {"incident_id": incident_id, "approved": True}


@router.post("/{incident_id}/apply-fix")
async def apply_fix(incident_id: str) -> dict:
    """Explicitly (re)apply the proposed patch to the project workspace."""
    inc = _get_or_404(incident_id)
    if not inc.fix_proposal or not (inc.fix_proposal.get("diff") or "").strip():
        raise HTTPException(409, "No fix proposal available to apply.")
    outcome = await orchestrator.stage_workspace_apply(incident_id)
    if not outcome.get("applied"):
        raise HTTPException(409, outcome.get("reason") or "Patch could not be applied.")
    return {
        "incident_id": incident_id,
        "applied": True,
        "files": outcome.get("files", []),
    }


@router.post("/{incident_id}/commit")
async def commit_changes(incident_id: str) -> dict:
    """Create a real git commit in the project workspace for applied changes."""
    _get_or_404(incident_id)
    try:
        outcome = await orchestrator.commit_changes(incident_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Commit failed: {exc}") from exc
    return {"incident_id": incident_id, "committed": True, **outcome}


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
        # An exception escaping this generator aborts the response mid-body,
        # which the browser reports as ERR_CONNECTION_RESET rather than a clean
        # stream close. Errors are logged and the stream is ended politely so a
        # single bad event can never look like a dead server.
        try:
            inc = incident_store.get(incident_id)
            if inc:
                for ev in inc.activity:
                    payload = ev.model_dump() if hasattr(ev, "model_dump") else dict(ev)
                    payload["replay"] = True
                    yield _sse(payload)
            yield _sse({"type": "connected"})
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                try:
                    event = json.loads(payload)
                except (TypeError, ValueError):
                    logger.warning(
                        "Dropping malformed event on incident %s stream", incident_id
                    )
                    continue
                yield _sse(event)
        except asyncio.CancelledError:
            # Normal client disconnect / server shutdown.
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Incident %s activity stream failed", incident_id)
            try:
                yield _sse({"type": "stream_error"})
            except Exception:  # noqa: BLE001
                pass
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
