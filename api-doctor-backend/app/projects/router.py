"""Project management, onboarding, and workspace endpoints."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth.dependencies import require_authenticated_user
from app.auth.schemas import UserResponse
from app.core.config import settings
from app.github.client import GitHubClient, GitHubError
from app.github.service import GitHubService
from app.integrations.render_provider import RenderLogProvider
from app.projects.discovery import discover_project
from app.projects.models import Project, ProjectProfile, ProjectSettings, ProjectStatus
from app.projects.store import project_store
from app.render.client import RenderError
from app.sandbox.workspace_manager import WorkspaceManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"], dependencies=[Depends(require_authenticated_user)])


class GitHubSelection(BaseModel):
    token: str = ""
    owner: str
    repo: str
    branch: str = "main"


class DeploymentSelection(BaseModel):
    provider: str = "manual"
    api_key: Optional[str] = None
    service_id: Optional[str] = None
    service_name: Optional[str] = None
    owner_id: Optional[str] = None


class ProjectOnboardingRequest(BaseModel):
    name: str
    description: str = ""
    github: GitHubSelection
    deployment: DeploymentSelection = Field(default_factory=DeploymentSelection)
    runtime_overrides: dict[str, Any] = Field(default_factory=dict)
    diagnosis_settings: dict[str, Any] = Field(default_factory=dict)
    repair_settings: dict[str, Any] = Field(default_factory=dict)
    activate: bool = True


class GitHubTokenRequest(BaseModel):
    token: str = ""


class RepositoryBranchRequest(BaseModel):
    token: str = ""
    owner: str
    repo: str


class RenderKeyRequest(BaseModel):
    api_key: str


class RenderVerifyRequest(BaseModel):
    api_key: str
    service_id: str
    owner_id: str = ""


class PreviewResponse(BaseModel):
    status: str
    checks: list[dict[str, Any]]
    profile: ProjectProfile
    settings: ProjectSettings
    repository: dict[str, Any]
    deployment: dict[str, Any]
    workspace_path: str


class CreateProjectResponse(BaseModel):
    status: str
    message: str
    project: Project
    checks: list[dict[str, Any]] = Field(default_factory=list)


class ConnectProjectRequest(BaseModel):
    github_owner: str
    github_repo: str
    github_branch: str = "main"
    github_token: Optional[str] = None
    render_service_id: Optional[str] = None
    render_api_key: Optional[str] = None
    render_owner_id: Optional[str] = None
    project_name: Optional[str] = None
    project_description: Optional[str] = None
    project_id: str = ""


class ConnectProjectResponse(BaseModel):
    status: str
    message: str
    project: Project
    steps_completed: list[str] = Field(default_factory=list)


class DuplicateProjectRequest(BaseModel):
    name: str | None = None


def _require_project(user_id: str, project_id: Optional[str] = None) -> Project:
    project = project_store.get(project_id, user_id) if project_id else project_store.get_current(user_id)
    if not project:
        raise HTTPException(404, "No project is configured.")
    return project


def _require_connected_workspace(user_id: str, project_id: Optional[str]) -> tuple[Project, Path]:
    project = _require_project(user_id, project_id)
    ws = Path(project.workspace_path or "")
    if not project.is_connected or not ws.is_dir():
        raise HTTPException(409, "Project workspace is not available. Reconnect or synchronize the repository.")
    return project, ws


async def _prepare_onboarding(req: ProjectOnboardingRequest) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], Path, ProjectProfile, ProjectSettings]:
    checks: list[dict[str, Any]] = []

    owner = req.github.owner.strip()
    repo = req.github.repo.strip()
    branch = req.github.branch.strip() or "main"
    token = (req.github.token or "").strip()

    if not owner or not repo:
        raise HTTPException(400, "Repository owner and name are required.")

    gh = GitHubClient(token=token, owner=owner, repo=repo, default_branch=branch)

    login = None
    if token:
        try:
            cred = await gh.verify_credentials()
            login = cred.get("login")
            checks.append({"key": "github_authenticated", "ok": True, "label": "GitHub authenticated", "detail": login or "authenticated"})
        except GitHubError as exc:
            raise HTTPException(401, f"GitHub authentication failed. Check the token permissions. ({exc})") from exc
    else:
        checks.append({"key": "github_authenticated", "ok": True, "label": "GitHub token omitted", "detail": "Proceeding with repository verification."})

    try:
        repo_info = await gh.verify_access()
        checks.append({"key": "repository_accessible", "ok": True, "label": "Repository accessible", "detail": repo_info.get("full_name") or f"{owner}/{repo}"})
    except GitHubError as exc:
        raise HTTPException(404, f"Repository not found or inaccessible. ({exc})") from exc

    try:
        branches = await gh.list_branches()
    except GitHubError as exc:
        raise HTTPException(400, f"Unable to load repository branches. ({exc})") from exc
    if branch not in branches:
        raise HTTPException(400, f"Branch '{branch}' was not found in {owner}/{repo}.")
    checks.append({"key": "branch_found", "ok": True, "label": "Branch found", "detail": branch})

    wm = WorkspaceManager()
    try:
        workspace_path = wm.sync_repository(owner=owner, repo=repo, branch=branch, token=token, base_url=gh.base_url)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to synchronize repository: %s", exc)
        raise HTTPException(500, f"Repository synchronization failed: {exc}") from exc
    checks.append({"key": "repository_synchronized", "ok": True, "label": "Repository synchronized", "detail": str(workspace_path)})

    profile = discover_project(workspace_path)
    checks.append({"key": "project_detected", "ok": True, "label": "Project detected", "detail": f"{profile.language} / {profile.framework}"})

    deployment_provider = (req.deployment.provider or "manual").lower()
    deployment_payload: dict[str, Any] = {"provider": deployment_provider, "status": "connected"}
    if deployment_provider == "render":
        api_key = (req.deployment.api_key or "").strip()
        service_id = (req.deployment.service_id or "").strip()
        owner_id = (req.deployment.owner_id or "").strip()
        if not api_key or not service_id:
            raise HTTPException(400, "Render API key and service selection are required.")
        provider = RenderLogProvider(api_key=api_key, service_id=service_id, owner_id=owner_id)
        try:
            verify = await provider.verify_connection()
        except RenderError as exc:
            raise HTTPException(400, f"Render authentication succeeded, but logs could not be accessed. ({exc})") from exc
        deployment_payload = {
            "provider": "render",
            "status": "connected",
            **(verify.get("service") or {}),
            "message": verify.get("message") or "",
        }
        checks.append({"key": "provider_authenticated", "ok": True, "label": "Render authenticated", "detail": deployment_payload.get("service_name") or service_id})
        checks.append({"key": "logs_accessible", "ok": True, "label": "Production logs accessible", "detail": verify.get("message") or "Logs accessible"})
    else:
        checks.append({"key": "provider_authenticated", "ok": True, "label": "Manual log provider ready", "detail": "Manual log ingestion available"})

    settings_payload = ProjectSettings(
        sandbox_mode=settings.SANDBOX_MODE,
        build_command=str(req.runtime_overrides.get("build_command") or ""),
        test_command=str(req.runtime_overrides.get("test_command") or profile.test_command or ""),
        run_command=str(req.runtime_overrides.get("run_command") or profile.run_command or ""),
        source_configuration={
            "entrypoint": req.runtime_overrides.get("entrypoint") or profile.entrypoint,
            "language": profile.language,
            "framework": profile.framework,
            "package_manager": profile.package_manager,
        },
        diagnosis_settings=req.diagnosis_settings or {},
        repair_settings=req.repair_settings or {},
        runtime_summary=profile.model_dump(),
    )

    repository_payload = {
        "owner": owner,
        "repo": repo,
        "branch": branch,
        "repository_url": repo_info.get("html_url") or f"https://github.com/{owner}/{repo}",
        "full_name": repo_info.get("full_name") or f"{owner}/{repo}",
        "description": repo_info.get("description") or "",
        "login": login,
    }
    return checks, repository_payload, deployment_payload, workspace_path, profile, settings_payload


@router.get("", response_model=list[Project])
async def list_projects(user: UserResponse = Depends(require_authenticated_user)) -> list[Project]:
    return project_store.list_all(user.id)


@router.get("/current", response_model=Project)
async def get_current_project(user: UserResponse = Depends(require_authenticated_user)) -> Project:
    project = project_store.get_current(user.id)
    if not project:
        raise HTTPException(404, "No project is configured.")
    return project


@router.post("/onboarding/github/repositories")
async def list_accessible_repositories(req: GitHubTokenRequest) -> dict[str, Any]:
    token = (req.token or "").strip()
    if not token:
        raise HTTPException(400, "GitHub token is required.")
    client = GitHubClient(token=token)
    try:
        user = await client.verify_credentials()
        repos = await client.list_accessible_repositories()
    except GitHubError as exc:
        raise HTTPException(401, f"GitHub authentication failed. Check the token permissions. ({exc})") from exc
    return {"status": "ok", "user": user, "repositories": repos}


@router.post("/onboarding/github/branches")
async def list_repository_branches(req: RepositoryBranchRequest) -> dict[str, Any]:
    client = GitHubClient(token=(req.token or "").strip(), owner=req.owner.strip(), repo=req.repo.strip())
    try:
        repo = await client.get_repo()
        branches = await client.list_branches()
    except GitHubError as exc:
        raise HTTPException(400, f"Repository not found or inaccessible. ({exc})") from exc
    return {
        "status": "ok",
        "repository": {
            "owner": req.owner,
            "repo": req.repo,
            "default_branch": repo.get("default_branch") or "main",
            "description": repo.get("description") or "",
            "html_url": repo.get("html_url") or "",
        },
        "branches": branches,
    }


@router.post("/onboarding/render/services")
async def list_render_services(req: RenderKeyRequest) -> dict[str, Any]:
    provider = RenderLogProvider(api_key=req.api_key.strip())
    try:
        services = await provider.get_services()
    except RenderError as exc:
        raise HTTPException(401, f"Render authentication failed. Check the API key. ({exc})") from exc
    return {"status": "ok", "services": services}


@router.post("/onboarding/render/verify")
async def verify_render_service(req: RenderVerifyRequest) -> dict[str, Any]:
    provider = RenderLogProvider(api_key=req.api_key.strip(), service_id=req.service_id.strip(), owner_id=req.owner_id.strip())
    try:
        result = await provider.verify_connection()
    except RenderError as exc:
        raise HTTPException(400, f"Render authentication succeeded, but logs could not be accessed. ({exc})") from exc
    return {"status": "ok", **result}


@router.post("/onboarding/preview", response_model=PreviewResponse)
async def preview_project(req: ProjectOnboardingRequest) -> PreviewResponse:
    checks, repository_payload, deployment_payload, workspace_path, profile, settings_payload = await _prepare_onboarding(req)
    return PreviewResponse(
        status="ok",
        checks=checks,
        profile=profile,
        settings=settings_payload,
        repository=repository_payload,
        deployment=deployment_payload,
        workspace_path=str(workspace_path),
    )


@router.post("", response_model=CreateProjectResponse)
async def create_project(req: ProjectOnboardingRequest, user: UserResponse = Depends(require_authenticated_user)) -> CreateProjectResponse:
    checks, repository_payload, deployment_payload, workspace_path, profile, settings_payload = await _prepare_onboarding(req)

    project = project_store.create_project(
        user_id=user.id,
        name=req.name.strip(),
        description=req.description.strip(),
        github_owner=repository_payload["owner"],
        github_repo=repository_payload["repo"],
        default_branch=repository_payload["branch"],
        repository_url=repository_payload["repository_url"],
        workspace_path=str(workspace_path),
        profile=profile,
        settings=settings_payload,
        status="connected",
        activate=req.activate,
    )

    project_store.upsert_integration(
        project_id=project.id,
        provider="github",
        configuration={
            "owner": repository_payload["owner"],
            "repo": repository_payload["repo"],
            "branch": repository_payload["branch"],
            "repository_url": repository_payload["repository_url"],
            "full_name": repository_payload["full_name"],
            "login": repository_payload.get("login") or "",
        },
        credentials={"token": (req.github.token or "").strip()} if req.github.token else {},
        enabled=True,
        status="connected",
    )

    provider_name = (req.deployment.provider or "manual").lower()
    if provider_name == "render":
        project_store.upsert_integration(
            project_id=project.id,
            provider="render",
            configuration={
                "service_id": deployment_payload.get("service_id") or req.deployment.service_id or "",
                "service_name": deployment_payload.get("service_name") or req.deployment.service_name or "",
                "owner_id": deployment_payload.get("owner_id") or req.deployment.owner_id or "",
            },
            credentials={"api_key": (req.deployment.api_key or "").strip()},
            enabled=True,
            status="connected",
        )
    else:
        project_store.upsert_integration(project_id=project.id, provider="manual", configuration={}, credentials={}, enabled=True, status="connected")

    project_store.save_settings(project.id, settings_payload.model_copy(update={"project_id": project.id}))
    project = project_store.get(project.id, user.id) or project
    return CreateProjectResponse(status="ok", message="Project created successfully.", project=project, checks=checks)


@router.post("/connect", response_model=ConnectProjectResponse)
async def connect_repository(req: ConnectProjectRequest, user: UserResponse = Depends(require_authenticated_user)) -> ConnectProjectResponse:
    payload = ProjectOnboardingRequest(
        name=req.project_name or f"{req.github_owner}/{req.github_repo}",
        description=req.project_description or "",
        github=GitHubSelection(token=req.github_token or "", owner=req.github_owner, repo=req.github_repo, branch=req.github_branch),
        deployment=DeploymentSelection(
            provider="render" if req.render_service_id or req.render_api_key else "manual",
            api_key=req.render_api_key or "",
            service_id=req.render_service_id or "",
            owner_id=req.render_owner_id or "",
        ),
        activate=True,
    )
    created = await create_project(payload, user)
    steps = ["github_connected", "repository_verified", "repository_synchronized", "project_discovered"]
    if payload.deployment.provider == "render":
        steps.extend(["render_connected", "logs_accessible"])
    return ConnectProjectResponse(status=created.status, message=created.message, project=created.project, steps_completed=steps)


@router.get("/files/list")
async def list_project_files(project_id: str | None = None, user: UserResponse = Depends(require_authenticated_user)) -> dict[str, Any]:
    project, ws_path = _require_connected_workspace(user.id, project_id)
    wm = WorkspaceManager(repo_root=ws_path)
    return {"project_id": project.id, "files": wm.files(), "tree": wm.file_tree()}


@router.get("/file-content")
async def get_file_content(path: str = Query(...), project_id: str | None = None, user: UserResponse = Depends(require_authenticated_user)) -> dict[str, Any]:
    _project, ws_path = _require_connected_workspace(user.id, project_id)
    wm = WorkspaceManager(repo_root=ws_path)
    content = wm.read_relative(None, path)
    if content is None:
        raise HTTPException(404, f"File {path!r} not found in workspace.")
    return {"path": path, "content": content}


@router.get("/{project_id}", response_model=Project)
async def get_project(project_id: str, user: UserResponse = Depends(require_authenticated_user)) -> Project:
    project = project_store.get(project_id, user.id)
    if not project:
        raise HTTPException(404, f"project {project_id!r} not found")
    return project


@router.post("/{project_id}/github/verify")
async def verify_project_github(project_id: str, user: UserResponse = Depends(require_authenticated_user)) -> dict[str, Any]:
    project = _require_project(user.id, project_id)
    github = project_store.resolve_github(project_id)
    if not github.get("owner") or not github.get("repo"):
        raise HTTPException(400, "GitHub repository is not configured for this project.")
    client = GitHubClient(token=github.get("token", ""), owner=github.get("owner", ""), repo=github.get("repo", ""), default_branch=github.get("branch", "main"))
    try:
        repo = await client.verify_access()
        branches = await client.list_branches()
    except GitHubError as exc:
        raise HTTPException(400, f"GitHub authentication failed. Check the token permissions. ({exc})") from exc
    return {"status": "connected", "repository": repo, "branches": branches, "message": "GitHub repository verified successfully.", "project_id": project.id}


@router.post("/{project_id}/render/verify")
async def verify_project_render(project_id: str, user: UserResponse = Depends(require_authenticated_user)) -> dict[str, Any]:
    _require_project(user.id, project_id)
    render = project_store.resolve_render(project_id)
    if not render.get("api_key") or not render.get("service_id"):
        raise HTTPException(400, "Render integration is not configured for this project.")
    provider = RenderLogProvider(api_key=render.get("api_key", ""), service_id=render.get("service_id", ""), owner_id=render.get("owner_id", ""))
    try:
        result = await provider.verify_connection()
    except RenderError as exc:
        raise HTTPException(400, f"Render authentication succeeded, but logs could not be accessed. ({exc})") from exc
    return {"status": "connected", "project_id": project_id, **result}


@router.put("/{project_id}", response_model=Project)
async def update_project(project_id: str, payload: dict[str, Any], user: UserResponse = Depends(require_authenticated_user)) -> Project:
    project = project_store.update_project(project_id, payload, user.id)
    if not project:
        raise HTTPException(404, f"project {project_id!r} not found")
    return project


@router.post("/{project_id}/duplicate", response_model=Project)
async def duplicate_project(project_id: str, payload: DuplicateProjectRequest, user: UserResponse = Depends(require_authenticated_user)) -> Project:
    project = project_store.duplicate_project(project_id, user.id, payload.name)
    if not project:
        raise HTTPException(404, f"project {project_id!r} not found")
    return project


@router.delete("/{project_id}")
async def delete_project(project_id: str, user: UserResponse = Depends(require_authenticated_user)) -> dict[str, Any]:
    deleted = project_store.delete(project_id, user.id)
    if not deleted:
        raise HTTPException(404, f"project {project_id!r} not found")
    from app.orchestrator import orchestrator

    await orchestrator.reset_current(user.id)
    return {"status": "ok", "deleted": True}


@router.post("/{project_id}/activate", response_model=Project)
async def activate_project(project_id: str, user: UserResponse = Depends(require_authenticated_user)) -> Project:
    project = project_store.set_current(project_id, user.id)
    if not project:
        raise HTTPException(404, f"project {project_id!r} not found")
    # A project switch is always a clean console; live diagnosis state is not
    # carried between workspaces.
    from app.orchestrator import orchestrator

    await orchestrator.reset_current(user.id)
    return project


@router.get("/{project_id}/integrations")
async def project_integrations(project_id: str, user: UserResponse = Depends(require_authenticated_user)) -> dict[str, Any]:
    _require_project(user.id, project_id)
    return {"project_id": project_id, "integrations": project_store.list_integrations(project_id)}


@router.get("/{project_id}/settings", response_model=ProjectSettings)
async def get_project_settings(project_id: str, user: UserResponse = Depends(require_authenticated_user)) -> ProjectSettings:
    _require_project(user.id, project_id)
    return project_store.get_settings(project_id)


@router.put("/{project_id}/settings", response_model=ProjectSettings)
async def update_project_settings(project_id: str, settings_payload: ProjectSettings, user: UserResponse = Depends(require_authenticated_user)) -> ProjectSettings:
    _require_project(user.id, project_id)
    payload = settings_payload.model_copy(update={"project_id": project_id})
    return project_store.save_settings(project_id, payload)


@router.get("/{project_id}/status", response_model=ProjectStatus)
async def get_project_status(project_id: str, user: UserResponse = Depends(require_authenticated_user)) -> ProjectStatus:
    project = _require_project(user.id, project_id)
    integrations = project_store.list_integrations(project_id)
    active_log_provider = next((item.provider for item in integrations if item.enabled and item.provider in {"render", "manual"}), None)
    return ProjectStatus(project=project, integrations=integrations, workspace_ready=bool(project.workspace_path and Path(project.workspace_path).is_dir()), active_log_provider=active_log_provider)


@router.post("/{project_id}/sync", response_model=Project)
async def sync_project(project_id: str, user: UserResponse = Depends(require_authenticated_user)) -> Project:
    project = _require_project(user.id, project_id)
    github = project_store.resolve_github(project_id)
    if not github.get("owner") or not github.get("repo"):
        raise HTTPException(400, "Project GitHub configuration is incomplete.")
    service = GitHubService(GitHubClient(token=github.get("token", ""), owner=github.get("owner", ""), repo=github.get("repo", ""), default_branch=github.get("branch", "main")))
    try:
        workspace = service.sync_project_workspace(project)
        profile = discover_project(workspace)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Failed to synchronize repository: {exc}") from exc
    refreshed = project_store.mark_synced(project_id, str(workspace), profile=profile)
    if not refreshed:
        raise HTTPException(404, f"project {project_id!r} not found")
    settings_payload = project_store.get_settings(project_id)
    if not settings_payload.run_command:
        settings_payload.run_command = profile.run_command or ""
    if not settings_payload.test_command:
        settings_payload.test_command = profile.test_command or ""
    project_store.save_settings(project_id, settings_payload)
    return refreshed
