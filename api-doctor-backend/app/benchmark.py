"""Model benchmark.

Compares the configured NVIDIA models on a small root-cause/patch task without
assuming the largest model is the fastest or best. Exposed as both a CLI
(``python -m app.benchmark``) and an API endpoint.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from pydantic import BaseModel

from app.agent.llm_client import LLMClient
from app.agent.fix_agent import FixProposal
from app.agent.root_cause_agent import RootCauseAnalysis
from app.core.config import settings

SAMPLE_TRACEBACK = (
    'Traceback (most recent call last):\n'
    '  File "app/demo_api/router.py", line 33, in charge\n'
    '    transaction_id = bugs.charge_user(user_id, body.amount)\n'
    '  File "app/demo_api/bugs.py", line 96, in charge_user\n'
    '    token = user.payment_method.token\n'
    "AttributeError: 'NoneType' object has no attribute 'token'"
)

SAMPLE_CONTEXT = {
    "request_snapshot": {"method": "POST", "path": "/api/v1/users/user_2/charge", "body": {"amount": 100}},
    "stack_trace": SAMPLE_TRACEBACK,
    "exception_type": "AttributeError",
    "exception_message": "'NoneType' object has no attribute 'token'",
    "code_snippets": {},
    "git_log": "No git history",
}


class BenchmarkResult(BaseModel):
    model: str
    task: str
    ttft_s: float | None = None
    total_s: float
    output_len: int
    success: bool
    error: str | None = None
    confidence: float | None = None
    correct: bool | None = None


async def run_benchmark(task: str = "root_cause") -> list[BenchmarkResult]:
    client = LLMClient()
    results: list[BenchmarkResult] = []
    models = {
        "root_cause": settings.INVESTIGATOR_MODEL,
        "patch": settings.CODER_MODEL,
    }
    model = models.get(task, settings.FAST_MODEL)

    start = time.perf_counter()
    try:
        if task == "patch":
            rc = RootCauseAnalysis(
                root_cause="user.payment_method is None; accessing .token raises AttributeError",
                category="CODE_BUG",
                confidence=0.9,
                affected_files=["app/demo_api/bugs.py"],
                affected_functions=["charge_user"],
                safe_to_repair=True,
                reason="missing null guard",
            )
            from app.agent.fix_agent import FixAgent

            proposal = await FixAgent(client).generate_fix(rc, {"app/demo_api/bugs.py": SAMPLE_TRACEBACK})
            correct = proposal.diff is not None and ("None" in proposal.diff or "if " in proposal.diff)
            results.append(
                BenchmarkResult(
                    model=model, task=task, total_s=time.perf_counter() - start,
                    output_len=len(proposal.diff), success=True, correct=correct,
                )
            )
        else:
            analysis = await RootCauseAgent(client).analyze(SAMPLE_CONTEXT)
            correct = analysis.category == "CODE_BUG" and analysis.confidence >= 0.5
            results.append(
                BenchmarkResult(
                    model=model, task=task, total_s=time.perf_counter() - start,
                    output_len=len(analysis.root_cause), success=True,
                    confidence=analysis.confidence, correct=correct,
                )
            )
    except Exception as exc:  # noqa: BLE001
        results.append(
            BenchmarkResult(
                model=model, task=task, total_s=time.perf_counter() - start,
                output_len=0, success=False, error=str(exc),
            )
        )
    return results


async def main() -> None:
    for task in ("root_cause", "patch"):
        results = await run_benchmark(task)
        for r in results:
            print(r.model_dump())


if __name__ == "__main__":
    asyncio.run(main())
