"""API Doctor backend — FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging_config import setup_logging
from app.db.base import init_db

setup_logging(settings.LOG_LEVEL)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.ai.base import selected_ai_provider
    from app.projects.store import project_store

    Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
    Path(settings.WORKSPACE_DIR).mkdir(parents=True, exist_ok=True)
    init_db()

    ai_provider = selected_ai_provider()
    logger.info(
        "API Doctor backend starting up (Mode: %s, AI provider: %s, DB: %s)",
        "DEMO" if settings.DEMO_MODE else "REAL PROJECT",
        ai_provider,
        settings.DATABASE_URL,
    )

    if ai_provider == "mock":
        logger.info("Deterministic mock AI is active. Set NVIDIA_API_KEY to use NVIDIA NIM.")
    elif not settings.has_nvidia:
        logger.warning("NVIDIA_API_KEY is not set; requests requiring external NVIDIA models will fall back.")

    logger.info(
        "Project database ready (%s project(s) configured).",
        project_store.count(),
    )
    yield
    logger.info("API Doctor backend shutting down")


app = FastAPI(
    title="API Doctor Backend",
    version="2.0.0",
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
            "detail": "Internal server error",
            "path": request.url.path,
        },
    )


def _register_routes() -> None:
    from app.auth.router import router as auth_router
    from app.incidents.router import router as incidents_router
    from app.projects.router import router as projects_router
    from app.tools.registry import tool_registry
    from app.tools import tools  # noqa: F401

    if settings.DEMO_MODE:
        from app.demo_api.router import router as demo_router

        app.include_router(demo_router)
        logger.info("Mounted demo API endpoints at /api/v1 (DEMO_MODE=true)")

    app.include_router(auth_router)
    app.include_router(incidents_router)
    app.include_router(projects_router)

    @app.get("/health")
    async def health() -> dict:
        from app.ai.base import selected_ai_provider
        from app.projects.store import project_store

        docker_ok = False
        try:
            import docker  # type: ignore

            docker.from_env().ping()
            docker_ok = True
        except Exception:
            docker_ok = False

        current = project_store.get_current()
        projects = project_store.list_all()
        return {
            "status": "ok",
            "demo_mode": settings.DEMO_MODE,
            "sandbox_mode": settings.SANDBOX_MODE,
            "docker": docker_ok,
            "ai_provider": selected_ai_provider(),
            "ai_configured": settings.has_nvidia,
            "database_configured": bool(settings.DATABASE_URL),
            "project_count": len(projects),
            "active_project_id": current.id if current else None,
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
