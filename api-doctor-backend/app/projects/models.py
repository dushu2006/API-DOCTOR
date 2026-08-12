"""Project configuration and metadata models.

Maps a project to its GitHub repository/branch, Render service, local workspace,
and discovered project profile.
"""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field

from app.core.config import settings


class ProjectProfile(BaseModel):
    """Discovered profile of a project repository."""

    language: str = "Unknown"
    framework: str = "Unknown"
    package_manager: str = "Unknown"
    entrypoint: Optional[str] = None
    test_framework: Optional[str] = None
    test_command: Optional[str] = None
    run_command: Optional[str] = None
    dependency_files: list[str] = Field(default_factory=list)
    configuration_files: list[str] = Field(default_factory=list)
    environment_variable_references: list[str] = Field(default_factory=list)
    source_directories: list[str] = Field(default_factory=list)


class Project(BaseModel):
    id: str = "default"
    name: str = "API Doctor"
    github_owner: str = Field(default_factory=lambda: settings.GITHUB_OWNER)
    github_repo: str = Field(default_factory=lambda: settings.GITHUB_REPO)
    github_branch: str = Field(default_factory=lambda: settings.GITHUB_DEFAULT_BRANCH)
    github_token: str = Field(default_factory=lambda: settings.GITHUB_TOKEN)
    render_service_id: str = Field(default_factory=lambda: settings.RENDER_SERVICE_ID)
    repo_root: str = Field(default_factory=lambda: settings.REPO_ROOT)
    workspace_path: Optional[str] = None
    is_connected: bool = False
    profile: Optional[ProjectProfile] = None
    auto_merge: bool = Field(default_factory=lambda: settings.AUTO_MERGE)
    auto_create_pr: bool = Field(default_factory=lambda: settings.AUTO_CREATE_PR)
