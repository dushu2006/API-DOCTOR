"""Test configuration.

Runs the sandbox in ``local`` mode (no Docker required) and points REPO_ROOT at
this repository so sandbox copies are self-contained.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
os.environ.setdefault("SANDBOX_MODE", "local")
os.environ.setdefault("REPO_ROOT", _REPO_ROOT)
os.environ.setdefault("MAX_REPAIR_ATTEMPTS", "2")
os.environ.setdefault("AUTO_CREATE_PR", "false")

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
    from app.incidents.store import incident_store

    incident_store.clear()
    # Clear AI cache between tests to avoid cross-test contamination
    try:
        from app.ai.cache import get_global_cache

        get_global_cache().clear()
    except Exception:
        pass
    yield
    incident_store.clear()
    try:
        from app.ai.cache import get_global_cache

        get_global_cache().clear()
    except Exception:
        pass


@pytest.fixture
def repo_root() -> Path:
    return Path(_REPO_ROOT)
