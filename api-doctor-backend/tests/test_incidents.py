"""Tests for the incident lifecycle and store."""

from __future__ import annotations

from app.incidents.models import Incident, IncidentStatus
from app.incidents.store import incident_store


def test_store_create_get_update_list():
    inc = Incident(request_snapshot={}, stack_trace="x")
    created = incident_store.create(inc)
    # The persistent store rehydrates records rather than retaining object identity.
    assert created.id == inc.id
    assert incident_store.get(inc.id).id == inc.id

    inc.status = IncidentStatus.INVESTIGATING
    incident_store.update(inc)
    assert incident_store.get(inc.id).status == IncidentStatus.INVESTIGATING

    listing = incident_store.list_all()
    assert listing[0].id == inc.id


def test_incident_add_activity_touches_updated_at():
    inc = Incident(request_snapshot={}, stack_trace="x")
    before = inc.updated_at
    inc.add_activity("error_detected", "done", "found")
    assert inc.activity
    assert inc.activity[0].step == "error_detected"
    assert inc.activity[0].status == "done"
    assert inc.updated_at >= before


def test_status_helpers():
    assert IncidentStatus.AWAITING_REVIEW.is_terminal
    assert IncidentStatus.REPAIR_LIMIT_REACHED.is_failed
    assert IncidentStatus.FIX_VERIFIED.is_failed is False


async def test_detect_and_create_flow():
    from app.orchestrator import orchestrator

    # Uses in-process detector (no AI needed for detection).
    inc = await orchestrator.detect_and_create("/api/v1/users/user_2/charge", "POST", {"amount": 5})
    assert inc.status == IncidentStatus.DETECTED
    assert inc.detection["error_message"] == "Internal server error"
    assert inc.request_snapshot.get("path") == "/api/v1/users/user_2/charge"
    assert incident_store.get(inc.id) is not None
