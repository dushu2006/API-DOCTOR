"""Stage 1 — Root cause analysis agent."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field, model_validator

from app.agent.llm_client import LLMClient
from app.core.config import settings


class RootCauseAnalysis(BaseModel):
    root_cause: str = Field(..., description="Technical explanation of WHY it broke.")
    classification: str = Field(
        default="CODE_BUG",
        description=(
            "One of: CODE_BUG, CONFIGURATION, DATABASE, EXTERNAL_SERVICE, DEPENDENCY, UNKNOWN"
        ),
    )
    category: str = Field(
        default="CODE_BUG",
        description="Category classification alias for backward compatibility.",
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="0.0-1.0 confidence score.")
    affected_files: list[str] = Field(
        default_factory=list, description="Relative paths of files implicated."
    )
    affected_lines: list[int] = Field(
        default_factory=list, description="Line numbers implicated."
    )
    affected_functions: list[str] = Field(
        default_factory=list, description="Function names implicated."
    )
    evidence: list[str] = Field(
        default_factory=list, description="Concrete evidence observed from stack trace and logs."
    )
    recommended_action: str = Field(
        default="", description="Recommended remediation action."
    )
    safe_to_repair: bool = Field(
        default=True, description="Whether an automated minimal repair appears safe."
    )
    reason: str = Field(
        default="", description="Short justification for safe_to_repair / confidence."
    )

    @model_validator(mode="before")
    @classmethod
    def _sync_category_and_classification(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Normalize category and classification
            cat = data.get("category")
            cls_field = data.get("classification")
            if cls_field and not cat:
                data["category"] = cls_field
            elif cat and not cls_field:
                # Normalize legacy strings like CONFIGURATION_ERROR -> CONFIGURATION
                norm = cat.replace("_ERROR", "").replace("_FAILURE", "")
                data["classification"] = norm if norm in {"CODE_BUG", "CONFIGURATION", "DATABASE", "EXTERNAL_SERVICE", "DEPENDENCY", "UNKNOWN"} else "CODE_BUG"
            elif not cat and not cls_field:
                data["classification"] = "CODE_BUG"
                data["category"] = "CODE_BUG"
        return data


SYSTEM_PROMPT = """You are a senior principal backend engineer diagnosing a real production API failure.

You are given:
1. The HTTP request / error snapshot.
2. The full stack trace.
3. Implicated source code snippets from the project repository.
4. Project profile and recent git history.

Identify the exact root cause. Reference specific files and line numbers from the
provided snippets. Be precise and concise. Classify the failure into one of:
CODE_BUG | CONFIGURATION | DATABASE | EXTERNAL_SERVICE | DEPENDENCY | UNKNOWN.

Do not attempt to directly modify files.

Respond ONLY with valid JSON matching EXACTLY this schema:
{
  "classification": "CODE_BUG",
  "root_cause": "Detailed technical root cause",
  "confidence": 0.95,
  "affected_files": ["app/services/payment.py"],
  "affected_lines": [121],
  "affected_functions": ["process_payment"],
  "evidence": ["AttributeError on line 121"],
  "recommended_action": "Add null check before accessing token",
  "safe_to_repair": true,
  "reason": "Deterministic null check bug"
}"""


class RootCauseAgent:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.client = llm_client or LLMClient()

    async def analyze(self, context: dict) -> RootCauseAnalysis:
        user_prompt = self._build_prompt(context)
        return await self.client.generate_structured(
            response_model=RootCauseAnalysis,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=settings.INVESTIGATOR_MODEL,
        )

    def _build_prompt(self, context: dict) -> str:
        snippets = context.get("code_snippets") or {}
        snippet_txt = []
        for rel, data in snippets.items():
            if isinstance(data, dict):
                content = data.get("content", "")
                line = data.get("error_line")
                funcs = data.get("functions", [])
                snippet_txt.append(
                    f"\n### File: {rel} (error near line {line}; funcs={funcs})\n"
                    f"```\n{content}\n```"
                )

        prof = context.get("project_profile")
        prof_txt = _fmt(prof) if prof else "(not available)"

        return "\n".join(
            [
                "## Request / Error snapshot",
                _fmt(context.get("request_snapshot")),
                "",
                "## Stack trace",
                str(context.get("stack_trace", "")),
                "",
                "## Implicated source",
                "".join(snippet_txt) or "(none retrieved)",
                "",
                "## Project Profile",
                prof_txt,
                "",
                "## Git history",
                str(context.get("git_log") or "(none)"),
            ]
        )


def _fmt(obj: Any) -> str:
    import json

    if isinstance(obj, (dict, list)):
        return json.dumps(obj, indent=2, default=str)
    return str(obj)
