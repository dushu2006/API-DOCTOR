"""Stage 1 — Root cause analysis agent."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent.llm_client import LLMClient
from app.core.config import settings


class RootCauseAnalysis(BaseModel):
    root_cause: str = Field(..., description="Technical explanation of WHY it broke.")
    category: str = Field(
        ...,
        description=(
            "One of: CODE_BUG, CONFIGURATION_ERROR, ENVIRONMENT_ERROR, "
            "DEPENDENCY_ERROR, EXTERNAL_API_FAILURE, DATABASE_FAILURE, "
            "DEPLOYMENT_FAILURE, AUTHENTICATION_FAILURE, NETWORK_FAILURE, UNKNOWN"
        ),
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="0.0-1.0 confidence.")
    affected_files: list[str] = Field(
        default_factory=list, description="Relative paths of files implicated."
    )
    affected_functions: list[str] = Field(
        default_factory=list, description="Function names implicated."
    )
    safe_to_repair: bool = Field(
        ..., description="Whether an automated minimal repair appears safe."
    )
    reason: str = Field(
        ..., description="Short justification for safe_to_repair / confidence."
    )


SYSTEM_PROMPT = """You are a senior backend engineer diagnosing a production API failure.

You are given:
1. The HTTP request that triggered the failure.
2. The full stack trace.
3. The implicated source code (with line numbers).
4. Recent git history.

Identify the exact root cause. Reference specific files and line numbers from the
provided snippets. Be precise and concise. Classify the failure into one of the
given categories. Lower confidence when important context is missing.

Respond ONLY with valid JSON matching the schema."""


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
                    f"```python\n{content}\n```"
                )
        return "\n".join(
            [
                "## Request",
                _fmt(context.get("request_snapshot")),
                "",
                "## Stack trace",
                str(context.get("stack_trace", "")),
                "",
                "## Implicated source",
                "".join(snippet_txt) or "(none retrieved)",
                "",
                "## Git history",
                str(context.get("git_log") or "(none)"),
            ]
        )


def _fmt(obj) -> str:
    import json

    if isinstance(obj, (dict, list)):
        return json.dumps(obj, indent=2, default=str)
    return str(obj)
