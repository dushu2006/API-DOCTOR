"""Unified-diff parsing, validation and application.

Diffs are applied with an internal Python patch engine in a sandboxed workspace,
never on the production repository. Before applying we validate the diff
structurally and restrict it to paths inside the workspace root.

LLM-generated diffs frequently carry git metadata headers (``diff --git``,
``index ...``) or paths that do not exactly match the repository layout.
:func:`normalize_diff` strips non-unified noise and :func:`resolve_diff_paths`
rewrites diff paths to canonical repository-relative paths so a patch that says
``app/main.py`` still finds ``src/app/main.py`` when that is the real location.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

_UNSAFE_PATH = re.compile(r"(\.\.|^/|:|[\\])")

# Git plumbing lines that may precede the actual unified diff body.
_NOISE_PREFIXES = (
    "diff --git ",
    "index ",
    "new file mode",
    "deleted file mode",
    "old mode",
    "new mode",
    "similarity index",
    "dissimilarity index",
    "rename from",
    "rename to",
    "copy from",
    "copy to",
    "Binary files",
)


class PatchError(Exception):
    """Raised for structurally invalid or unsafe patches."""


def normalize_diff(diff: str) -> str:
    """Strip git metadata noise so only the unified diff body remains.

    Guarantees the result starts with a ``--- `` header (synthesizing one from
    the first ``+++ `` header when the model omitted it) and ends with a
    newline. Raises :class:`PatchError` when no usable diff body is present.
    """
    if not diff or not diff.strip():
        raise PatchError("Empty diff")

    cleaned: list[str] = []
    for raw in diff.splitlines():
        if any(raw.startswith(prefix) for prefix in _NOISE_PREFIXES):
            continue
        cleaned.append(raw.rstrip("\r"))

    # Drop leading blanks / stray lines before the first file header.
    while cleaned and not cleaned[0].startswith("--- ") and not cleaned[0].startswith("+++ "):
        cleaned.pop(0)

    if not cleaned:
        raise PatchError("Diff contains no file headers")

    if cleaned[0].startswith("+++ "):
        # Model emitted only the new-side header; synthesize the old side.
        new_header = cleaned[0][4:].strip()
        old_path = new_header[2:] if new_header.startswith("b/") else new_header
        cleaned.insert(0, f"--- a/{old_path}" if new_header != "/dev/null" else "--- /dev/null")

    return "\n".join(cleaned).rstrip("\n") + "\n"


def _header_path(header_line: str) -> str:
    """Extract the path from a ``--- a/x`` / ``+++ b/x`` header."""
    path = header_line[4:].strip()
    # Strip tab-separated timestamps some tools append.
    return path.split("\t")[0].strip()


def resolve_diff_paths(diff: str, workspace_root: Path) -> tuple[str, dict[str, str]]:
    """Rewrite diff file headers to canonical workspace-relative paths.

    AI models often emit paths that are close but not exact (``main.py``
    instead of ``app/main.py``, or vice versa). For every header path that does
    not exist in the workspace we look for the best-matching real file by
    shared trailing path segments. Paths that already exist (and ``/dev/null``)
    are left untouched.

    Returns ``(resolved_diff, mapping)`` where mapping is
    ``{original_path: resolved_path}`` for every rewritten path.
    """
    root = Path(workspace_root)
    normalized = normalize_diff(diff)
    lines = normalized.splitlines()

    # Index workspace files once.
    workspace_files: list[str] | None = None

    def _files() -> list[str]:
        nonlocal workspace_files
        if workspace_files is None:
            from app.sandbox.workspace_manager import WorkspaceManager

            workspace_files = WorkspaceManager(repo_root=root).files(root if root.is_dir() else None)
        return workspace_files

    def _resolve(path: str) -> str:
        if not path or path == "/dev/null":
            return path
        rel = _strip_prefix(path)
        if (root / rel).is_file():
            return path  # already correct (keep original a/ b/ prefix)
        candidates = _files()
        best = _best_match(rel, candidates)
        if not best:
            return path
        prefix = path[:2] if path.startswith(("a/", "b/")) else ""
        return f"{prefix}{best}"

    mapping: dict[str, str] = {}
    out_lines: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            old_p = _header_path(line)
            new_p = _header_path(lines[i + 1])
            # New-file diffs key off the +++ path; deletions off the --- path.
            resolved_new = _resolve(new_p)
            resolved_old = _resolve(old_p) if old_p != "/dev/null" else old_p
            if new_p != "/dev/null":
                resolved_old = _align_old_with_new(old_p, new_p, resolved_new)
            if _strip_prefix(resolved_new) != _strip_prefix(new_p):
                mapping[_strip_prefix(new_p)] = _strip_prefix(resolved_new)
            if old_p != "/dev/null" and _strip_prefix(resolved_old) != _strip_prefix(old_p):
                mapping.setdefault(_strip_prefix(old_p), _strip_prefix(resolved_old))
            out_lines.append(f"--- {resolved_old}")
            out_lines.append(f"+++ {resolved_new}")
            i += 2
            continue
        out_lines.append(line)
        i += 1

    return "\n".join(out_lines) + "\n", mapping


def _align_old_with_new(old_p: str, new_p: str, resolved_new: str) -> str:
    """Keep ---/+++ pairs consistent when the +++ side was relocated."""
    if old_p == "/dev/null":
        return old_p
    if _strip_prefix(old_p) == _strip_prefix(new_p):
        prefix = old_p[:2] if old_p.startswith(("a/", "b/")) else ""
        return f"{prefix}{_strip_prefix(resolved_new)}"
    return _resolve_same(old_p, resolved_new)


def _resolve_same(path: str, resolved_other: str) -> str:
    prefix = path[:2] if path.startswith(("a/", "b/")) else ""
    return f"{prefix}{_strip_prefix(resolved_other)}"


def _best_match(rel: str, candidates: list[str]) -> str | None:
    """Pick the workspace file sharing the most trailing path segments."""
    rel_parts = [p for p in Path(rel).parts if p not in (".", "/")]
    if not rel_parts:
        return None
    scored: list[tuple[int, str]] = []
    for cand in candidates:
        cand_parts = Path(cand).parts
        shared = 0
        for a, b in zip(reversed(rel_parts), reversed(cand_parts)):
            if a == b:
                shared += 1
            else:
                break
        if shared > 0:
            scored.append((shared, cand))
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
    best_shared, best = scored[0]
    # Require at least the filename to match; a bare directory-segment match is
    # too weak to justify rewriting the patch target.
    if best_shared < 1 or Path(best).name != rel_parts[-1]:
        return None
    return best


def preview_patch(diff: str, workspace_root: Path) -> list[dict[str, Any]]:
    """Compute per-file before/after contents without touching the workspace.

    Used to power the side-by-side diff editor. Each entry contains::

        {"path": str, "original": str, "proposed": str, "error": str | None}
    """
    root = Path(workspace_root)
    resolved, _mapping = resolve_diff_paths(diff, root)
    patches = _parse_unified_diff(resolved)
    previews: list[dict[str, Any]] = []
    for patch in patches:
        rel_old = _strip_prefix(patch["old_path"])
        rel_new = _strip_prefix(patch["new_path"])
        entry: dict[str, Any] = {
            "path": rel_new if patch["new_path"] != "/dev/null" else rel_old,
            "original": "",
            "proposed": "",
            "error": None,
        }
        try:
            if patch["old_path"] == "/dev/null":
                orig_lines: list[str] = []
            else:
                original_file = root / rel_old
                if not original_file.is_file():
                    raise PatchError(f"Original file not found: {rel_old}")
                entry["original"] = original_file.read_text(encoding="utf-8", errors="replace")
                orig_lines = entry["original"].splitlines()
            result_lines = _apply_hunks(orig_lines, patch["hunks"])
            if patch["new_path"] == "/dev/null":
                entry["proposed"] = ""
            else:
                text = "\n".join(result_lines)
                if result_lines:
                    text += "\n"
                entry["proposed"] = text
        except PatchError as exc:
            entry["error"] = str(exc)
        previews.append(entry)
    return previews


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

    The diff is normalized (git metadata stripped) and its paths are resolved
    against the workspace before application, so relocated files are still
    found. Returns the list of affected relative paths. Raises
    :class:`PatchError` on structural problems or when the patch fails to apply
    cleanly.
    """
    resolved, _mapping = resolve_diff_paths(diff, workspace_root)
    affected = validate_diff(resolved, allowed_roots=[str(workspace_root)])
    _apply_diff(resolved, workspace_root)
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


