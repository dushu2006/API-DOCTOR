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
1. Produce ONE unified diff (standard diff -u format, hunk headers @@ -a,b +c,d @@).
2. Make the smallest possible change. Never rewrite whole files.
3. No style-only changes. Only add imports if required for the fix.
4. Preserve behaviour for all unrelated cases.
5. The diff MUST apply cleanly with patch -p1.
6. Diff paths must be relative to the repository root (e.g. app/demo_api/bugs.py).

Respond ONLY with valid JSON matching EXACTLY this shape (top-level keys:
summary, files_changed, diff, reason, risk). Do NOT return a mapping of
file paths to diffs -- always use this exact structure:
{
  "summary": "Add null check for payment_method before accessing .token",
  "files_changed": ["app/demo_api/bugs.py"],
  "diff": "--- a/app/demo_api/bugs.py\\n+++ b/app/demo_api/bugs.py\\n@@ -118,3 +118,5 @@\\n     user = get_user(user_id)\\n-    token = user.payment_method.token\\n+    if user.payment_method is None:\\n+        raise ValueError(\\"no payment method\\")\\n+    token = user.payment_method.token\\n",
  "reason": "user.payment_method can be None; accessing .token crashes with AttributeError",
  "risk": "low"
}
Inside the diff string: use \\n for every newline and \\" for every double
quote. NEVER use HTML entities (no &#10;, no &quot;, no &amp;) and never a
literal unescaped newline or quote inside the JSON string."""


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
