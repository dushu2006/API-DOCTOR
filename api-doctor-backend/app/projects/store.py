"""In-memory project store (maps projects to GitHub repository, workspace, and profile)."""

from __future__ import annotations

import threading
from typing import Optional

from app.core.config import settings
from app.projects.models import Project


class ProjectStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._projects: dict[str, Project] = {}
        self._current_id: str = "default"
        self._seed_default()

    def _seed_default(self) -> None:
        """Seed an unconnected placeholder. Repositories are connected via POST /connect."""
        self._projects["default"] = Project(
            id="default",
            name="API Doctor",
            github_owner="",
            github_repo="",
            github_branch="main",
            github_token="",
            render_service_id="",
            repo_root=settings.REPO_ROOT,
            workspace_path=None,
            is_connected=False,
            profile=None,
        )
        self._current_id = "default"

    def create(self, project: Project) -> Project:
        with self._lock:
            self._projects[project.id] = project
        return project

    def get(self, project_id: str = "default") -> Optional[Project]:
        with self._lock:
            return self._projects.get(project_id)

    def get_current(self) -> Optional[Project]:
        with self._lock:
            return self._projects.get(self._current_id) or (
                list(self._projects.values())[0] if self._projects else None
            )

    def set_current(self, project_id: str) -> None:
        with self._lock:
            if project_id in self._projects:
                self._current_id = project_id

    def list_all(self) -> list[Project]:
        with self._lock:
            return list(self._projects.values())

    def update(self, project: Project) -> Project:
        with self._lock:
            self._projects[project.id] = project
        return project

    def reset(self) -> None:
        with self._lock:
            self._projects.clear()
            self._current_id = "default"
        self._seed_default()


project_store = ProjectStore()
