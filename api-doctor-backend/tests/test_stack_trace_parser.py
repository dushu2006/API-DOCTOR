"""Tests for the traceback parser."""

from __future__ import annotations

from app.context_builder.stack_trace_parser import parse_stack_trace

TRACE = (
    'Traceback (most recent call last):\n'
    '  File "/repo/app/demo_api/router.py", line 83, in charge\n'
    '    transaction_id = bugs.charge_user(user_id, body.amount)\n'
    '  File "/repo/app/demo_api/bugs.py", line 121, in charge_user\n'
    '    token = user.payment_method.token\n'
    "AttributeError: 'NoneType' object has no attribute 'token'"
)


def test_parses_frames():
    parsed = parse_stack_trace(TRACE, repo_root="/repo")
    assert len(parsed.frames) == 2
    f0, f1 = parsed.frames
    assert f0.file == "/repo/app/demo_api/router.py"
    assert f0.line == 83
    assert f0.function == "charge"
    assert f1.function == "charge_user"
    assert f1.relative_path == "app/demo_api/bugs.py"
    assert f1.path is not None


def test_extracts_exception_and_message():
    parsed = parse_stack_trace(TRACE, repo_root="/repo")
    assert parsed.exception_type == "AttributeError"
    assert parsed.message == "'NoneType' object has no attribute 'token'"


def test_call_chain_order():
    parsed = parse_stack_trace(TRACE, repo_root="/repo")
    assert parsed.call_chain[0].startswith("/repo/app/demo_api/router.py:83")
    assert parsed.call_chain[-1].endswith("in charge_user")
    assert parsed.deepest_frame is parsed.frames[-1]


def test_pydantic_validation_error_header():
    trace = (
        "Traceback (most recent call last):\n"
        '  File "/repo/app/demo_api/router.py", line 97, in get_order\n'
        "    return OrderResponse.model_validate(order.model_dump())\n"
        "pydantic_core._pydantic_core.ValidationError: 1 validation error for OrderResponse\n"
        "status\n"
        "  Input should be 'pending', 'paid' or 'delivered' [type=literal_error]\n"
    )
    parsed = parse_stack_trace(trace, repo_root="/repo")
    assert parsed.exception_type == "pydantic_core._pydantic_core.ValidationError"
    assert parsed.message == "1 validation error for OrderResponse"


def test_empty_trace():
    parsed = parse_stack_trace("", repo_root="/repo")
    assert parsed.frames == []
    assert parsed.exception_type is None
