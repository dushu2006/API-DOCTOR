"""API Doctor backend — FastAPI application entry point.

Mounts:
    * the "patient" demo API  -> /api/v1
    * the incident dashboard  -> /api/incidents
    * project config          -> /api/projects
    * a generic Exception handler that surfaces tracebacks on 5xx so the
      detector (and dashboard) can see realistic failures.
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

    ai_provider = selected_ai_provider()
    logger.info("API Doctor backend starting up (AI provider: %s)", ai_provider)
    if ai_provider == "mock":
        logger.warning(
            "Deterministic mock AI is active. Set AI_PROVIDER=nvidia and "
            "NVIDIA_API_KEY to run real model diagnosis."
        )
    elif not settings.has_nvidia:
        logger.error("NVIDIA_API_KEY is not set; NVIDIA AI requests will fail.")
    yield
    logger.info("API Doctor backend shutting down")


app = FastAPI(
    title="API Doctor Backend",
    version="1.0.0",
    description="AI-powered production incident diagnosis and repair system.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Demo frontend; tighten for production.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a JSON 500 with the real traceback (mirrors a debug-mode server /
    an APM agent report). This is what the detector parses."""
    if isinstance(exc, HTTPException):
        # Let FastAPI's default HTTPException handling win.
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
    from app.demo_api.router import router as demo_router
    from app.incidents.router import router as incidents_router
    from app.projects.router import router as projects_router
    from app.tools.registry import tool_registry
    from app.tools import tools  # noqa: F401  (registers tools)

    app.include_router(demo_router)
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
