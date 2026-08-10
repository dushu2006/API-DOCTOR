"""Project endpoints (project -> GitHub repo/branch -> Render service)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.projects.models import Project
from app.projects.store import project_store

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("")
async def list_projects() -> list[Project]:
    return project_store.list_all()


@router.get("/{project_id}")
async def get_project(project_id: str) -> Project:
    project = project_store.get(project_id)
    if not project:
        raise HTTPException(404, f"project {project_id!r} not found")
    return project


@router.post("")
async def upsert_project(project: Project) -> Project:
    return project_store.update(project)
