"""Project configuration and metadata models."""

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


class IntegrationInfo(BaseModel):
    id: str = ""
    project_id: str = ""
    provider: str
    enabled: bool = True
    configured: bool = True
    status: str = "disconnected"
    safe_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_verified_at: Optional[str] = None


class ProjectSettings(BaseModel):
    project_id: str = ""
    sandbox_mode: str = ""
    build_command: str = ""
    test_command: str = ""
    run_command: str = ""
    source_configuration: dict[str, Any] = Field(default_factory=dict)
    diagnosis_settings: dict[str, Any] = Field(default_factory=dict)
    repair_settings: dict[str, Any] = Field(default_factory=dict)
    runtime_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class Project(BaseModel):
    id: str = ""
    name: str = ""
    description: str = ""
    github_owner: str = ""
    github_repo: str = ""
    default_branch: str = "main"
    github_branch: str = "main"
    repository_url: str = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_synced_at: Optional[str] = None
    is_active: bool = False
    is_connected: bool = False
    status: str = "draft"
    workspace_path: Optional[str] = None
    profile: Optional[ProjectProfile] = None
    integrations: list[IntegrationInfo] = Field(default_factory=list)
    settings: Optional[ProjectSettings] = None
    render_service_id: str = ""
    auto_merge: bool = Field(default_factory=lambda: settings.AUTO_MERGE)
    auto_create_pr: bool = Field(default_factory=lambda: settings.AUTO_CREATE_PR)


class ProjectStatus(BaseModel):
    project: Project
    integrations: list[IntegrationInfo] = Field(default_factory=list)
    workspace_ready: bool = False
    active_log_provider: Optional[str] = None
