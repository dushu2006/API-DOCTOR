import asyncio
import difflib
from unittest.mock import AsyncMock
from app.agent.fix_agent import FixProposal
from app.agent.root_cause_agent import RootCauseAnalysis
from app.incidents.models import IncidentStatus
from app.orchestrator import Orchestrator
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
    orch = Orchestrator()
    incident = await orch.detect_and_create('/api/v1/users/user_2/charge', 'POST', {'amount': 100.0})
    print('incident status', incident.status)
    print('request_snapshot', incident.request_snapshot)
    print('detection status', incident.detection.get('status_code'))
    print('stack_trace starts', incident.stack_trace[:200])
    fix = _null_check_fix()
    print('fix diff:')
    print(fix.diff)
    ws = orch.sandbox_runner.workspace_mgr.create_workspace()
    print('workspace created', ws)
    print('workspace router path', (ws / 'app' / 'demo_api' / 'router.py').exists())
    print('workspace router snippet:')
    print('\n'.join((ws / 'app' / 'demo_api' / 'router.py').read_text().splitlines()[70:90]))
    repro = orch.sandbox_runner._run_phase(ws, incident.request_snapshot, expect_success=False)
    print('repro', repro)
    print('repro ok', repro['ok'])
    print('repro detail', repro['detail'])
    print('repro logs', repro['logs'][:500])
    print('apply patch')
    try:
        affected = orch.sandbox_runner.apply_patch(fix.diff, ws)
        print('affected', affected)
    except Exception as e:
        print('apply_patch failed', type(e), e)
    ws2 = orch.sandbox_runner.workspace_mgr.create_workspace()
    print('workspace2 created', ws2)
    print('workspace2 router snippet:')
    print('\n'.join((ws2 / 'app' / 'demo_api' / 'router.py').read_text().splitlines()[70:90]))
    orch.sandbox_runner.workspace_mgr.cleanup(ws)
    orch.sandbox_runner.workspace_mgr.cleanup(ws2)

asyncio.run(main())
