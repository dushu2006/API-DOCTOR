"""Tests for the orchestrator pipeline (AI + sandbox mocked)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.agent.fix_agent import FixProposal
from app.agent.root_cause_agent import RootCauseAnalysis
from app.incidents.models import Incident, IncidentStatus
from app.incidents.store import incident_store
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


async def test_full_pipeline_success(monkeypatch):
    orch = Orchestrator()

    monkeypatch.setattr(
        orch.context_builder, "build", lambda inc: _context()
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

    inc = Incident(request_snapshot=_context()["request_snapshot"], stack_trace="t")
    incident_store.create(inc)
    result = await orch.run_pipeline(inc.id)

    assert result.status == IncidentStatus.FIX_VERIFIED
    assert result.root_cause["category"] == "CODE_BUG"
    assert result.fix_proposal["summary"] == "null check"
    assert result.sandbox_result["passed"] is True
    assert any(a.step == "fix_verified" for a in result.activity)


async def test_low_confidence_stops_pipeline(monkeypatch):
    orch = Orchestrator()
    monkeypatch.setattr(orch.context_builder, "build", lambda inc: _context())
    monkeypatch.setattr(
        orch.root_cause_agent, "analyze",
        AsyncMock(return_value=RootCauseAnalysis(
            root_cause="?", category="UNKNOWN", confidence=0.1,
            affected_files=[], affected_functions=[], safe_to_repair=False,
            reason="not enough info",
        )),
    )
    inc = Incident(request_snapshot={}, stack_trace="t")
    incident_store.create(inc)
    result = await orch.run_pipeline(inc.id)
    assert result.status == IncidentStatus.INVESTIGATION_FAILED
    assert result.fix_proposal is None


async def test_repair_limit_reached(monkeypatch):
    orch = Orchestrator()
    monkeypatch.setattr(orch.context_builder, "build", lambda inc: _context())
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
            summary="s", files_changed=["f"], diff="--- a/b\n+++ b/b\n@@ -1 +1 @@\n-x\n+y",
            reason="r", risk="low",
        )),
    )
    monkeypatch.setattr(
        orch.sandbox_runner, "run_verification",
        MagicMock(return_value=SandboxResult(passed=False, error="still crashes", logs="x")),
    )
    inc = Incident(request_snapshot={}, stack_trace="t")
    incident_store.create(inc)
    result = await orch.run_pipeline(inc.id)
    assert result.status == IncidentStatus.REPAIR_LIMIT_REACHED
    assert result.attempt_count == 2  # MAX_REPAIR_ATTEMPTS


async def test_start_diagnosis_allows_only_one_active_task(monkeypatch):
    orch = Orchestrator()
    inc = incident_store.create(Incident())
    pipeline_started = asyncio.Event()
    release_pipeline = asyncio.Event()

    async def slow_pipeline(incident_id: str):
        pipeline_started.set()
        await release_pipeline.wait()
        return incident_store.get(incident_id)

    monkeypatch.setattr(orch, "run_pipeline", slow_pipeline)

    assert orch.start_diagnosis(inc.id) is True
    await pipeline_started.wait()
    assert orch.start_diagnosis(inc.id) is False

    release_pipeline.set()
    await orch._pipeline_tasks[inc.id]
    await asyncio.sleep(0)
    assert inc.id not in orch._pipeline_tasks


async def test_cancel_diagnosis_sets_terminal_status(monkeypatch):
    orch = Orchestrator()
    inc = incident_store.create(Incident())
    pipeline_started = asyncio.Event()

    async def waiting_pipeline(incident_id: str):
        pipeline_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(orch, "run_pipeline", waiting_pipeline)

    assert orch.start_diagnosis(inc.id) is True
    await pipeline_started.wait()
    assert await orch.cancel_diagnosis(inc.id) is True

    persisted = incident_store.get(inc.id)
    assert persisted is not None
    assert persisted.status == IncidentStatus.CANCELLED
    assert persisted.status.is_terminal
    assert persisted.activity[-1].status == "cancelled"
