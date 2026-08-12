"""Regression tests for the repository-root launcher dependency check."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_PATH = ROOT / "run.py"


def _load_launcher():
    spec = importlib.util.spec_from_file_location("api_doctor_launcher", LAUNCHER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_requires_sqlalchemy_and_runtime_stack() -> None:
    launcher = _load_launcher()
    required = set(launcher.REQUIRED_BACKEND_MODULES)
    assert "sqlalchemy" in required
    assert "cryptography" in required
    assert "fastapi" in required
    assert "uvicorn" in required
    assert "pydantic" in required


def test_requirements_stamp_detects_requirement_changes(tmp_path: Path) -> None:
    launcher = _load_launcher()
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("SQLAlchemy==2.0.43\n", encoding="utf-8")
    venv_dir = tmp_path / ".venv"
    venv_dir.mkdir()

    assert launcher._requirements_are_current(venv_dir, requirements) is False
    launcher._write_requirements_stamp(venv_dir, requirements)
    assert launcher._requirements_are_current(venv_dir, requirements) is True

    requirements.write_text("SQLAlchemy==2.0.43\ncryptography==45.0.6\n", encoding="utf-8")
    assert launcher._requirements_are_current(venv_dir, requirements) is False
