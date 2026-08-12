import asyncio
from pathlib import Path
from app.sandbox.sandbox_runner import SandboxRunner
from app.agent.fix_agent import FixProposal

fix = FixProposal(
    summary='test',
    files_changed=['app/demo_api/router.py'],
    diff='''--- a/app/demo_api/router.py
+++ b/app/demo_api/router.py
@@
-    transaction_id = bugs.charge_user(user_id, body.amount)
+    if user.payment_method is None:
+        raise HTTPException(status_code=400, detail="no payment method on file")
+    transaction_id = bugs.charge_user(user_id, body.amount)
''',
    reason='test',
    risk='low',
)
runner = SandboxRunner()

async def main():
    ws = runner.workspace_mgr.create_workspace()
    print('workspace', ws)
    print('workspace file exists', (ws / 'app' / 'demo_api' / 'router.py').exists())
    print('workspace router snippet:')
    lines = (ws / 'app' / 'demo_api' / 'router.py').read_text().splitlines()
    print('\n'.join(lines[70:90]))
    result = runner._run_phase(ws, {'method':'POST','path':'/api/v1/users/user_2/charge','body':{'amount':100.0}}, expect_success=False)
    print('result', result)
    runner.workspace_mgr.cleanup(ws)

asyncio.run(main())
