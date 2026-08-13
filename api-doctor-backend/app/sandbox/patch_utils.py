"""Unified-diff parsing, validation and application.

Diffs are applied with an internal Python patch engine to a caller-selected
sandbox or approved project workspace. Before applying we validate the diff
structurally and restrict it to paths inside that workspace root.

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

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))?(?: \+(\d*)(?:,(\d+))?)? @@")

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
            _fill_error_preview(entry, patch)
        previews.append(entry)
    return previews


def _fill_error_preview(entry: dict[str, Any], patch: dict[str, Any]) -> None:
    """Populate a reviewable before/after view when strict application fails.

    A patch whose hunks do not match the current file used to surface as a
    full red pane (whole file shown as removed) next to an empty green pane,
    completely hiding the change under review. Two readable fallbacks instead:

    1.  If the patch's changes are *already present* in the file (detected by
        reverse-applying the hunks to the current content) reconstruct the
        pre-fix content for the red side and keep the current, fixed content
        on the green side. That renders the exact change set normally, and
        because the application path accepts this state as already applied
        the error banner is cleared as well.
    2.  Otherwise the workspace genuinely drifted. Best-effort apply the
        hunks at their fuzzy/claimed positions without verifying context so
        the intended removals still show red and the additions green. The
        strict error message stays, as a banner, to warn the review is of a
        stale patch.
    """
    if patch["new_path"] == "/dev/null":
        # File-deletion patch: the empty green pane is the correct outcome.
        return
    current_text = entry.get("original") or ""
    orig_lines = current_text.splitlines()

    if patch["old_path"] != "/dev/null" and orig_lines:
        try:
            pre_lines = _apply_hunks(orig_lines, _reverse_file_patch(patch)["hunks"])
        except PatchError:
            pass
        else:
            pre_text = "\n".join(pre_lines)
            if pre_lines:
                pre_text += "\n"
            entry["original"] = pre_text
            entry["proposed"] = current_text
            entry["error"] = None
            return

    result_lines = _apply_hunks_lenient(orig_lines, patch["hunks"])
    text = "\n".join(result_lines)
    if result_lines:
        text += "\n"
    entry["proposed"] = text


def _apply_hunks_lenient(orig_lines: list[str], hunks: list[dict[str, Any]]) -> list[str]:
    """Best-effort hunk application for the preview pane when strict matching
    failed because the file drifted since the patch was generated.

    Hunks are placed at their fuzzy-located (or claimed) position and applied
    without verifying that context/removal lines still match: context keeps
    whatever content is currently in the file, removals drop the line sitting
    at the slot, additions are inserted verbatim. The result is used only for
    the review diff and is never written to the workspace.
    """
    result_lines: list[str] = []
    current_index = 0

    for hunk in hunks:
        try:
            start = _locate_hunk(orig_lines, hunk, current_index)
        except PatchError:
            start = _best_effort_locate(orig_lines, hunk, current_index)
        result_lines.extend(orig_lines[current_index:start])
        idx = start
        for hline in hunk["lines"]:
            if not hline:
                continue
            opcode = hline[0]
            content = hline[1:]
            if opcode == " ":
                if idx < len(orig_lines):
                    # Whatever currently sits on a context row counts as
                    # unchanged for this degraded preview.
                    result_lines.append(orig_lines[idx])
                    idx += 1
                else:
                    result_lines.append(content)
            elif opcode == "-":
                if idx < len(orig_lines):
                    idx += 1
            elif opcode == "+":
                result_lines.append(content)
            elif opcode == "\\":
                continue
        current_index = idx
    result_lines.extend(orig_lines[current_index:])
    return result_lines


def validate_diff(diff: str, allowed_roots: list[str] | None = None) -> list[str]:
    """Validate a unified diff.

    Returns the list of affected file paths (relative). Raises :class:`PatchError`
    for malformed/unsafe diffs.  Both sides of every file header are checked;
    for a deletion, where the new side is ``/dev/null``, the old path is the
    affected path.
    """
    if not diff or not diff.strip():
        raise PatchError("Empty diff")
    lines = diff.splitlines()
    if not lines[0].startswith("--- "):
        raise PatchError("Diff must start with a `--- a/...` header")

    patches = _parse_unified_diff(diff)
    if not patches:
        raise PatchError("No file headers found in diff")

    affected: list[str] = []
    for patch in patches:
        if not patch["hunks"]:
            raise PatchError("File section contains no hunks")
        old_path = patch["old_path"]
        new_path = patch["new_path"]
        if old_path == "/dev/null" and new_path == "/dev/null":
            raise PatchError("A patch cannot use /dev/null for both file paths")
        if old_path != "/dev/null":
            _check_path(_strip_prefix(old_path), allowed_roots)
        if new_path != "/dev/null":
            _check_path(_strip_prefix(new_path), allowed_roots)
        target = new_path if new_path != "/dev/null" else old_path
        rel_target = _strip_prefix(target)
        if rel_target in affected:
            raise PatchError(f"Duplicate file section in diff: {rel_target}")
        affected.append(rel_target)
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
    found.  Every file is rendered in memory before the first write.  A bad
    hunk in file two therefore cannot leave file one partially modified.

    Returns the list of affected relative paths. Raises :class:`PatchError` on
    structural problems or when the patch fails to apply cleanly.
    """
    resolved, _mapping = resolve_diff_paths(diff, workspace_root)
    affected = validate_diff(resolved, allowed_roots=[str(workspace_root)])
    _apply_diff(resolved, workspace_root)
    return affected