def _hunk_old_contents(hunk: dict[str, Any]) -> list[str]:
    """Old-file lines referenced by a hunk (context + removals)."""
    old: list[str] = []
    for hline in hunk["lines"]:
        if hline and hline[0] in (" ", "-"):
            old.append(hline[1:])
    return old


def _lines_equal(left: str, right: str) -> bool:
    # Tolerate trailing whitespace / CRLF differences that LLMs often introduce.
    return left.rstrip() == right.rstrip()


def _match_old_at(orig_lines: list[str], old_contents: list[str], idx: int) -> bool:
    if idx < 0 or idx + len(old_contents) > len(orig_lines):
        return False
    return all(
        _lines_equal(orig_lines[idx + offset], old)
        for offset, old in enumerate(old_contents)
    )


def _locate_hunk(orig_lines: list[str], hunk: dict[str, Any], current_index: int) -> int:
    """Find where a hunk applies.

    Prefer the ``@@`` header line number. If that context does not match
    (generated diffs frequently have slightly-off line numbers), search the
    file for the hunk's old lines — the same idea as GNU patch's fuzz factor.
    """
    claimed = max(0, int(hunk["old_start"]) - 1)
    old_contents = _hunk_old_contents(hunk)

    if not old_contents:
        if current_index <= claimed <= len(orig_lines):
            return claimed
        return current_index

    if claimed >= current_index and _match_old_at(orig_lines, old_contents, claimed):
        return claimed

    search_from = current_index
    search_to = len(orig_lines) - len(old_contents) + 1
    matches = [
        idx
        for idx in range(search_from, max(search_from, search_to))
        if _match_old_at(orig_lines, old_contents, idx)
    ]
    if not matches:
        matches = [
            idx
            for idx in range(0, min(current_index, max(0, search_to)))
            if _match_old_at(orig_lines, old_contents, idx)
        ]
    if not matches:
        raise PatchError(
            f"Patch failed to apply cleanly: context mismatch at line {claimed + 1}"
        )
    return min(matches, key=lambda idx: abs(idx - claimed))


