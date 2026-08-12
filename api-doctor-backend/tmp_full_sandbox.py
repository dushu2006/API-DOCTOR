import asyncio
import difflib
from app.agent.fix_agent import FixProposal
from app.sandbox.sandbox_runner import SandboxRunner

original = open('app/demo_api/router.py', encoding='utf-8').read()
ORIGINAL_MARKER = '    transaction_id = bugs.charge_user(user_id, body.amount)\n    return {"success": True, "transaction_id": transaction_id}\n'
FIXED_MARKER = '    if user.payment_method is None:\n        raise HTTPException(status_code=400, detail="no payment method on file")\n    transaction_id = bugs.charge_user(user_id, body.amount)\n    return {"success": True, "transaction_id": transaction_id}\n'
fixed = original.replace(ORIGINAL_MARKER, FIXED_MARKER, 1)
diff = "\n".join(difflib.unified_diff(original.splitlines(), fixed.splitlines(), fromfile='a/app/demo_api/router.py', tofile='b/app/demo_api/router.py', lineterm='')) + '\n'
fix = FixProposal(summary='test', files_changed=['app/demo_api/router.py'], diff=diff, reason='test', risk='low')
runner = SandboxRunner()

async def main():
    result = await runner.run_verification(fix, {'method':'POST','path':'/api/v1/users/user_2/charge','body':{'amount':100.0}})
    print(result.model_dump_json(indent=2))

asyncio.run(main())
