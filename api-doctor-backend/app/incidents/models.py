"""Incident state and data models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class IncidentStatus(str, Enum):
    DETECTED = "DETECTED"
    COLLECTING_CONTEXT = "COLLECTING_CONTEXT"
    INVESTIGATING = "INVESTIGATING"
    ROOT_CAUSE_FOUND = "ROOT_CAUSE_FOUND"
    FIX_PLANNED = "FIX_PLANNED"
    SANDBOX_TESTING = "SANDBOX_TESTING"
    VERIFYING = "VERIFYING"
    FIX_VERIFIED = "FIX_VERIFIED"
    PR_CREATED = "PR_CREATED"
    AWAITING_REVIEW = "AWAITING_REVIEW"

    # Failure states
    INVESTIGATION_FAILED = "INVESTIGATION_FAILED"
    FIX_GENERATION_FAILED = "FIX_GENERATION_FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    REPAIR_LIMIT_REACHED = "REPAIR_LIMIT_REACHED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            IncidentStatus.INVESTIGATION_FAILED,
            IncidentStatus.FIX_GENERATION_FAILED,
            IncidentStatus.VERIFICATION_FAILED,
            IncidentStatus.REPAIR_LIMIT_REACHED,
            IncidentStatus.AWAITING_REVIEW,
        }

    @property
    def is_failed(self) -> bool:
        return self in {
            IncidentStatus.INVESTIGATION_FAILED,
            IncidentStatus.FIX_GENERATION_FAILED,
            IncidentStatus.VERIFICATION_FAILED,
            IncidentStatus.REPAIR_LIMIT_REACHED,
        }


class ProgressEvent(BaseModel):
    step: str
    status: str  # pending | running | done | failed
    message: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Incident(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str = "default"
    status: IncidentStatus = IncidentStatus.DETECTED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Input / detection
    detection: dict[str, Any] = Field(default_factory=dict)
    request_snapshot: dict[str, Any] = Field(default_factory=dict)
    stack_trace: str = ""

    # Stage outputs
    context: Optional[dict[str, Any]] = None
    root_cause: Optional[dict[str, Any]] = None
    fix_proposal: Optional[dict[str, Any]] = None
    sandbox_result: Optional[dict[str, Any]] = None
    pr_info: Optional[dict[str, Any]] = None

    # Repair loop
    attempt_count: int = 0
    error_message: Optional[str] = None

    # Live activity
    activity: list[ProgressEvent] = Field(default_factory=list)

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)

    def add_activity(self, step: str, status: str = "done", message: str = "") -> None:
        self.activity.append(ProgressEvent(step=step, status=status, message=message))
        self.touch()
