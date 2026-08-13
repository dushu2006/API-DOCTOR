"""Regression tests for the post-diagnosis approval pipeline:

    Keep Changes (approve-fix) -> local commit -> create pull request

These target the stage *after* the agent decided what to change, which is
where user-facing failures must never misreport. Covered:

- double-clicking / retrying "Keep Changes" while verification is in flight
  must be an idempotent success, not a 500/409 conflict
- PR creation must fail with an actionable 409 when GitHub is not configured
- "branch created" must only be reported after the branch actually exists
- a failed PR attempt must record the failure on the run timeline
- committing must work for deletion patches and be idempotent on retry,
  including when the AI produced un-relocated file paths
"""

from __future__ import annotations

import asyncio
import subprocess
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx

from app.agent.fix_agent import FixProposal
from app.agent.root_cause_agent import RootCauseAnalysis
from app.runs.models import Run, RunStatus
from app.runs.store import run_store
from app.main import app
from app.orchestrator import orchestrator
from app.projects.discovery import discover_project
from app.projects.store import project_store
from app.sandbox.sandbox_runner import SandboxResult, SandboxStep


def _git(ws: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(ws), *args], capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout.strip()


def _make_git_workspace(tmp_path: Path, name: str = "payments-api") -> Path:
    ws = tmp_path / "myorg" / name
    (ws / "app" / "services").mkdir(parents=True)
    (ws / "app" / "services" / "payment.py").write_text(
        "def process_payment(user):\n"
        "    token = user.payment_method.token\n"
        "    return token\n"
    )
    (ws / "app" / "legacy.py").write_text("OLD = True\n")
    (ws / "requirements.txt").write_text("fastapi\n")
    _git(ws, "init", "-q")
    _git(ws, "config", "user.email", "tester@example.com")
    _git(ws, "config", "user.name", "Tester")
    _git(ws, "add", ".")
    _git(ws, "commit", "-q", "-m", "initial")
    return ws


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

_DELETE_DIFF = (
    "--- a/app/legacy.py\n"
    "+++ /dev/null\n"
    "@@ -1 +0,0 @@\n"
    "-OLD = True\n"
)

# AI-generated patch whose file path needs relocation against the workspace
# layout (db.py at repo root vs the actual app/services/payment.py location).
_RELOCATED_DIFF = (
    "--- a/payment.py\n"
    "+++ b/payment.py\n"
    "@@ -1,3 +1,5 @@\n"
    " def process_payment(user):\n"
    "-    token = user.payment_method.token\n"
    "+    if user.payment_method is None:\n"
    "+        raise ValueError('no payment method')\n"
    "+    token = user.payment_method.token\n"
    "     return token\n"
)


def _run_with_proposal(project_id: str, diff: str = _DIFF) -> Run:
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
            diff=diff,
            reason="null check",
            risk="low",
        ).model_dump(),
    )
    run.add_activity("fix_approval", "pending", "proposed")
    run.add_activity("file_read_approval", "done", "pre-approved")
    run.context = {
        "run_id": run.id,
        "stack_trace": run.stack_trace,
        "affected_files": ["app/services/payment.py"],
        "code_snippets": {},
        "_complete": True,
    }
    return run_store.create(run)


def _passing_verification(*args, **kwargs) -> SandboxResult:
    return SandboxResult(passed=True, steps=[
        SandboxStep(name="reproduce_failure", passed=True),
        SandboxStep(name="apply_patch", passed=True),
        SandboxStep(name="verify_fix", passed=True),
    ], logs="ok")


async def _request(method: str, path: str, headers: dict, json_body: dict | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, json=json_body, headers=headers)


