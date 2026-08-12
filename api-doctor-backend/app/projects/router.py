"""Project management endpoints (GitHub repository -> workspace -> profile -> file tree)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.config import settings
from app.github.client import GitHubClient, GitHubError
from app.projects.discovery import discover_project
from app.projects.models import Project, ProjectProfile
from app.projects.store import project_store
from app.sandbox.workspace_manager import WorkspaceManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ConnectProjectRequest(BaseModel):
    github_owner: str
    github_repo: str
    github_branch: str = "main"
    github_token: Optional[str] = None
    render_service_id: Optional[str] = None
    project_id: str = "default"


class ConnectProjectResponse(BaseModel):
    status: str
    message: str
    project: Project
    steps_completed: list[str] = Field(default_factory=list)


@router.get("", response_model=list[Project])
async def list_projects() -> list[Project]:
    return project_store.list_all()


@router.get("/current", response_model=Project)
async def get_current_project() -> Project:
    project = project_store.get_current()
    if not project:
        raise HTTPException(404, "no current project found")
    return project


@router.get("/files/list")
async def list_project_files(project_id: str = "default") -> dict[str, Any]:
    """Return all repository-relative file paths for the project workspace."""
    project = project_store.get(project_id)
    ws_path = project.workspace_path if (project and project.workspace_path and Path(project.workspace_path).is_dir()) else (project.repo_root if (project and project.repo_root and Path(project.repo_root).is_dir()) else settings.REPO_ROOT)
    wm = WorkspaceManager(repo_root=ws_path)
    return {
        "project_id": project_id,
        "files": wm.files(),
        "tree": wm.file_tree(),
    }


@router.get("/file-content")
async def get_file_content(path: str = Query(..., description="Repository-relative file path"), project_id: str = "default") -> dict[str, Any]:
    """Read file content safely from the synchronized project workspace."""
    project = project_store.get(project_id)
    ws_path = project.workspace_path if (project and project.workspace_path and Path(project.workspace_path).is_dir()) else (project.repo_root if (project and project.repo_root and Path(project.repo_root).is_dir()) else settings.REPO_ROOT)
    wm = WorkspaceManager(repo_root=ws_path)

    content = wm.read_relative(None, path)
    if content is None:
        raise HTTPException(404, f"File {path!r} not found in workspace.")

    return {
        "path": path,
        "content": content,
    }


@router.post("/connect", response_model=ConnectProjectResponse)
async def connect_repository(req: ConnectProjectRequest) -> ConnectProjectResponse:
    """Connect a real GitHub repository, synchronize workspace, and discover project profile."""
    steps_completed: list[str] = []

    owner = req.github_owner.strip()
    repo = req.github_repo.strip()
    branch = req.github_branch.strip() or "main"
    token = (req.github_token or "").strip() or settings.GITHUB_TOKEN

    if not owner or not repo:
        raise HTTPException(400, "github_owner and github_repo are required.")

    # 1. Validate GitHub configuration & verify repository access
    gh_client = GitHubClient(token=token, owner=owner, repo=repo, default_branch=branch)
    try:
        if token:
            await gh_client.verify_access()
        steps_completed.append("github_connected")
        steps_completed.append("repository_verified")
    except GitHubError as exc:
        logger.warning("GitHub verification error: %s", exc)
        steps_completed.append("github_connected")

    # 2. Synchronize repository to local workspace
    wm = WorkspaceManager()
    try:
        ws_path = wm.sync_repository(
            owner=owner,
            repo=repo,
            branch=branch,
            token=token,
            base_url=gh_client.base_url,
        )
        steps_completed.append("repository_synchronized")
    except Exception as exc:
        logger.exception("Failed to sync repository into workspace: %s", exc)
        raise HTTPException(500, f"Failed to sync repository: {exc}")

    # 3. Discover project structure
    profile = discover_project(ws_path)
    steps_completed.append("project_discovered")

    # 4. Store project record
    project = Project(
        id=req.project_id,
        name=f"{owner}/{repo}",
        github_owner=owner,
        github_repo=repo,
        github_branch=branch,
        github_token=token,
        render_service_id=req.render_service_id or settings.RENDER_SERVICE_ID,
        repo_root=str(ws_path),
        workspace_path=str(ws_path),
        is_connected=True,
        profile=profile,
    )
    project_store.update(project)
    project_store.set_current(project.id)

    return ConnectProjectResponse(
        status="ok",
        message="Repository connected and discovered successfully.",
        project=project,
        steps_completed=steps_completed,
    )


@router.post("/sync", response_model=Project)
async def sync_current_project() -> Project:
    """Pull latest updates from GitHub for the currently active project."""
    project = project_store.get_current()
    if not project or not project.github_owner or not project.github_repo:
        raise HTTPException(400, "No repository configured to sync.")

    wm = WorkspaceManager()
    ws_path = wm.sync_repository(
        owner=project.github_owner,
        repo=project.github_repo,
        branch=project.github_branch,
        token=project.github_token,
    )
    project.profile = discover_project(ws_path)
    project.workspace_path = str(ws_path)
    project.is_connected = True
    project_store.update(project)
    return project


@router.get("/{project_id}", response_model=Project)
async def get_project(project_id: str) -> Project:
    project = project_store.get(project_id)
    if not project:
        raise HTTPException(404, f"project {project_id!r} not found")
    return project


@router.post("", response_model=Project)
async def upsert_project(project: Project) -> Project:
    return project_store.update(project)
