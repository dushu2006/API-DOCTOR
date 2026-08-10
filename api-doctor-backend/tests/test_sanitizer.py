"""Tests for secret sanitisation."""

from __future__ import annotations

from app.security.sanitizer import redact_text, sanitize


def test_redacts_patterned_values():
    text = "key=sk-abcdef1234567890 and token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    out = redact_text(text)
    assert "sk-abcdef1234567890" not in out
    assert "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345" not in out
    assert "<SECRET_PRESENT>" in out


def test_redacts_secret_keys_in_dict():
    payload = {
        "DATABASE_URL": "postgres://u:super-secret@host/db",
        "authorization": "Bearer abc123",
        "api_key": "nvidia-xyz",
        "normal": "hello",
        "nested": {"GITHUB_TOKEN": "ghp_1234567890abcdefghijkl"},
    }
    out = sanitize(payload)
    assert out["DATABASE_URL"] == "<SECRET_PRESENT>"
    assert out["authorization"] == "<SECRET_PRESENT>"
    assert out["api_key"] == "<SECRET_PRESENT>"
    assert out["normal"] == "hello"
    assert out["nested"]["GITHUB_TOKEN"] == "<SECRET_PRESENT>"


def test_sanitize_in_place():
    payload = {"password": "hunter2", "other": {"secret": "x"}}
    sanitize(payload, in_place=True)
    assert payload["password"] == "<SECRET_PRESENT>"
    assert payload["other"]["secret"] == "<SECRET_PRESENT>"


def test_context_has_no_secret_values():
    # Verify a built context never contains actual secret-shaped values.
    from app.context_builder.context_builder import ContextBuilder
    from app.incidents.models import Incident

    ctx = ContextBuilder().build(
        Incident(request_snapshot={}, stack_trace="Traceback\nValueError: x")
    )
    blob = repr(ctx)
    assert "sk-" not in blob
    assert "ghp_" not in blob
