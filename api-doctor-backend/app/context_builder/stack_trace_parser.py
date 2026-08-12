"""Traceback parsing.

Extracts structured information from a Python traceback string:
file, line, function, exception, message, and the call chain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

# Matches:  File "/path/to/file.py", line 42, in function_name
_FRAME_REGEX = re.compile(r'File "([^"]+)", line (\d+), in (.+)')

# The last line of a traceback carries the exception type and message,
# e.g.  AttributeError: 'NoneType' object has no attribute 'token'
_EXC_REGEX = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_.]*):\s*(.*)$", re.MULTILINE
)


@dataclass
class StackFrame:
    file: str          # raw path as it appears in the traceback
    line: int
    function: str
    path: Path | None = None  # resolved path within the repository, if any
    relative_path: str | None = None  # path relative to repo root


@dataclass
class ParsedTraceback:
    frames: List[StackFrame]
    exception_type: str | None = None
    message: str | None = None
    # Reverse chronological call chain (deepest call last -> outermost first).
    call_chain: List[str] = field(default_factory=list)

    @property
    def deepest_frame(self) -> StackFrame | None:
        # The deepest frame is the last one in the traceback.
        return self.frames[-1] if self.frames else None


def parse_stack_trace(trace: str, repo_root: Path | str | None = None) -> ParsedTraceback:
    """Parse a traceback string into structured data.

    ``repo_root`` is used to resolve frame paths to repository-relative paths.
    """
    root = Path(repo_root).resolve() if repo_root else None

    frames: List[StackFrame] = []
    for match in _FRAME_REGEX.finditer(trace):
        file_str, line_str, func = match.group(1), match.group(2), match.group(3)
        try:
            line_no = int(line_str)
        except ValueError:
            line_no = 0
        path = None
        rel = None
        if root:
            try:
                resolved = Path(file_str).resolve()
                rel = str(resolved.relative_to(root))
                path = resolved
            except (ValueError, OSError):
                # Try treating it as already relative to repo root.
                candidate = (root / file_str).resolve()
                try:
                    if candidate.is_relative_to(root) or file_str.startswith("."):
                        path = candidate
                        rel = file_str
                except (ValueError, OSError):
                    pass
        if rel is not None:
            try:
                rel = Path(rel).as_posix()
            except Exception:
                pass
        frames.append(
            StackFrame(file=file_str, line=line_no, function=func, path=path, relative_path=rel)
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


def _extract_exception(trace: str) -> tuple[str | None, str | None]:
    # Find the last non-indented line that looks like "ExceptionType: message"
    # (exception headers are at column 0 and contain a colon; pydantic field /
    # detail lines are indented or colon-less).
    candidate = None
    for raw in trace.strip().splitlines():
        if not raw.strip() or raw[0] in (" ", "\t"):
            continue
        match = _EXC_REGEX.match(raw)
        if not match:
            continue
        candidate = match
    if not candidate:
        return None, None
    exc_type = candidate.group(1)
    message = (candidate.group(2) or "").strip() or None
    # Drop verbose pydantic error summaries — keep the header concise.
    if "validation error" in message:
        message = message.split("\n")[0]
    return exc_type, message
