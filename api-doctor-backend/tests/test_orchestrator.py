"""Tests for the orchestrator pipeline (AI + sandbox mocked)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.agent.fix_agent import FixProposal
from app.agent.root_cause_agent import RootCauseAnalysis
from app.runs.models import Run, RunStatus
from app.runs.store import run_store
from app.orchestrator import Orchestrator
from app.sandbox.sandbox_runner import SandboxResult, SandboxStep


def _context() -> dict:
    return {
        "request_snapshot": {"method": "POST", "path": "/api/v1/users/user_2/charge"},
        "stack_trace": "Traceback\nAttributeError: x",
        "affected_files": ["app/demo_api/bugs.py"],
        "code_snippets": {"app/demo_api/bugs.py": {"content": "code", "error_line": 1}},
        "git_log": "",
    }


def _preapprove_gates(run_id: str) -> None:
    """Skip interactive pause points so unit tests ca run the pipeline in one shot."""
    run = run_store.get(run_id)
    assert run is not None
    run.add_activity("file_read_approval", "done", "pre-approved")
    run.add_activity("fix_approval", "done", "pre-approved")
    run_store.update(run)


async def _await_pipeline(orch: Orchestrator, run_id: str):
    task = orch._pipeline_tasks.get(run_id)
    if not task:
        return run_store.get(run_id)
    result = await task
    await asyncio.sleep(0)
    return result


async def test_full_pipeline_success(monkeypatch):
    orch = Orchestrator()

    monkeypatch.setattr(
        orch.context_builder, "build", lambda run: _context()
    )
    monkeypatch.setattr(
        orch.root_cause_agent, "analyze",
        AsyncMock(return_value=RootCauseAnalysis(
            root_cause="missing null guard",
            category="CODE_BUG",
            confidence=0.9,
            affected_files=["app/demo_api/bugs.py"],
            affected_functions=["charge_user"],
            safe_to_repair=True,
            reason="clear",
        )),
    )
    monkeypatch.setattr(
        orch.fix_agent, "generate_fix",
        AsyncMock(return_value=FixProposal(
            summary="null check", files_changed=["app/demo_api/bugs.py"],
            diff="--- a/app/demo_api/bugs.py\n+++ b/app/demo_api/bugs.py\n@@ -1 +1 @@\n-x\n+y",
            reason="fix", risk="low",
        )),
    )
    monkeypatch.setattr(
        orch.sandbox_runner, "run_verification",
        MagicMock(return_value=SandboxResult(passed=True, steps=[
            SandboxStep(name="reproduce_failure", passed=True),
            SandboxStep(name="apply_patch", passed=True),
            SandboxStep(name="verify_fix", passed=True),
        ], logs="ok")),
    )

    run = Run(request_snapshot=_context()["request_snapshot"], stack_trace="t")
    run_store.create(run)
    _preapprove_gates(run.id)
    result = await orch.run_pipeline(run.id)

    assert result.status == RunStatus.FIX_VERIFIED
    assert result.root_cause["category"] == "CODE_BUG"
    assert result.fix_proposal["summary"] == "null check"
    assert result.sandbox_result["passed"] is True
    assert any(a.step == "fix_verified" for a in result.activity)


async def test_low_confidence_stops_pipeline(monkeypatch):
    orch = Orchestrator()
    monkeypatch.setattr(orch.context_builder, "build", lambda run: _context())
    monkeypatch.setattr(
        orch.root_cause_agent, "analyze",
        AsyncMock(return_value=RootCauseAnalysis(
            root_cause="?", category="UNKNOWN", confidence=0.1,
            affected_files=[], affected_functions=[], safe_to_repair=False,
            reason="not enough info",
        )),
    )
    run = Run(request_snapshot={}, stack_trace="t")
    run_store.create(run)
    _preapprove_gates(run.id)
    result = await orch.run_pipeline(run.id)
    assert result.status == RunStatus.INVESTIGATION_FAILED
    assert result.fix_proposal is None


async def test_repair_limit_reached(monkeypatch):
    orch = Orchestrator()
    monkeypatch.setattr(orch.context_builder, "build", lambda run: _context())
    monkeypatch.setattr(
        orch.root_cause_agent, "analyze",
        AsyncMock(return_value=RootCauseAnalysis(
            root_cause="c", category="CODE_BUG", confidence=0.95,
            affected_files=["app/demo_api/bugs.py"], affected_functions=["f"],
            safe_to_repair=True, reason="r",
        )),
    )
    monkeypatch.setattr(
        orch.fix_agent, "generate_fix",
        AsyncMock(return_value=FixProposal(
            summary="s", files_changed=["app/demo_api/bugs.py"],
            diff="--- a/app/demo_api/bugs.py\n+++ b/app/demo_api/bugs.py\n@@ -1 +1 @@\n-x\n+y",
            reason="r", risk="low",
        )),
    )
    monkeypatch.setattr(
        orch.sandbox_runner, "run_verification",
        MagicMock(return_value=SandboxResult(passed=False, error="still crashes", logs="x")),
    )
    run = Run(request_snapshot={}, stack_trace="t")
    run_store.create(run)
    _preapprove_gates(run.id)
    result = await orch.run_pipeline(run.id)
    assert result.status == RunStatus.REPAIR_LIMIT_REACHED
    assert result.attempt_count == 2  # MAX_REPAIR_ATTEMPTS


async def test_start_diagnosis_allows_only_one_active_task(monkeypatch):
    orch = Orchestrator()
    run = run_store.create(Run())
    pipeline_started = asyncio.Event()
    release_pipeline = asyncio.Event()

    async def slow_pipeline(run_id: str):
        pipeline_started.set()
        await release_pipeline.wait()
        return run_store.get(run_id)

    monkeypatch.setattr(orch, "run_pipeline", slow_pipeline)

    assert orch.start_diagnosis(run.id) is True
    await pipeline_started.wait()
    assert orch.start_diagnosis(run.id) is False

    release_pipeline.set()
    await orch._pipeline_tasks[run.id]
    await asyncio.sleep(0)
    assert run.id not in orch._pipeline_tasks


async def test_cancel_diagnosis_sets_terminal_status(monkeypatch):
    orch = Orchestrator()
    run = run_store.create(Run())
    pipeline_started = asyncio.Event()

    async def waiting_pipeline(run_id: str):
        pipeline_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(orch, "run_pipeline", waiting_pipeline)

    assert orch.start_diagnosis(run.id) is True
    await pipeline_started.wait()
    assert await orch.cancel_diagnosis(run.id) is True

    persisted = run_store.get(run.id)
    assert persisted is not None
    assert persisted.status == RunStatus.CANCELLED
    assert persisted.status.is_terminal
    assert persisted.activity[-1].status == "cancelled"


def _mock_successful_agents(orch: Orchestrator, monkeypatch) -> None:
    monkeypatch.setattr(orch.context_builder, "build", lambda run: _context())
    monkeypatch.setattr(
        orch.root_cause_agent, "analyze",
        AsyncMock(return_value=RootCauseAnalysis(
            root_cause="missing null guard",
            category="CODE_BUG",
            confidence=0.9,
            affected_files=["app/demo_api/bugs.py"],
            affected_functions=["charge_user"],
            safe_to_repair=True,
            reason="clear",
        )),
    )
    monkeypatch.setattr(
        orch.fix_agent, "generate_fix",
        AsyncMock(return_value=FixProposal(
            summary="null check", files_changed=["app/demo_api/bugs.py"],
            diff="--- a/app/demo_api/bugs.py\n+++ b/app/demo_api/bugs.py\n@@ -1 +1 @@\n-x\n+y",
            reason="fix", risk="low",
        )),
    )
    monkeypatch.setattr(
        orch.sandbox_runner, "run_verification",
        MagicMock(return_value=SandboxResult(passed=True, steps=[
            SandboxStep(name="reproduce_failure", passed=True),
            SandboxStep(name="apply_patch", passed=True),
            SandboxStep(name="verify_fix", passed=True),
        ], logs="ok")),
    )


async def test_pipeline_pauses_for_file_read_approval(monkeypatch):
    orch = Orchestrator()
    _mock_successful_agents(orch, monkeypatch)
    run = Run(request_snapshot=_context()["request_snapshot"], stack_trace="t")
    run_store.create(run)

    result = await orch.run_pipeline(run.id)

    assert result.status == RunStatus.AWAITING_FILE_READ_APPROVAL
    assert result.fix_proposal is None
    assert result.context is not None


async def test_file_read_approval_continues_to_fix_approval(monkeypatch):
    orch = Orchestrator()
    _mock_successful_agents(orch, monkeypatch)
    run = Run(request_snapshot=_context()["request_snapshot"], stack_trace="t")
    run_store.create(run)

    paused = await orch.run_pipeline(run.id)
    assert paused.status == RunStatus.AWAITING_FILE_READ_APPROVAL

    assert await orch.resume_file_read(run.id) is True
    result = await _await_pipeline(orch, run.id)

    assert result is not None
    assert result.status == RunStatus.AWAITING_FIX_APPROVAL
    assert result.fix_proposal is not None
    assert result.root_cause is not None


async def test_fix_approval_continues_to_sandbox(monkeypatch):
    orch = Orchestrator()
    _mock_successful_agents(orch, monkeypatch)
    run = Run(request_snapshot=_context()["request_snapshot"], stack_trace="t")
    run_store.create(run)

    await orch.run_pipeline(run.id)
    assert await orch.resume_file_read(run.id) is True
    paused = await _await_pipeline(orch, run.id)
    assert paused.status == RunStatus.AWAITING_FIX_APPROVAL

    assert await orch.resume_fix(run.id) is True
    result = await _await_pipeline(orch, run.id)

    assert result is not None
    assert result.status == RunStatus.FIX_VERIFIED
    assert result.sandbox_result["passed"] is True


async def test_cancel_paused_file_read_approval():
    orch = Orchestrator()
    run = run_store.create(Run(status=RunStatus.AWAITING_FILE_READ_APPROVAL))

    assert orch.has_active_pipeline(run.id) is False
    assert await orch.cancel_diagnosis(run.id) is True

    persisted = run_store.get(run.id)
    assert persisted is not None
    assert persisted.status == RunStatus.CANCELLED
    assert persisted.error_message == "Diagnosis cancelled by user"


async def test_cancel_stuck_collecting_context():
    orch = Orchestrator()
    run = run_store.create(Run(status=RunStatus.COLLECTING_CONTEXT))

    assert await orch.cancel_diagnosis(run.id) is True
    persisted = run_store.get(run.id)
    assert persisted is not None
    assert persisted.status == RunStatus.CANCELLED


async def test_cancel_already_terminal_returns_false():
    orch = Orchestrator()
    run = run_store.create(Run(status=RunStatus.CANCELLED))
    assert await orch.cancel_diagnosis(run.id) is False


async def test_start_diagnosis_recovers_stuck_collecting_context(monkeypatch):
    orch = Orchestrator()
    _mock_successful_agents(orch, monkeypatch)
    run = run_store.create(Run(
        status=RunStatus.COLLECTING_CONTEXT,
        request_snapshot=_context()["request_snapshot"],
        stack_trace="t",
    ))
    run.add_activity("file_read_approval", "done", "already approved")
    run_store.update(run)

    assert orch.start_diagnosis(run.id) is True
    result = await _await_pipeline(orch, run.id)
    assert result is not None
    assert result.status == RunStatus.AWAITING_FIX_APPROVAL


async def test_pipeline_fails_gracefully_when_no_workspace(monkeypatch):
    """Regression: with no synchronized workspace and DEMO_MODE off, the pipeline
    must mark the run FAILED instead of raising out of the background task
    and leaving it stuck in RECEIVED."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "DEMO_MODE", False)
    # No project exists (autouse fixture reset projects), so no workspace resolves.
    orch = Orchestrator()
    run = run_store.create(Run(stack_trace="t"))
    assert run.project_id == "default"

    result = await orch.run_pipeline(run.id)

    persisted = run_store.get(run.id)
    assert persisted is not None
    assert persisted.status == RunStatus.FAILED
    assert "workspace" in (persisted.error_message or "").lower()


