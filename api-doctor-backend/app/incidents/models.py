"""Incident state machine and data models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class IncidentStatus(str, Enum):
    # Canonical Real Project States
    RECEIVED = "RECEIVED"
    DETECTING = "DETECTING"
    CONTEXT_BUILDING = "CONTEXT_BUILDING"
    INVESTIGATING = "INVESTIGATING"
    ROOT_CAUSE_IDENTIFIED = "ROOT_CAUSE_IDENTIFIED"
    FIX_GENERATING = "FIX_GENERATING"
    FIX_READY = "FIX_READY"
    SANDBOX_RUNNING = "SANDBOX_RUNNING"
    TESTING = "TESTING"
    FIX_VERIFIED = "FIX_VERIFIED"
    PR_READY = "PR_READY"
    PR_CREATED = "PR_CREATED"
    FAILED = "FAILED"
    REQUIRES_HUMAN_REVIEW = "REQUIRES_HUMAN_REVIEW"
    CANCELLED = "CANCELLED"

    # Backward compatibility aliases
    DETECTED = "DETECTED"
    COLLECTING_CONTEXT = "COLLECTING_CONTEXT"
    ROOT_CAUSE_FOUND = "ROOT_CAUSE_FOUND"
    FIX_PLANNED = "FIX_PLANNED"
    SANDBOX_TESTING = "SANDBOX_TESTING"
    VERIFYING = "VERIFYING"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    INVESTIGATION_FAILED = "INVESTIGATION_FAILED"
    FIX_GENERATION_FAILED = "FIX_GENERATION_FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    REPAIR_LIMIT_REACHED = "REPAIR_LIMIT_REACHED"

    @property
    def is_terminal(self) -> bool:
        return self in {
            IncidentStatus.FAILED,
            IncidentStatus.CANCELLED,
            IncidentStatus.REQUIRES_HUMAN_REVIEW,
            IncidentStatus.PR_CREATED,
            IncidentStatus.INVESTIGATION_FAILED,
            IncidentStatus.FIX_GENERATION_FAILED,
            IncidentStatus.VERIFICATION_FAILED,
            IncidentStatus.REPAIR_LIMIT_REACHED,
            IncidentStatus.AWAITING_REVIEW,
        }

    @property
    def is_failed(self) -> bool:
        return self in {
            IncidentStatus.FAILED,
            IncidentStatus.INVESTIGATION_FAILED,
            IncidentStatus.FIX_GENERATION_FAILED,
            IncidentStatus.VERIFICATION_FAILED,
            IncidentStatus.REPAIR_LIMIT_REACHED,
        }


class ProgressEvent(BaseModel):
    step: str
    status: str  # pending | running | done | failed | cancelled
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

    def set_activity(self, step: str, status: str, message: str = "") -> None:
        """Update the latest entry for ``step`` in place. If none exists, append."""
        for ev in reversed(self.activity):
            if ev.step == step:
                ev.status = status
                ev.message = message
                ev.timestamp = datetime.now(timezone.utc).isoformat()
                self.touch()
                return
        self.add_activity(step, status, message)
