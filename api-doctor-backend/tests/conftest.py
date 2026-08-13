"""Test configuration.

Runs the sandbox in ``local`` mode (no Docker required) and uses an isolated
SQLite database. External clients receive explicit test credentials in each test;
production credentials are intentionally never read from environment variables.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_TEST_DB = _REPO_ROOT / "data" / "pytest_api_doctor.db"
_TEST_DB.parent.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ.setdefault("SANDBOX_MODE", "local")
os.environ.setdefault("MAX_REPAIR_ATTEMPTS", "2")
os.environ.setdefault("AUTO_CREATE_PR", "false")
os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("GITHUB_API_BASE_URL", "https://api.github.com")
os.environ.setdefault("RENDER_API_BASE_URL", "https://api.render.com/v1")


@pytest.fixture(autouse=True)
def _clear_runs():
    from app.db.base import init_db
    from app.runs.store import run_store
    from app.projects.store import project_store

    init_db()
    run_store.clear()
    project_store.reset()
    # Clear AI cache between tests to avoid cross-test contamination
    try:
        from app.ai.cache import get_global_cache

        get_global_cache().clear()
    except Exception:
        pass
    yield
    run_store.clear()
    project_store.reset()
    try:
        from app.ai.cache import get_global_cache

        get_global_cache().clear()
    except Exception:
        pass


@pytest.fixture
def repo_root() -> Path:
    return _BACKEND_ROOT


@pytest.fixture
def authenticated_user():
    """Create a real session for API route tests."""
    from app.auth.schemas import RegisterRequest
    from app.auth.store import auth_store

    user, token = auth_store.register(
        RegisterRequest(
            email="tester@example.com",
            username="tester",
            password="test-password",
            full_name="Test User",
        )
    )
    return user, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_headers(authenticated_user) -> dict[str, str]:
    return authenticated_user[1]


@pytest.fixture
def project_factory(authenticated_user):
    """Create a database-backed project owned by the active test user."""
    from app.projects.models import ProjectProfile, ProjectSettings
    from app.projects.store import project_store

    user, _headers = authenticated_user

    def _create(
        *,
        project_id: str = "default",
        name: str = "acme/demo",
        description: str = "",
        github_owner: str = "acme",
        github_repo: str = "demo",
        default_branch: str = "main",
        repository_url: str = "https://github.com/acme/demo",
        workspace_path: str = "",
        profile: ProjectProfile | None = None,
        settings: ProjectSettings | None = None,
        status: str = "connected",
        activate: bool = True,
    ):
        return project_store.create_project(
            user_id=user.id,
            project_id=project_id,
            name=name,
            description=description,
            github_owner=github_owner,
            github_repo=github_repo,
            default_branch=default_branch,
            repository_url=repository_url,
            workspace_path=workspace_path,
            profile=profile,
            settings=settings,
            status=status,
            activate=activate,
        )

    return _create
