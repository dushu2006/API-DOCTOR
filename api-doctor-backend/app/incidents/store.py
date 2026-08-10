"""Incident store.

Initially an in-memory store with a lock. The interface is designed so it can be
replaced with PostgreSQL/SQLite later without touching the rest of the system.
"""

from __future__ import annotations

import threading
from typing import Optional

from app.incidents.models import Incident


class IncidentStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._incidents: dict[str, Incident] = {}

    def create(self, incident: Incident) -> Incident:
        with self._lock:
            self._incidents[incident.id] = incident
        return incident

    def get(self, incident_id: str) -> Optional[Incident]:
        with self._lock:
            return self._incidents.get(incident_id)

    def update(self, incident: Incident) -> Incident:
        incident.touch()
        with self._lock:
            self._incidents[incident.id] = incident
        return incident

    def list_all(self, project_id: str | None = None) -> list[Incident]:
        with self._lock:
            items = list(self._incidents.values())
        if project_id:
            items = [i for i in items if i.project_id == project_id]
        return sorted(items, key=lambda i: i.created_at, reverse=True)

    def delete(self, incident_id: str) -> bool:
        with self._lock:
            return self._incidents.pop(incident_id, None) is not None

    def clear(self) -> None:
        with self._lock:
            self._incidents.clear()


incident_store = IncidentStore()
