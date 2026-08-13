"""Regression tests for the agentic one-step-at-a-time flow and run hygiene.

Covers the confirmed root causes from live testing:

1. Every diagnosis is bound to ITS OWN project workspace (the sandbox/context
   runners must never leak a previously-diagnosed project's repo_root into the
   next run — including when the project's stored workspace_path is unset
   and the canonical ``WorkspaceManager`` layout must be used).
2. A FixProposal that references paths outside the run's known context is
   rejected and regenerated with corrective feedback — never applied.
3. A sandbox retry emits a single "Attempt N of M" marker instead of replaying
   the setup sequence (repo sync / discovery / file reads) a second time.
4. Repeated ingestion of the same project+error reuses the open run
   instead of piling up duplicate RECEIVED rows.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from app.agent.fix_agent import FixProposal
from app.agent.root_cause_agent import RootCauseAnalysis
from app.core.config import settings
from app.runs.models import Run, RunStatus
from app.runs.store import run_store
from app.orchestrator import Orchestrator, orchestrator
from app.sandbox.sandbox_runner import SandboxResult, SandboxStep


def _valid_diff(rel: str = "main.py") -> str:
    return (
        f"--- a/{rel}\n"
        f"+++ b/{rel}\n"
        "@@ -1 +1 @@\n"
        "-x\n"
        "+y\n"
    )


def _analysis(affected_files: list[str] | None = None) -> RootCauseAnalysis:
    return RootCauseAnalysis(
        root_cause="bug",
        category="CODE_BUG",
        classification="CODE_BUG",
        confidence=0.95,
        affected_files=affected_files or ["main.py"],
        affected_functions=["f"],
        safe_to_repair=True,
        reason="r",
    )


def _preapproved_run(project_id: str = "default", *, with_cache: bool = True) -> Run:
    """Run with both approval gates pre-seeded so the pipeline runs
    end-to-end in one shot. Context is marked complete so no file is re-read."""
    run = Run(
        project_id=project_id,
        request_snapshot={"method": "GET", "path": "/"},
        stack_trace="t",
    )
    context: dict = {
        "run_id": run.id,
        "affected_files": ["main.py"],
        "code_snippets": {"main.py": {"content": "x\n"}},
        "_complete": True,
    }
    if with_cache:
        context["file_contents"] = {"main.py": "x\n"}
    run.context = context
    run.add_activity("file_read_approval", "done", "pre-approved")
    run.add_activity("fix_approval", "done", "pre-approved")
    return run_store.create(run)


def _good_proposal(rel: str = "main.py", summary: str = "fix") -> FixProposal:
    return FixProposal(
        summary=summary,
        files_changed=[rel],
        diff=_valid_diff(rel),
        reason="r",
        risk="low",
    )


def _mock_agents(
    orch: Orchestrator,
    monkeypatch,
    *,
    fix_calls: list[FixProposal] | None = None,
    sandbox: SandboxResult | None = None,
) -> list[tuple[dict, str | None]]:
    """Shared agent mocks. Returns the recorded (files, feedback) fix calls."""
    calls: list[tuple[dict, str | None]] = []

    async def fake_fix(root_cause, files, project_profile=None, feedback=None):
        calls.append((dict(files), feedback))
        if fix_calls is not None and len(calls) <= len(fix_calls):
            return fix_calls[len(calls) - 1]
        return _good_proposal()

    monkeypatch.setattr(orch.root_cause_agent, "analyze", AsyncMock(return_value=_analysis()))
    monkeypatch.setattr(orch.fix_agent, "generate_fix", fake_fix)
    if sandbox is None:
        sandbox = SandboxResult(
            passed=True, steps=[SandboxStep(name="verify_fix", passed=True)], logs="ok"
        )
    monkeypatch.setattr(
        orch.sandbox_runner, "run_verification", MagicMock(return_value=sandbox)
    )
    return calls


# ---------------------------------------------------------------------------
# 1. Two projects back-to-back never cross-contaminate workspaces
# ---------------------------------------------------------------------------
async def test_two_projects_diagnosed_back_to_back_never_cross_contaminate(
    tmp_path, monkeypatch, authenticated_user, project_factory
):
    """The sandbox/context runners must be re-bound per run, even when the
    project's stored workspace_path is empty and the canonical
    WorkspaceManager layout (data/workspaces/{owner}/{repo}) has to be used."""
    ws_root = tmp_path / "workspaces"
    ws_a = ws_root / "orga" / "repo-a"
    ws_b = ws_root / "orgb" / "repo-b"
    ws_a.mkdir(parents=True)
    ws_b.mkdir(parents=True)
    (ws_a / "main.py").write_text("A_CONTENT\n")
    (ws_b / "main.py").write_text("B_CONTENT\n")

    # Patch BEFORE constructing the orchestrator so its WorkspaceManager picks
    # up the test workspace root.
    monkeypatch.setattr(settings, "WORKSPACE_DIR", str(ws_root))
    orch = Orchestrator()

    project_factory(
        project_id="proj-a", name="orga/repo-a",
        github_owner="orga", github_repo="repo-a", workspace_path="",
    )
    project_factory(
        project_id="proj-b", name="orgb/repo-b",
        github_owner="orgb", github_repo="repo-b", workspace_path="",
    )
    calls = _mock_agents(orch, monkeypatch)

    inc_a = _preapproved_run("proj-a", with_cache=False)
    result_a = await orch.run_pipeline(inc_a.id)
    assert result_a.status == RunStatus.FIX_VERIFIED
    assert orch.sandbox_runner.repo_root == ws_a.resolve()
    assert orch.context_builder.repo_root == ws_a.resolve()
    assert calls[-1][0]["main.py"] == "A_CONTENT\n"

    inc_b = _preapproved_run("proj-b", with_cache=False)
    result_b = await orch.run_pipeline(inc_b.id)
    assert result_b.status == RunStatus.FIX_VERIFIED
    # repo_root must have moved to project B — never a shared global default.
    assert orch.sandbox_runner.repo_root == ws_b.resolve()
    assert orch.context_builder.repo_root == ws_b.resolve()
    assert calls[-1][0]["main.py"] == "B_CONTENT\n"


# ---------------------------------------------------------------------------
# 2. Hallucinated fix paths are rejected and regenerated
# ---------------------------------------------------------------------------
async def test_hallucinated_fix_path_rejected_and_regenerated(monkeypatch):
    orch = Orchestrator()
    bad = FixProposal(
        summary="bad",
        files_changed=["app/main.py"],
        diff="--- a/app/main.py\n+++ b/app/main.py\n@@ -1 +1 @@\n-x\n+y\n",
        reason="r",
        risk="low",
    )
    calls = _mock_agents(orch, monkeypatch, fix_calls=[bad, _good_proposal(summary="good")])

    run = _preapproved_run()
    result = await orch.run_pipeline(run.id)

    assert result.status == RunStatus.FIX_VERIFIED
    # The corrected proposal won — never the hallucinated "app/main.py".
    assert result.fix_proposal["files_changed"] == ["main.py"]
    assert result.fix_proposal["summary"] == "good"
    # The model was re-invoked exactly once with corrective feedback naming
    # the invented path and the allowed paths.
    assert len(calls) == 2
    assert calls[1][1] is not None
    assert "app/main.py" in calls[1][1]
    assert "main.py" in calls[1][1]
    # The rejection was surfaced as a visible timeline marker (a distinct
    # fix_regenerating step: running for the rejection, then closed out).
    regenerated = [ev for ev in result.activity if ev.step == "fix_regenerating"]
    assert len(regenerated) == 2, [ev.model_dump() for ev in regenerated]
    assert any("not found in project" in ev.message for ev in regenerated)
    assert regenerated[-1].status == "done"


async def test_unresolvable_hallucinated_paths_fail_fix_generation(monkeypatch):
    """A model that keeps inventing paths exhausts its bounded retries and the
    run fails with a precise message — it is never handed to the sandbox."""
    orch = Orchestrator()
    bad = FixProposal(
        summary="bad",
        files_changed=["app/main.py"],
        diff="--- a/app/main.py\n+++ b/app/main.py\n@@ -1 +1 @@\n-x\n+y\n",
        reason="r",
        risk="low",
    )
    _mock_agents(orch, monkeypatch, fix_calls=[bad, bad, bad])

    run = _preapproved_run()
    result = await orch.run_pipeline(run.id)

    assert result.status == RunStatus.FIX_GENERATION_FAILED
    assert "app/main.py" in (result.error_message or "")
    assert result.fix_proposal is None


# ---------------------------------------------------------------------------
# 3. Retry emits a single marker, never a setup replay
# ---------------------------------------------------------------------------
async def test_retry_emits_single_marker_and_no_setup_replay(monkeypatch):
    orch = Orchestrator()
    calls = _mock_agents(
        orch,
        monkeypatch,
        sandbox=SandboxResult(
            passed=False, error="boom", logs="boom"
        ),
    )
    # First verification attempt fails; the second passes.
    orch.sandbox_runner.run_verification = MagicMock(
        side_effect=[
            SandboxResult(passed=False, error="boom", logs="boom"),
            SandboxResult(
                passed=True,
                steps=[SandboxStep(name="verify_fix", passed=True)],
                logs="ok",
            ),
        ]
    )

    run = _preapproved_run()
    result = await orch.run_pipeline(run.id)

    assert result.status == RunStatus.FIX_VERIFIED
    assert result.attempt_count == 2

    # Setup stages ran exactly ONCE — a retry must never re-emit them.
    for step in (
        "repository_connected",
        "repository_synced",
        "project_discovered",
        "collecting_context",
        "investigating",
        "root_cause_identified",
    ):
        done = [ev for ev in result.activity if ev.step == step and ev.status == "done"]
        assert len(done) == 1, f"{step} emitted {len(done)} times: {[d.message for d in done]}"

    # Exactly one retry marker with the explicit attempt counter. It lives on
    # its own fix_regenerating step so it is not merged away by the
    # fix_generated "done" event, and it is closed out as done (no spinner).
    markers = [
        ev for ev in result.activity
        if ev.step == "fix_regenerating" and "Attempt 2 of 2" in ev.message
    ]
    assert len(markers) == 1, [m.message for m in markers]
    assert markers[0].status == "done"

    # The coder was re-invoked once with the sandbox failure as feedback.
    assert len(calls) == 2
    assert "boom" in (calls[1][1] or "")


# ---------------------------------------------------------------------------
# HACK-STORE end-to-end (the exact failing scenario from live screenshots)
# ---------------------------------------------------------------------------
_HACK_STORE_MAIN = (
    "from fastapi import FastAPI\n"
    "\n"
    "app = FastAPI()\n"
    "\n"
    "ORDERS = [\n"
    '    {"id": "1", "status": "shipped"},\n'
    '    {"id": "2", "status": "pending"},\n'
    "]\n"
    "\n"
    "\n"
    "@app.get(\"/api/orders\")\n"
    "def list_orders(status: str = \"\"):\n"
    "    orders = ORDERS\n"
    "    if status:\n"
    "        orders = [o for o in orders if o.status == status]\n"
    "    return orders\n"
)

_HACK_STORE_TRACE = (
    "Traceback (most recent call last):\n"
    '  File "main.py", line 14, in list_orders\n'
    "    orders = [o for o in orders if o.status == status]\n"
    "AttributeError: 'dict' object has no attribute 'status'\n"
)

_HACK_STORE_FIX_DIFF = (
    "--- a/main.py\n"
    "+++ b/main.py\n"
    "@@ -14,1 +14,1 @@\n"
    "-        orders = [o for o in orders if o.status == status]\n"
    '+        orders = [o for o in orders if o["status"] == status]\n'
)


def _make_hackstore(tmp_path) -> Path:
    """Flat HACK-STORE layout: main.py/db.py/flags.py/providers at the repo
    root — deliberately NO app/ prefix (the real connected repo's structure)."""
    ws = Path(tmp_path) / "hackstore-owner" / "hack-store"
    ws.mkdir(parents=True)
    (ws / "main.py").write_text(_HACK_STORE_MAIN)
    (ws / "db.py").write_text("DB = {}\n")
    (ws / "flags.py").write_text("FLAGS = {'payment': False}\n")
    (ws / "providers").mkdir()
    (ws / "providers" / "payment.py").write_text("def charge():\n    pass\n")
    (ws / "requirements.txt").write_text("fastapi\n")
    return ws


async def _run_hackstore_pipeline(
    monkeypatch, tmp_path, project_factory, fix_calls
) -> tuple[Run, Orchestrator]:
    """Run the real pipeline (real context build + real sandbox) for the
    HACK-STORE list_orders 'shipped' bug. ``fix_calls`` seeds the coder model
    outputs; a final ``None`` falls back to the correct patch."""
    from app.projects.discovery import discover_project

    ws = _make_hackstore(tmp_path)
    project = project_factory(
        project_id="hack-store-proj",
        name="hackstore/hack-store",
        github_owner="hackstore",
        github_repo="hack-store",
        workspace_path=str(ws),
        profile=discover_project(ws),
    )
    orch = Orchestrator()
    calls: list[str | None] = []

    async def fake_fix(root_cause, files, project_profile=None, feedback=None):
        calls.append(feedback)
        idx = len(calls) - 1
        if idx < len(fix_calls) and fix_calls[idx] is not None:
            return fix_calls[idx]
        return FixProposal(
            summary="Compare by key, not attribute",
            files_changed=["main.py"],
            diff=_HACK_STORE_FIX_DIFF,
            reason="orders are dicts; use o['status']",
            risk="low",
        )

    monkeypatch.setattr(
        orch.root_cause_agent, "analyze",
        AsyncMock(return_value=RootCauseAnalysis(
            root_cause="list_orders compares dict orders by attribute",
            category="CODE_BUG",
            classification="CODE_BUG",
            confidence=0.95,
            affected_files=["main.py"],
            affected_lines=[14],
            affected_functions=["list_orders"],
            safe_to_repair=True,
            reason="AttributeError on dict access",
        )),
    )
    monkeypatch.setattr(orch.fix_agent, "generate_fix", fake_fix)
    monkeypatch.setattr(
        orch.sandbox_runner, "run_verification",
        MagicMock(wraps=orch.sandbox_runner.run_verification),
    )

    run = await orch.ingest_run(
        source="manual",
        stack_trace=_HACK_STORE_TRACE,
        message="AttributeError: 'dict' object has no attribute 'status'",
        endpoint="/api/orders",
        method="GET",
        project_id=project.id,
    )
    # Pre-approve the interactive gates so the pipeline runs end to end.
    run.add_activity("file_read_approval", "done", "pre-approved")
    run.add_activity("fix_approval", "done", "pre-approved")
    run_store.update(run)

    result = await orch.run_pipeline(run.id)
    return result, orch


async def test_hackstore_list_orders_shipped_bug_end_to_end(
    tmp_path, monkeypatch, project_factory, authenticated_user
):
    """Regression for the exact screenshot failure: with a FLAT repo layout
    (main.py at the root, no app/ prefix), the coder hallucinates
    'app/main.py'. The new validation must reject it, regenerate against the
    real 'main.py', and the pipeline must verify cleanly — never an
    'Original file not found' apply error."""
    bad = FixProposal(
        summary="bad",
        files_changed=["app/main.py"],
        diff="--- a/app/main.py\n+++ b/app/main.py\n@@ -1 +1 @@\n-x\n+y\n",
        reason="r",
        risk="low",
    )
    result, orch = await _run_hackstore_pipeline(
        monkeypatch, tmp_path, project_factory, [bad]
    )

    assert result.status == RunStatus.FIX_VERIFIED, (
        f"pipeline failed: {result.error_message}"
    )
    assert result.fix_proposal["files_changed"] == ["main.py"]
    assert result.sandbox_result["passed"] is True
    # The hallucination was rejected pre-sandbox and corrected.
    regenerated = [ev for ev in result.activity if ev.step == "fix_regenerating"]
    assert any("not found in project" in ev.message for ev in regenerated)
    # The failure class is gone entirely: no "Original file not found" anywhere.
    all_messages = " | ".join(
        f"{ev.step}:{ev.message}" for ev in result.activity
    ) + f" | {result.error_message or ''}"
    assert "Original file not found" not in all_messages
    # Sandbox ran against an isolated copy — the real workspace is untouched.
    ws = orch.sandbox_runner.repo_root
    assert "o.status" in (ws / "main.py").read_text()


async def test_hackstore_list_orders_correct_patch_applies(
    tmp_path, monkeypatch, project_factory, authenticated_user
):
    """The happy path: the coder emits the correct flat-path patch on the
    first try and the real sandbox applies + verifies it."""
    result, _ = await _run_hackstore_pipeline(monkeypatch, tmp_path, project_factory, [])
    assert result.status == RunStatus.FIX_VERIFIED
    assert result.sandbox_result["passed"] is True
    apply_step = next(
        s for s in result.sandbox_result["steps"] if s["name"] == "apply_patch"
    )
    assert "main.py" in apply_step["detail"]


# ---------------------------------------------------------------------------
# Root-cause-named paths that do not exist on disk are still rejected
# ---------------------------------------------------------------------------
async def test_root_cause_named_path_not_on_disk_is_still_rejected(
    tmp_path, monkeypatch, project_factory, authenticated_user
):
    """A path named by the root-cause agent (rather than by the real context)
    must not become acceptable just because the model said it — it also has to
    actually exist in the run's read-cache or on the bound workspace."""
    from app.projects.discovery import discover_project

    ws = _make_hackstore(tmp_path)
    project = project_factory(
        project_id="poison-proj",
        name="hackstore/hack-store",
        github_owner="hackstore",
        github_repo="hack-store",
        workspace_path=str(ws),
        profile=discover_project(ws),
    )
    orch = Orchestrator()
    # The (bad) root-cause agent names a plausible-looking app/ path that does
    # not exist in this flat workspace.
    monkeypatch.setattr(
        orch.root_cause_agent, "analyze",
        AsyncMock(return_value=RootCauseAnalysis(
            root_cause="bug", category="CODE_BUG", classification="CODE_BUG",
            confidence=0.95,
            affected_files=["main.py", "app/demo_api/router.py"],
            affected_functions=["f"], safe_to_repair=True, reason="r",
        )),
    )
    # The coder keeps proposing a patch against that non-existent path.
    bad = FixProposal(
        summary="bad",
        files_changed=["app/demo_api/router.py"],
        diff="--- a/app/demo_api/router.py\n+++ b/app/demo_api/router.py\n@@ -1 +1 @@\n-x\n+y\n",
        reason="r",
        risk="low",
    )
    monkeypatch.setattr(orch.fix_agent, "generate_fix", AsyncMock(return_value=bad))
    monkeypatch.setattr(
        orch.sandbox_runner, "run_verification",
        MagicMock(return_value=SandboxResult(
            passed=True, steps=[SandboxStep(name="verify_fix", passed=True)], logs="ok"
        )),
    )

    run = _preapproved_run("poison-proj")
    result = await orch.run_pipeline(run.id)

    assert result.status == RunStatus.FIX_GENERATION_FAILED
    assert "app/demo_api/router.py" in (result.error_message or "")


# ---------------------------------------------------------------------------
# Resume after approval must not replay the setup sequence
# ---------------------------------------------------------------------------
async def test_resume_after_file_read_approval_does_not_replay_setup(
    tmp_path, monkeypatch, project_factory, authenticated_user
):
    """Regression for the live 'scripted replay' symptom: approving the
    file-read gate re-invokes the pipeline, which previously re-emitted
    repository verification + stack-trace parsing + file discovery a second
    time. The resume must pick up at the reading stage only."""
    from app.projects.discovery import discover_project

    ws = _make_hackstore(tmp_path)
    project = project_factory(
        project_id="resume-proj",
        name="hackstore/hack-store",
        github_owner="hackstore",
        github_repo="hack-store",
        workspace_path=str(ws),
        profile=discover_project(ws),
    )
    orch = Orchestrator()
    _mock_agents(orch, monkeypatch)

    run = await orch.ingest_run(
        source="manual",
        stack_trace=_HACK_STORE_TRACE,
        message="AttributeError: 'dict' object has no attribute 'status'",
        endpoint="/api/orders",
        method="GET",
        project_id=project.id,
    )
    # No pre-seeded approvals: the pipeline pauses at the file-read gate.
    paused = await orch.run_pipeline(run.id)
    assert paused.status == RunStatus.AWAITING_FILE_READ_APPROVAL

    assert await orch.resume_file_read(run.id) is True
    task = orch._pipeline_tasks.get(run.id)
    result = await task
    assert result.status == RunStatus.AWAITING_FIX_APPROVAL

    # Every setup step was emitted exactly ONCE across the two pipeline runs.
    for step in (
        "repository_connected",
        "repository_synced",
        "project_discovered",
        "stack_trace_parsed",
        "relevant_source_identified",
    ):
        done = [ev for ev in result.activity if ev.step == step and ev.status == "done"]
        assert len(done) == 1, f"{step} emitted {len(done)} times: {[d.message for d in done]}"
    # The single file was read exactly once (running+done merge into one row).
    reads = [ev for ev in result.activity if ev.step == "file_read"]
    assert len(reads) == 1, [r.message for r in reads]
    # The exact approved snapshot survives context assembly. Keep-Changes uses
    # it to tell a genuine workspace edit from a lost-response retry.
    assert result.context["file_contents"]["main.py"] == (ws / "main.py").read_text()


# ---------------------------------------------------------------------------
# 4. Every new input replaces the current run instead of creating history
# ---------------------------------------------------------------------------
async def test_new_input_replaces_current_run(
    tmp_path, authenticated_user, project_factory
):
    ws = tmp_path / "org" / "repo"
    ws.mkdir(parents=True)
    project = project_factory(
        project_id="dup-proj", name="org/repo",
        github_owner="org", github_repo="repo", workspace_path=str(ws),
    )

    trace = (
        "Traceback (most recent call last):\n"
        '  File "main.py", line 4, in list_orders\n'
        "    raise ValueError('bad status')\n"
        "ValueError: bad status\n"
    )

    first = await orchestrator.ingest_run(
        source="render", stack_trace=trace,
        endpoint="/api/orders", method="GET", project_id=project.id,
    )
    second = await orchestrator.ingest_run(
        source="render", stack_trace=trace,
        endpoint="/api/orders", method="GET", project_id=project.id,
    )
    assert second.id != first.id
    assert run_store.get(first.id) is None
    assert run_store.get_current("local", project.id).id == second.id

    other = await orchestrator.ingest_run(
        source="render", stack_trace=trace,
        endpoint="/api/other", method="GET", project_id=project.id,
    )
    assert other.id != second.id
    assert run_store.get(second.id) is None
    assert run_store.get_current("local", project.id).id == other.id