def _mock_github(monkeypatch, *, pr_number: int = 7) -> None:
    from app.github.client import GitHubClient

    branch = "api-doctor/fix/mock"
    pr = {
        "number": pr_number,
        "html_url": f"https://github.com/acme/demo/pull/{pr_number}",
        "state": "open",
        "merged": False,
        "head": {"ref": branch, "sha": "cafe0123" * 5},
    }
    # First PR creation finds nothing and walks the full create path; the
    # second call finds the existing PR and reuses it (idempotency).
    monkeypatch.setattr(GitHubClient, "list_pull_requests", AsyncMock(side_effect=[[], [pr]]))
    monkeypatch.setattr(GitHubClient, "list_branches", AsyncMock(return_value=["main"]))
    monkeypatch.setattr(GitHubClient, "create_branch", AsyncMock(return_value=branch))
    monkeypatch.setattr(GitHubClient, "create_commit", AsyncMock(return_value="cafe0123" * 5))
    monkeypatch.setattr(GitHubClient, "create_pull_request", AsyncMock(return_value=pr))


# ---------------------------------------------------------------------------
# Keep Changes idempotency
# ---------------------------------------------------------------------------
async def test_approve_fix_while_verification_in_flight_is_idempotent(
    tmp_path, monkeypatch, auth_headers, project_factory
):
    """A second Keep-Changes click during sandbox verification must not
    explode as 'Failed to resume fix' (500) or a misleading 409."""
    ws = _make_git_workspace(tmp_path)
    project_factory(project_id="dup-proj", workspace_path=str(ws), profile=discover_project(ws))
    run = _run_with_proposal("dup-proj")

    # Park sandbox verification on a gate so the pipeline is genuinely running
    # when the duplicate approval arrives.
    gate = threading.Event()
    monkeypatch.setattr(
        orchestrator.sandbox_runner, "run_verification",
        MagicMock(side_effect=lambda *a, **k: (gate.wait(15), _passing_verification())[1]),
    )

    first = await _request("POST", f"/api/diagnosis/{run.id}/approve-fix", auth_headers, {"approved": True})
    assert first.status_code == 200, first.text

    # Wait until the pipeline is inside sandbox verification.
    for _ in range(200):
        if run_store.get(run.id).status == RunStatus.SANDBOX_TESTING:
            break
        await asyncio.sleep(0.02)
    assert run_store.get(run.id).status == RunStatus.SANDBOX_TESTING

    second = await _request("POST", f"/api/diagnosis/{run.id}/approve-fix", auth_headers, {"approved": True})
    assert second.status_code == 200, second.text
    assert second.json()["approved"] is True

    gate.set()
    for _ in range(300):
        if run_store.get(run.id).status == RunStatus.FIX_VERIFIED:
            break
        await asyncio.sleep(0.02)
    assert run_store.get(run.id).status == RunStatus.FIX_VERIFIED

    # Only one approval recorded on the timeline.
    approvals = [
        ev for ev in run_store.get(run.id).activity
        if ev.step == "fix_approval" and ev.status == "done"
    ]
    assert len(approvals) == 1


async def test_resume_fix_twice_is_idempotent(tmp_path, monkeypatch, auth_headers, project_factory):
    ws = _make_git_workspace(tmp_path)
    project_factory(project_id="resume-proj", workspace_path=str(ws), profile=discover_project(ws))
    run = _run_with_proposal("resume-proj")

    monkeypatch.setattr(
        orchestrator.sandbox_runner, "run_verification",
        MagicMock(side_effect=lambda *a, **k: _passing_verification()),
    )
    assert await orchestrator.resume_fix(run.id) is True
    assert await orchestrator.resume_fix(run.id) is True  # duplicate -> idempotent True

    task = orchestrator._pipeline_tasks.get(run.id)
    result = await task
    assert result.status == RunStatus.FIX_VERIFIED


