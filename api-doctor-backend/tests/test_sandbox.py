"""End-to-end sandbox verification using a real, hand-crafted fix.

The null-pointer bug (POST /users/user_2/charge -> AttributeError -> 500) is
fixed by returning a graceful 400 when ``payment_method`` is missing. The
sandbox must reproduce the original 500, apply the patch, and verify the same
request no longer crashes.
"""

from __future__ import annotations

import difflib

from app.agent.fix_agent import FixProposal
from app.core.config import settings
from app.sandbox.sandbox_runner import SandboxRunner

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

REQUEST = {
    "method": "POST",
    "path": "/api/v1/users/user_2/charge",
    "body": {"amount": 100.0},
}


def _make_fix() -> FixProposal:
    path = settings.REPO_ROOT + "/app/demo_api/router.py"
    with open(path) as fh:
        original = fh.read()
    assert ORIGINAL_MARKER in original, "expected marker present in router.py"
    fixed = original.replace(ORIGINAL_MARKER, FIXED_MARKER, 1)
    assert fixed != original

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


def test_sandbox_reproduce_patch_verify():
    # Keep this fast/deterministic: targeted repro test only.
    # run_verification is a synchronous (blocking) method — call it directly.
    old_tests = settings.REQUIRE_TESTS
    settings.REQUIRE_TESTS = False
    try:
        runner = SandboxRunner()
        result = runner.run_verification(_make_fix(), REQUEST)
    finally:
        settings.REQUIRE_TESTS = old_tests

    assert result.passed, f"sandbox failed: {result.error}\n{result.logs}"
    steps = {s.name: s.passed for s in result.steps}
    assert steps["reproduce_failure"] is True
    assert steps["apply_patch"] is True
    assert steps["verify_fix"] is True


def test_sandbox_requires_valid_diff():
    runner = SandboxRunner()
    bad = FixProposal(
        summary="bad",
        files_changed=["x"],
        diff="not a diff",
        reason="x",
        risk="high",
    )
    result = runner.run_verification(bad, REQUEST)
    assert result.passed is False
    assert "Invalid diff" in result.error
