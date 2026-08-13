"""Tests for the Keep-Changes workflow: real workspace patch application,
verification against the pre-apply snapshot, rollback, and local commits."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.fix_agent import FixProposal
from app.agent.root_cause_agent import RootCauseAnalysis
from app.runs.models import Run, RunStatus
from app.runs.store import run_store
from app.orchestrator import Orchestrator
from app.projects.discovery import discover_project
from app.sandbox.patch_utils import PatchError, apply_patch, normalize_diff, resolve_diff_paths
from app.sandbox.sandbox_runner import SandboxResult, SandboxStep


# ---------------------------------------------------------------------------
# patch_utils: normalization and path resolution
# ---------------------------------------------------------------------------
def test_normalize_diff_strips_git_metadata():
    raw = (
        "diff --git a/app/main.py b/app/main.py\n"
        "index 1234567..89abcde 100644\n"
        "--- a/app/main.py\n"
        "+++ b/app/main.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    normalized = normalize_diff(raw)
    assert normalized.startswith("--- a/app/main.py")
    assert "diff --git" not in normalized
    assert "index " not in normalized


def test_normalize_diff_synthesizes_missing_old_header():
    raw = "+++ b/app/main.py\n@@ -1 +1 @@\n-old\n+new\n"
    normalized = normalize_diff(raw)
    assert normalized.startswith("--- a/app/main.py")


def test_normalize_diff_empty_raises():
    with pytest.raises(PatchError):
        normalize_diff("   \n")


def test_resolve_diff_paths_relocates_misnamed_files(tmp_path):
    (tmp_path / "src" / "app").mkdir(parents=True)
    (tmp_path / "src" / "app" / "main.py").write_text("x = 1\n")

    diff = "--- a/app/main.py\n+++ b/app/main.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    resolved, mapping = resolve_diff_paths(diff, tmp_path)

    assert mapping == {"app/main.py": "src/app/main.py"}
    assert "+++ b/src/app/main.py" in resolved
    assert "--- a/src/app/main.py" in resolved


def test_resolve_diff_paths_keeps_existing_paths(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("x = 1\n")

    diff = "--- a/app/main.py\n+++ b/app/main.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    resolved, mapping = resolve_diff_paths(diff, tmp_path)
    assert mapping == {}
    assert "+++ b/app/main.py" in resolved


# ---------------------------------------------------------------------------
# Orchestrator: Keep-Changes apply / verify / rollback / commit
# ---------------------------------------------------------------------------
_BUGGY = (
    "def process_payment(user):\n"
    "    token = user.payment_method.token\n"
    "    return token\n"
)
_DIFF = (
    "--- a/app/services/payment.py\n"
    "+++ b/app/services/payment.py\n"
    "@@ -1,3 +1,5 @@\n"
    " def process_payment(user):\n"
    "-    token = user.payment_method.token\n"
    "+    if user.payment_method is None:\n"
    "+        raise ValueError('no payment method')\n"
    "+    token = user.payment_method.token\n"
    "     return token\n"
)


def _make_project_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "myorg" / "payments-api"
    (ws / "app" / "services").mkdir(parents=True)
    (ws / "app" / "services" / "payment.py").write_text(_BUGGY)
    (ws / "requirements.txt").write_text("fastapi\n")
    return ws


def _run_with_proposal(project_id: str) -> Run:
    run = Run(
        project_id=project_id,
        status=RunStatus.AWAITING_FIX_APPROVAL,
        stack_trace=(
            "Traceback (most recent call last):\n"
            '  File "app/services/payment.py", line 2, in process_payment\n'
            "AttributeError: 'NoneType' object has no attribute 'token'"
        ),
        root_cause=RootCauseAnalysis(
            root_cause="null deref",
            classification="CODE_BUG",
            category="CODE_BUG",
            confidence=0.95,
            affected_files=["app/services/payment.py"],
            affected_functions=["process_payment"],
            safe_to_repair=True,
            reason="AttributeError",
        ).model_dump(),
        fix_proposal=FixProposal(
            summary="Guard payment_method",
            files_changed=["app/services/payment.py"],
            diff=_DIFF,
            reason="null check",
            risk="low",
        ).model_dump(),
    )
    run.add_activity("fix_approval", "pending", "proposed")
    # Pre-seed a complete context + file-read approval so resume_fix goes
    # straight to sandbox verification (mirrors the UI flow after both gates).
    run.add_activity("file_read_approval", "done", "pre-approved")
    run.context = {
        "run_id": run.id,
        "stack_trace": run.stack_trace,
        "affected_files": ["app/services/payment.py"],
        "code_snippets": {},
        "_complete": True,
    }
    return run_store.create(run)


async def test_keep_changes_applies_patch_and_keeps_it_after_verification(
    tmp_path, monkeypatch, authenticated_user, project_factory
):
    user, _ = authenticated_user
    ws = _make_project_workspace(tmp_path)
    project_factory(project_id="kp-proj", workspace_path=str(ws), profile=discover_project(ws))
    orch = Orchestrator()
    orch.context_builder.set_repo_root(ws)
    orch.sandbox_runner.set_repo_root(ws)

    run = _run_with_proposal("kp-proj")

    outcome = await orch.stage_workspace_apply(run.id)
    assert outcome["applied"] is True
    assert outcome["files"] == ["app/services/payment.py"]

    content = (ws / "app" / "services" / "payment.py").read_text()
    assert "raise ValueError('no payment method')" in content

    # Verification runs against the pre-apply snapshot and passes.
    monkeypatch.setattr(
        orch.sandbox_runner, "run_verification",
        MagicMock(return_value=SandboxResult(passed=True, steps=[
            SandboxStep(name="reproduce_failure", passed=True),
            SandboxStep(name="apply_patch", passed=True),
            SandboxStep(name="verify_fix", passed=True),
        ], logs="ok")),
    )
    assert await orch.resume_fix(run.id) is True
    task = orch._pipeline_tasks.get(run.id)
    result = await task
    assert result.status == RunStatus.FIX_VERIFIED

    # Passed verification -> the applied change stays in the workspace.
    content = (ws / "app" / "services" / "payment.py").read_text()
    assert "raise ValueError('no payment method')" in content
    persisted = run_store.get(run.id)
    assert persisted.fix_proposal["applied_files"] == ["app/services/payment.py"]

    # A delayed duplicate apply request must not attempt the old hunk again.
    # The temporary rollback state is gone after a successful verification.
    duplicate = await orch.stage_workspace_apply(run.id)
    assert duplicate == {"applied": True, "files": ["app/services/payment.py"]}


async def test_stage_apply_recovers_when_patch_is_already_on_disk(
    tmp_path, authenticated_user, project_factory
):
    """A lost response/restart after the write must be an idempotent success.

    The run metadata intentionally says "not applied" while the workspace
    already contains the exact post-image. The safety copy is reconstructed to
    the original source so a subsequent verification can still reproduce it.
    """
    ws = _make_project_workspace(tmp_path)
    project_factory(project_id="kp-retry", workspace_path=str(ws), profile=discover_project(ws))
    orch = Orchestrator()
    run = _run_with_proposal("kp-retry")
    run.context["file_contents"] = {"app/services/payment.py": _BUGGY}
    run_store.update(run)

    # Simulate a process dying after the workspace write and before
    # fix_proposal.applied_files was persisted.
    apply_patch(_DIFF, ws)
    assert not (run_store.get(run.id).fix_proposal or {}).get("applied_files")

    outcome = await orch.stage_workspace_apply(run.id)

    assert outcome["applied"] is True
    assert outcome["already_applied"] is True
    assert "raise ValueError('no payment method')" in (
        ws / "app" / "services" / "payment.py"
    ).read_text()
    persisted = run_store.get(run.id)
    assert persisted.fix_proposal["applied_files"] == ["app/services/payment.py"]
    state = orch._load_apply_state(run.id)
    assert state is not None
    assert state["snapshots"]["app/services/payment.py"].decode("utf-8") == _BUGGY
    assert "backup" not in state


async def test_keep_changes_rolls_back_when_verification_fails(
    tmp_path, monkeypatch, authenticated_user, project_factory
):
    user, _ = authenticated_user
    ws = _make_project_workspace(tmp_path)
    project_factory(project_id="kp-fail", workspace_path=str(ws), profile=discover_project(ws))
    orch = Orchestrator()
    orch.context_builder.set_repo_root(ws)
    orch.sandbox_runner.set_repo_root(ws)

    run = _run_with_proposal("kp-fail")
    outcome = await orch.stage_workspace_apply(run.id)
    assert outcome["applied"] is True

    monkeypatch.setattr(
        orch.sandbox_runner, "run_verification",
        MagicMock(return_value=SandboxResult(passed=False, error="still crashes", logs="x")),
    )
    assert await orch.resume_fix(run.id) is True
    task = orch._pipeline_tasks.get(run.id)
    result = await task
    assert result.status in (RunStatus.VERIFICATION_FAILED, RunStatus.REPAIR_LIMIT_REACHED)

    # Failed verification -> workspace restored to the original code.
    assert (ws / "app" / "services" / "payment.py").read_text() == _BUGGY
    persisted = run_store.get(run.id)
    assert not persisted.fix_proposal.get("applied_files")


async def test_stage_apply_refuses_missing_original_file(
    tmp_path, authenticated_user, project_factory
):
    user, _ = authenticated_user
    ws = tmp_path / "org" / "other"
    ws.mkdir(parents=True)
    (ws / "unrelated.py").write_text("x = 1\n")
    project_factory(project_id="kp-missing", workspace_path=str(ws), profile=discover_project(ws))
    orch = Orchestrator()

    run = _run_with_proposal("kp-missing")
    outcome = await orch.stage_workspace_apply(run.id)
    assert outcome["applied"] is False
    assert "Original file not found" in outcome["reason"]
    # Nothing was touched.
    assert (ws / "unrelated.py").read_text() == "x = 1\n"


async def test_stage_apply_reports_genuine_workspace_change(
    tmp_path, authenticated_user, project_factory
):
    ws = _make_project_workspace(tmp_path)
    project_factory(project_id="kp-stale", workspace_path=str(ws), profile=discover_project(ws))
    orch = Orchestrator()
    run = _run_with_proposal("kp-stale")
    run.context["file_contents"] = {"app/services/payment.py": _BUGGY}
    run_store.update(run)

    changed = _BUGGY.replace(
        "token = user.payment_method.token",
        "token = user.primary_payment_method.token",
    )
    (ws / "app" / "services" / "payment.py").write_text(changed)

    outcome = await orch.stage_workspace_apply(run.id)

    assert outcome["applied"] is False
    assert outcome["conflict"] == "workspace_changed"
    assert outcome["stale_files"] == ["app/services/payment.py"]
    assert "File changed since diagnosis" in outcome["reason"]
    assert (ws / "app" / "services" / "payment.py").read_text() == changed


async def test_stage_apply_relocates_misnamed_patch_paths(
    tmp_path, authenticated_user, project_factory
):
    """AI said app/services/payment.py but the repo nests it under src/."""
    user, _ = authenticated_user
    ws = tmp_path / "org" / "nested"
    (ws / "src" / "app" / "services").mkdir(parents=True)
    (ws / "src" / "app" / "services" / "payment.py").write_text(_BUGGY)
    project_factory(project_id="kp-nested", workspace_path=str(ws), profile=discover_project(ws))
    orch = Orchestrator()

    run = _run_with_proposal("kp-nested")
    outcome = await orch.stage_workspace_apply(run.id)
    assert outcome["applied"] is True, outcome
    content = (ws / "src" / "app" / "services" / "payment.py").read_text()
    assert "raise ValueError('no payment method')" in content


async def test_commit_changes_creates_real_git_commit(
    tmp_path, authenticated_user, project_factory
):
    user, _ = authenticated_user
    ws = _make_project_workspace(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    subprocess.run(["git", "add", "-A"], cwd=ws, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"],
        cwd=ws,
        check=True,
    )
    project_factory(project_id="kp-commit", workspace_path=str(ws), profile=discover_project(ws))
    orch = Orchestrator()

    run = _run_with_proposal("kp-commit")
    outcome = await orch.stage_workspace_apply(run.id)
    assert outcome["applied"] is True

    commit = await orch.commit_changes(run.id)
    assert commit["sha"]
    assert commit["files"] == ["app/services/payment.py"]

    log = subprocess.run(
        ["git", "-C", str(ws), "log", "--oneline", "-1"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "Guard payment_method" in log


async def test_commit_changes_requires_applied_fix(tmp_path, authenticated_user, project_factory):
    user, _ = authenticated_user
    ws = _make_project_workspace(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    project_factory(project_id="kp-nocommit", workspace_path=str(ws), profile=discover_project(ws))
    orch = Orchestrator()
    run = _run_with_proposal("kp-nocommit")
    run.fix_proposal.pop("applied_files", None)
    run_store.update(run)

    with pytest.raises(ValueError, match="Keep Changes"):
        await orch.commit_changes(run.id)


async def test_reject_fix_leaves_workspace_untouched(
    tmp_path, auth_headers, project_factory
):
    """Reject must discard the proposal without touching the workspace and
    surface a 'patch rejected' event — never a half-applied file."""
    from app.main import app

    ws = _make_project_workspace(tmp_path)
    project_factory(project_id="kp-reject", workspace_path=str(ws), profile=discover_project(ws))
    run = _run_with_proposal("kp-reject")
    assert run.status == RunStatus.AWAITING_FIX_APPROVAL

    import httpx

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/diagnosis/{run.id}/approve-fix",
            headers=auth_headers,
            json={"approved": False},
        )

    assert response.status_code == 200
    assert response.json() == {"run_id": run.id, "approved": False}

    persisted = run_store.get(run.id)
    assert persisted.status == RunStatus.REQUIRES_HUMAN_REVIEW
    # Proposal discarded, nothing applied, workspace byte-identical.
    assert not persisted.fix_proposal.get("applied_files")
    assert (ws / "app" / "services" / "payment.py").read_text() == _BUGGY
    assert any(ev.step == "fix_approval" and ev.status == "failed" for ev in persisted.activity)