# ---------------------------------------------------------------------------
# Full user journey: keep -> commit -> PR
# ---------------------------------------------------------------------------
async def test_keep_commit_pr_journey(tmp_path, monkeypatch, auth_headers, project_factory):
    ws = _make_git_workspace(tmp_path)
    project_factory(project_id="journey-proj", workspace_path=str(ws), profile=discover_project(ws))
    project_store.upsert_integration(
        project_id="journey-proj", provider="github", credentials={"token": "ghp_test"}
    )
    run = _run_with_proposal("journey-proj")
    _mock_github(monkeypatch)
    monkeypatch.setattr(
        orchestrator.sandbox_runner, "run_verification",
        MagicMock(side_effect=lambda *a, **k: _passing_verification()),
    )

    # 1) Keep Changes
    res = await _request("POST", f"/api/diagnosis/{run.id}/approve-fix", auth_headers, {"approved": True})
    assert res.status_code == 200, res.text
    task = orchestrator._pipeline_tasks.get(run.id)
    result = await task
    assert result.status == RunStatus.FIX_VERIFIED
    assert "no payment method" in (ws / "app" / "services" / "payment.py").read_text()

    # 2) Commit
    res = await _request("POST", f"/api/diagnosis/{run.id}/commit", auth_headers)
    assert res.status_code == 200, res.text
    sha = res.json()["sha"]
    assert _git(ws, "rev-parse", "HEAD") == sha
    assert "api-doctor run" in _git(ws, "log", "-1", "--pretty=%B")
    # workspace clean afterwards for the touched file
    assert "app/services/payment.py" not in _git(ws, "status", "--porcelain")

    # 2b) Commit again -> idempotent success instead of a bogus error
    res = await _request("POST", f"/api/diagnosis/{run.id}/commit", auth_headers)
    assert res.status_code == 200, res.text
    assert res.json()["sha"] == sha

    # 3) Create PR
    res = await _request("POST", f"/api/diagnosis/{run.id}/create-pr", auth_headers, {"approved": True})
    assert res.status_code == 200, res.text
    assert res.json()["pr_url"].endswith("/pull/7")
    stored = run_store.get(run.id)
    assert stored.status == RunStatus.PR_CREATED
    steps = [(ev.step, ev.status) for ev in stored.activity]
    assert ("branch_created", "done") in steps
    assert ("pr_created", "done") in steps

    # 3b) Create PR again -> idempotent reuse
    res = await _request("POST", f"/api/diagnosis/{run.id}/create-pr", auth_headers, {"approved": True})
    assert res.status_code == 200, res.text
    assert res.json()["pr_url"].endswith("/pull/7")


# ---------------------------------------------------------------------------
# PR creation failure behaviour
# ---------------------------------------------------------------------------
async def test_create_pr_without_github_config_is_actionable(
    tmp_path, monkeypatch, auth_headers, project_factory
):
    """No token configured: must be a 409 guidance response, and the run
    must never claim a branch was created."""
    ws = _make_git_workspace(tmp_path)
    project_factory(project_id="nogh-proj", workspace_path=str(ws), profile=discover_project(ws))
    run = _run_with_proposal("nogh-proj")
    run.status = RunStatus.FIX_VERIFIED
    run.sandbox_result = {"passed": True, "steps": []}
    run_store.update(run)

    emitted: list[tuple[str, str]] = []
    real_emit = __import__("app.events.hub", fromlist=["emit"]).emit

    async def _capture(run_id: str, step: str, status: str, message: str = "") -> None:
        emitted.append((step, status))
        await real_emit(run_id, step, status, message)

    monkeypatch.setattr("app.orchestrator.emit", _capture)

    res = await _request("POST", f"/api/diagnosis/{run.id}/create-pr", auth_headers, {"approved": True})

    assert res.status_code == 409, res.text
    detail = res.json()["detail"].lower()
    assert "github" in detail and ("token" in detail or "configured" in detail)

    stored = run_store.get(run.id)
    assert stored.status != RunStatus.PR_CREATED
    assert not any(
        ev.step == "branch_created" and ev.status == "done" for ev in stored.activity
    ), "timeline must not claim a branch was created when none exists"
    assert ("branch_created", "done") not in emitted


