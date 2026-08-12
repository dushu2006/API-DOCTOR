"""API Doctor backend — FastAPI application entry point.

Mounts:
    * real project workspace and incident management -> /api/incidents, /api/projects
    * demo patient API -> /api/v1 (mounted ONLY when DEMO_MODE=true)
"""

from __future__ import annotations

import logging
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging_config import setup_logging

setup_logging("INFO")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.ai.base import selected_ai_provider
    from app.github.client import GitHubClient, GitHubError
    from app.projects.discovery import discover_project
    from app.projects.models import Project
    from app.projects.store import project_store
    from app.sandbox.workspace_manager import WorkspaceManager

    ai_provider = selected_ai_provider()
    logger.info("API Doctor backend starting up (Mode: %s, AI provider: %s)", "DEMO" if settings.DEMO_MODE else "REAL PROJECT", ai_provider)

    if ai_provider == "mock":
        logger.info("Deterministic mock AI is active. Set AI_PROVIDER=nvidia and NVIDIA_API_KEY for NVIDIA NIM.")
    elif not settings.has_nvidia:
        logger.warning("NVIDIA_API_KEY is not set; requests requiring external NVIDIA models will fall back.")

    # Validate Render configuration
    if not settings.has_render:
        logger.info("Render integration is not configured (RENDER_API_KEY / RENDER_SERVICE_ID missing).")
    else:
        logger.info("Render integration configured for service: %s", settings.RENDER_SERVICE_ID)

    # Validate and synchronize GitHub repository at startup if configured
    if settings.has_github:
        logger.info("GitHub integration configured: %s/%s@%s", settings.GITHUB_OWNER, settings.GITHUB_REPO, settings.GITHUB_DEFAULT_BRANCH)
        try:
            gh_client = GitHubClient()
            if settings.GITHUB_TOKEN:
                await gh_client.verify_access()
                logger.info("GitHub repository access verified successfully.")

            # Synchronize repository into local working workspace
            wm = WorkspaceManager()
            ws_path = wm.sync_repository(
                owner=settings.GITHUB_OWNER,
                repo=settings.GITHUB_REPO,
                branch=settings.GITHUB_DEFAULT_BRANCH,
                token=settings.GITHUB_TOKEN,
            )
            logger.info("Repository synchronized to workspace: %s", ws_path)

            # Discover project profile
            profile = discover_project(ws_path)
            logger.info(
                "Project discovered: Language=%s, Framework=%s, PackageManager=%s, Entrypoint=%s",
                profile.language, profile.framework, profile.package_manager, profile.entrypoint
            )

            # Update project store
            proj = Project(
                id="default",
                name=f"{settings.GITHUB_OWNER}/{settings.GITHUB_REPO}",
                github_owner=settings.GITHUB_OWNER,
                github_repo=settings.GITHUB_REPO,
                github_branch=settings.GITHUB_DEFAULT_BRANCH,
                github_token=settings.GITHUB_TOKEN,
                render_service_id=settings.RENDER_SERVICE_ID,
                repo_root=str(ws_path),
                workspace_path=str(ws_path),
                is_connected=True,
                profile=profile,
            )
            project_store.update(proj)
            project_store.set_current("default")
        except Exception as exc:
            logger.warning("Could not complete initial GitHub sync at startup: %s", exc)
    else:
        logger.info("No GitHub repository configured at startup. Connect a repository via the UI.")

    yield
    logger.info("API Doctor backend shutting down")


app = FastAPI(
    title="API Doctor Backend",
    version="1.0.0",
    description="Real GitHub-project-driven API debugging and repair system.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        raise exc
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": str(exc),
            "traceback": traceback.format_exc(),
            "path": request.url.path,
        },
    )


def _register_routes() -> None:
    from app.incidents.router import router as incidents_router
    from app.projects.router import router as projects_router
    from app.tools.registry import tool_registry
    from app.tools import tools  # noqa: F401

    # Demo API router is mounted ONLY when explicitly configured
    if settings.DEMO_MODE:
        from app.demo_api.router import router as demo_router
        app.include_router(demo_router)
        logger.info("Mounted demo API endpoints at /api/v1 (DEMO_MODE=true)")

    app.include_router(incidents_router)
    app.include_router(projects_router)

    @app.get("/health")
    async def health() -> dict:
        from app.ai.base import selected_ai_provider

        docker_ok = False
        try:
            import docker  # type: ignore

            docker.from_env().ping()
            docker_ok = True
        except Exception:
            docker_ok = False
        return {
            "status": "ok",
            "demo_mode": settings.DEMO_MODE,
            "sandbox_mode": settings.SANDBOX_MODE,
            "docker": docker_ok,
            "ai_provider": selected_ai_provider(),
            "ai_configured": settings.has_nvidia,
            "github_configured": settings.has_github,
            "render_configured": settings.has_render,
        }

    @app.get("/api/tools")
    async def list_tools() -> dict:
        return {"tools": tool_registry.list()}

    @app.post("/api/benchmark")
    async def benchmark(task: str = "root_cause") -> dict:
        from app.benchmark import run_benchmark

        results = await run_benchmark(task)
        return {"results": [r.model_dump() for r in results]}


_register_routes()
