"""Concrete implementations of the controlled tools, registered on import."""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.code_retrieval.local_retriever import LocalRetriever
from app.core.config import settings
from app.sandbox.patch_utils import apply_patch, validate_diff
from app.tools.registry import Tool, tool_registry

_ROOT = Path(settings.INTERNAL_REPO_ROOT).resolve()


def _safe_rel(path: str) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p.resolve().relative_to(_ROOT)
    resolved = (_ROOT / p).resolve()
    try:
        resolved.relative_to(_ROOT)
    except ValueError as exc:
        raise PermissionError(f"path outside repo: {path}") from exc
    return p


async def _read_file(path: str) -> dict:
    rel = _safe_rel(path)
    full = _ROOT / rel
    if not full.is_file():
        return {"error": f"not found: {rel}"}
    return {"path": str(rel), "content": full.read_text(encoding="utf-8", errors="replace")}


async def _search_code(pattern: str) -> dict:
    import re

    regex = re.compile(pattern)
    hits = []
    for p in _ROOT.rglob("*.py"):
        if any(x in {part for part in p.parts} for x in ("__pycache__", ".git", ".venv")):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                rel = str(p.relative_to(_ROOT))
                hits.append({"file": rel, "line": i, "text": line.strip()[:200]})
                if len(hits) >= 50:
                    return {"count": len(hits), "hits": hits}
    return {"count": len(hits), "hits": hits}


async def _list_files(path: str = ".") -> dict:
    base = (_ROOT / _safe_rel(path)).resolve()
    try:
        base.relative_to(_ROOT)
    except ValueError as exc:
        raise PermissionError(f"path outside repo: {path}") from exc
    files = []
    for p in sorted(base.rglob("*")):
        if p.is_file() and not any(x in p.parts for x in ("__pycache__", ".git", ".venv")):
            files.append(str(p.relative_to(_ROOT)))
    return {"path": str(path), "files": files[:500], "count": len(files)}