async def test_create_pr_github_failure_records_failure(
    tmp_path, monkeypatch, auth_headers, project_factory
):
    """GitHub itself failing (bad token) must leave a truthful timeline."""
    from app.github.client import GitHubClient, GitHubError

    ws = _make_git_workspace(tmp_path)
    project_factory(project_id="badgh-proj", workspace_path=str(ws), profile=discover_project(ws))
    project_store.upsert_integration(
        project_id="badgh-proj", provider="github", credentials={"token": "ghp_expired"}
    )
    run = _run_with_proposal("badgh-proj")
    run.status = RunStatus.FIX_VERIFIED
    run.sandbox_result = {"passed": True, "steps": []}
    run_store.update(run)

    monkeypatch.setattr(
        GitHubClient, "list_pull_requests",
        AsyncMock(side_effect=GitHubError("GitHub API GET /pulls -> 401: bad credentials")),
    )

    res = await _request("POST", f"/api/diagnosis/{run.id}/create-pr", auth_headers, {"approved": True})

    assert res.status_code == 502, res.text
    stored = run_store.get(run.id)
    assert stored.status != RunStatus.PR_CREATED
    assert not any(
        ev.step == "branch_created" and ev.status == "done" for ev in stored.activity
    )
    assert any(
        ev.step == "branch_created" and ev.status == "failed" for ev in stored.activity
    ), "a failed PR attempt must surface as a failed branch_created activity"


# ---------------------------------------------------------------------------
# Commit edge cases
# ---------------------------------------------------------------------------
async def test_commit_handles_file_deletion_patch(
    tmp_path, monkeypatch, auth_headers, project_factory
):
    ws = _make_git_workspace(tmp_path)
    project_factory(project_id="del-proj", workspace_path=str(ws), profile=discover_project(ws))
    run = _run_with_proposal("del-proj", diff=_DELETE_DIFF)
    run.fix_proposal["files_changed"] = ["app/legacy.py"]
    run.fix_proposal["summary"] = "Remove legacy module"
    run_store.update(run)

    monkeypatch.setattr(
        orchestrator.sandbox_runner, "run_verification",
        MagicMock(side_effect=lambda *a, **k: _passing_verification()),
    )

    res = await _request("POST", f"/api/diagnosis/{run.id}/approve-fix", auth_headers, {"approved": True})
    assert res.status_code == 200, res.text
    task = orchestrator._pipeline_tasks.get(run.id)
    assert (await task).status == RunStatus.FIX_VERIFIED
    assert not (ws / "app" / "legacy.py").exists()

    res = await _request("POST", f"/api/diagnosis/{run.id}/commit", auth_headers)
    assert res.status_code == 200, res.text
    assert "app/legacy.py" not in _git(ws, "ls-files"), "deletion must be staged and committed"


async def test_commit_retry_with_relocated_patch_paths(
    tmp_path, monkeypatch, auth_headers, project_factory
):
    """The 'already committed' probe must use the resolved diff; the raw
    AI path (payment.py) does not exist in the workspace (app/services/...)."""
    ws = _make_git_workspace(tmp_path)
    project_factory(project_id="reloc-proj", workspace_path=str(ws), profile=discover_project(ws))
    run = _run_with_proposal("reloc-proj", diff=_RELOCATED_DIFF)
    run.fix_proposal["files_changed"] = ["payment.py"]
    run_store.update(run)

    monkeypatch.setattr(
        orchestrator.sandbox_runner, "run_verification",
        MagicMock(side_effect=lambda *a, **k: _passing_verification()),
    )

    res = await _request("POST", f"/api/diagnosis/{run.id}/approve-fix", auth_headers, {"approved": True})
    assert res.status_code == 200, res.text
    task = orchestrator._pipeline_tasks.get(run.id)
    assert (await task).status == RunStatus.FIX_VERIFIED

    first = await _request("POST", f"/api/diagnosis/{run.id}/commit", auth_headers)
    assert first.status_code == 200, first.text
    retry = await _request("POST", f"/api/diagnosis/{run.id}/commit", auth_headers)
    assert retry.status_code == 200, retry.text
    assert retry.json()["sha"] == first.json()["sha"]
