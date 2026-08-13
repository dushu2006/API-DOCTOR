"""API request/response schemas for run ingestion and workflow."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from app.runs.models import Run, RunStatus, ProgressEvent


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------
class DiagnoseRequest(BaseModel):
    """Manually kick off diagnosis for a detected run."""

    project_id: str = "default"
    endpoint: Optional[str] = None
    method: str = "GET"
    payload: Optional[dict[str, Any]] = None
    headers: Optional[dict[str, str]] = None


class IngestRunRequest(BaseModel):
    """Ingest a real production failure/log into an Run."""

    source: str = Field(default="manual", description="render | github_actions | manual | log")
    service_id: Optional[str] = None
    log_text: Optional[str] = None
    message: Optional[str] = None
    stack_trace: Optional[str] = None
    raw_logs: Optional[str] = None
    endpoint: Optional[str] = None
    method: Optional[str] = "GET"
    status_code: Optional[int] = 500
    project_id: str = "default"
    auto_diagnose: bool = True


class TriggerRequest(BaseModel):
    scenario: str = Field(
        ..., description="'external_api' | 'config' | 'null_pointer' | 'schema'"
    )


class ApproveRequest(BaseModel):
    approved: bool = True
    comment: str = ""


class CreatePRRequest(BaseModel):
    approved: bool = True


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------
class DiagnoseResponse(BaseModel):
    run_id: str
    status: RunStatus
    message: str = "Diagnosis started. Poll the status endpoint or subscribe to stream for updates."


class RunResponse(BaseModel):
    id: str
    project_id: str
    status: RunStatus
    created_at: str
    updated_at: str
    detection: dict[str, Any]
    root_cause: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    attempt_count: int = 0
    activity: list[ProgressEvent] = Field(default_factory=list)
    applied_files: list[str] = Field(default_factory=list)
    commit_sha: Optional[str] = None

    @classmethod
    def from_model(cls, m: Run) -> "RunResponse":
        proposal = m.fix_proposal or {}
        return cls(
            id=m.id,
            project_id=m.project_id,
            status=m.status,
            created_at=m.created_at.isoformat(),
            updated_at=m.updated_at.isoformat(),
            detection=m.detection,
            root_cause=m.root_cause,
            error_message=m.error_message,
            attempt_count=m.attempt_count,
            activity=m.activity,
            applied_files=proposal.get("applied_files") or [],
            commit_sha=proposal.get("commit_sha"),
        )


class StatusResponse(BaseModel):
    run_id: str
    status: RunStatus
    attempt_count: int
    error_message: Optional[str] = None
    activity: list[ProgressEvent] = Field(default_factory=list)

    @classmethod
    def from_model(cls, m: Run) -> "StatusResponse":
        return cls(
            run_id=m.id,
            status=m.status,
            attempt_count=m.attempt_count,
            error_message=m.error_message,
            activity=m.activity,
        )


class ContextResponse(BaseModel):
    run_id: str
    stack_trace: str
    implicated_files: list[str] = Field(default_factory=list)
    code_snippets: dict[str, Any] = Field(default_factory=dict)
    git_log: str = ""


class DiffFilePreview(BaseModel):
    path: str
    original: str = ""
    proposed: str = ""
    error: Optional[str] = None


class DiffResponse(BaseModel):
    run_id: str
    present: bool
    summary: Optional[str] = None
    diff: Optional[str] = None
    files_changed: list[str] = Field(default_factory=list)
    risk: Optional[str] = None
    reason: Optional[str] = None
    applied: bool = False
    applied_files: list[str] = Field(default_factory=list)
    files: list[DiffFilePreview] = Field(default_factory=list)


class SandboxResponse(BaseModel):
    run_id: str
    present: bool
    passed: Optional[bool] = None
    steps: list[dict[str, Any]] = Field(default_factory=list)
    logs: str = ""
    error: str = ""


class PRInfoResponse(BaseModel):
    run_id: str
    present: bool
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    branch: Optional[str] = None
    status: Optional[str] = None
    checks: Optional[dict[str, Any]] = None
