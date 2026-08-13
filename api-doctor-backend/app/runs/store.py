"""Ephemeral store for the one diagnosis run that exists right now.

Runs are intentionally never written to SQL or any other durable storage. Each
user can have at most one current run; starting a fresh run atomically replaces
the previous one. Restarting the backend also starts with an empty console.
"""

from __future__ import annotations

import threading
from typing import Optional

from app.runs.models import Run


class RunStore:
    """Keep only each user's current run in process memory."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._current: dict[str, Run] = {}

    @staticmethod
    def _copy(run: Run) -> Run:
        return run.model_copy(deep=True)

    def create(self, run: Run) -> Run:
        """Replace the owner's current run; no prior run is retained."""
        run.touch()
        with self._lock:
            self._current[run.owner_id] = self._copy(run)
            return self._copy(run)

    def get(self, run_id: str) -> Optional[Run]:
        with self._lock:
            for run in self._current.values():
                if run.id == run_id:
                    return self._copy(run)
        return None

    def get_current(self, owner_id: str, project_id: str | None = None) -> Optional[Run]:
        with self._lock:
            run = self._current.get(owner_id)
            if not run or (project_id and run.project_id != project_id):
                return None
            return self._copy(run)

    def update(self, run: Run) -> Run:
        """Update a current run without allowing stale workers to resurrect it."""
        run.touch()
        with self._lock:
            current = self._current.get(run.owner_id)
            if current and current.id == run.id:
                self._current[run.owner_id] = self._copy(run)
            return self._copy(run)

    def delete(self, run_id: str) -> bool:
        with self._lock:
            for owner_id, run in tuple(self._current.items()):
                if run.id == run_id:
                    self._current.pop(owner_id, None)
                    return True
        return False

    def clear(self, owner_id: str | None = None) -> None:
        with self._lock:
            if owner_id is None:
                self._current.clear()
            else:
                self._current.pop(owner_id, None)


run_store = RunStore()
