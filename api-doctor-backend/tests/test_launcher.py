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


def test_service_restart_window_tracks_recent_crashes_only() -> None:
    """Old crashes must age out so a long-lived run is not killed by history."""
    launcher = _load_launcher()
    service = launcher.Service("backend", ["true"], Path("."), {})

    for _ in range(launcher.MAX_RESTARTS_PER_WINDOW):
        service.record_restart(1000.0)
    assert service.is_crash_looping() is True

    # A crash well outside the window discards the earlier ones.
    service.record_restart(1000.0 + launcher.RESTART_WINDOW_SECONDS + 1)
    assert len(service.restarts) == 1
    assert service.is_crash_looping() is False


def test_monitor_restarts_crashed_service_without_stopping_healthy_one() -> None:
    """A backend crash must not take the frontend down with it."""
    launcher = _load_launcher()
    launcher.RESTART_BACKOFF_SECONDS = 0

    class FakeProcess:
        def __init__(self, codes):
            self._codes = list(codes)

        def poll(self):
            return self._codes.pop(0) if self._codes else None

    crashed = launcher.Service("backend", ["backend"], Path("."), {})
    healthy = launcher.Service("frontend", ["frontend"], Path("."), {})

    # The backend reports a crash, then stays up after being restarted.
    crashed.process = FakeProcess([1])
    healthy.process = FakeProcess([])

    starts: list[str] = []

    def fake_start(self=crashed):
        starts.append(self.label)
        self.process = FakeProcess([])

    crashed.start = fake_start  # type: ignore[method-assign]

    # Stop the loop once the restart has happened.
    original_sleep = launcher.time.sleep
    calls = {"n": 0}

    def stop_after_restart(_seconds):
        calls["n"] += 1
        if calls["n"] > 2:
            raise KeyboardInterrupt

    launcher.time.sleep = stop_after_restart
    try:
        try:
            launcher._monitor_services([crashed, healthy])
        except KeyboardInterrupt:
            pass
    finally:
        launcher.time.sleep = original_sleep

    assert starts == ["backend"], "crashed backend should be restarted"
    assert healthy.poll() is None, "healthy frontend must stay running"
