"""Multi-language traceback and error log parsing.

Extracts structured information from traceback strings across Python,
JavaScript/TypeScript, Go, and Java: file, line, function, module, exception,
message, and the call chain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

# Python: File "/path/to/file.py", line 42, in function_name
_PY_FRAME_REGEX = re.compile(r'File "([^"]+)", line (\d+), in (.+)')

# JS/TS: at functionName (/path/to/file.js:42:10) OR at /path/to/file.js:42:10
_JS_FRAME_REGEX = re.compile(r'at (?:([A-Za-z0-9_$.<>]+)\s+\(([^)]+):(\d+):(\d+)\)|([^()]+):(\d+):(\d+))')

# Java: at com.example.Class.method(Class.java:42)
_JAVA_FRAME_REGEX = re.compile(r'at\s+([A-Za-z0-9_$.]+)\.([A-Za-z0-9_$]+)\(([^:]+):(\d+)\)')

# Go: /path/to/file.go:42 +0x123
_GO_FRAME_REGEX = re.compile(r'([^\s:]+\.go):(\d+)')

# Python exception line: e.g. AttributeError: 'NoneType' object has no attribute 'token'
_PY_EXC_REGEX = re.compile(r"^([A-Za-z_][A-Za-z0-9_.]*):\s*(.*)$", re.MULTILINE)

# JS exception line: e.g. TypeError: Cannot read properties of undefined
_JS_EXC_REGEX = re.compile(r"^([A-Za-z_][A-Za-z0-9_.]*Error):\s*(.*)$", re.MULTILINE)


@dataclass
class StackFrame:
    file: str  # raw path as it appears in the traceback
    line: int
    function: str
    module: str = ""
    path: Path | None = None  # resolved path within the repository, if any
    relative_path: str | None = None  # path relative to repo root


@dataclass
class ParsedTraceback:
    frames: List[StackFrame]
    exception_type: str | None = None
    message: str | None = None
    call_chain: List[str] = field(default_factory=list)

    @property
    def deepest_frame(self) -> StackFrame | None:
        return self.frames[-1] if self.frames else None


def parse_stack_trace(trace: str, repo_root: Path | str | None = None) -> ParsedTraceback:
    """Parse a traceback string into structured data."""
    if not trace or not trace.strip():
        return ParsedTraceback(frames=[], exception_type=None, message=None, call_chain=[])

    root = Path(repo_root).resolve() if repo_root else None
    frames: List[StackFrame] = []

    # 1. Try Python frames
    for match in _PY_FRAME_REGEX.finditer(trace):
        file_str, line_str, func = match.group(1), match.group(2), match.group(3)
        try:
            line_no = int(line_str)
        except ValueError:
            line_no = 0
        path, rel = _resolve_frame_path(file_str, root)
        module = _extract_module(rel or file_str)
        frames.append(
            StackFrame(file=file_str, line=line_no, function=func, module=module, path=path, relative_path=rel)
        )

    # 2. Try JavaScript / TypeScript frames if no Python frames found
    if not frames:
        for match in _JS_FRAME_REGEX.finditer(trace):
            if match.group(2):  # at func (file:line:col)
                func = match.group(1)
                file_str = match.group(2)
                line_no = int(match.group(3))
            else:  # at file:line:col
                func = "<anonymous>"
                file_str = match.group(5)
                line_no = int(match.group(6))
            path, rel = _resolve_frame_path(file_str, root)
            module = _extract_module(rel or file_str)
            frames.append(
                StackFrame(file=file_str, line=line_no, function=func, module=module, path=path, relative_path=rel)
            )

    # 3. Try Java frames if still empty
    if not frames:
        for match in _JAVA_FRAME_REGEX.finditer(trace):
            cls_name, method, file_str, line_str = match.group(1), match.group(2), match.group(3), match.group(4)
            line_no = int(line_str) if line_str.isdigit() else 0
            path, rel = _resolve_frame_path(file_str, root)
            frames.append(
                StackFrame(file=file_str, line=line_no, function=f"{cls_name}.{method}", module=cls_name, path=path, relative_path=rel)
            )

    # 4. Try Go frames if still empty
    if not frames:
        for match in _GO_FRAME_REGEX.finditer(trace):
            file_str, line_str = match.group(1), match.group(2)
            line_no = int(line_str) if line_str.isdigit() else 0
            path, rel = _resolve_frame_path(file_str, root)
            frames.append(
                StackFrame(file=file_str, line=line_no, function="<go_routine>", module=_extract_module(rel or file_str), path=path, relative_path=rel)
            )

    exception_type, message = _extract_exception(trace)

    call_chain: List[str] = []
    for f in frames:
        call_chain.append(f"{f.file}:{f.line} in {f.function}")

    return ParsedTraceback(
        frames=frames,
        exception_type=exception_type,
        message=message,
        call_chain=call_chain,
    )


def _resolve_frame_path(file_str: str, root: Path | None) -> tuple[Path | None, str | None]:
    """Resolve a file path from a traceback against repository root."""
    if not root:
        return None, file_str
    try:
        resolved = Path(file_str).resolve()
        rel = str(resolved.relative_to(root)).replace("\\", "/")
        return resolved, rel
    except (ValueError, OSError):
        pass

    # Try treating as relative path to root
    candidate = (root / file_str.lstrip("/")).resolve()
    try:
        # Only return as a resolved project path if the file actually exists
        # within the workspace. is_relative_to alone is too permissive.
        if candidate.is_file() and candidate.is_relative_to(root):
            rel = str(candidate.relative_to(root)).replace("\\", "/")
            return candidate, rel
    except (ValueError, OSError):
        pass

    # Search by basename in repo
    base_name = Path(file_str).name
    if base_name:
        for match in root.rglob(base_name):
            if match.is_file():
                try:
                    rel = str(match.relative_to(root)).replace("\\", "/")
                    return match, rel
                except ValueError:
                    pass

    return None, file_str.replace("\\", "/")


def _extract_module(path_str: str) -> str:
    p = Path(path_str)
    stem = p.stem
    parent = p.parent.name
    return f"{parent}.{stem}" if parent and parent != "." else stem


def _extract_exception(trace: str) -> tuple[str | None, str | None]:
    """Extract the exception type and message from the error log."""
    candidate = None
    for raw in trace.strip().splitlines():
        if not raw.strip() or raw[0] in (" ", "\t"):
            continue
        match = _PY_EXC_REGEX.match(raw) or _JS_EXC_REGEX.match(raw)
        if match:
            candidate = match
    if not candidate:
        # Check last non-empty line as fallback
        lines = [l.strip() for l in trace.strip().splitlines() if l.strip()]
        if lines:
            last = lines[-1]
            if ":" in last:
                parts = last.split(":", 1)
                return parts[0].strip(), parts[1].strip()
            return "Error", last
        return None, None

    exc_type = candidate.group(1)
    message = (candidate.group(2) or "").strip() or None
    if message and "validation error" in message:
        message = message.split("\n")[0]
    return exc_type, message