def apply_patch_idempotent(
    diff: str, workspace_root: Path
) -> tuple[list[str], list[str]]:
    """Apply ``diff`` while accepting files that already contain its result.

    A client can lose the HTTP response after the workspace write but before
    the current run's ``applied_files`` metadata is recorded in memory.  Retrying that
    request used to report a false "file changed since diagnosis" conflict.
    For each file whose forward patch does not apply, this function tries the
    exact reverse patch in memory.  If the reverse applies, the requested
    change is already present and that file is safely treated as complete.

    All still-required file writes are preflighted before any are committed.
    The return value is ``(affected_paths, already_applied_paths)``.
    """
    root = Path(workspace_root)
    resolved, _mapping = resolve_diff_paths(diff, root)
    affected = validate_diff(resolved, allowed_roots=[str(root)])
    patches = _parse_unified_diff(resolved)

    operations: list[dict[str, Any]] = []
    already_applied: list[str] = []
    for patch in patches:
        try:
            operations.append(_prepare_file_patch(patch, root))
        except PatchError as forward_error:
            try:
                _prepare_file_patch(_reverse_file_patch(patch), root)
            except PatchError:
                # Preserve the forward error: it identifies the stale hunk the
                # user actually attempted to apply, rather than a less useful
                # failure from the reverse probe.
                raise forward_error
            rel = _affected_path(patch)
            if rel not in already_applied:
                already_applied.append(rel)

    _commit_file_operations(operations)
    return affected, already_applied


def reverse_applied_files(
    diff: str, workspace_root: Path, paths: list[str] | set[str]
) -> list[str]:
    """Reverse selected, already-applied file patches in ``workspace_root``.

    Keep-Changes uses this only on its *backup copy*.  It reconstructs the
    pre-apply source when recovering an idempotent retry, allowing sandbox
    verification to reproduce the original failure even though the live
    workspace already contains the fix.
    """
    root = Path(workspace_root)
    resolved, _mapping = resolve_diff_paths(diff, root)
    wanted = set(paths)
    operations: list[dict[str, Any]] = []
    reverted: list[str] = []
    for patch in _parse_unified_diff(resolved):
        rel = _affected_path(patch)
        if rel not in wanted:
            continue
        operations.append(_prepare_file_patch(_reverse_file_patch(patch), root))
        reverted.append(rel)
    _commit_file_operations(operations)
    return reverted


