"""Incident context builder.

Builds a *minimal* context bundle for the LLM. It never sends the whole
repository — only the traceback-derived files, surrounding lines, related
symbols/imports and recent git changes. All secrets are sanitised first.

Improvements for latency:
- Trims stack trace to project-relevant frames only (drops .venv, site-packages,
  starlette, fastapi, uvicorn, etc.).
- Code snippets are trimmed to error-line window (handled in LocalRetriever).
- Total files limited via MAX_CONTEXT_FILES (default 4).
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from app.code_retrieval.local_retriever import LocalRetriever
from app.code_retrieval.semantic_retriever import SemanticRetriever
from app.context_builder.stack_trace_parser import parse_stack_trace, StackFrame
from app.core.config import settings
from app.incidents.models import Incident
from app.security.sanitizer import sanitize

logger = logging.getLogger(__name__)

# Substrings that indicate a frame is from site-packages or framework internals
# and should not be sent to the LLM.
_IGNORED_TRACE_PARTS = {
    "site-packages",
    ".venv",
    "venv",
    "/venv/",
    "starlette",
    "fastapi",
    "uvicorn",
    "anyio",
    "pydantic",
    "httpx",
    "starlite",
    "dist-packages",
    "importlib",
    "asyncio",
    "concurrent",
}


def _is_project_frame(frame: StackFrame) -> bool:
    """True if frame looks like project code (not vendored/framework)."""
    # Must have a relative path inside repo to be considered project-relevant.
    if not frame.relative_path:
        return False
    lower_file = (frame.file or "").lower()
    # Also check relative path
    lower_rel = (frame.relative_path or "").lower()
    for ignored in _IGNORED_TRACE_PARTS:
        if ignored in lower_file or ignored in lower_rel:
            return False
    return True


def _trim_stack_trace(raw_trace: str, frames: list[StackFrame], exception_type: str | None, message: str | None) -> str:
    """Build a minimal stack trace containing only project-relevant frames.

    If no project frames survive filtering, fall back to last N project-adjacent
    lines but still drop obvious venv noise.
    """
    project_frames = [f for f in frames if _is_project_frame(f)]

    # If filtering removed everything, keep at most last 10 frames that are not pure noise
    if not project_frames:
        # keep frames whose path doesn't contain ignored parts (even if not relative)
        filtered = []
        for f in frames:
            low = (f.file or "").lower()
            if any(ig in low for ig in _IGNORED_TRACE_PARTS):
                continue
            filtered.append(f)
        # keep last 10
        project_frames = filtered[-10:] if filtered else frames[-10:]

    # Reconstruct concise trace
    lines = ["Traceback (most recent call last):"]
    for f in project_frames[-20:]:  # cap to 20 frames max
        # Prefer relative path for brevity
        path = f.relative_path or f.file
        lines.append(f'  File "{path}", line {f.line}, in {f.function}')

    if exception_type:
        msg = f": {message}" if message else ""
        lines.append(f"{exception_type}{msg}")
    else:
        # Fall back to last line of original trace if exception not parsed
        try:
            last_line = raw_trace.strip().splitlines()[-1].strip()
            if last_line:
                lines.append(last_line)
        except Exception:
            pass

    return "\n".join(lines)


class ContextBuilder:
    def __init__(
        self,
        repo_root: Path | str | None = None,
        retriever: LocalRetriever | None = None,
        semantic: SemanticRetriever | None = None,
    ) -> None:
        self.repo_root = Path(repo_root or settings.REPO_ROOT).resolve()
        self.retriever = retriever or LocalRetriever(self.repo_root)
        self.semantic = semantic or SemanticRetriever(self.retriever)

    def build(self, incident: Incident) -> dict:
        parsed = parse_stack_trace(incident.stack_trace, self.repo_root)

        # Filter frames to project-relevant before retrieval to cut latency
        project_frames = [f for f in parsed.frames if _is_project_frame(f)]
        # If filtering removed all, use original but we already trimmed aggressively
        frames_for_retrieval = project_frames if project_frames else parsed.frames

        snippets = self.retriever.retrieve(frames_for_retrieval)
        snippets = {s["path"]: dict(s) for s in snippets}

        affected_files = [s["path"] for s in snippets.values()] or [
            f.relative_path for f in frames_for_retrieval if f.relative_path
        ]

        config_refs = self._collect_config_refs(snippets)
        git_log = self._git_log()

        # Trimmed stack trace (project-relevant only)
        trimmed_trace = _trim_stack_trace(
            incident.stack_trace, parsed.frames, parsed.exception_type, parsed.message
        )

        # Logs: trimmed trace lines, capped at 30 for token savings
        log_lines = trimmed_trace.splitlines()[:30]

        context = {
            "incident_id": incident.id,
            "request_snapshot": incident.request_snapshot,
            "logs": log_lines,
            "stack_trace": trimmed_trace,
            "exception_type": parsed.exception_type,
            "exception_message": parsed.message,
            "call_chain": [
                f"{f.relative_path or f.file}:{f.line} in {f.function}"
                for f in frames_for_retrieval
            ][-15:],
            "affected_files": list(dict.fromkeys(affected_files))[: settings.MAX_CONTEXT_FILES],
            "code_snippets": snippets,
            "configuration_references": config_refs,
            "git_log": git_log,
            "project_id": incident.project_id,
        }
        # Secrets must never reach the LLM.
        return sanitize(context)

    # ------------------------------------------------------------------
    def _collect_config_refs(self, snippets: dict) -> list[str]:
        refs: list[str] = []
        for snippet in snippets.values():
            for imp in snippet.get("imports", []):
                if any(k in imp.lower() for k in ("os", "environ", "config", "settings", "getenv")):
                    refs.append(imp)
        return list(dict.fromkeys(refs))

    def _git_log(self, n: int = 5) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(self.repo_root), "log", "--oneline", f"-{n}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip() or "No git history"
        except Exception:
            return "Git not available"

    def build_incident_payload(self, incident: Incident) -> dict:
        """Sanitised serialisable version used for the /context API response."""
        parsed = parse_stack_trace(incident.stack_trace, self.repo_root)
        project_frames = [f for f in parsed.frames if _is_project_frame(f)]
        frames_for_retrieval = project_frames if project_frames else parsed.frames
        return sanitize(
            {
                "incident_id": incident.id,
                "stack_trace": _trim_stack_trace(
                    incident.stack_trace, parsed.frames, parsed.exception_type, parsed.message
                ),
                "affected_files": list(
                    dict.fromkeys(
                        f.relative_path
                        for f in frames_for_retrieval
                        if f.relative_path
                    )
                )[: settings.MAX_CONTEXT_FILES],
                "code_snippets": {
                    s["path"]: dict(s)
                    for s in self.retriever.retrieve(frames_for_retrieval)
                },
                "git_log": self._git_log(),
            }
        )
