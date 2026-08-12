"""Incident context builder.

Builds a minimal, repository-aware context bundle for the LLM using the synchronized
GitHub project workspace. Retrieves only required files (exact stack-trace file,
calling functions, imported modules, related configs, tests, dependencies, and profile).
Sanitizes all secrets.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

from app.code_retrieval.local_retriever import LocalRetriever
from app.code_retrieval.semantic_retriever import SemanticRetriever
from app.context_builder.stack_trace_parser import parse_stack_trace, StackFrame
from app.core.config import settings
from app.incidents.models import Incident
from app.security.sanitizer import sanitize

logger = logging.getLogger(__name__)

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
    "node_modules",
}


def _is_project_frame(frame: StackFrame) -> bool:
    """True if frame looks like project code (not vendored/framework)."""
    if not frame.path or not frame.relative_path:
        return False
    lower_file = (frame.file or "").lower()
    lower_rel = (frame.relative_path or "").lower()
    for ignored in _IGNORED_TRACE_PARTS:
        if ignored in lower_file or ignored in lower_rel:
            return False
    return True


def _trim_stack_trace(raw_trace: str, frames: list[StackFrame], exception_type: str | None, message: str | None) -> str:
    """Build a minimal stack trace containing project-relevant frames."""
    project_frames = [f for f in frames if _is_project_frame(f)]

    if not project_frames:
        filtered = []
        for f in frames:
            low = (f.file or "").lower()
            if any(ig in low for ig in _IGNORED_TRACE_PARTS):
                continue
            filtered.append(f)
        project_frames = filtered[-10:] if filtered else frames[-10:]

    lines = ["Traceback (most recent call last):"]
    for f in project_frames[-20:]:
        path = f.relative_path or f.file
        lines.append(f'  File "{path}", line {f.line}, in {f.function}')

    if exception_type:
        msg = f": {message}" if message else ""
        lines.append(f"{exception_type}{msg}")
    else:
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
        self.repo_root = Path(repo_root or settings.INTERNAL_REPO_ROOT).resolve()
        self.retriever = retriever or LocalRetriever(self.repo_root)
        self.semantic = semantic or SemanticRetriever(self.retriever)

    def set_repo_root(self, repo_root: Path | str) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.retriever.set_repo_root(self.repo_root)

    def identify_files(self, incident: Incident, project_profile: Any = None) -> list[str]:
        """Identify relevant file paths WITHOUT reading their contents.

        This powers the honest two-phase workflow: first the agent names the
        files it wants to read (and the user approves), then the files are
        actually read one by one. Falls back to locating the project's primary
        entrypoint modules when the stack trace names no resolvable files.
        """
        parsed = parse_stack_trace(incident.stack_trace, self.repo_root)
        project_frames = [f for f in parsed.frames if _is_project_frame(f)]
        frames = project_frames if project_frames else parsed.frames

        files: list[str] = []
        for frame in frames:
            rel = frame.relative_path or self.retriever._to_relative(frame.file)
            if not rel:
                continue
            path = self.repo_root / rel
            if not path.is_file() or self.retriever._ignored(rel):
                cand = self.retriever._find_by_name(Path(rel).name)
                if cand:
                    rel = self.retriever._to_relative(str(cand)) or rel
            if not (self.repo_root / rel).is_file() or self.retriever._ignored(rel):
                continue
            if rel not in files:
                files.append(rel)
            if len(files) >= settings.MAX_CONTEXT_FILES:
                return files

        if not files:
            files = self._identify_entrypoints(project_profile)
        return files[: settings.MAX_CONTEXT_FILES]

    def _identify_entrypoints(self, project_profile: Any = None) -> list[str]:
        """Locate primary application modules when no trace frames resolve."""
        candidates: list[str] = []
        entrypoint = getattr(project_profile, "entrypoint", None)
        if entrypoint:
            candidates.append(str(entrypoint))
        candidates.extend(
            [
                "app/main.py",
                "main.py",
                "src/main.py",
                "server.py",
                "app.py",
                "src/index.js",
                "src/index.ts",
                "index.js",
                "src/App.jsx",
                "src/App.tsx",
            ]
        )
        found: list[str] = []
        for rel in candidates:
            if (self.repo_root / rel).is_file() and rel not in found:
                found.append(rel)
            if len(found) >= 3:
                break
        return found

    def parse_trace(self, incident: Incident) -> Any:
        """Parse the incident stack trace (exposed for live progress events)."""
        return parse_stack_trace(incident.stack_trace, self.repo_root)

    def build(self, incident: Incident, project_profile: Any = None) -> dict:
        parsed = parse_stack_trace(incident.stack_trace, self.repo_root)

        project_frames = [f for f in parsed.frames if _is_project_frame(f)]
        frames_for_retrieval = project_frames if project_frames else parsed.frames

        snippets = self.retriever.retrieve(frames_for_retrieval, project_profile=project_profile)
        snippet_map = {s["path"]: dict(s) for s in snippets}

        affected_files = [s["path"] for s in snippets] or [
            f.relative_path for f in frames_for_retrieval if f.relative_path
        ]

        config_refs = self._collect_config_refs(snippet_map)
        git_log = self._git_log()

        trimmed_trace = _trim_stack_trace(
            incident.stack_trace, parsed.frames, parsed.exception_type, parsed.message
        )
        log_lines = trimmed_trace.splitlines()[:30]

        context = {
            "incident_id": incident.id,
            "project_id": incident.project_id,
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
            "code_snippets": snippet_map,
            "configuration_references": config_refs,
            "git_log": git_log,
            "project_profile": project_profile.model_dump() if hasattr(project_profile, "model_dump") else project_profile,
        }
        return sanitize(context)

    # ------------------------------------------------------------------
    def _collect_config_refs(self, snippets: dict) -> list[str]:
        refs: list[str] = []
        for snippet in snippets.values():
            for imp in snippet.get("imports", []):
                if any(k in imp.lower() for k in ("os", "environ", "config", "settings", "getenv", "dotenv")):
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
        """Sanitized serializable version used for the /context API response."""
        parsed = parse_stack_trace(incident.stack_trace, self.repo_root)
        project_frames = [f for f in parsed.frames if _is_project_frame(f)]
        frames_for_retrieval = project_frames if project_frames else parsed.frames
        return sanitize(
            {
                "incident_id": incident.id,
                "stack_trace": _trim_stack_trace(
                    incident.stack_trace, parsed.frames, parsed.exception_type, parsed.message
                ),
                "implicated_files": list(
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
