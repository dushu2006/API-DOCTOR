"""Persistent project store backed by the application database."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.db.base import session_scope
from app.db.models import IntegrationRecord, ProjectRecord, ProjectSettingsRecord, UserRecord
from app.projects.models import IntegrationInfo, Project, ProjectProfile, ProjectSettings, ProjectStatus
from app.security.secrets import secret_store


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class ProjectStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    def _base_stmt(self):
        return select(ProjectRecord).options(
            selectinload(ProjectRecord.integrations),
            selectinload(ProjectRecord.settings),
        )

    def _render_service_id(self, integrations: list[IntegrationRecord]) -> str:
        for integration in integrations:
            if integration.provider == "render":
                return str((integration.configuration or {}).get("service_id") or "")
        return ""

    def _integration_info(self, row: IntegrationRecord) -> IntegrationInfo:
        return IntegrationInfo(
            id=row.id,
            project_id=row.project_id,
            provider=row.provider,
            enabled=bool(row.enabled),
            configured=bool(row.credentials_encrypted or row.configuration),
            status=row.status,
            safe_metadata=row.configuration or {},
            created_at=_iso(row.created_at),
            updated_at=_iso(row.updated_at),
            last_verified_at=_iso(row.last_verified_at),
        )

    def _settings_model(self, row: ProjectSettingsRecord | None, project_id: str = "") -> ProjectSettings:
        if not row:
            return ProjectSettings(project_id=project_id)
        return ProjectSettings(
            project_id=row.project_id,
            sandbox_mode=row.sandbox_mode or "",
            build_command=row.build_command or "",
            test_command=row.test_command or "",
            run_command=row.run_command or "",
            source_configuration=row.source_configuration or {},
            diagnosis_settings=row.diagnosis_settings or {},
            repair_settings=row.repair_settings or {},
            runtime_summary=row.runtime_summary or {},
            created_at=_iso(row.created_at),
            updated_at=_iso(row.updated_at),
        )

    def _project_model(self, row: ProjectRecord, include_details: bool = True) -> Project:
        profile = ProjectProfile.model_validate(row.profile_json) if row.profile_json else None
        integrations = [self._integration_info(item) for item in row.integrations] if include_details else []
        settings = self._settings_model(row.settings, row.id) if include_details else None
        workspace_path = row.workspace_path or None
        is_connected = row.status == "connected" and bool(workspace_path)
        default_branch = row.default_branch or "main"
        return Project(
            id=row.id,
            name=row.name,
            description=row.description or "",
            github_owner=row.github_owner or "",
            github_repo=row.github_repo or "",
            default_branch=default_branch,
            github_branch=default_branch,
            repository_url=row.repository_url or "",
            created_at=_iso(row.created_at),
            updated_at=_iso(row.updated_at),
            last_synced_at=_iso(row.last_synced_at),
            is_active=bool(row.is_active),
            is_connected=is_connected,
            status=row.status,
            workspace_path=workspace_path,
            profile=profile,
            integrations=integrations,
            settings=settings,
            render_service_id=self._render_service_id(row.integrations),
        )

    def list_all(self, user_id: str | None = None) -> list[Project]:
        with session_scope() as session:
            stmt = self._base_stmt().order_by(ProjectRecord.updated_at.desc())
            if user_id:
                stmt = stmt.where(ProjectRecord.user_id == user_id)
            rows = session.execute(stmt).scalars().all()
            return [self._project_model(row) for row in rows]

    def count(self, user_id: str | None = None) -> int:
        return len(self.list_all(user_id))

    def reset(self) -> None:
        """Remove all projects and users. Used by tests to isolate state."""
        from app.db.models import SessionRecord, UserRecord

        with self._lock:
            with session_scope() as session:
                for row in session.execute(select(ProjectRecord)).scalars().all():
                    session.delete(row)
                for row in session.execute(select(SessionRecord)).scalars().all():
                    session.delete(row)
                for row in session.execute(select(UserRecord)).scalars().all():
                    session.delete(row)

    def _first(self, session, stmt) -> ProjectRecord | None:
        """Return the first matching project, or None.

        Callers that order a multi-row result must use this instead of
        ``scalar_one_or_none()``, which raises ``MultipleResultsFound``.
        """
        return session.execute(stmt).scalars().first()

    def _clear_active_flag(self, session, *, except_project_id: str, user_id: str) -> None:
        """Ensure at most one project is marked active for the owner."""
        session.execute(
            update(ProjectRecord)
            .where(
                ProjectRecord.user_id == user_id,
                ProjectRecord.id != except_project_id,
                ProjectRecord.is_active.is_(True),
            )
            .values(is_active=False)
        )

    def get(self, project_id: str, user_id: str | None = None) -> Optional[Project]:
        with session_scope() as session:
            stmt = self._base_stmt().where(ProjectRecord.id == project_id)
            if user_id:
                stmt = stmt.where(ProjectRecord.user_id == user_id)
            row = session.execute(stmt).scalar_one_or_none()
            return self._project_model(row) if row else None

    def get_current(self, user_id: str | None = None) -> Optional[Project]:
        with session_scope() as session:
            if user_id:
                user = session.get(UserRecord, user_id)
                if not user:
                    return None
                if user.current_project_id:
                    row = session.execute(
                        self._base_stmt().where(
                            ProjectRecord.id == user.current_project_id,
                            ProjectRecord.user_id == user_id,
                        )
                    ).scalar_one_or_none()
                    if row:
                        return self._project_model(row)
                row = self._first(
                    session,
                    self._base_stmt()
                    .where(ProjectRecord.user_id == user_id)
                    .order_by(
                        ProjectRecord.is_active.desc(),
                        ProjectRecord.updated_at.desc(),
                        ProjectRecord.created_at.asc(),
                    ),
                )
                return self._project_model(row) if row else None

            # Unscoped lookup used by /health and internal fallbacks. Creating a
            # second project used to leave multiple is_active rows, and
            # scalar_one_or_none() turned that into a 500.
            row = self._first(
                session,
                self._base_stmt()
                .where(ProjectRecord.is_active.is_(True))
                .order_by(ProjectRecord.updated_at.desc(), ProjectRecord.created_at.asc()),
            )
            if row:
                return self._project_model(row)
            row = self._first(
                session,
                self._base_stmt().order_by(ProjectRecord.created_at.asc()),
            )
            return self._project_model(row) if row else None

    def set_current(self, project_id: str, user_id: str | None = None) -> Optional[Project]:
        with self._lock:
            with session_scope() as session:
                row = session.get(ProjectRecord, project_id)
                if not row or (user_id and row.user_id != user_id):
                    return None
                row.is_active = True
                row.updated_at = _utcnow()
                session.add(row)
                self._clear_active_flag(session, except_project_id=row.id, user_id=row.user_id)
                if user_id:
                    user = session.get(UserRecord, user_id)
                    if user:
                        user.current_project_id = project_id
                        user.updated_at = _utcnow()
                        session.add(user)
                session.flush()
                session.refresh(row)
                _ = row.integrations, row.settings
                return self._project_model(row)

    def create_project(
        self,
        *,
        user_id: str,
        name: str,
        description: str = "",
        github_owner: str,
        github_repo: str,
        default_branch: str,
        repository_url: str,
        workspace_path: str,
        profile: ProjectProfile | None,
        settings: ProjectSettings | None,
        status: str = "connected",
        project_id: str | None = None,
        activate: bool = True,
    ) -> Project:
        with self._lock:
            with session_scope() as session:
                now = _utcnow()
                row = ProjectRecord(
                    id=project_id or str(uuid.uuid4()),
                    user_id=user_id,
                    name=name,
                    description=description,
                    github_owner=github_owner,
                    github_repo=github_repo,
                    default_branch=default_branch or "main",
                    repository_url=repository_url,
                    workspace_path=workspace_path,
                    profile_json=profile.model_dump() if profile else {},
                    created_at=now,
                    updated_at=now,
                    last_synced_at=now if workspace_path else None,
                    is_active=activate,
                    status=status,
                )
                session.add(row)
                session.flush()

                settings_payload = settings or ProjectSettings(project_id=row.id)
                session.add(
                    ProjectSettingsRecord(
                        project_id=row.id,
                        sandbox_mode=settings_payload.sandbox_mode or "",
                        build_command=settings_payload.build_command or "",
                        test_command=settings_payload.test_command or "",
                        run_command=settings_payload.run_command or "",
                        source_configuration=settings_payload.source_configuration or {},
                        diagnosis_settings=settings_payload.diagnosis_settings or {},
                        repair_settings=settings_payload.repair_settings or {},
                        runtime_summary=settings_payload.runtime_summary or {},
                        created_at=now,
                        updated_at=now,
                    )
                )

                if activate:
                    self._clear_active_flag(session, except_project_id=row.id, user_id=user_id)
                    user = session.get(UserRecord, user_id)
                    if user:
                        user.current_project_id = row.id
                        user.updated_at = now
                        session.add(user)

                session.flush()
                session.refresh(row)
                _ = row.integrations, row.settings
                return self._project_model(row)

    def update_project(self, project_id: str, payload: dict[str, Any], user_id: str | None = None) -> Optional[Project]:
        allowed = {
            "name",
            "description",
            "github_owner",
            "github_repo",
            "default_branch",
            "repository_url",
            "workspace_path",
            "status",
        }
        with self._lock:
            with session_scope() as session:
                stmt = self._base_stmt().where(ProjectRecord.id == project_id)
                if user_id:
                    stmt = stmt.where(ProjectRecord.user_id == user_id)
                row = session.execute(stmt).scalar_one_or_none()
                if not row:
                    return None
                for key, value in payload.items():
                    if key in allowed:
                        setattr(row, key, value)
                row.updated_at = _utcnow()
                if payload.get("workspace_path"):
                    row.last_synced_at = _utcnow()
                session.add(row)
                session.flush()
                return self._project_model(row)

    def delete(self, project_id: str, user_id: str | None = None) -> bool:
        with self._lock:
            with session_scope() as session:
                row = session.get(ProjectRecord, project_id)
                if not row or (user_id and row.user_id != user_id):
                    return False
                owner_id = row.user_id
                session.delete(row)
                session.flush()
                user = session.get(UserRecord, owner_id)
                if user and user.current_project_id == project_id:
                    replacement = self._first(
                        session,
                        select(ProjectRecord)
                        .where(ProjectRecord.user_id == owner_id)
                        .order_by(
                            ProjectRecord.is_active.desc(),
                            ProjectRecord.updated_at.desc(),
                            ProjectRecord.created_at.asc(),
                        ),
                    )
                    user.current_project_id = replacement.id if replacement else None
                    if replacement:
                        replacement.is_active = True
                        session.add(replacement)
                    user.updated_at = _utcnow()
                    session.add(user)
                return True

    def duplicate_project(self, project_id: str, user_id: str, new_name: str | None = None) -> Optional[Project]:
        with self._lock:
            with session_scope() as session:
                source = session.execute(
                    self._base_stmt().where(ProjectRecord.id == project_id, ProjectRecord.user_id == user_id)
                ).scalar_one_or_none()
                if not source:
                    return None
                now = _utcnow()
                new_id = str(uuid.uuid4())
                name = (new_name or f"{source.name} Copy").strip()
                clone = ProjectRecord(
                    id=new_id,
                    user_id=user_id,
                    name=name,
                    description=source.description,
                    github_owner=source.github_owner,
                    github_repo=source.github_repo,
                    default_branch=source.default_branch,
                    repository_url=source.repository_url,
                    workspace_path=source.workspace_path,
                    profile_json=source.profile_json or {},
                    created_at=now,
                    updated_at=now,
                    last_synced_at=source.last_synced_at,
                    is_active=False,
                    status=source.status,
                )
                session.add(clone)
                session.flush()

                if source.settings:
                    session.add(
                        ProjectSettingsRecord(
                            project_id=new_id,
                            sandbox_mode=source.settings.sandbox_mode,
                            build_command=source.settings.build_command,
                            test_command=source.settings.test_command,
                            run_command=source.settings.run_command,
                            source_configuration=source.settings.source_configuration or {},
                            diagnosis_settings=source.settings.diagnosis_settings or {},
                            repair_settings=source.settings.repair_settings or {},
                            runtime_summary=source.settings.runtime_summary or {},
                            created_at=now,
                            updated_at=now,
                        )
                    )
                else:
                    session.add(ProjectSettingsRecord(project_id=new_id, created_at=now, updated_at=now))

                for integration in source.integrations:
                    session.add(
                        IntegrationRecord(
                            project_id=new_id,
                            provider=integration.provider,
                            enabled=integration.enabled,
                            status=integration.status,
                            configuration=integration.configuration or {},
                            credentials_encrypted=integration.credentials_encrypted,
                            created_at=now,
                            updated_at=now,
                            last_verified_at=integration.last_verified_at,
                        )
                    )

                session.flush()
                session.refresh(clone)
                _ = clone.integrations, clone.settings
                return self._project_model(clone)

    def get_settings(self, project_id: str) -> ProjectSettings:
        with session_scope() as session:
            row = session.get(ProjectSettingsRecord, project_id)
            return self._settings_model(row, project_id)

    def save_settings(self, project_id: str, settings: ProjectSettings) -> ProjectSettings:
        with self._lock:
            with session_scope() as session:
                row = session.get(ProjectSettingsRecord, project_id)
                now = _utcnow()
                if not row:
                    row = ProjectSettingsRecord(project_id=project_id, created_at=now)
                row.sandbox_mode = settings.sandbox_mode or ""
                row.build_command = settings.build_command or ""
                row.test_command = settings.test_command or ""
                row.run_command = settings.run_command or ""
                row.source_configuration = settings.source_configuration or {}
                row.diagnosis_settings = settings.diagnosis_settings or {}
                row.repair_settings = settings.repair_settings or {}
                row.runtime_summary = settings.runtime_summary or {}
                row.updated_at = now
                session.add(row)
                session.flush()
                return self._settings_model(row, project_id)

    def list_integrations(self, project_id: str) -> list[IntegrationInfo]:
        with session_scope() as session:
            rows = session.execute(
                select(IntegrationRecord).where(IntegrationRecord.project_id == project_id).order_by(IntegrationRecord.provider.asc())
            ).scalars().all()
            return [self._integration_info(row) for row in rows]

    def get_integration(self, project_id: str, provider: str) -> Optional[IntegrationInfo]:
        with session_scope() as session:
            row = session.execute(
                select(IntegrationRecord).where(
                    IntegrationRecord.project_id == project_id,
                    IntegrationRecord.provider == provider,
                )
            ).scalar_one_or_none()
            return self._integration_info(row) if row else None

    def upsert_integration(
        self,
        *,
        project_id: str,
        provider: str,
        configuration: dict[str, Any] | None = None,
        credentials: dict[str, Any] | None = None,
        enabled: bool = True,
        status: str = "connected",
        verified: bool = True,
    ) -> IntegrationInfo:
        with self._lock:
            with session_scope() as session:
                row = session.execute(
                    select(IntegrationRecord).where(
                        IntegrationRecord.project_id == project_id,
                        IntegrationRecord.provider == provider,
                    )
                ).scalar_one_or_none()
                now = _utcnow()
                if not row:
                    row = IntegrationRecord(project_id=project_id, provider=provider, created_at=now)
                row.enabled = enabled
                row.status = status
                row.configuration = configuration or {}
                if credentials is not None:
                    row.credentials_encrypted = secret_store.encrypt_dict(credentials)
                row.updated_at = now
                if verified:
                    row.last_verified_at = now
                session.add(row)
                session.flush()
                return self._integration_info(row)

    def get_integration_credentials(self, project_id: str, provider: str) -> dict[str, Any]:
        with session_scope() as session:
            row = session.execute(
                select(IntegrationRecord).where(
                    IntegrationRecord.project_id == project_id,
                    IntegrationRecord.provider == provider,
                )
            ).scalar_one_or_none()
            if not row:
                return {}
            return secret_store.decrypt_dict(row.credentials_encrypted)

    def resolve_github(self, project_id: str | None = None) -> dict[str, Any]:
        project = self.get(project_id) if project_id else self.get_current()
        if not project:
            return {}
        creds = self.get_integration_credentials(project.id, "github")
        return {
            "project_id": project.id,
            "owner": project.github_owner,
            "repo": project.github_repo,
            "branch": project.default_branch or project.github_branch or "main",
            "token": creds.get("token", ""),
            "repository_url": project.repository_url,
        }

    def resolve_render(self, project_id: str | None = None) -> dict[str, Any]:
        project = self.get(project_id) if project_id else self.get_current()
        if not project:
            return {}
        creds = self.get_integration_credentials(project.id, "render")
        integration = self.get_integration(project.id, "render")
        metadata = integration.safe_metadata if integration else {}
        return {
            "project_id": project.id,
            "api_key": creds.get("api_key", ""),
            "service_id": metadata.get("service_id", ""),
            "service_name": metadata.get("service_name", ""),
            "owner_id": metadata.get("owner_id", ""),
            "provider": "render",
        }

    def mark_synced(self, project_id: str, workspace_path: str, profile: ProjectProfile | None = None) -> Optional[Project]:
        payload: dict[str, Any] = {"workspace_path": workspace_path, "status": "connected"}
        project = self.update_project(project_id, payload)
        if not project:
            return None
        if profile is not None:
            with self._lock:
                with session_scope() as session:
                    row = session.get(ProjectRecord, project_id)
                    if not row:
                        return None
                    row.profile_json = profile.model_dump()
                    row.last_synced_at = _utcnow()
                    row.updated_at = _utcnow()
                    session.add(row)
        return self.get(project_id)

    def status(self, project_id: str) -> Optional[ProjectStatus]:
        from app.incidents.store import incident_store

        project = self.get(project_id)
        if not project:
            return None
        integrations = self.list_integrations(project_id)
        active_log_provider = next((item.provider for item in integrations if item.provider in {"render", "manual"} and item.enabled), None)
        return ProjectStatus(
            project=project,
            incidents_count=len(incident_store.list_all(project_id)),
            integrations=integrations,
            workspace_ready=bool(project.workspace_path),
            active_log_provider=active_log_provider,
        )


project_store = ProjectStore()
