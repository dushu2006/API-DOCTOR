"""Tests for AI response parsing and structured output handling."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent.llm_client import LLMClient
from app.agent.root_cause_agent import RootCauseAnalysis


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

