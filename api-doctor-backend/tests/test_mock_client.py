"""MockAIClient must emit a unified diff that applies to the live demo API."""

from __future__ import annotations

from pathlib import Path

from app.agent.fix_agent import FixProposal
from app.agent.llm_client import LLMClient
from app.ai.mock_client import MockAIClient, build_demo_null_pointer_diff
from app.core.config import settings
from app.sandbox.patch_utils import apply_patch


def test_demo_diff_applies_to_repo(tmp_path: Path):
    repo = Path(settings.INTERNAL_REPO_ROOT)
    # Copy just the demo API files so we don't mutate the real tree.
    dest = tmp_path / "app" / "demo_api"
    dest.mkdir(parents=True)
    for name in ("router.py", "bugs.py"):
        (dest / name).write_text((repo / "app" / "demo_api" / name).read_text(encoding="utf-8"))

    diff = build_demo_null_pointer_diff(repo)
    assert diff.startswith("--- ")
    affected = apply_patch(diff, tmp_path)
    assert affected
    patched = (tmp_path / affected[0]).read_text(encoding="utf-8")
    assert "no payment method" in patched or "missing_payment_method" in patched


async def test_mock_client_fix_proposal_validates_and_applies(tmp_path: Path):
    client = LLMClient(MockAIClient())
    proposal = await client.generate_structured(
        response_model=FixProposal,
        system_prompt="You are a staff engineer writing a minimal, safe patch.",
        user_prompt="Fix the null pointer in charge_user.",
        model="mock",
    )
    assert proposal.risk == "low"
    assert proposal.diff.startswith("--- ")
    assert proposal.summary != "mock"

    repo = Path(settings.INTERNAL_REPO_ROOT)
    dest = tmp_path / "app" / "demo_api"
    dest.mkdir(parents=True)
    for name in ("router.py", "bugs.py"):
        (dest / name).write_text((repo / "app" / "demo_api" / name).read_text(encoding="utf-8"))

    affected = apply_patch(proposal.diff, tmp_path)
    assert affected
    patched = (tmp_path / affected[0]).read_text(encoding="utf-8")
    assert "no payment method" in patched or "missing_payment_method" in patched
