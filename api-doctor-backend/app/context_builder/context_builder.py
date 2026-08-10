"""Incident context builder.

Builds a *minimal* context bundle for the LLM. It never sends the whole
repository — only the traceback-derived files, surrounding lines, related
symbols/imports and recent git changes. All secrets are sanitised first.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from app.code_retrieval.local_retriever import LocalRetriever
from app.code_retrieval.semantic_retriever import SemanticRetriever
from app.context_builder.stack_trace_parser import parse_stack_trace
from app.core.config import settings
from app.incidents.models import Incident
from app.security.sanitizer import sanitize

logger = logging.getLogger(__name__)


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
        snippets = self.retriever.retrieve(parsed.frames)
        snippets = {s["path"]: dict(s) for s in snippets}

        affected_files = [s["path"] for s in snippets.values()] or [
            f.relative_path for f in parsed.frames if f.relative_path
        ]

        config_refs = self._collect_config_refs(snippets)
        git_log = self._git_log()

        context = {
            "incident_id": incident.id,
            "request_snapshot": incident.request_snapshot,
            "logs": incident.stack_trace.splitlines()[:60],
            "stack_trace": incident.stack_trace,
            "exception_type": parsed.exception_type,
            "exception_message": parsed.message,
            "call_chain": parsed.call_chain,
            "affected_files": list(dict.fromkeys(affected_files)),
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
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() or "No git history"
        except Exception:
            return "Git not available"

    def build_incident_payload(self, incident: Incident) -> dict:
        """Sanitised serialisable version used for the /context API response."""
        return sanitize(
            {
                "incident_id": incident.id,
                "stack_trace": incident.stack_trace,
                "affected_files": list(dict.fromkeys(
                    f.relative_path for f in parse_stack_trace(incident.stack_trace, self.repo_root).frames if f.relative_path
                )),
                "code_snippets": {
                    s["path"]: dict(s) for s in self.retriever.retrieve(
                        parse_stack_trace(incident.stack_trace, self.repo_root).frames
                    )
                },
                "git_log": self._git_log(),
            }
        )
