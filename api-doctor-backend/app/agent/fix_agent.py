"""Stage 2 — Fix generation agent (minimal unified diff)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.agent.llm_client import LLMClient
from app.core.config import settings


class FixProposal(BaseModel):
    summary: str = Field(..., description="One-line summary of the change.")
    files_changed: list[str] = Field(
        default_factory=list, description="Relative paths of files changed."
    )
    diff: str = Field(..., description="A single unified diff covering all changes.")
    reason: str = Field(..., description="Why this diff fixes the root cause.")
    risk: Literal["low", "medium", "high"] = Field(
        ..., description="Estimated risk of the change."
    )


SYSTEM_PROMPT = """You are a staff engineer writing a minimal, safe patch.

Constraints:
1. Produce ONE unified diff (standard `diff -u` format, hunk headers `@@ -a,b +c,d @@`).
2. Make the smallest possible change. Never rewrite whole files.
3. No style-only changes. Only add imports if required for the fix.
4. Preserve behaviour for all unrelated cases.
5. The diff MUST apply cleanly with `patch -p1`.
6. Diff paths must be relative to the repository root (e.g. `app/demo_api/bugs.py`).

Respond ONLY with valid JSON matching the schema (double-quoted keys and strings — never single quotes, never a Python dict literal). Escape all newlines in the diff field as \\n. Do not wrap the diff value in its own markdown code fence."""


class FixAgent:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.client = llm_client or LLMClient()

    async def generate_fix(
        self,
        root_cause: RootCauseAnalysis,
        files: dict[str, str],
        feedback: str | None = None,
    ) -> FixProposal:
        user_prompt = self._build_prompt(root_cause, files, feedback)
        return await self.client.generate_structured(
            response_model=FixProposal,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=settings.CODER_MODEL,
            temperature=0.0,
        )

    def _build_prompt(
        self, rc: RootCauseAnalysis, files: dict[str, str], feedback: str | None = None
    ) -> str:
        blocks = []
        for rel, content in files.items():
            blocks.append(f"\n### File: {rel}\n```python\n{content}\n```")
        parts = [
            "## Root cause analysis",
            f"category: {rc.category}",
            f"confidence: {rc.confidence}",
            f"root cause: {rc.root_cause}",
            f"affected files: {rc.affected_files}",
            f"affected functions: {rc.affected_functions}",
            "",
            "## Full file content",
            "".join(blocks) or "(no files supplied)",
            "",
            "## Task",
            "Generate a minimal unified diff (relative repo paths) that fixes "
            "this root cause.",
        ]
        if feedback:
            parts += [
                "",
                "## Previous attempt failed verification — feedback",
                feedback,
                "Revise the diff so the reproduction test passes.",
            ]
        return "\n".join(parts)
