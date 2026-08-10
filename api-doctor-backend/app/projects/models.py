"""Project configuration — maps a project to its GitHub repository/branch and
Render service. Stored in memory for the MVP; designed so a database can replace
the store later."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.config import settings


class Project(BaseModel):
    id: str = "default"
    name: str = "API Doctor"
    github_owner: str = Field(default_factory=lambda: settings.GITHUB_OWNER)
    github_repo: str = Field(default_factory=lambda: settings.GITHUB_REPO)
    github_branch: str = Field(default_factory=lambda: settings.GITHUB_DEFAULT_BRANCH)
    render_service_id: str = Field(default_factory=lambda: settings.RENDER_SERVICE_ID)
    repo_root: str = Field(default_factory=lambda: settings.REPO_ROOT)
    auto_merge: bool = Field(default_factory=lambda: settings.AUTO_MERGE)
    auto_create_pr: bool = Field(default_factory=lambda: settings.AUTO_CREATE_PR)
