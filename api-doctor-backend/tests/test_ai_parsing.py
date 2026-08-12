"""Tests for AI response parsing and structured output handling."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

import pytest

from app.agent.llm_client import LLMClient, _choice_content, _parse_json
from app.agent.root_cause_agent import RootCauseAnalysis
from app.ai.base import AIProviderError


class SampleModel(BaseModel):
    name: str
    value: int = Field(..., ge=0)


class FakeAI:
    name = "fake"
    responses: list[str]

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def chat(self, *, model, messages, temperature=0.1, max_tokens=2048,
                   response_format=None, stream=False):
        self.calls += 1
        content = self.responses.pop(0)
        return {"choices": [{"message": {"role": "assistant", "content": content}}], "usage": {}}

    async def embed(self, model, texts):
        return [[0.0] * 4 for _ in texts]

    async def check_health(self):
        return True


async def test_parses_fenced_json():
    client = LLMClient(FakeAI(["```json\n{\"name\": \"x\", \"value\": 3}\n```"]))
    result = await client.generate_structured(
        response_model=SampleModel, system_prompt="", user_prompt=""
    )
    assert result.name == "x"
    assert result.value == 3


async def test_parses_bare_json_with_surrounding_prose():
    client = LLMClient(FakeAI(["Sure!\n{\"name\": \"y\", \"value\": 1}\nDone."]))
    result = await client.generate_structured(
        response_model=SampleModel, system_prompt="", user_prompt=""
    )
    assert result.name == "y"


def test_ignores_think_block_before_structured_response():
    content = '''
    <think>
    I am inspecting files: {"./app/demo_api/router.py": "/app/demo_api/router.py"}
    </think>
    {"name": "final answer", "value": 9}
    '''

    assert _parse_json(content) == {"name": "final answer", "value": 9}


def test_selects_balanced_response_after_json_like_prose_fragment():
    content = (
        'Inspecting context: {"./app/demo_api/bugs.py": []}. '
        'Final response: {"name": "selected", "value": 4}'
    )

    assert _parse_json(content) == {"name": "selected", "value": 4}


async def test_retries_on_validation_error():
    fake = FakeAI([
        '{"name": "bad", "value": -1}',   # invalid (value < 0)
        '{"name": "good", "value": 5}',
    ])
    client = LLMClient(fake)
    result = await client.generate_structured(
        response_model=SampleModel, system_prompt="", user_prompt=""
    )
    assert result.name == "good"
    assert fake.calls >= 2


async def test_root_cause_parsing():
    from app.agent.root_cause_agent import RootCauseAgent

    payload = {
        "root_cause": "missing null guard",
        "category": "CODE_BUG",
        "confidence": 0.9,
        "affected_files": ["app/demo_api/bugs.py"],
        "affected_functions": ["charge_user"],
        "safe_to_repair": True,
        "reason": "clear null pointer",
    }
    import json

    fake = FakeAI([json.dumps(payload)])
    agent = RootCauseAgent(LLMClient(fake))
    analysis = await agent.analyze({"request_snapshot": {}, "stack_trace": "", "code_snippets": {}})
    assert analysis.category == "CODE_BUG"
    assert analysis.confidence == 0.9
    assert analysis.safe_to_repair is True


async def test_parses_python_dict_literal():
    client = LLMClient(FakeAI(["{'name': 'z', 'value': 42}"]))
    result = await client.generate_structured(
        response_model=SampleModel, system_prompt="", user_prompt=""
    )
    assert result.name == "z"
    assert result.value == 42


async def test_parses_embedded_markdown_fence_in_diff():
    from app.agent.fix_agent import FixProposal

    simulated = (
        '{\n'
        '  "summary": "Add null check for payment_method",\n'
        '  "files_changed": ["app/demo_api/bugs.py"],\n'
        '  "diff": "```diff\\n--- a/app/demo_api/bugs.py\\n+++ b/app/demo_api/bugs.py\\n@@ -118,7 +118,9 @@\\n def charge_user(user_id, amount):\\n     user = get_user(user_id)\\n-    token = user.payment_method.token\\n+    if user.payment_method is None:\\n+        raise ValueError(\'no payment method on file\')\\n+    token = user.payment_method.token\\n```",\n'
        '  "reason": "Adds a null guard before accessing payment_method.token",\n'
        '  "risk": "low"\n'
        '}'
    )
    client = LLMClient(FakeAI([simulated]))
    result = await client.generate_structured(
        response_model=FixProposal, system_prompt="", user_prompt=""
    )
    assert result.summary == "Add null check for payment_method"
    assert "--- a/app/demo_api/bugs.py" in result.diff
    assert result.risk == "low"


async def test_parses_outer_fence_with_embedded_fence():
    from app.agent.fix_agent import FixProposal

    simulated = (
        '```json\n'
        '{\n'
        '  "summary": "Add null check for payment_method",\n'
        '  "files_changed": ["app/demo_api/bugs.py"],\n'
        '  "diff": "```diff\\n--- a/app/demo_api/bugs.py\\n+++ b/app/demo_api/bugs.py\\n```",\n'
        '  "reason": "null guard",\n'
        '  "risk": "low"\n'
        '}\n'
        '```'
    )
    client = LLMClient(FakeAI([simulated]))
    result = await client.generate_structured(
        response_model=FixProposal, system_prompt="", user_prompt=""
    )
    assert result.summary == "Add null check for payment_method"
    assert result.risk == "low"


async def test_parses_raw_newlines_in_json_strings():
    raw_newlines = (
        '{\n'
        '  "name": "multiline",\n'
        '  "value": 10\n'
        '}'
    )
    client = LLMClient(FakeAI([raw_newlines]))
    result = await client.generate_structured(
        response_model=SampleModel, system_prompt="", user_prompt=""
    )
    assert result.name == "multiline"
    assert result.value == 10


async def test_retries_on_malformed_json():
    fake = FakeAI([
        '{"name": unquoted_value, ...}',   # Malformed JSON syntax error
        '{"name": "recovered", "value": 7}',
    ])
    client = LLMClient(fake)
    result = await client.generate_structured(
        response_model=SampleModel, system_prompt="", user_prompt=""
    )
    assert result.name == "recovered"
    assert result.value == 7
    assert fake.calls == 2


def test_recovers_html_entities_in_json_strings():
    content = (
        '{"name": "test &amp; recovery", '
        '"value": 5, '
        '"diff": "--- a/foo&#10;+++ b/foo&#10;- token = user.payment_method.token&#10;+ if user.payment_method is None:&#10;+     raise ValueError(&quot;no payment method&quot;)&#10;"}'
    )
    parsed = _parse_json(content)
    assert parsed["name"] == "test & recovery"
    assert "--- a/foo\n" in parsed["diff"]
    assert 'raise ValueError("no payment method")' in parsed["diff"]


async def test_parses_python_dict_with_json_boolean_and_null_literals():
    content = (
        "{\n"
        "  'root_cause': 'user.payment_method is None; accessing .token crashes with AttributeError',\n"
        "  'category': 'CODE_BUG',\n"
        "  'confidence': 0.95,\n"
        "  'affected_files': ['app/demo_api/bugs.py'],\n"
        "  'affected_functions': ['charge_user'],\n"
        "  'safe_to_repair': true,\n"
        "  'reason': 'clear null pointer on optional field'\n"
        "}"
    )
    client = LLMClient(FakeAI([content]))
    result = await client.generate_structured(
        response_model=RootCauseAnalysis, system_prompt="", user_prompt=""
    )
    assert result.category == "CODE_BUG"
    assert result.safe_to_repair is True
    assert result.confidence == 0.95
    assert result.affected_files == ["app/demo_api/bugs.py"]


def test_parse_json_handles_nested_single_quoted_dict_with_booleans():
    content = "{'summary': 'Fix bug', 'files_changed': ['app/demo_api/bugs.py'], 'diff': '--- a/bugs.py\\n+++ b/bugs.py\\n', 'reason': 'null check', 'risk': 'low', 'active': true, 'disabled': false, 'extra': null}"
    parsed = _parse_json(content)
    assert parsed["summary"] == "Fix bug"
    assert parsed["active"] is True
    assert parsed["disabled"] is False
    assert parsed["extra"] is None




def test_choice_content_falls_back_to_reasoning_fields():
    assert _choice_content(
        {"choices": [{"message": {"role": "assistant", "content": None, "reasoning_content": '{"name": "x"}'}}]}
    ) == '{"name": "x"}'
    assert _choice_content(
        {"choices": [{"message": {"content": "", "reasoning": '{"ok": true}'}}]}
    ) == '{"ok": true}'
    assert _choice_content({"choices": [{"message": {"content": None}}]}) == ""
    assert _choice_content({}) == ""
    assert _choice_content(None) == ""  # type: ignore[arg-type]


def test_parse_json_accepts_none_without_raising_typeerror():
    with pytest.raises((json.JSONDecodeError, ValueError)):
        _parse_json(None)  # type: ignore[arg-type]


def test_parse_json_recovers_after_unclosed_think_block():
    content = (
        "<think>\n"
        "Looking at the stack trace. payment_method is None.\n"
        '{"name": "recovered", "value": 4}'
    )
    assert _parse_json(content) == {"name": "recovered", "value": 4}


def test_root_cause_accepts_percentage_confidence():
    analysis = RootCauseAnalysis.model_validate(
        {
            "root_cause": "null deref",
            "classification": "CODE_BUG",
            "confidence": "95%",
            "affected_files": ["app/demo_api/bugs.py"],
        }
    )
    assert analysis.confidence == 0.95

    analysis = RootCauseAnalysis.model_validate(
        {
            "root_cause": "null deref",
            "confidence": 87,
        }
    )
    assert analysis.confidence == 0.87


async def test_generate_structured_recovers_from_null_content():
    fake = FakeAI(['{"name": "recovered", "value": 2}'])
    original_chat = fake.chat
    calls = {"n": 0}

    async def chat_with_null(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "choices": [{"message": {"role": "assistant", "content": None}}],
                "usage": {},
            }
        return await original_chat(**kwargs)

    fake.chat = chat_with_null  # type: ignore[method-assign]
    client = LLMClient(fake)
    result = await client.generate_structured(
        response_model=SampleModel, system_prompt="", user_prompt=""
    )
    assert result.name == "recovered"
    assert result.value == 2


async def test_generate_structured_uses_reasoning_content():
    fake = FakeAI([])

    async def chat_reasoning(**kwargs):
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "reasoning_content": '{"name": "from_reasoning", "value": 8}',
                    }
                }
            ],
            "usage": {},
        }

    fake.chat = chat_reasoning  # type: ignore[method-assign]
    client = LLMClient(fake)
    result = await client.generate_structured(
        response_model=SampleModel, system_prompt="", user_prompt=""
    )
    assert result.name == "from_reasoning"
    assert result.value == 8


async def test_generate_structured_does_not_crash_on_missing_choices():
    fake = FakeAI([])

    async def chat_empty(**kwargs):
        return {"choices": [], "usage": {}}

    fake.chat = chat_empty  # type: ignore[method-assign]
    client = LLMClient(fake)
    with pytest.raises(AIProviderError, match="valid SampleModel"):
        await client.generate_structured(
            response_model=SampleModel, system_prompt="", user_prompt=""
        )
