"""Tests for the context builder and code retrieval."""

from __future__ import annotations

from app.context_builder.context_builder import ContextBuilder
from app.incidents.models import Incident

TRACE = (
    'Traceback (most recent call last):\n'
    '  File "app/demo_api/router.py", line 83, in charge\n'
    '    transaction_id = bugs.charge_user(user_id, body.amount)\n'
    '  File "app/demo_api/bugs.py", line 121, in charge_user\n'
    '    token = user.payment_method.token\n'
    "AttributeError: 'NoneType' object has no attribute 'token'"
)


def _incident() -> Incident:
    return Incident(
        request_snapshot={"method": "POST", "path": "/api/v1/users/user_2/charge", "body": {"amount": 1}},
        stack_trace=TRACE,
    )


def test_builds_minimal_context():
    ctx = ContextBuilder().build(_incident())
    assert ctx["incident_id"]
    assert ctx["exception_type"] == "AttributeError"
    # Stack trace is trimmed to project-relevant frames (no .venv noise)
    assert "AttributeError" in ctx["stack_trace"]
    assert "app/demo_api/bugs.py" in ctx["stack_trace"]
    assert "app/demo_api/bugs.py" in ctx["affected_files"]
    assert "app/demo_api/bugs.py" in ctx["code_snippets"]
    snippet = ctx["code_snippets"]["app/demo_api/bugs.py"]
    assert snippet["error_line"] == 121
    assert snippet["functions"]  # extracted function names
    assert ctx["call_chain"]


def test_context_small_enough():
    ctx = ContextBuilder().build(_incident())
    total = sum(len(s["content"]) for s in ctx["code_snippets"].values())
    assert len(ctx["affected_files"]) <= 10  # MAX_CONTEXT_FILES
    # The whole repo must never be sent.
    assert total < 50_000


def test_retriever_does_not_read_everything():
    from app.code_retrieval.local_retriever import LocalRetriever

    retriever = LocalRetriever()
    # The null-pointer trace points at bugs.py; retrieval must include it.
    frames = [
        __import__("app.context_builder.stack_trace_parser", fromlist=["StackFrame"])
        .StackFrame(file="app/demo_api/bugs.py", line=121, function="charge_user", relative_path="app/demo_api/bugs.py")
    ]
    snippets = retriever.retrieve(frames)
    assert snippets
    assert snippets[0]["path"] == "app/demo_api/bugs.py"
