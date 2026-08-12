from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    gender: Mapped[str] = mapped_column(String(64), default="")
    date_of_birth: Mapped[str] = mapped_column(String(64), default="")
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avatar_data: Mapped[str] = mapped_column(Text, default="")
    current_project_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    sessions: Mapped[list[SessionRecord]] = relationship(
        "SessionRecord", back_populates="user", cascade="all, delete-orphan"
    )
    projects: Mapped[list[ProjectRecord]] = relationship(
        "ProjectRecord", back_populates="user", cascade="all, delete-orphan"
    )


class SessionRecord(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[UserRecord] = relationship("UserRecord", back_populates="sessions")


class ProjectRecord(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    github_owner: Mapped[str] = mapped_column(String(255), default="")
    github_repo: Mapped[str] = mapped_column(String(255), default="")
    default_branch: Mapped[str] = mapped_column(String(255), default="main")
    repository_url: Mapped[str] = mapped_column(String(1024), default="")
    workspace_path: Mapped[str] = mapped_column(String(2048), default="")
    profile_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(64), default="draft")

    user: Mapped[UserRecord] = relationship("UserRecord", back_populates="projects")
    integrations: Mapped[list[IntegrationRecord]] = relationship(
        "IntegrationRecord", back_populates="project", cascade="all, delete-orphan"
    )
    settings: Mapped[ProjectSettingsRecord | None] = relationship(
        "ProjectSettingsRecord", back_populates="project", cascade="all, delete-orphan", uselist=False
    )
    incidents: Mapped[list[IncidentRecord]] = relationship(
        "IncidentRecord", back_populates="project", cascade="all, delete-orphan"
    )


class IntegrationRecord(Base):
    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("project_id", "provider", name="uq_project_provider"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(64), default="disconnected")
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    credentials_encrypted: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[ProjectRecord] = relationship("ProjectRecord", back_populates="integrations")


class ProjectSettingsRecord(Base):
    __tablename__ = "project_settings"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    sandbox_mode: Mapped[str] = mapped_column(String(64), default="")
    build_command: Mapped[str] = mapped_column(Text, default="")
    test_command: Mapped[str] = mapped_column(Text, default="")
    run_command: Mapped[str] = mapped_column(Text, default="")
    source_configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    diagnosis_settings: Mapped[dict] = mapped_column(JSON, default=dict)
    repair_settings: Mapped[dict] = mapped_column(JSON, default=dict)
    runtime_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    project: Mapped[ProjectRecord] = relationship("ProjectRecord", back_populates="settings")


class IncidentRecord(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="RECEIVED")
    detection: Mapped[dict] = mapped_column(JSON, default=dict)
    request_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    stack_trace: Mapped[str] = mapped_column(Text, default="")
    context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    root_cause: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fix_proposal: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sandbox_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    pr_info: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    activity: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    project: Mapped[ProjectRecord] = relationship("ProjectRecord", back_populates="incidents")
