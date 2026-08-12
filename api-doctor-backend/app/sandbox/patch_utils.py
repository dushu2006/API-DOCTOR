"""Unified-diff parsing, validation and application.

Diffs are applied with an internal Python patch engine in a sandboxed workspace,
never on the production repository. Before applying we validate the diff
structurally and restrict it to paths inside the workspace root.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

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
    _apply_diff(diff, workspace_root)
    return affected


def _apply_diff(diff: str, workspace_root: Path) -> None:
    file_patches = _parse_unified_diff(diff)
    for patch in file_patches:
        _apply_file_patch(patch, workspace_root)


def _parse_unified_diff(diff: str) -> list[dict[str, Any]]:
    lines = diff.splitlines()
    patches: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- "):
            old_path = line[4:].strip()
            i += 1
            if i >= len(lines) or not lines[i].startswith("+++ "):
                raise PatchError("Malformed unified diff: missing +++ header")
            new_path = lines[i][4:].strip()
            i += 1
            hunks: list[dict[str, Any]] = []
            while i < len(lines) and lines[i].startswith("@@ "):
                header = lines[i]
                match = _HUNK_HEADER.match(header)
                if not match:
                    raise PatchError(f"Malformed hunk header: {header!r}")
                old_start = int(match.group(1))
                old_count = int(match.group(2) or "1")
                new_start = int(match.group(3))
                new_count = int(match.group(4) or "1")
                i += 1
                hunk_lines: list[str] = []
                while i < len(lines) and lines[i] and lines[i][0] in (" ", "+", "-", "\\"):
                    hunk_lines.append(lines[i])
                    i += 1
                hunks.append(
                    {
                        "old_start": old_start,
                        "old_count": old_count,
                        "new_start": new_start,
                        "new_count": new_count,
                        "lines": hunk_lines,
                    }
                )
            patches.append(
                {
                    "old_path": old_path,
                    "new_path": new_path,
                    "hunks": hunks,
                }
            )
        else:
            i += 1
    return patches


def _apply_file_patch(patch: dict[str, Any], workspace_root: Path) -> None:
    old_path = patch["old_path"]
    new_path = patch["new_path"]
    if old_path == "/dev/null":
        orig_lines: list[str] = []
    else:
        rel_old = _strip_prefix(old_path)
        old_file = workspace_root / rel_old
        if not old_file.exists():
            raise PatchError(f"Original file not found: {rel_old}")
        orig_lines = old_file.read_text().splitlines()

    rel_new = _strip_prefix(new_path)
    result_lines = []
    current_index = 0

    for hunk in patch["hunks"]:
        old_start = hunk["old_start"] - 1
        old_count = hunk["old_count"]
        if old_start < current_index or old_start > len(orig_lines):
            raise PatchError("Hunk location out of range")
        result_lines.extend(orig_lines[current_index:old_start])
        idx = old_start
        for hline in hunk["lines"]:
            if not hline:
                continue
            opcode = hline[0]
            content = hline[1:]
            if opcode == " ":
                if idx >= len(orig_lines) or orig_lines[idx] != content:
                    raise PatchError(
                        f"Patch failed to apply cleanly: context mismatch at line {idx + 1}"
                    )
                result_lines.append(content)
                idx += 1
            elif opcode == "-":
                if idx >= len(orig_lines) or orig_lines[idx] != content:
                    raise PatchError(
                        f"Patch failed to apply cleanly: removal mismatch at line {idx + 1}"
                    )
                idx += 1
            elif opcode == "+":
                result_lines.append(content)
            elif opcode == "\\":
                continue
            else:
                raise PatchError(f"Unsupported patch opcode: {opcode}")
        current_index = idx
    result_lines.extend(orig_lines[current_index:])

    if new_path == "/dev/null":
        # file deletion
        (workspace_root / rel_old).unlink(missing_ok=True)
        return
    target_file = workspace_root / rel_new
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text("\n".join(result_lines) + ("\n" if result_lines and not result_lines[-1].endswith("\n") else ""))


def _strip_prefix(path: str) -> str:
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path