async def test_restart_replaces_run_without_stale_outputs(monkeypatch):
    orch = Orchestrator()
    original = run_store.create(Run(
        project_id="fresh-project",
        status=RunStatus.FIX_VERIFIED,
        detection={"endpoint": "/orders", "nested": {"value": 1}},
        request_snapshot={"method": "GET", "path": "/orders"},
        stack_trace="ValueError: stale",
        context={"file_contents": {"db.py": "old"}, "_complete": True},
        root_cause={"root_cause": "old"},
        fix_proposal={"diff": "old"},
        sandbox_result={"passed": True},
    ))
    started: list[str] = []
    monkeypatch.setattr(
        orch, "start_diagnosis", lambda run_id: started.append(run_id) or True
    )

    fresh = await orch.restart(original.id)

    assert fresh.id != original.id
    assert fresh.status == RunStatus.RECEIVED
    assert fresh.project_id == original.project_id
    assert fresh.stack_trace == original.stack_trace
    assert fresh.context is None
    assert fresh.root_cause is None
    assert fresh.fix_proposal is None
    assert fresh.sandbox_result is None
    assert started == [fresh.id]
    assert run_store.get(original.id) is None
    assert run_store.get_current(original.owner_id).id == fresh.id
    # Input data is copied before the old run is discarded.
    fresh.detection["nested"]["value"] = 2
    assert original.detection["nested"]["value"] == 1


