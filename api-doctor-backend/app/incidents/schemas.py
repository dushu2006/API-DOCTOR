"""API request/response schemas."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from app.incidents.models import Incident, IncidentStatus, ProgressEvent


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------
class DiagnoseRequest(BaseModel):
    """Manually kick off diagnosis for a detected incident.

    Either ``incident_id`` refers to an existing incident, or raw detection
    fields are supplied to create one.
    """

    project_id: str = "default"
    endpoint: Optional[str] = None
    method: str = "GET"
    payload: Optional[dict[str, Any]] = None
    headers: Optional[dict[str, str]] = None


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
    incident_id: str
    status: IncidentStatus
    message: str = "Diagnosis started. Poll the status endpoint for updates."


class IncidentResponse(BaseModel):
    id: str
    project_id: str
    status: IncidentStatus
    created_at: str
    updated_at: str
    detection: dict[str, Any]
    root_cause: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    attempt_count: int = 0

    @classmethod
    def from_model(cls, m: Incident) -> "IncidentResponse":
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
        )


class StatusResponse(BaseModel):
    incident_id: str
    status: IncidentStatus
    attempt_count: int
    error_message: Optional[str] = None
    activity: list[ProgressEvent] = Field(default_factory=list)

    @classmethod
    def from_model(cls, m: Incident) -> "StatusResponse":
        return cls(
            incident_id=m.id,
            status=m.status,
            attempt_count=m.attempt_count,
            error_message=m.error_message,
            activity=m.activity,
        )


class ContextResponse(BaseModel):
    incident_id: str
    stack_trace: str
    implicated_files: list[str] = Field(default_factory=list)
    code_snippets: dict[str, Any] = Field(default_factory=dict)
    git_log: str = ""


class DiffResponse(BaseModel):
    incident_id: str
    present: bool
    summary: Optional[str] = None
    diff: Optional[str] = None
    files_changed: list[str] = Field(default_factory=list)
    risk: Optional[str] = None
    reason: Optional[str] = None


class SandboxResponse(BaseModel):
    incident_id: str
    present: bool
    passed: Optional[bool] = None
    steps: list[dict[str, Any]] = Field(default_factory=list)
    logs: str = ""
    error: str = ""


class PRInfoResponse(BaseModel):
    incident_id: str
    present: bool
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    branch: Optional[str] = None
    status: Optional[str] = None
    checks: Optional[dict[str, Any]] = None
