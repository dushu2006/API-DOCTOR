"""Regression tests for project current-selection and /health.

Creating more than one project used to leave multiple ``is_active`` rows.
``get_current()`` then called ``scalar_one_or_none()``, which raised
``MultipleResultsFound`` and turned ``GET /health`` into a 500 that blocked
frontend bootstrap.
"""

from __future__ import annotations

from sqlalchemy import select

import httpx

from app.auth.schemas import RegisterRequest
from app.auth.store import auth_store
from app.db.base import session_scope
from app.db.models import ProjectRecord, UserRecord
from app.main import app
from app.projects.store import project_store


async def _request(method: str, path: str, headers: dict[str, str] | None = None, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=headers or {}, **kwargs)


def _force_all_active() -> int:
    with session_scope() as session:
        rows = session.execute(select(ProjectRecord)).scalars().all()
        for row in rows:
            row.is_active = True
            session.add(row)
        return len(rows)


def test_create_project_deactivates_previous(project_factory, authenticated_user):
    user, _headers = authenticated_user
    first = project_factory(project_id="alpha", name="alpha", github_repo="alpha")
    second = project_factory(project_id="beta", name="beta", github_repo="beta")

    assert project_store.get("alpha").is_active is False
    assert project_store.get("beta").is_active is True
    current = project_store.get_current(user.id)
    assert current is not None
    assert current.id == second.id
    assert first.id != second.id


def test_set_current_is_exclusive(project_factory, authenticated_user):
    user, _headers = authenticated_user
    project_factory(project_id="alpha", name="alpha", github_repo="alpha")
    project_factory(project_id="beta", name="beta", github_repo="beta")

    activated = project_store.set_current("alpha", user.id)
    assert activated is not None
    assert activated.id == "alpha"
    assert project_store.get("alpha").is_active is True
    assert project_store.get("beta").is_active is False
    assert project_store.get_current(user.id).id == "alpha"


def test_get_current_tolerates_legacy_duplicate_active_flags(project_factory, authenticated_user):
    user, _headers = authenticated_user
    project_factory(project_id="alpha", name="alpha", github_repo="alpha")
    project_factory(project_id="beta", name="beta", github_repo="beta")
    assert _force_all_active() == 2

    # The exact crash from GET /health: unscoped get_current() with two active rows.
    unscoped = project_store.get_current()
    assert unscoped is not None
    assert unscoped.id in {"alpha", "beta"}

    scoped = project_store.get_current(user.id)
    assert scoped is not None
    assert scoped.id == "beta"


def test_get_current_without_pointer_picks_active(project_factory, authenticated_user):
    user, _headers = authenticated_user
    project_factory(project_id="alpha", name="alpha", github_repo="alpha", activate=False)
    project_factory(project_id="beta", name="beta", github_repo="beta", activate=True)

    with session_scope() as session:
        row = session.get(UserRecord, user.id)
        assert row is not None
        row.current_project_id = None
        session.add(row)

    current = project_store.get_current(user.id)
    assert current is not None
    assert current.id == "beta"


def test_delete_current_project_with_siblings(project_factory, authenticated_user):
    user, _headers = authenticated_user
    project_factory(project_id="alpha", name="alpha", github_repo="alpha")
    project_factory(project_id="beta", name="beta", github_repo="beta")
    project_factory(project_id="gamma", name="gamma", github_repo="gamma")

    assert project_store.delete("gamma", user.id) is True
    remaining = {item.id for item in project_store.list_all(user.id)}
    assert remaining == {"alpha", "beta"}
    current = project_store.get_current(user.id)
    assert current is not None
    assert current.id in remaining
    assert current.is_active is True


async def test_health_ok_with_multiple_active_projects(project_factory):
    project_factory(project_id="alpha", name="alpha", github_repo="alpha")
    project_factory(project_id="beta", name="beta", github_repo="beta")
    assert _force_all_active() == 2

    response = await _request("GET", "/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["project_count"] == 2
    assert body["active_project_id"] in {"alpha", "beta"}


async def test_health_ok_with_no_projects():
    response = await _request("GET", "/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["project_count"] == 0
    assert body["active_project_id"] is None


async def test_current_project_endpoint_with_duplicates(project_factory, auth_headers):
    project_factory(project_id="alpha", name="alpha", github_repo="alpha")
    project_factory(project_id="beta", name="beta", github_repo="beta")
    _force_all_active()

    response = await _request("GET", "/api/projects/current", auth_headers)
    assert response.status_code == 200
    assert response.json()["id"] == "beta"


def test_second_user_projects_do_not_collide(project_factory, authenticated_user):
    user, _headers = authenticated_user
    project_factory(project_id="mine", name="mine", github_repo="mine")

    other, _token = auth_store.register(
        RegisterRequest(
            email="other@example.com",
            username="other",
            password="other-password",
            full_name="Other User",
        )
    )
    theirs = project_store.create_project(
        user_id=other.id,
        project_id="theirs",
        name="theirs",
        github_owner="acme",
        github_repo="theirs",
        default_branch="main",
        repository_url="https://github.com/acme/theirs",
        workspace_path="",
        profile=None,
        settings=None,
        activate=True,
    )

    assert project_store.get_current(user.id).id == "mine"
    assert project_store.get_current(other.id).id == theirs.id
    # Unscoped lookup used by /health must still return a single project.
    assert project_store.get_current() is not None
    assert project_store.get("mine").is_active is True
    assert project_store.get("theirs").is_active is True
