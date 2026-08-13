"""End-to-end test: failure -> diagnosis -> fix -> sandbox -> verification.

The AI agents are mocked (no real NVIDIA key in CI), but the detector, context
builder, and sandbox all run for real in local mode.
"""

from __future__ import annotations

import difflib
from unittest.mock import AsyncMock

from app.agent.fix_agent import FixProposal
from app.agent.root_cause_agent import RootCauseAnalysis
from app.core.config import settings
from app.runs.models import RunStatus
from app.runs.store import run_store
from app.orchestrator import Orchestrator


async def _await_started(orch: Orchestrator, run_id: str):
    task = orch._pipeline_tasks.get(run_id)
    if task:
        return await task
    return run_store.get(run_id)


async def _drive_pipeline(orch: Orchestrator, run_id: str):
    """Run the pipeline through interactive approval gates."""
    result = await orch.run_pipeline(run_id)
    if result and result.status == RunStatus.AWAITING_FILE_READ_APPROVAL:
        assert await orch.resume_file_read(run_id)
        result = await _await_started(orch, run_id)
    if result and result.status == RunStatus.AWAITING_FIX_APPROVAL:
        assert await orch.resume_fix(run_id)
        result = await _await_started(orch, run_id)
    return result

ORIGINAL_MARKER = (
    '    transaction_id = bugs.charge_user(user_id, body.amount)\n'
    '    return {"success": True, "transaction_id": transaction_id}\n'
)
FIXED_MARKER = (
    '    if user.payment_method is None:\n'
    '        raise HTTPException(status_code=400, detail="no payment method on file")\n'
    '    transaction_id = bugs.charge_user(user_id, body.amount)\n'
    '    return {"success": True, "transaction_id": transaction_id}\n'
)


def _null_check_fix() -> FixProposal:
    path = settings.INTERNAL_REPO_ROOT + "/app/demo_api/router.py"
    original = open(path).read()
    fixed = original.replace(ORIGINAL_MARKER, FIXED_MARKER, 1)
    diff = "\n".join(
        difflib.unified_diff(
            original.splitlines(), fixed.splitlines(),
            fromfile="a/app/demo_api/router.py",
            tofile="b/app/demo_api/router.py",
            lineterm="",
        )
    ) + "\n"
    return FixProposal(
        summary="Gracefully handle missing payment method",
        files_changed=["app/demo_api/router.py"],
        diff=diff,
        reason="Return 400 instead of crashing when payment_method is None",
        risk="low",
    )


async def test_e2e_null_pointer(monkeypatch):
    orch = Orchestrator()

    # 1. Real detection.
    run = await orch.detect_and_create(
        "/api/v1/users/user_2/charge", "POST", {"amount": 100.0}
    )
    assert run.status == RunStatus.DETECTED

    # 2-3. Real context build; mock the AI agents (no API key in CI).
    monkeypatch.setattr(
        orch.root_cause_agent, "analyze",
        AsyncMock(return_value=RootCauseAnalysis(
            root_cause="missing null guard on user.payment_method",
            category="CODE_BUG",
            confidence=0.9,
            affected_files=["app/demo_api/bugs.py", "app/demo_api/router.py"],
            affected_functions=["charge_user", "charge"],
            safe_to_repair=True,
            reason="deterministic null pointer",
        )),
    )
    monkeypatch.setattr(
        orch.fix_agent, "generate_fix", AsyncMock(return_value=_null_check_fix())
    )

    # 4-7. Run the full pipeline with a real sandbox verification.
    result = await _drive_pipeline(orch, run.id)

    assert result.status == RunStatus.FIX_VERIFIED
    assert result.sandbox_result["passed"] is True
    step_names = {s["name"]: s["passed"] for s in result.sandbox_result["steps"]}
    assert step_names["reproduce_failure"] is True
    assert step_names["apply_patch"] is True
    assert step_names["verify_fix"] is True
    assert run_store.get(run.id).attempt_count >= 1


async def test_e2e_null_pointer_with_mock_ai():
    """Full pipeline using MockAIClient (the no-key AI_PROVIDER=auto path).

    This is the auto_trigger.py flow: detect the charge 500, generate a
    mock fix, apply it in the sandbox, and verify the crash is gone.
    """
    orch = Orchestrator()
    old_tests = settings.REQUIRE_TESTS
    settings.REQUIRE_TESTS = False
    try:
        run = await orch.detect_and_create(
            "/api/v1/users/user_2/charge", "POST", {"amount": 100.0}
        )
        result = await _drive_pipeline(orch, run.id)
    finally:
        settings.REQUIRE_TESTS = old_tests

    assert result is not None
    assert result.status == RunStatus.FIX_VERIFIED, (
        f"expected FIX_VERIFIED, got {result.status}: {result.error_message}"
    )
    assert result.fix_proposal and result.fix_proposal.get("diff")
    assert result.sandbox_result["passed"] is True
    step_names = {s["name"]: s["passed"] for s in result.sandbox_result["steps"]}
    assert step_names["reproduce_failure"] is True
    assert step_names["apply_patch"] is True
    assert step_names["verify_fix"] is True
