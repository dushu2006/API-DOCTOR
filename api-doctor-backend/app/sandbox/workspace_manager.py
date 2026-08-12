"""Isolated project and sandbox workspace management.

Manages the synchronization of real GitHub repositories into local working
workspaces and provides isolated sandbox copies for AI repair verification.
The user's main working repository and baseline branches are never modified directly.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


_CRED_URL_RE = re.compile(r"(https?://)[^/@:]+(?::[^/@]*)?@", re.IGNORECASE)


def _redact_git_secrets(text: str, token: str = "") -> str:
    """Strip embedded credentials from git URLs/outputs before logging or raising.

    Git echoes the clone URL (which may contain ``x-access-token:<TOKEN>@``) into
    stderr on failure, so without redaction the token would leak into logs and
    error messages returned to the caller.
    """
    if not text:
        return text
    redacted = _CRED_URL_RE.sub(r"\1***@", str(text))
    if token:
        redacted = redacted.replace(token, "***")
    return redacted

_IGNORE_PATTERNS = shutil.ignore_patterns(
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    "*.pyc",
    "*.pyo",
    ".pytest_cache",
    ".mypy_cache",
    "htmlcov",
    "dist",
    "build",
    ".tox",
    ".nox",
    ".turbo",
    ".next",
    ".nuxt",
    ".output",
    "target",
)

_IGNORED_NAMES = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    "htmlcov",
    "dist",
    "build",
    ".tox",
    ".turbo",
    ".next",
    ".nuxt",
    ".output",
    "target",
}


class WorkspaceManager:
    def __init__(
        self,
        repo_root: Path | str | None = None,
        workspace_base: Path | str | None = None,
    ) -> None:
        self.workspace_base = Path(workspace_base or settings.WORKSPACE_DIR).resolve()
        self.repo_root = Path(repo_root or settings.INTERNAL_REPO_ROOT).resolve()

    def get_project_workspace_path(self, owner: str, repo: str) -> Path:
        """Return the baseline workspace directory for a given owner/repo."""
        return (self.workspace_base / owner / repo).resolve()

    def sync_repository(
        self,
        owner: str,
        repo: str,
        branch: str = "main",
        token: str = "",
        base_url: str = "https://api.github.com",
    ) -> Path:
        """Clone or update a GitHub repository into the local workspace."""
        target_dir = self.get_project_workspace_path(owner, repo)
        target_dir.parent.mkdir(parents=True, exist_ok=True)

        token = token or ""
        branch = branch or "main"

        # Determine git clone URL
        if token:
            clone_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
        else:
            clone_url = f"https://github.com/{owner}/{repo}.git"

        git_dir = target_dir / ".git"

        if git_dir.is_dir():
            logger.info("Updating existing repository at %s", target_dir)
            try:
                # Fetch latest updates
                subprocess.run(
                    ["git", "fetch", "--all", "--prune"],
                    cwd=str(target_dir),
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True,
                )
                # Checkout configured branch
                subprocess.run(
                    ["git", "checkout", branch],
                    cwd=str(target_dir),
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=True,
                )
                # Reset or pull to match remote baseline
                subprocess.run(
                    ["git", "pull", "origin", branch],
                    cwd=str(target_dir),
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True,
                )
            except subprocess.CalledProcessError as exc:
                logger.warning(
                    "Git pull failed on existing workspace at %s (%s). Attempting reset.",
                    target_dir,
                    _redact_git_secrets(exc.stderr or str(exc), token),
                )
                try:
                    subprocess.run(
                        ["git", "reset", "--hard", f"origin/{branch}"],
                        cwd=str(target_dir),
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                except Exception:
                    pass
        else:
            logger.info("Cloning repository %s/%s into %s", owner, repo, target_dir)
            cloned = False
            last_error = ""
            try:
                # Try branch clone
                res = subprocess.run(
                    ["git", "clone", "--branch", branch, "--depth", "50", clone_url, str(target_dir)],
                    capture_output=True,
                    text=True,
                    timeout=90,
                )
                if res.returncode == 0:
                    cloned = True
                else:
                    last_error = _redact_git_secrets(
                        (res.stderr or res.stdout or "branch clone failed").strip(), token
                    )
                    logger.warning("Branch clone failed: %s. Trying default clone.", last_error)
                    res = subprocess.run(
                        ["git", "clone", "--depth", "50", clone_url, str(target_dir)],
                        capture_output=True,
                        text=True,
                        timeout=90,
                    )
                    if res.returncode == 0:
                        cloned = True
                        subprocess.run(
                            ["git", "checkout", branch],
                            cwd=str(target_dir),
                            capture_output=True,
                            text=True,
                            timeout=15,
                        )
                    else:
                        last_error = _redact_git_secrets(
                            (res.stderr or res.stdout or last_error or "git clone failed").strip(),
                            token,
                        )
            except Exception as exc:
                logger.warning("Git clone failed for %s/%s: %s", owner, repo, _redact_git_secrets(str(exc), token))
                last_error = _redact_git_secrets(str(exc), token)

            if not cloned:
                if target_dir.exists() and not (target_dir / ".git").is_dir():
                    shutil.rmtree(target_dir, ignore_errors=True)
                raise RuntimeError(
                    f"Failed to clone {owner}/{repo}@{branch}: {last_error or 'git clone failed'}"
                )

        self.repo_root = target_dir
        return self.repo_root

    def create_workspace(self) -> Path:
        """Copy the project source into a fresh isolated temporary directory for sandbox testing."""
        tmpdir = Path(tempfile.mkdtemp(prefix="api_doctor_workspace_"))
        workspace = tmpdir / "repo"
        if self.repo_root.is_dir():
            shutil.copytree(
                self.repo_root,
                workspace,
                ignore=_IGNORE_PATTERNS,
                dirs_exist_ok=False,
            )
        else:
            workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    @staticmethod
    def cleanup(workspace: Path) -> None:
        """Safely remove a temporary workspace."""
        if workspace and workspace.parent:
            shutil.rmtree(workspace.parent, ignore_errors=True)

    def read_relative(self, workspace: Path | None, rel_path: str) -> str | None:
        """Read a file safely from the workspace or repository root by relative path."""
        root = (workspace or self.repo_root).resolve()
        try:
            full = (root / rel_path).resolve()
            full.relative_to(root)
        except (ValueError, OSError):
            return None

        if not full.is_file():
            return None
        try:
            return full.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None

    def write_relative(self, workspace: Path, rel_path: str, content: str) -> bool:
        """Write content safely to a relative file path within the workspace."""
        root = workspace.resolve()
        try:
            full = (root / rel_path).resolve()
            full.relative_to(root)
        except (ValueError, OSError):
            return False

        full.parent.mkdir(parents=True, exist_ok=True)
        try:
            full.write_text(content, encoding="utf-8")
            return True
        except Exception:
            return False

    def files(self, workspace: Path | None = None) -> list[str]:
        """List repository-relative file paths present in the workspace."""
        root = (workspace or self.repo_root).resolve()
        if not root.is_dir():
            return []

        out: list[str] = []
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            # Skip ignored directories
            if any(part in _IGNORED_NAMES for part in p.relative_to(root).parts):
                continue
            if ".api_doctor_" in p.name:
                continue
            try:
                out.append(str(p.relative_to(root)).replace("\\", "/"))
            except ValueError:
                pass
        return sorted(out)

    def file_tree(self, workspace: Path | None = None) -> list[dict[str, Any]]:
        """Return a hierarchical file tree structure for frontend explorer navigation."""
        paths = self.files(workspace)
        root_nodes: list[dict[str, Any]] = []

        for path in paths:
            parts = path.split("/")
            current_level = root_nodes
            parent_path = ""

            for i, part in enumerate(parts):
                current_path = f"{parent_path}/{part}" if parent_path else part
                is_file = i == len(parts) - 1

                existing = next((n for n in current_level if n["name"] == part), None)
                if not existing:
                    node: dict[str, Any] = {
                        "name": part,
                        "path": current_path,
                        "type": "file" if is_file else "folder",
                    }
                    if is_file:
                        node["ext"] = part.split(".")[-1] if "." in part else ""
                    else:
                        node["children"] = []
                    current_level.append(node)
                    existing = node

                if not is_file:
                    current_level = existing["children"]
                parent_path = current_path

        def sort_tree(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            folders = [it for it in items if it["type"] == "folder"]
            files = [it for it in items if it["type"] == "file"]
            folders.sort(key=lambda x: x["name"].lower())
            files.sort(key=lambda x: x["name"].lower())
            for f in folders:
                f["children"] = sort_tree(f.get("children", []))
            return folders + files

        return sort_tree(root_nodes)
