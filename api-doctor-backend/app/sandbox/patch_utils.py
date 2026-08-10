"""Unified-diff parsing, validation and application.

Diffs are applied with the system ``patch`` tool in a sandboxed workspace, never
on the production repository. Before applying we validate the diff structurally
and restrict it to paths inside the workspace root.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

_UNSAFE_PATH = re.compile(r"(\.\.|^/|:|[\\])")


class PatchError(Exception):
    """Raised for structurally invalid or unsafe patches."""


def validate_diff(diff: str, allowed_roots: list[str] | None = None) -> list[str]:
    """Validate a unified diff.

    Returns the list of affected file paths (relative). Raises :class:`PatchError`
    for malformed/unsafe diffs.
    """
    if not diff or not diff.strip():
        raise PatchError("Empty diff")
    lines = diff.splitlines()
    if not lines[0].startswith("--- "):
        raise PatchError("Diff must start with a `--- a/...` header")

    affected: list[str] = []
    for i, line in enumerate(lines):
        if line.startswith("+++ b/"):
            path = line[6:].strip()
            _check_path(path, allowed_roots)
            affected.append(path)
        elif line.startswith("+++ "):
            path = line[4:].strip()
            _check_path(path, allowed_roots)
            affected.append(path)
        elif line.startswith("@@ "):
            if not _HUNK_HEADER.match(line):
                raise PatchError(f"Malformed hunk header: {line!r}")
    if not affected:
        raise PatchError("No file headers found in diff")
    return affected


def _check_path(path: str, allowed_roots: list[str] | None) -> None:
    if not path or _UNSAFE_PATH.search(path):
        raise PatchError(f"Unsafe or non-relative diff path: {path!r}")
    if allowed_roots:
        normalized = Path(path)
        ok = False
        for root in allowed_roots:
            try:
                (Path(root) / normalized).resolve().relative_to(Path(root).resolve())
                ok = True
                break
            except (ValueError, OSError):
                continue
        if not ok:
            raise PatchError(f"Diff path {path!r} is outside allowed roots")


def apply_patch(diff: str, workspace_root: Path) -> list[str]:
    """Apply a validated unified diff to ``workspace_root``.

    Returns the list of affected relative paths. Raises :class:`PatchError` on
    structural problems or when the patch fails to apply cleanly.
    """
    affected = validate_diff(diff, allowed_roots=[str(workspace_root)])
    patch_file = workspace_root / ".api_doctor_fix.patch"
    patch_file.write_text(diff)
    try:
        result = subprocess.run(
            ["patch", "-p1", "--no-backup-if-mismatch", "--forward", "-i", str(patch_file)],
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired as exc:
        raise PatchError("patch command timed out") from exc
    finally:
        patch_file.unlink(missing_ok=True)

    if result.returncode != 0:
        raise PatchError(f"patch failed to apply cleanly: {result.stdout}\n{result.stderr}")
    return affected
