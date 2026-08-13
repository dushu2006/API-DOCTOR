"""Tests for the run lifecycle and store."""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.db.base import engine, init_db
from app.runs.models import Run, RunStatus
from app.runs.store import run_store


def test_store_keeps_only_the_current_run():
    first = Run(owner_id="user-1", request_snapshot={}, stack_trace="x")
    created = run_store.create(first)
    assert created.id == first.id
    assert run_store.get_current("user-1").id == first.id

    first.status = RunStatus.INVESTIGATING
    run_store.update(first)
    assert run_store.get(first.id).status == RunStatus.INVESTIGATING

    second = Run(owner_id="user-1", request_snapshot={}, stack_trace="y")
    run_store.create(second)
    assert run_store.get(first.id) is None
    assert run_store.get_current("user-1").id == second.id


def test_database_prunes_the_removed_workflow_table():
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS obsolete_workflow_state"))
        connection.execute(text("""
            CREATE TABLE obsolete_workflow_state (
                id TEXT PRIMARY KEY,
                project_id TEXT REFERENCES projects(id),
                detection JSON,
                stack_trace TEXT,
                root_cause JSON,
                fix_proposal JSON,
                sandbox_result JSON,
                activity JSON
            )
        """))
    assert "obsolete_workflow_state" in inspect(engine).get_table_names()

    init_db()

    assert "obsolete_workflow_state" not in inspect(engine).get_table_names()


def test_run_add_activity_touches_updated_at():
    run = Run(request_snapshot={}, stack_trace="x")
    before = run.updated_at
    run.add_activity("error_detected", "done", "found")
    assert run.activity
    assert run.activity[0].step == "error_detected"
    assert run.activity[0].status == "done"
    assert run.updated_at >= before


def test_status_helpers():
    assert RunStatus.AWAITING_REVIEW.is_terminal
    assert RunStatus.REPAIR_LIMIT_REACHED.is_failed
    assert RunStatus.FIX_VERIFIED.is_failed is False


async def test_detect_and_create_flow():
    from app.orchestrator import orchestrator

    # Uses in-process detector (no AI needed for detection).
    run = await orchestrator.detect_and_create("/api/v1/users/user_2/charge", "POST", {"amount": 5})
    assert run.status == RunStatus.DETECTED
    assert run.detection["error_message"] == "Internal server error"
    assert run.request_snapshot.get("path") == "/api/v1/users/user_2/charge"
    assert run_store.get(run.id) is not None
