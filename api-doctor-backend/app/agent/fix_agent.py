"""Stage 2 — Fix generation agent (minimal structured patch / unified diff)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.agent.llm_client import LLMClient
from app.agent.root_cause_agent import RootCauseAnalysis
from app.core.config import settings


class FilePatch(BaseModel):
    path: str
    patch: str = ""
    reason: str = ""


class FixProposal(BaseModel):
    summary: str = Field(..., description="One-line summary of the change.")
    files_changed: list[str] = Field(
        default_factory=list, description="Relative paths of files changed."
    )
    files: list[FilePatch] = Field(
        default_factory=list, description="Structured list of per-file changes."
    )
    diff: str = Field(default="", description="A single unified diff covering all changes.")
    reason: str = Field(default="", description="Why this diff fixes the root cause.")
    risk: Literal["low", "medium", "high"] = Field(
        default="low", description="Estimated risk of the change."
    )

    @model_validator(mode="before")
    @classmethod
    def _sync_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # If files list is provided but not diff, construct diff
            files_list = data.get("files")
            diff_str = data.get("diff", "")
            files_changed = data.get("files_changed") or []

            if files_list and isinstance(files_list, list):
                if not files_changed:
                    data["files_changed"] = [f.get("path") for f in files_list if isinstance(f, dict) and f.get("path")]
                if not diff_str:
                    diff_parts = []
                    for f in files_list:
                        if isinstance(f, dict) and f.get("patch"):
                            diff_parts.append(f["patch"])
                    data["diff"] = "\n".join(diff_parts)

            if diff_str and not files_list:
                # If diff is provided, populate files_changed if empty
                if not files_changed:
                    detected: list[str] = []
                    for line in diff_str.splitlines():
                        if line.startswith("--- a/") or line.startswith("+++ b/"):
                            p = line[6:].strip()
                            if p and p not in detected:
                                detected.append(p)
                    data["files_changed"] = detected
        return data


SYSTEM_PROMPT = """You are a staff engineer writing a minimal, safe patch for a real production repository.

Constraints:
1. Produce ONE unified diff (standard diff -u format, hunk headers @@ -a,b +c,d @@).
2. Make the smallest possible change. Never rewrite whole files.
3. No style-only changes. Only add imports if required for the fix.
4. Preserve existing behaviour for all unrelated cases.
5. The diff MUST apply cleanly with patch -p1.
6. Diff paths must be relative to the repository root (e.g. app/services/payment.py).

Respond ONLY with valid JSON matching EXACTLY this shape:
{
  "summary": "Add null check for payment_method before accessing token",
  "files_changed": ["app/services/payment.py"],
  "files": [
    {
      "path": "app/services/payment.py",
      "patch": "--- a/app/services/payment.py\\n+++ b/app/services/payment.py\\n@@ -120,3 +120,5 @@\\n-    token = user.payment_method.token\\n+    if user.payment_method is None:\\n+        token = None\\n+    else:\\n+        token = user.payment_method.token\\n",
      "reason": "Prevent AttributeError when payment_method is None"
    }
  ],
  "diff": "--- a/app/services/payment.py\\n+++ b/app/services/payment.py\\n@@ -120,3 +120,5 @@\\n-    token = user.payment_method.token\\n+    if user.payment_method is None:\\n+        token = None\\n+    else:\\n+        token = user.payment_method.token\\n",
  "reason": "user.payment_method can be None; accessing .token crashes with AttributeError",
  "risk": "low"
}
Inside the diff/patch strings: use \\n for newlines and \\" for quotes. Never use HTML entities and never unescaped literal newlines."""


class FixAgent:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.client = llm_client or LLMClient()

    async def generate_fix(
        self,
        root_cause: RootCauseAnalysis,
        files: dict[str, str],
        project_profile: Any = None,
        feedback: str | None = None,
    ) -> FixProposal:
        user_prompt = self._build_prompt(root_cause, files, project_profile, feedback)
        return await self.client.generate_structured(
            response_model=FixProposal,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=settings.CODER_MODEL,
            temperature=0.0,
        )

    def _build_prompt(
        self,
        rc: RootCauseAnalysis,
        files: dict[str, str],
        project_profile: Any = None,
        feedback: str | None = None,
    ) -> str:
        blocks = []
        for rel, content in files.items():
            blocks.append(f"\n### File: {rel}\n```\n{content}\n```")

        prof_txt = ""
        if project_profile:
            import json
            p_data = project_profile.model_dump() if hasattr(project_profile, "model_dump") else project_profile
            prof_txt = f"\n## Project Profile\n```json\n{json.dumps(p_data, indent=2)}\n```\n"

        parts = [
            "## Root cause analysis",
            f"classification: {rc.classification}",
            f"confidence: {rc.confidence}",
            f"root cause: {rc.root_cause}",
            f"affected files: {rc.affected_files}",
            f"affected lines: {rc.affected_lines}",
            f"affected functions: {rc.affected_functions}",
            f"recommended action: {rc.recommended_action}",
            prof_txt,
            "## Relevant file content",
            "".join(blocks) or "(no files supplied)",
            "",
            "## Task",
            "Generate a minimal patch (relative repo paths) that fixes this root cause.",
        ]
        if feedback:
            parts += [
                "",
                "## Previous attempt failed verification — feedback",
                feedback,
                "Revise the patch so the reproduction and tests pass cleanly.",
            ]
        return "\n".join(parts)
