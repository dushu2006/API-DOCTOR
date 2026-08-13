"""Run dashboard and ingestion API endpoints."""

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
from app.runs.models import Run, RunStatus
from app.runs.schemas import (
    ApproveRequest,
    ContextResponse,
    CreatePRRequest,
    DiagnoseRequest,
    DiagnoseResponse,
    DiffFilePreview,
    DiffResponse,
    RunResponse,
    IngestRunRequest,
    PRInfoResponse,
    SandboxResponse,
    StatusResponse,
)
from app.runs.store import run_store
from app.integrations.factory import get_log_provider
from app.orchestrator import POST_FIX_GATE_STATUSES, orchestrator
from app.projects.store import project_store
from app.render.client import RenderError
from app.security.sanitizer import redact_text, sanitize

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/diagnosis", tags=["diagnosis"], dependencies=[Depends(require_authenticated_user)])

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
# Current, ephemeral diagnosis
# ---------------------------------------------------------------------------
@router.get("/current", response_model=RunResponse | None)
async def get_current_run(
    project_id: str | None = None,
    user: UserResponse = Depends(require_authenticated_user),
) -> RunResponse | None:
    if project_id:
        _require_project_for_user(user, project_id)
    resolved = _resolved_project_id(project_id, user.id)
    current = run_store.get_current(user.id, resolved)
    return RunResponse.from_model(current) if current else None


@router.delete("/current")
async def reset_current_run(
    user: UserResponse = Depends(require_authenticated_user),
) -> dict[str, bool]:
    cleared = await orchestrator.reset_current(user.id)
    return {"cleared": cleared}


