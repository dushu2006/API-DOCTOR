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
    from app.github.client import GitHubClient
    from app.render.client import RenderClient

    ai_provider = selected_ai_provider()
    logger.info(
        "API Doctor backend starting up (Mode: %s, AI provider: %s)",
        "DEMO" if settings.DEMO_MODE else "REAL PROJECT",
        ai_provider,
    )

    if ai_provider == "mock":
        logger.info("Deterministic mock AI is active. Set AI_PROVIDER=nvidia and NVIDIA_API_KEY for NVIDIA NIM.")
    elif not settings.has_nvidia:
        logger.warning("NVIDIA_API_KEY is not set; requests requiring external NVIDIA models will fall back.")

    # Validate GitHub credentials only — never clone or synchronize a repository at startup.
    if settings.GITHUB_TOKEN:
        try:
            gh_client = GitHubClient()
            info = await gh_client.verify_credentials()
            logger.info("GitHub credentials validated (login=%s).", info.get("login"))
        except Exception as exc:
            logger.warning("GitHub credential validation failed: %s", exc)
    else:
        logger.info("GitHub token not configured. Connect a repository via POST /api/projects/connect.")

    if settings.GITHUB_OWNER or settings.GITHUB_REPO:
        logger.info(
            "GITHUB_OWNER/GITHUB_REPO are set (%s/%s) but will not be auto-synchronized. "
            "Select a repository with POST /api/projects/connect.",
            settings.GITHUB_OWNER,
            settings.GITHUB_REPO,
        )

    # Validate Render integration (service access only — do not pull logs at startup).
    if settings.RENDER_API_KEY and settings.RENDER_SERVICE_ID:
        try:
            render = RenderClient()
            service = await render.get_service()
            logger.info(
                "Render integration validated for service %s (%s).",
                service.get("id") or settings.RENDER_SERVICE_ID,
                service.get("name") or "unnamed",
            )
        except Exception as exc:
            logger.warning("Render integration validation failed: %s", exc)
    elif settings.RENDER_API_KEY or settings.RENDER_SERVICE_ID:
        logger.warning("Render integration is incomplete (need both RENDER_API_KEY and RENDER_SERVICE_ID).")
    else:
        logger.info("Render integration is not configured (RENDER_API_KEY / RENDER_SERVICE_ID missing).")

    logger.info("Backend ready. Project connection APIs exposed at /api/projects/connect.")
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
        from app.projects.store import project_store

        current = project_store.get_current()
        return {
            "status": "ok",
            "demo_mode": settings.DEMO_MODE,
            "sandbox_mode": settings.SANDBOX_MODE,
            "docker": docker_ok,
            "ai_provider": selected_ai_provider(),
            "ai_configured": settings.has_nvidia,
            "github_configured": bool(settings.GITHUB_TOKEN),
            "render_configured": settings.has_render,
            "project_connected": bool(current and current.is_connected),
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
