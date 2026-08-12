import asyncio
import difflib
from unittest.mock import AsyncMock
from app.agent.fix_agent import FixProposal
from app.agent.root_cause_agent import RootCauseAnalysis
from app.incidents.models import IncidentStatus
from app.orchestrator import Orchestrator
from app.sandbox.sandbox_runner import SandboxRunner
from app.sandbox.workspace_manager import WorkspaceManager
from app.core.config import settings
from pathlib import Path

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
    original = Path(path).read_text(encoding='utf-8')
    fixed = original.replace(ORIGINAL_MARKER, FIXED_MARKER, 1)
    diff = "\n".join(
        difflib.unified_diff(
            original.splitlines(), fixed.splitlines(),
            fromfile='a/app/demo_api/router.py',
            tofile='b/app/demo_api/router.py',
            lineterm='',
        )
    ) + "\n"
    return FixProposal(
        summary='Gracefully handle missing payment method',
        files_changed=['app/demo_api/router.py'],
        diff=diff,
        reason='Return 400 instead of crashing when payment_method is None',
        risk='low',
    )

async def main():
    print('repo root:', settings.REPO_ROOT)
    orch = Orchestrator()
    incident = await orch.detect_and_create('/api/v1/users/user_2/charge', 'POST', {'amount': 100.0})
    print('incident detection status:', incident.status)
    print('stack_trace present:', bool(incident.stack_trace))
    orch.root_cause_agent.analyze = AsyncMock(return_value=RootCauseAnalysis(
        root_cause='missing null guard on user.payment_method',
        category='CODE_BUG',
        confidence=0.9,
        affected_files=['app/demo_api/bugs.py', 'app/demo_api/router.py'],
        affected_functions=['charge_user', 'charge'],
        safe_to_repair=True,
        reason='deterministic null pointer',
    ))
    orch.fix_agent.generate_fix = AsyncMock(return_value=_null_check_fix())
    result = await orch.run_pipeline(incident.id)
    print('pipeline result status:', result.status)
    print('attempt_count', result.attempt_count)
    print('sandbox_result', result.sandbox_result)
    if result.sandbox_result:
        for step in result.sandbox_result.get('steps', []):
            print('step', step['name'], step['passed'], step['detail'])
    print('--- sandbox workspace root ---')
    ws = orch.sandbox_runner.workspace_mgr.create_workspace()
    print('workspace', ws)
    print((ws / 'app' / 'demo_api' / 'router.py').read_text().splitlines()[70:90])
    repro = orch.sandbox_runner._run_phase(ws, incident.request_snapshot, expect_success=False)
    print('direct repro:', repro)
    orch.sandbox_runner.workspace_mgr.cleanup(ws)

asyncio.run(main())