async def _get_git_status() -> dict:
    try:
        status = subprocess.run(
            ["git", "-C", str(_ROOT), "status", "--short"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        log = subprocess.run(
            ["git", "-C", str(_ROOT), "log", "--oneline", "-5"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception as exc:
        return {"error": str(exc)}
    return {"status": status, "recent_commits": log}


async def _get_logs(incident_id: str | None = None) -> dict:
    from app.incidents.store import incident_store

    if incident_id:
        inc = incident_store.get(incident_id)
        if not inc:
            return {"error": f"incident not found: {incident_id}"}
        return {"incident_id": incident_id, "stack_trace": inc.stack_trace}
    return {"note": "Provide incident_id to fetch its logs."}


async def _get_deployment_status(project_id: str = "default") -> dict:
    from app.projects.store import project_store
    from app.render.client import RenderClient

    project = project_store.get(project_id)
    render = project_store.resolve_render(project_id)
    if not project or not render.get("service_id"):
        return {"present": False, "note": "no Render service mapped for project"}
    client = RenderClient(
        api_key=render.get("api_key", ""),
        service_id=render.get("service_id", ""),
        owner_id=render.get("owner_id", ""),
    )
    return await client.get_deployment_status(service_id=render.get("service_id"))


async def _run_test(incident_id: str) -> dict:
    # Runs the sandbox verification (reproduce -> patch -> tests) for an incident.
    import asyncio

    from app.incidents.store import incident_store
    from app.sandbox.sandbox_runner import SandboxRunner

    inc = incident_store.get(incident_id)
    if not inc or not inc.fix_proposal:
        return {"error": "incident has no fix proposal to test"}
    runner = SandboxRunner()
    # run_verification is synchronous (subprocess-blocking); offload it.
    result = await asyncio.to_thread(runner.run_verification, inc.fix_proposal, inc.request_snapshot)
    return result.model_dump()


async def _run_build(incident_id: str | None = None) -> dict:
    import subprocess as sp

    result = sp.run(
        ["python", "-m", "compileall", "-q", "app"],
        cwd=str(_ROOT), capture_output=True, text=True, timeout=120,
    )
    return {"ok": result.returncode == 0, "detail": (result.stdout + result.stderr)[-1500:]}


async def _apply_patch(diff: str, workspace_root: str | None = None) -> dict:
    validate_diff(diff)
    root = Path(workspace_root) if workspace_root else _ROOT
    affected = apply_patch(diff, root)
    return {"ok": True, "affected_files": affected}


def _github_service_for_project(project_id: str):
    """Build a GitHub service from one project's stored integration credentials."""
    from app.github.client import GitHubClient
    from app.github.service import GitHubService
    from app.projects.store import project_store

    project = project_store.get(project_id)
    if not project:
        raise ValueError(f"project not found: {project_id}")
    github = project_store.resolve_github(project.id)
    if not github.get("owner") or not github.get("repo") or not github.get("token"):
        raise ValueError("GitHub integration is not configured for this project")
    return project, GitHubService(
        GitHubClient(
            token=github["token"],
            owner=github["owner"],
            repo=github["repo"],
            default_branch=github.get("branch") or "main",
        )
    )


async def _create_branch(incident_id: str, project_id: str = "default") -> dict:
    project, service = _github_service_for_project(project_id)
    branch = service._branch_name(incident_id)
    base = project.github_branch or service.client.default_branch
    branches = await service.client.list_branches()
    if branch not in branches:
        await service.client.create_branch(branch, base)
    return {"ok": True, "branch": branch}


async def _commit_changes(
    incident_id: str, message: str, files: list[dict], project_id: str = "default"
) -> dict:
    _project, service = _github_service_for_project(project_id)
    branch = service._branch_name(incident_id)
    sha = await service.client.create_commit(branch, message, files)
    return {"ok": True, "branch": branch, "commit": sha}


async def _create_pull_request(
    incident_id: str, title: str, body: str, project_id: str = "default"
) -> dict:
    project, service = _github_service_for_project(project_id)
    branch = service._branch_name(incident_id)
    pr = await service.client.create_pull_request(
        head=branch, title=title, body=body, base=project.github_branch
    )
    return {"ok": True, "pr_number": pr.get("number"), "pr_url": pr.get("html_url")}


def _register_tools() -> None:
    tool_registry.register(
        Tool("read_file", "Read a file from the repository (relative path).",
             {"path": "string"}, ["path"], _read_file)
    )
    tool_registry.register(
        Tool("search_code", "Regex-search source files for a symbol/pattern.",
             {"pattern": "string"}, ["pattern"], _search_code)
    )
    tool_registry.register(
        Tool("list_files", "List files under a directory (relative path).",
             {"path": "string"}, [], _list_files)
    )
    tool_registry.register(
        Tool("get_logs", "Get logs / stack trace for an incident.",
             {"incident_id": "string"}, ["incident_id"], _get_logs)
    )
    tool_registry.register(
        Tool("get_deployment_status", "Get Render deployment status for a project.",
             {"project_id": "string"}, [], _get_deployment_status)
    )
    tool_registry.register(
        Tool("get_git_status", "Get repository git status and recent commits.",
             {}, [], _get_git_status)
    )
    tool_registry.register(
        Tool("run_test", "Run sandbox verification for an incident.",
             {"incident_id": "string"}, ["incident_id"], _run_test)
    )
    tool_registry.register(
        Tool("run_build", "Compile-check the repository.",
             {"incident_id": "string"}, [], _run_build)
    )
    tool_registry.register(
        Tool("apply_patch", "Apply a validated unified diff.",
             {"diff": "string", "workspace_root": "string"}, ["diff"], _apply_patch)
    )
    tool_registry.register(
        Tool("create_branch", "Create the repair branch for an incident.",
             {"incident_id": "string", "project_id": "string"}, ["incident_id"], _create_branch)
    )
    tool_registry.register(
        Tool("commit_changes", "Commit changed files to the repair branch.",
             {"incident_id": "string", "message": "string", "files": "list", "project_id": "string"},
             ["incident_id", "message", "files"], _commit_changes)
    )
    tool_registry.register(
        Tool("create_pull_request", "Open a pull request for the repair.",
             {"incident_id": "string", "title": "string", "body": "string", "project_id": "string"},
             ["incident_id", "title", "body"], _create_pull_request)
    )


_register_tools()
