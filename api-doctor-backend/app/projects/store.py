"""In-memory project store (maps projects to GitHub repository, workspace, and profile)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.projects.models import Project, ProjectProfile


class ProjectStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._projects: dict[str, Project] = {}
        self._current_id: str = "default"
        self._seed_default()

    def _seed_default(self) -> None:
        owner = settings.GITHUB_OWNER
        repo = settings.GITHUB_REPO
        branch = settings.GITHUB_DEFAULT_BRANCH or "main"

        is_connected = bool(owner and repo)
        workspace_path = str(Path(settings.WORKSPACE_DIR) / owner / repo) if (owner and repo) else None

        default_proj = Project(
            id="default",
            name=f"{owner}/{repo}" if (owner and repo) else "API Doctor",
            github_owner=owner,
            github_repo=repo,
            github_branch=branch,
            github_token=settings.GITHUB_TOKEN,
            render_service_id=settings.RENDER_SERVICE_ID,
            repo_root=settings.REPO_ROOT,
            workspace_path=workspace_path,
            is_connected=is_connected,
        )

        if is_connected and workspace_path and Path(workspace_path).is_dir():
            from app.projects.discovery import discover_project
            default_proj.profile = discover_project(workspace_path)

        self._projects["default"] = default_proj

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


project_store = ProjectStore()