def _apply_diff(diff: str, workspace_root: Path) -> None:
    # Preflight every hunk before touching the workspace.  This makes patch
    # context failures transactional across a multi-file diff.
    operations = [
        _prepare_file_patch(patch, workspace_root)
        for patch in _parse_unified_diff(diff)
    ]
    _commit_file_operations(operations)


def _parse_unified_diff(diff: str) -> list[dict[str, Any]]:
    lines = diff.splitlines()
    patches: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- "):
            old_path = _header_path(line)
            i += 1
            if i >= len(lines) or not lines[i].startswith("+++ "):
                raise PatchError("Malformed unified diff: missing +++ header")
            new_path = _header_path(lines[i])
            i += 1
            hunks: list[dict[str, Any]] = []
            while i < len(lines) and lines[i].startswith("@@ "):
                header = lines[i]
                match = _HUNK_HEADER.match(header)
                if not match:
                    raise PatchError(f"Malformed hunk header: {header!r}")
                old_start = int(match.group(1))
                old_count = int(match.group(2) or "1")
                # The new-file side (+start,+count) is optional or may be
                # malformed from LLM output (e.g. a trailing '+' with no
                # numbers). If the captured new-start is missing or not a
                # digit, fall back to the old range values for safety.
                new_start_raw = match.group(3)
                if new_start_raw and new_start_raw.isdigit():
                    new_start = int(new_start_raw)
                    new_count = int(match.group(4) or "1")
                else:
                    new_start = old_start
                    new_count = old_count
                i += 1
                hunk_lines: list[str] = []
                while i < len(lines):
                    raw = lines[i]
                    # A multi-file unified diff commonly places the next file's
                    # ---/+++ headers immediately after the previous hunk (no
                    # blank separator). Those are headers, not removal/addition
                    # lines belonging to this hunk.
                    if (
                        raw.startswith("--- ")
                        and i + 1 < len(lines)
                        and lines[i + 1].startswith("+++ ")
                    ):
                        break
                    if raw == "":
                        # Models routinely strip the leading space from blank
                        # context lines (PEP8 code is full of blank lines), and
                        # a bare empty line used to truncate the hunk here and
                        # silently drop every +/-/context line after it. Like
                        # GNU patch, absorb a run of blank lines as empty
                        # context lines — but only when the hunk body actually
                        # resumes afterwards; otherwise the blanks separate
                        # sections and the hunk is over.
                        j = i
                        while j < len(lines) and lines[j] == "":
                            j += 1
                        nxt = lines[j] if j < len(lines) else ""
                        resumes_hunk = (
                            nxt.startswith((" ", "+", "-", "\\"))
                            and not (
                                nxt.startswith("--- ")
                                and j + 1 < len(lines)
                                and lines[j + 1].startswith("+++ ")
                            )
                        )
                        if not resumes_hunk:
                            break
                        hunk_lines.extend(" " for _ in range(j - i))
                        i = j
                        continue
                    if not raw.startswith((" ", "+", "-", "\\")):
                        break
                    hunk_lines.append(raw)
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


def _best_effort_locate(orig_lines: list[str], hunk: dict[str, Any], current_index: int) -> int:
    """Locate a hunk that no longer matches anywhere exactly.

    Used only by the degraded preview: slide the hunk's old-side lines over
    the file and return the position with the most matching lines (preferring
    the claimed line on ties), so the review stays anchored near the edit
    instead of dumping the hunk at whatever the stale header claimed.
    """
    claimed = max(0, int(hunk["old_start"]) - 1)
    fallback = min(max(claimed, current_index), len(orig_lines))
    old_contents = _hunk_old_contents(hunk)
    if not old_contents:
        return fallback
    best_idx = fallback
    best_score = 0
    stop = len(orig_lines) - len(old_contents) + 1
    for idx in range(current_index, max(current_index, stop)):
        score = sum(
            1
            for offset, old in enumerate(old_contents)
            if _lines_equal(orig_lines[idx + offset], old)
        )
        if score > best_score or (score == best_score and abs(idx - claimed) < abs(best_idx - claimed)):
            best_idx = idx
            best_score = score
    return best_idx


