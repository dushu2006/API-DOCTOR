"""Isolated temporary workspace management.

The sandbox works on a private copy of the project source. The original
production repository is never modified directly.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from app.core.config import settings

_IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", ".venv", "venv", "node_modules", "*.pyc",
    ".pytest_cache", ".mypy_cache", "htmlcov", "dist", "build", ".tox",
)


class WorkspaceManager:
    def __init__(self, repo_root: Path | str | None = None) -> None:
        self.repo_root = Path(repo_root or settings.REPO_ROOT).resolve()

    def create_workspace(self) -> Path:
        """Copy the project source into a fresh temporary directory."""
        tmpdir = Path(tempfile.mkdtemp(prefix="api_doctor_workspace_"))
        workspace = tmpdir / "repo"
        shutil.copytree(self.repo_root, workspace, ignore=_IGNORE, dirs_exist_ok=False)
        return workspace

    @staticmethod
    def cleanup(workspace: Path) -> None:
        shutil.rmtree(workspace.parent, ignore_errors=True)

    def read_relative(self, workspace: Path, rel_path: str) -> str | None:
        """Read a file from the workspace by repository-relative path."""
        full = (workspace / rel_path).resolve()
        try:
            full.relative_to(workspace.resolve())
        except ValueError:
            return None
        if not full.is_file():
            return None
        return full.read_text(encoding="utf-8", errors="replace")

    def files(self, workspace: Path) -> list[str]:
        """List repository-relative file paths present in the workspace."""
        out: list[str] = []
        for p in workspace.rglob("*"):
            if p.is_file() and ".api_doctor_" not in p.name:
                try:
                    out.append(str(p.relative_to(workspace)))
                except ValueError:
                    pass
        return sorted(out)
