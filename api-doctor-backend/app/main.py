"""API Doctor backend — FastAPI application entry point."""

from __future__ import annotations

import logging
import shutil
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
    # Remove rollback artifacts created by older builds. Current diagnosis
    # snapshots live only in memory and disappear at reset/shutdown.
    shutil.rmtree(Path(settings.DATA_DIR) / "apply_backups", ignore_errors=True)
    init_db()

    ai_provider = selected_ai_provider()
    logger.info(
        "API Doctor backend starting up (Mode: %s, AI provider: %s, DB: %s)",
        "REAL PROJECT",
        ai_provider,
        settings.DATABASE_URL,
    )

    if not settings.has_nvidia:
        logger.warning(
            "NVIDIA_API_KEY is not set. The application cannot run real AI "
            "diagnosis until a key is configured."
        )

    logger.info(
        "Project database ready (%s project(s) configured).",
        project_store.count(),
    )
    yield
    from app.runs.store import run_store

    run_store.clear()
    logger.info("API Doctor backend shutting down; current diagnosis state cleared")


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
    from app.runs.router import router as runs_router
    from app.projects.router import router as projects_router
    from app.tools.registry import tool_registry
    from app.tools import tools  # noqa: F401

    # INTERNAL SAMPLE / REGRESSION HARNESS. Not a product feature: it is never
    # surfaced in the UI and is hidden from the OpenAPI docs. The sandbox
    # verification (reproduce -> patch -> verify) and the failure detector
    # exercise a FastAPI project's own ``app.main``; this sample API gives the
    # automated tests a deterministic live target without a real deployment.
    from app.demo_api.router import router as sample_router

    app.include_router(sample_router, include_in_schema=False)

    app.include_router(auth_router)
    app.include_router(runs_router)
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

        current = None
        projects: list = []
        try:
            projects = project_store.list_all()
            current = project_store.get_current()
        except Exception:
            logger.exception("Health check could not resolve project state")

        return {
            "status": "ok",
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
