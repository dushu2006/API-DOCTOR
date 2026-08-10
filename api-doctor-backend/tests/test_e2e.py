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
from app.incidents.models import IncidentStatus
from app.incidents.store import incident_store
from app.orchestrator import Orchestrator

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
    path = settings.REPO_ROOT + "/app/demo_api/router.py"
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
    incident = await orch.detect_and_create(
        "/api/v1/users/user_2/charge", "POST", {"amount": 100.0}
    )
    assert incident.status == IncidentStatus.DETECTED

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
    result = await orch.run_pipeline(incident.id)

    assert result.status == IncidentStatus.FIX_VERIFIED
    assert result.sandbox_result["passed"] is True
    step_names = {s["name"]: s["passed"] for s in result.sandbox_result["steps"]}
    assert step_names["reproduce_failure"] is True
    assert step_names["apply_patch"] is True
    assert step_names["verify_fix"] is True
    assert incident_store.get(incident.id).attempt_count >= 1
