"""Persistent incident store backed by the application database."""

from __future__ import annotations

import threading
from typing import Optional

from sqlalchemy import select

from app.db.base import session_scope
from app.db.models import IncidentRecord
from app.incidents.models import Incident


class IncidentStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    def _to_model(self, row: IncidentRecord | None) -> Optional[Incident]:
        if not row:
            return None
        return Incident(
            id=row.id,
            project_id=row.project_id,
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
            detection=row.detection or {},
            request_snapshot=row.request_snapshot or {},
            stack_trace=row.stack_trace or "",
            context=row.context,
            root_cause=row.root_cause,
            fix_proposal=row.fix_proposal,
            sandbox_result=row.sandbox_result,
            pr_info=row.pr_info,
            attempt_count=row.attempt_count or 0,
            error_message=row.error_message,
            activity=row.activity or [],
        )

    def _apply(self, row: IncidentRecord, incident: Incident) -> IncidentRecord:
        row.project_id = incident.project_id
        row.status = incident.status.value if hasattr(incident.status, "value") else str(incident.status)
        row.detection = incident.detection or {}
        row.request_snapshot = incident.request_snapshot or {}
        row.stack_trace = incident.stack_trace or ""
        row.context = incident.context
        row.root_cause = incident.root_cause
        row.fix_proposal = incident.fix_proposal
        row.sandbox_result = incident.sandbox_result
        row.pr_info = incident.pr_info
        row.attempt_count = incident.attempt_count or 0
        row.error_message = incident.error_message
        row.activity = [ev.model_dump() if hasattr(ev, "model_dump") else ev for ev in (incident.activity or [])]
        row.created_at = incident.created_at
        row.updated_at = incident.updated_at
        return row

    def create(self, incident: Incident) -> Incident:
        with self._lock:
            with session_scope() as session:
                row = IncidentRecord(id=incident.id)
                self._apply(row, incident)
                session.add(row)
                session.flush()
                return self._to_model(row) or incident

    def get(self, incident_id: str) -> Optional[Incident]:
        with session_scope() as session:
            row = session.get(IncidentRecord, incident_id)
            return self._to_model(row)

    def update(self, incident: Incident) -> Incident:
        incident.touch()
        with self._lock:
            with session_scope() as session:
                row = session.get(IncidentRecord, incident.id)
                if not row:
                    row = IncidentRecord(id=incident.id)
                self._apply(row, incident)
                session.add(row)
                session.flush()
                return self._to_model(row) or incident

    def list_all(self, project_id: str | None = None) -> list[Incident]:
        with session_scope() as session:
            stmt = select(IncidentRecord)
            if project_id:
                stmt = stmt.where(IncidentRecord.project_id == project_id)
            rows = session.execute(stmt.order_by(IncidentRecord.created_at.desc())).scalars().all()
            return [item for row in rows if (item := self._to_model(row)) is not None]

    def delete(self, incident_id: str) -> bool:
        with self._lock:
            with session_scope() as session:
                row = session.get(IncidentRecord, incident_id)
                if not row:
                    return False
                session.delete(row)
                return True

    def clear(self) -> None:
        with self._lock:
            with session_scope() as session:
                for row in session.execute(select(IncidentRecord)).scalars().all():
                    session.delete(row)


incident_store = IncidentStore()
