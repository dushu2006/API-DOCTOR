"""Test configuration.

Runs the sandbox in ``local`` mode (no Docker required) and points REPO_ROOT at
this repository so sandbox copies are self-contained.
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
os.environ.setdefault("REPO_ROOT", str(_BACKEND_ROOT))
os.environ.setdefault("MAX_REPAIR_ATTEMPTS", "2")
os.environ.setdefault("AUTO_CREATE_PR", "false")
os.environ.setdefault("DEMO_MODE", "true")

# GitHub/Render client tests use these (mocked over HTTP).
os.environ.setdefault("GITHUB_TOKEN", "test-token")
os.environ.setdefault("GITHUB_OWNER", "acme")
os.environ.setdefault("GITHUB_REPO", "demo")
os.environ.setdefault("GITHUB_DEFAULT_BRANCH", "main")
os.environ.setdefault("RENDER_API_KEY", "test-render-key")
os.environ.setdefault("RENDER_SERVICE_ID", "srv_test")
os.environ.setdefault("GITHUB_API_BASE_URL", "https://api.github.com")
os.environ.setdefault("RENDER_API_BASE_URL", "https://api.render.com/v1")


@pytest.fixture(autouse=True)
def _clear_incidents():
    from app.db.base import init_db
    from app.incidents.store import incident_store
    from app.projects.store import project_store

    init_db()
    incident_store.clear()
    project_store.reset()
    # Clear AI cache between tests to avoid cross-test contamination
    try:
        from app.ai.cache import get_global_cache

        get_global_cache().clear()
    except Exception:
        pass
    yield
    incident_store.clear()
    project_store.reset()
    try:
        from app.ai.cache import get_global_cache

        get_global_cache().clear()
    except Exception:
        pass


@pytest.fixture
def repo_root() -> Path:
    return _BACKEND_ROOT
