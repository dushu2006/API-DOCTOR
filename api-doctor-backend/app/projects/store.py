"""In-memory project store (replaceable with a database later)."""

from __future__ import annotations

import threading
from typing import Optional

from app.core.config import settings
from app.projects.models import Project


class ProjectStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._projects: dict[str, Project] = {}
        self._seed_default()

    def _seed_default(self) -> None:
        # A default project seeded from configuration so the MVP works out of
        # the box; can be overridden/provisioned via the API later.
        if settings.GITHUB_REPO:
            self._projects["default"] = Project()

    def create(self, project: Project) -> Project:
        with self._lock:
            self._projects[project.id] = project
        return project

    def get(self, project_id: str = "default") -> Optional[Project]:
        with self._lock:
            return self._projects.get(project_id)

    def list_all(self) -> list[Project]:
        with self._lock:
            return list(self._projects.values())

    def update(self, project: Project) -> Project:
        with self._lock:
            self._projects[project.id] = project
        return project


project_store = ProjectStore()