async def test_create_pull_request_requires_synchronized_workspace(monkeypatch):
    """create_pull_request must refuse (clear error) when the project has no
    workspace, and not read from a stale repo_root."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "DEMO_MODE", False)
    orch = Orchestrator()
    run = run_store.create(Run(
        status=RunStatus.FIX_VERIFIED,
        stack_trace="t",
        fix_proposal={
            "summary": "fix",
            "diff": "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n",
            "files_changed": ["x"],
        },
        sandbox_result={"passed": True},
    ))

    import pytest

    with pytest.raises(ValueError, match="workspace"):
        await orch.create_pull_request(run.id)


async def test_empty_coder_diff_fails_fix_generation(monkeypatch):
    """An empty diff from the coder model must surface as a fix-generation
    failure, not proceed to a confusing sandbox verification failure."""
    orch = Orchestrator()
    monkeypatch.setattr(orch.context_builder, "build", lambda run: _context())
    monkeypatch.setattr(
        orch.root_cause_agent, "analyze",
        AsyncMock(return_value=RootCauseAnalysis(
            root_cause="c", category="CODE_BUG", confidence=0.95,
            affected_files=["app/demo_api/bugs.py"], affected_functions=["f"],
            safe_to_repair=True, reason="r",
        )),
    )
    monkeypatch.setattr(
        orch.fix_agent, "generate_fix",
        AsyncMock(return_value=FixProposal(
            summary="s", files_changed=["f"], diff="", reason="r", risk="low",
        )),
    )
    run = Run(request_snapshot=_context()["request_snapshot"], stack_trace="t")
    run_store.create(run)
    _preapprove_gates(run.id)

    result = await orch.run_pipeline(run.id)
    assert result.status == RunStatus.FIX_GENERATION_FAILED
    assert "empty diff" in (result.error_message or "").lower()