def _affected_path(patch: dict[str, Any]) -> str:
    path = patch["new_path"] if patch["new_path"] != "/dev/null" else patch["old_path"]
    return _strip_prefix(path)


def _render_file_patch(
    patch: dict[str, Any], original_text: str
) -> tuple[str | None, str | None, str | None]:
    """Render one parsed patch without reading or writing the filesystem.

    Returns ``(target_path, target_text, deleted_path)``.
    """
    orig_lines = original_text.splitlines()
    result_lines = _apply_hunks(orig_lines, patch["hunks"])
    if patch["new_path"] == "/dev/null":
        return None, None, _strip_prefix(patch["old_path"])

    text = "\n".join(result_lines)
    if result_lines:
        text += "\n"
    return _strip_prefix(patch["new_path"]), text, None


def _prepare_file_patch(
    patch: dict[str, Any], workspace_root: Path
) -> dict[str, Any]:
    """Read and render one file patch, returning a deferred write operation."""
    old_path = patch["old_path"]
    if old_path == "/dev/null":
        # A creation patch must never silently replace an unrelated file.  The
        # idempotent caller will reverse-probe an existing target and accept it
        # only when its contents are the exact post-image of this patch.
        rel_new = _strip_prefix(patch["new_path"])
        if (workspace_root / rel_new).exists():
            raise PatchError(f"New file already exists: {rel_new}")
        original_text = ""
    else:
        rel_old = _strip_prefix(old_path)
        old_file = workspace_root / rel_old
        if not old_file.is_file():
            raise PatchError(f"Original file not found: {rel_old}")
        original_text = old_file.read_text(encoding="utf-8", errors="replace")

    target_path, target_text, deleted_path = _render_file_patch(patch, original_text)
    return {
        "root": Path(workspace_root),
        "target_path": target_path,
        "target_text": target_text,
        "deleted_path": deleted_path,
    }


def _commit_file_operations(operations: list[dict[str, Any]]) -> None:
    for operation in operations:
        root = Path(operation["root"])
        deleted_path = operation.get("deleted_path")
        if deleted_path:
            (root / deleted_path).unlink(missing_ok=True)
            continue
        target_path = operation.get("target_path")
        if target_path is None:
            continue
        target_file = root / target_path
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(operation.get("target_text") or "", encoding="utf-8")


def _reverse_file_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """Return a parsed patch that exactly reverses ``patch``."""
    reversed_hunks: list[dict[str, Any]] = []
    for hunk in patch["hunks"]:
        reversed_lines: list[str] = []
        for line in hunk["lines"]:
            if line.startswith("+"):
                reversed_lines.append("-" + line[1:])
            elif line.startswith("-"):
                reversed_lines.append("+" + line[1:])
            else:
                reversed_lines.append(line)
        reversed_hunks.append(
            {
                "old_start": hunk["new_start"],
                "old_count": hunk["new_count"],
                "new_start": hunk["old_start"],
                "new_count": hunk["old_count"],
                "lines": reversed_lines,
            }
        )
    return {
        "old_path": patch["new_path"],
        "new_path": patch["old_path"],
        "hunks": reversed_hunks,
    }


def _apply_file_patch(patch: dict[str, Any], workspace_root: Path) -> None:
    """Backward-compatible single-file helper used by older callers/tests."""
    _commit_file_operations([_prepare_file_patch(patch, workspace_root)])


def _strip_prefix(path: str) -> str:
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path