@router.get("/render-logs")
async def get_render_logs(
    project_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=800),
    user: UserResponse = Depends(require_authenticated_user),
) -> dict[str, Any]:
    """Retrieve sanitized Render log entries without running run detection.

    This endpoint exists separately from ``sync-render`` so a connected project
    can inspect its runtime logs even when no failure is detected. It must stay
    above ``/{run_id}`` because FastAPI matches routes in declaration order.
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


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(run_id: str) -> RunResponse:
    return RunResponse.from_model(_get_or_404(run_id))


@router.get("/{run_id}/status", response_model=StatusResponse)
async def get_status(run_id: str) -> StatusResponse:
    return StatusResponse.from_model(_get_or_404(run_id))


@router.get("/{run_id}/context", response_model=ContextResponse)
async def get_context(run_id: str) -> ContextResponse:
    run = _get_or_404(run_id)
    if run.context:
        ctx = run.context
    else:
        # Build context on demand when the pipeline hasn't finished saving it.
        project = project_store.get(run.project_id)
        workspace_path = (
            project.workspace_path
            if project and project.workspace_path and Path(project.workspace_path).is_dir()
            else settings.INTERNAL_REPO_ROOT
        )

        def _build() -> dict:
            builder = ContextBuilder(repo_root=workspace_path)
            return builder.build_run_payload(run)

        ctx = await asyncio.to_thread(_build)
    # Saved context uses "affected_files"; dynamic payload uses "implicated_files".
    if "implicated_files" in ctx:
        implicated_files = ctx["implicated_files"]
    else:
        implicated_files = ctx.get("affected_files", [])
    return ContextResponse(
        run_id=run_id,
        stack_trace=ctx.get("stack_trace", ""),
        implicated_files=implicated_files,
        code_snippets=ctx.get("code_snippets", {}),
        git_log=ctx.get("git_log", ""),
    )


@router.get("/{run_id}/diff", response_model=DiffResponse)
async def get_diff(run_id: str) -> DiffResponse:
    run = _get_or_404(run_id)
    fix = run.fix_proposal
    if not fix:
        return DiffResponse(run_id=run_id, present=False)

    # Compute real before/after content per file so the frontend can render a
    # proper side-by-side diff editor (and later the applied normal code).
    previews: list[DiffFilePreview] = []
    diff_text = fix.get("diff") or ""
    if diff_text.strip():
        project = project_store.get(run.project_id) or project_store.get_current()
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
            logger.warning("Diff preview failed for run %s: %s", run_id, exc)

    return DiffResponse(
        run_id=run_id,
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


@router.get("/{run_id}/sandbox", response_model=SandboxResponse)
async def get_sandbox(run_id: str) -> SandboxResponse:
    run = _get_or_404(run_id)
    sb = run.sandbox_result
    if not sb:
        return SandboxResponse(run_id=run_id, present=False)
    return SandboxResponse(
        run_id=run_id,
        present=True,
        passed=sb.get("passed"),
        steps=sb.get("steps", []),
        logs=sb.get("logs", ""),
        error=sb.get("error", ""),
    )


@router.get("/{run_id}/pr", response_model=PRInfoResponse)
async def get_pr(run_id: str) -> PRInfoResponse:
    run = _get_or_404(run_id)
    if not run.pr_info:
        return PRInfoResponse(run_id=run_id, present=False)
    info = run.pr_info
    return PRInfoResponse(
        run_id=run_id,
        present=True,
        pr_number=info.get("pr_number"),
        pr_url=info.get("pr_url"),
        branch=info.get("branch"),
        status=info.get("status"),
        checks=None,
    )


# ---------------------------------------------------------------------------
# Fresh diagnosis inputs
# ---------------------------------------------------------------------------
@router.post("/start", response_model=DiagnoseResponse)
async def ingest_run(
    req: IngestRunRequest,
    user: UserResponse = Depends(require_authenticated_user),
) -> DiagnoseResponse:
    trace = req.stack_trace or req.log_text or req.raw_logs or req.message or ""
    if not trace.strip():
        raise HTTPException(400, "Log text, stack trace, or error message is required.")

    project = _require_project_for_user(user, req.project_id or None)
    run = await orchestrator.ingest_run(
        source=req.source,
        raw_logs=req.raw_logs or req.log_text or trace,
        stack_trace=trace,
        message=req.message or "",
        endpoint=req.endpoint or "",
        method=req.method or "GET",
        status_code=req.status_code or 500,
        service_id=req.service_id or "",
        project_id=project.id,
        owner_id=user.id,
    )

    if req.auto_diagnose:
        orchestrator.start_diagnosis(run.id)

    return DiagnoseResponse(
        run_id=run.id,
        status=run.status,
        message=f"Fresh diagnosis started from {req.source} input.",
    )


def _render_error_payload(exc: RenderError, service_id: str | None = None) -> dict[str, Any]:
    return {
        "status": "error",
        "message": str(exc),
        "error_type": exc.error_type,
        "http_status": exc.status_code,
        "service_id": service_id,
        "run_id": None,
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
            "run_id": None,
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
            "run_id": None,
            "logs_retrieved": 0,
            "logs": [],
        }
    if not render.get("service_id"):
        return {
            "status": "error",
            "message": "Render service is not configured for the selected project.",
            "error_type": "unconfigured",
            "run_id": None,
            "logs_retrieved": 0,
            "logs": [],
        }

    # Sync is a new diagnosis attempt. Discard the prior console before
    # retrieving this point-in-time log window.
    await orchestrator.reset_current(user.id)

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
            "run_id": None,
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

    current: Run | None = None
    if detections:
        detection = detections[0]
        current = await orchestrator.ingest_run(
            source="render",
            raw_logs=detection.get("raw_logs", ""),
            stack_trace=detection.get("stack_trace", ""),
            message=detection.get("error_message", ""),
            endpoint=detection.get("endpoint", ""),
            method=detection.get("method", "GET"),
            status_code=detection.get("status_code", 500),
            service_id=render.get("service_id", ""),
            project_id=project.id,
            owner_id=user.id,
        )

    diagnosed = bool(
        current
        and auto_diagnose
        and project.is_connected
        and orchestrator.start_diagnosis(current.id)
    )

    return {
        "status": "success",
        "message": (
            f"Retrieved {len(logs)} Render log entries; starting from the first detected error."
            if current
            else f"Retrieved {len(logs)} Render log entries; no error was detected."
        ),
        "project_id": project.id,
        "logs_retrieved": len(logs),
        "logs": safe_logs,
        "errors_detected": len(detections),
        "run_id": current.id if current else None,
        "diagnosis_started": diagnosed,
        "service_id": payload.get("service_id"),
        "owner_id": payload.get("owner_id"),
        "service_name": payload.get("service_name"),
    }


# ---------------------------------------------------------------------------
# Workflow triggers
# ---------------------------------------------------------------------------
@router.post("/trigger/{scenario}", response_model=DiagnoseResponse)
async def trigger_scenario(
    scenario: str,
    user: UserResponse = Depends(require_authenticated_user),
) -> DiagnoseResponse:
    if not settings.DEMO_MODE:
        raise HTTPException(404, "Demo scenarios are disabled when DEMO_MODE=false.")
    if scenario not in SCENARIOS:
        raise HTTPException(400, f"unknown scenario {scenario!r}; choose from {sorted(SCENARIOS)}")
    method, path, payload = SCENARIOS[scenario]
    project = project_store.get_current(user.id)
    run = await orchestrator.detect_and_create(
        path,
        method,
        payload,
        project_id=project.id if project else "default",
        owner_id=user.id,
    )
    if not orchestrator.start_diagnosis(run.id):
        raise HTTPException(409, "diagnosis could not be started")
    return DiagnoseResponse(run_id=run.id, status=run.status)


@router.post("/{run_id}/diagnose", response_model=DiagnoseResponse)
async def diagnose(run_id: str, req: DiagnoseRequest | None = None) -> DiagnoseResponse:
    run = _get_or_404(run_id)
    if not orchestrator.start_diagnosis(run_id):
        raise HTTPException(
            409,
            f"diagnosis is already running or cannot start from status {run.status.value}",
        )
    return DiagnoseResponse(run_id=run_id, status=run.status)


@router.post("/{run_id}/restart", response_model=DiagnoseResponse)
async def restart(run_id: str) -> DiagnoseResponse:
    """Replace the current console and run this diagnosis again."""
    _get_or_404(run_id)
    try:
        fresh = await orchestrator.restart(run_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return DiagnoseResponse(
        run_id=fresh.id,
        status=fresh.status,
        message="Fresh diagnosis started from the current workspace state.",
    )


@router.post("/{run_id}/cancel")
async def cancel_diagnosis(run_id: str) -> dict:
    run = _get_or_404(run_id)
    if not await orchestrator.cancel_diagnosis(run_id):
        raise HTTPException(
            409,
            f"no active diagnosis to cancel (status={run.status.value})",
        )
    return {"run_id": run_id, "cancelled": True}


@router.post("/{run_id}/approve")
async def approve(run_id: str, req: ApproveRequest) -> dict:
    run = _get_or_404(run_id)
    if not run.fix_proposal:
        raise HTTPException(409, "no fix proposal to approve yet")
    run.add_activity("human_review", "done", "approved" if req.approved else "rejected")
    run_store.update(run)
    if not req.approved:
        run.status = RunStatus.REQUIRES_HUMAN_REVIEW
        run_store.update(run)
        return {"run_id": run_id, "approved": False}
    return {"run_id": run_id, "approved": True}


@router.post("/{run_id}/approve-file-read")
async def approve_file_read(run_id: str, req: ApproveRequest) -> dict:
    """Resume pipeline after user approves file reading."""
    run = _get_or_404(run_id)
    if run.status != RunStatus.AWAITING_FILE_READ_APPROVAL:
        # Approval changes the status before the resumed background task starts.
        # A double-click (or a delayed browser retry) can therefore legitimately
        # arrive while the run is already COLLECTING_CONTEXT.  Treat that
        # exact completed approval as idempotent rather than reporting a false
        # conflict to the user.
        already_approved = any(
            event.step == "file_read_approval" and event.status == "done"
            for event in run.activity
        )
        if req.approved and already_approved and run.status in {
            RunStatus.COLLECTING_CONTEXT,
            RunStatus.INVESTIGATING,
            RunStatus.ROOT_CAUSE_FOUND,
            RunStatus.AWAITING_FIX_APPROVAL,
            RunStatus.SANDBOX_RUNNING,
            RunStatus.SANDBOX_TESTING,
            RunStatus.TESTING,
            RunStatus.VERIFYING,
            RunStatus.FIX_VERIFIED,
        }:
            return {"run_id": run_id, "approved": True, "already_processed": True}
        raise HTTPException(
            409,
            f"Cannot approve file read: run is in {run.status.value} state, not AWAITING_FILE_READ_APPROVAL"
        )
    if not req.approved:
        run.status = RunStatus.REQUIRES_HUMAN_REVIEW
        run.add_activity("file_read_approval", "failed", "rejected by user")
        run_store.update(run)
        return {"run_id": run_id, "approved": False}
    
    success = await orchestrator.resume_file_read(run_id)
    if not success:
        raise HTTPException(500, "Failed to resume file reading")
    return {"run_id": run_id, "approved": True}


@router.post("/{run_id}/approve-fix")
async def approve_fix(run_id: str, req: ApproveRequest) -> dict:
    """Keep Changes / resume pipeline after the user approves the proposed fix.

    Approving applies the patch to the real project workspace first (a
    pre-apply snapshot is kept), then verification runs against the snapshot.
    If verification fails, the workspace is rolled back automatically.
    """
    run = _get_or_404(run_id)

    # Duplicate "Keep Changes" clicks (or browser retries on a dropped
    # response) can land while the earlier approval is already being
    # verified/committed downstream. The recorded approval plus a
    # post-gate status proves this request is a duplicate: answer with an
    # idempotent success instead of a misleading 409/500, and — critically —
    # never re-apply or regenerate anything. Mirrored from the
    # approve-file-read gate.
    already_approved = (
        any(
            event.step == "fix_approval" and event.status == "done"
            for event in run.activity or []
        )
        and run.status in POST_FIX_GATE_STATUSES
    )
    if run.status != RunStatus.AWAITING_FIX_APPROVAL and not already_approved:
        raise HTTPException(
            409,
            f"Cannot approve fix: run is in {run.status.value} state, not AWAITING_FIX_APPROVAL"
        )
    if not req.approved:
        if run.status != RunStatus.AWAITING_FIX_APPROVAL:
            raise HTTPException(
                409,
                "The fix was already approved and is being processed — it can no longer be rejected here."
            )
        run.status = RunStatus.REQUIRES_HUMAN_REVIEW
        run.add_activity("fix_approval", "failed", "rejected by user")
        run_store.update(run)
        await event_hub.publish(run_id, {"type": "progress", "step": "fix_rejected", "status": "done", "message": "Patch rejected — workspace untouched"})
        return {"run_id": run_id, "approved": False}

    if already_approved:
        return {"run_id": run_id, "approved": True, "already_approved": True}

    # Keep Changes: apply to the real workspace, then resume into sandbox
    # verification (which runs against the pre-apply snapshot). Never approve
    # after an unexpected workspace failure; the only exception is the
    # explicit read-only demo skip, which remains sandbox-only by design.
    outcome = await orchestrator.stage_workspace_apply(run_id)
    if not outcome.get("applied") and not outcome.get("skipped"):
        raise HTTPException(409, outcome.get("reason") or "Patch could not be applied.")

    success = await orchestrator.resume_fix(run_id)
    if not success:
        raise HTTPException(500, "Failed to resume fix")
    return {"run_id": run_id, "approved": True}


@router.post("/{run_id}/apply-fix")
async def apply_fix(run_id: str) -> dict:
    """Explicitly (re)apply the proposed patch to the project workspace."""
    run = _get_or_404(run_id)
    if not run.fix_proposal or not (run.fix_proposal.get("diff") or "").strip():
        raise HTTPException(409, "No fix proposal available to apply.")
    outcome = await orchestrator.stage_workspace_apply(run_id)
    if not outcome.get("applied"):
        raise HTTPException(409, outcome.get("reason") or "Patch could not be applied.")
    return {
        "run_id": run_id,
        "applied": True,
        "files": outcome.get("files", []),
    }


@router.post("/{run_id}/commit")
async def commit_changes(run_id: str) -> dict:
    """Create a real git commit in the project workspace for applied changes."""
    _get_or_404(run_id)
    try:
        outcome = await orchestrator.commit_changes(run_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Commit failed: {exc}") from exc
    return {"run_id": run_id, "committed": True, **outcome}


@router.post("/{run_id}/create-pr")
async def create_pr(run_id: str, req: CreatePRRequest | None = None) -> dict:
    run = _get_or_404(run_id)
    if not (req or CreatePRRequest()).approved:
        return {"run_id": run_id, "approved": False}
    try:
        pr_info = await orchestrator.create_pull_request(run_id)
    except ValueError as exc:
        # Configuration/gating problems are client-fixable — surface them as
        # a 409 with the actionable message instead of an opaque 502.
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"PR creation failed: {exc}") from exc
    return {"run_id": run_id, **pr_info}


@router.get("/{run_id}/pr-status")
async def pr_status(run_id: str) -> dict:
    _get_or_404(run_id)
    return await orchestrator.pr_status(run_id)


# ---------------------------------------------------------------------------
# Live activity stream (SSE)
# ---------------------------------------------------------------------------
@router.get("/{run_id}/stream")
async def stream_run(run_id: str, request: Request) -> StreamingResponse:
    _get_or_404(run_id)
    queue = event_hub.subscribe(run_id)

    async def gen():
        # An exception escaping this generator aborts the response mid-body,
        # which the browser reports as ERR_CONNECTION_RESET rather than a clean
        # stream close. Errors are logged and the stream is ended politely so a
        # single bad event can never look like a dead server.
        try:
            run = run_store.get(run_id)
            if run:
                for ev in run.activity:
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
                        "Dropping malformed event on run %s stream", run_id
                    )
                    continue
                yield _sse(event)
                if event.get("step") == "reset":
                    break
        except asyncio.CancelledError:
            # Normal client disconnect / server shutdown.
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Run %s activity stream failed", run_id)
            try:
                yield _sse({"type": "stream_error"})
            except Exception:  # noqa: BLE001
                pass
        finally:
            event_hub.unsubscribe(run_id, queue)

    return StreamingResponse(gen(), media_type="text/event-stream")


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _get_or_404(run_id: str) -> Run:
    run = run_store.get(run_id)
    if not run:
        raise HTTPException(404, f"run {run_id!r} not found")
    return run