def _apply_hunks(orig_lines: list[str], hunks: list[dict[str, Any]]) -> list[str]:
    """Apply parsed hunks to a list of source lines, returning the new lines."""
    result_lines: list[str] = []
    current_index = 0

    for hunk in hunks:
        old_start = _locate_hunk(orig_lines, hunk, current_index)
        result_lines.extend(orig_lines[current_index:old_start])
        idx = old_start
        for hline in hunk["lines"]:
            if not hline:
                continue
            opcode = hline[0]
            content = hline[1:]
            if opcode == " ":
                if idx >= len(orig_lines) or not _lines_equal(orig_lines[idx], content):
                    raise PatchError(
                        f"Patch failed to apply cleanly: context mismatch at line {idx + 1}"
                    )
                result_lines.append(orig_lines[idx])
                idx += 1
            elif opcode == "-":
                if idx >= len(orig_lines) or not _lines_equal(orig_lines[idx], content):
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
    return result_lines


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
        orig_lines = old_file.read_text(encoding="utf-8", errors="replace").splitlines()

    rel_new = _strip_prefix(new_path)
    result_lines = _apply_hunks(orig_lines, patch["hunks"])

    if new_path == "/dev/null":
        # file deletion
        (workspace_root / _strip_prefix(old_path)).unlink(missing_ok=True)
        return
    target_file = workspace_root / rel_new
    target_file.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(result_lines)
    if result_lines:
        text += "\n"
    target_file.write_text(text, encoding="utf-8")


def _strip_prefix(path: str) -> str:
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path
