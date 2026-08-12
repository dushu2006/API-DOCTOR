import difflib
import os
from unittest.mock import AsyncMock
from app.agent.fix_agent import FixProposal
from app.agent.root_cause_agent import RootCauseAnalysis
from app.core.config import settings
from app.incidents.models import IncidentStatus
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
    original = open(path, encoding='utf-8').read()
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


async def main():
    print('sandbox mode:', settings.SANDBOX_MODE)
    print('repo root:', settings.REPO_ROOT)
    orch = Orchestrator()
    incident = await orch.detect_and_create(
        "/api/v1/users/user_2/charge", "POST", {"amount": 100.0}
    )
    print('incident status after detect:', incident.status)
    monkeypatch = None
    # monkeypatch with AsyncMock by directly assigning attributes
    orch.root_cause_agent.analyze = AsyncMock(return_value=RootCauseAnalysis(
        root_cause="missing null guard on user.payment_method",
        category="CODE_BUG",
        confidence=0.9,
        affected_files=["app/demo_api/bugs.py", "app/demo_api/router.py"],
        affected_functions=["charge_user", "charge"],
        safe_to_repair=True,
        reason="deterministic null pointer",
    ))
    orch.fix_agent.generate_fix = AsyncMock(return_value=_null_check_fix())
    result = await orch.run_pipeline(incident.id)
    print('result status:', result.status)
    print('attempt count:', result.attempt_count)
    print('sandbox_result:', result.sandbox_result)
    if result.sandbox_result:
        for step in result.sandbox_result.get('steps', []):
            print('STEP', step['name'], 'passed=', step['passed'], 'detail=', step['detail'])
    if result.sandbox_result and result.sandbox_result.get('error'):
        print('error:', result.sandbox_result['error'])


import asyncio
asyncio.run(main())
