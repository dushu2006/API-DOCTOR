from pathlib import Path
from app.context_builder.stack_trace_parser import parse_stack_trace
from app.sandbox.patch_utils import apply_patch
import difflib
import os

TRACE = (
    'Traceback (most recent call last):\n'
    '  File "/repo/app/demo_api/router.py", line 83, in charge\n'
    '    transaction_id = bugs.charge_user(user_id, body.amount)\n'
    '  File "/repo/app/demo_api/bugs.py", line 121, in charge_user\n'
    '    token = user.payment_method.token\n'
    "AttributeError: 'NoneType' object has no attribute 'token'"
)
parsed = parse_stack_trace(TRACE, repo_root='/repo')
print('rel paths:', [f.relative_path for f in parsed.frames])
print('as posix:', [Path(p).as_posix() if p else None for p in [f.relative_path for f in parsed.frames]])

repo_root = Path(os.getcwd())
path = repo_root / 'app' / 'demo_api' / 'router.py'
original = path.read_text()
ORIGINAL_MARKER = '    transaction_id = bugs.charge_user(user_id, body.amount)\n    return {"success": True, "transaction_id": transaction_id}\n'
FIXED_MARKER = '    if user.payment_method is None:\n        raise HTTPException(status_code=400, detail="no payment method on file")\n    transaction_id = bugs.charge_user(user_id, body.amount)\n    return {"success": True, "transaction_id": transaction_id}\n'
if ORIGINAL_MARKER not in original:
    print('marker not found')
else:
    fixed = original.replace(ORIGINAL_MARKER, FIXED_MARKER, 1)
    diff = '\n'.join(difflib.unified_diff(original.splitlines(), fixed.splitlines(), fromfile='a/app/demo_api/router.py', tofile='b/app/demo_api/router.py', lineterm='')) + '\n'
    try:
        affected = apply_patch(diff, repo_root)
        print('apply_patch succeeded', affected)
    except Exception as e:
        print('apply_patch failed', repr(e))
