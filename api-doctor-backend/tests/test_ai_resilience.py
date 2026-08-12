"""Resilience tests for the AI call layer.

Covers the failure mode that previously surfaced as INVESTIGATION_FAILED in
the UI: a slow or hung NVIDIA NIM endpoint causing ReadTimeout after ReadTimeout,
with retries multiplying the wait to several minutes before failing.

Expected behaviour:
* NIMClient honours the overall AI_TIMEOUT_SECONDS budget across retries and
  fallback models (fail fast with a clear error instead of stalling).
* Streaming requests keep timeout/retry/fallback semantics.
* LLMClient streams by default and does not re-attempt a provider call after
  the provider itself exhausted its retries.
"""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel, Field

from app.ai.base import AIProviderError
from app.ai.nim_client import NIMClient
from app.agent.llm_client import LLMClient
from app.core.config import settings


class SampleModel(BaseModel):
    name: str
    value: int = Field(..., ge=0)


# ---------------------------------------------------------------------------
# NIMClient: overall budget enforcement
# ---------------------------------------------------------------------------


async def test_nim_client_enforces_overall_timeout_budget(monkeypatch):
    """A hung endpoint must be bounded by AI_TIMEOUT_SECONDS, not by
    AI_MAX_RETRIES * AI_REQUEST_TIMEOUT_SECONDS."""
    orig_key = settings.NVIDIA_API_KEY
    orig_fallback = settings.AI_MODEL_FALLBACK
    orig_fast = settings.FAST_MODEL
    orig_req = settings.AI_REQUEST_TIMEOUT_SECONDS
    orig_overall = settings.AI_TIMEOUT_SECONDS
    orig_retries = settings.AI_MAX_RETRIES

    settings.NVIDIA_API_KEY = "test-key"
    settings.AI_MODEL_FALLBACK = False
    settings.FAST_MODEL = "unused-fallback"
    settings.AI_REQUEST_TIMEOUT_SECONDS = 1.0
    settings.AI_TIMEOUT_SECONDS = 1.2
    settings.AI_MAX_RETRIES = 3

    try:
        client = NIMClient()
        calls: list[str] = []

        async def hung_post(url, json=None, timeout=None):
            calls.append(json.get("model") if json else "?")
            raise httpx.TimeoutException("simulated hang")

        monkeypatch.setattr(client.client, "post", hung_post)

        with pytest.raises(AIProviderError, match="AI_TIMEOUT_SECONDS"):
            await client.chat(
                model="primary-model",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=4,
            )

        # The backoff sleeps consumed the budget before the 3rd retry started.
        assert calls == ["primary-model", "primary-model"]
        await client.close()
    finally:
        settings.NVIDIA_API_KEY = orig_key
        settings.AI_MODEL_FALLBACK = orig_fallback
        settings.FAST_MODEL = orig_fast
        settings.AI_REQUEST_TIMEOUT_SECONDS = orig_req
        settings.AI_TIMEOUT_SECONDS = orig_overall
        settings.AI_MAX_RETRIES = orig_retries


# ---------------------------------------------------------------------------
# NIMClient: streaming path
# ---------------------------------------------------------------------------


class FakeStream:
    """Stand-in for an httpx streaming response."""

    status_code = 200

    def __init__(self, fail_with: Exception | None = None):
        self._fail = fail_with
        self._lines = [
            'data: {"choices":[{"delta":{"content":"{\\"ok\\": true}"}}]}',
            "data: [DONE]",
        ]

    async def __aenter__(self):
        if self._fail is not None:
            raise self._fail
        return self

    async def __aexit__(self, *args):
        return False

    async def aread(self) -> bytes:
        return b""

    async def aiter_lines(self):
        for line in self._lines:
            yield line


async def test_nim_client_streaming_timeout_falls_back_to_fast_model(monkeypatch):
    """A streaming timeout on the primary model must still fall back to
    FAST_MODEL, exactly like the non-streaming path."""
    orig_key = settings.NVIDIA_API_KEY
    orig_fallback = settings.AI_MODEL_FALLBACK
    orig_fast = settings.FAST_MODEL
    orig_req = settings.AI_REQUEST_TIMEOUT_SECONDS
    orig_overall = settings.AI_TIMEOUT_SECONDS
    orig_retries = settings.AI_MAX_RETRIES

    settings.NVIDIA_API_KEY = "test-key"
    settings.AI_MODEL_FALLBACK = True
    settings.FAST_MODEL = "fast-fallback-model"
    settings.AI_REQUEST_TIMEOUT_SECONDS = 1.0
    settings.AI_TIMEOUT_SECONDS = 5.0
    settings.AI_MAX_RETRIES = 1

    try:
        client = NIMClient()
        calls: list[str] = []

        def fake_stream(method, url, json=None, timeout=None):
            model_try = json.get("model") if json else "?"
            calls.append(model_try)
            if model_try == settings.FAST_MODEL:
                return FakeStream()
            return FakeStream(fail_with=httpx.TimeoutException("stream timeout"))

        monkeypatch.setattr(client.client, "stream", fake_stream)

        data = await client.chat(
            model="primary-model",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=10,
            stream=True,
        )

        assert calls == ["primary-model", "fast-fallback-model"]
        assert data["model"] == "fast-fallback-model"
        assert json.loads(data["choices"][0]["message"]["content"]) == {"ok": True}
        await client.close()
    finally:
        settings.NVIDIA_API_KEY = orig_key
        settings.AI_MODEL_FALLBACK = orig_fallback
        settings.FAST_MODEL = orig_fast
        settings.AI_REQUEST_TIMEOUT_SECONDS = orig_req
        settings.AI_TIMEOUT_SECONDS = orig_overall
        settings.AI_MAX_RETRIES = orig_retries


async def test_nim_client_streaming_http_error_is_provider_error(monkeypatch):
    """A non-200 streaming response surfaces as AIProviderError, not as a
    confusing raw exception."""
    orig_key = settings.NVIDIA_API_KEY
    orig_fallback = settings.AI_MODEL_FALLBACK
    orig_req = settings.AI_REQUEST_TIMEOUT_SECONDS
    orig_overall = settings.AI_TIMEOUT_SECONDS
    orig_retries = settings.AI_MAX_RETRIES

    settings.NVIDIA_API_KEY = "test-key"
    settings.AI_MODEL_FALLBACK = False
    settings.AI_REQUEST_TIMEOUT_SECONDS = 1.0
    settings.AI_TIMEOUT_SECONDS = 5.0
    settings.AI_MAX_RETRIES = 1

    try:
        client = NIMClient()

        class ErrorStream(FakeStream):
            status_code = 429

        def fake_stream(method, url, json=None, timeout=None):
            return ErrorStream()

        monkeypatch.setattr(client.client, "stream", fake_stream)

        with pytest.raises(AIProviderError, match="streaming chat failed"):
            await client.chat(
                model="primary-model",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=10,
                stream=True,
            )
        await client.close()
    finally:
        settings.NVIDIA_API_KEY = orig_key
        settings.AI_MODEL_FALLBACK = orig_fallback
        settings.AI_REQUEST_TIMEOUT_SECONDS = orig_req
        settings.AI_TIMEOUT_SECONDS = orig_overall
        settings.AI_MAX_RETRIES = orig_retries


# ---------------------------------------------------------------------------
# LLMClient: streaming flag + no double-retry spiral
# ---------------------------------------------------------------------------


class RecordingAI:
    """Records every chat call (model + stream flag); optionally fails."""

    def __init__(self, fail_all: bool = False):
        self.calls: list[dict] = []
        self.fail_all = fail_all

    async def chat(self, *, model, messages, temperature=0.1, max_tokens=2048,
                   response_format=None, stream=False):
        self.calls.append({"model": model, "stream": stream})
        if self.fail_all:
            raise AIProviderError("simulated provider outage")
        content = '{"name": "ok", "value": 7}'
        return {"choices": [{"message": {"role": "assistant", "content": content}}], "usage": {}}

    async def embed(self, model, texts):
        return [[0.0] * 4 for _ in texts]

    async def check_health(self):
        return True


async def test_llm_client_streams_by_default():
    orig_cache = settings.AI_CACHE_ENABLED
    orig_fallback = settings.AI_MODEL_FALLBACK
    orig_stream = getattr(settings, "AI_STREAMING", True)
    settings.AI_CACHE_ENABLED = False
    settings.AI_MODEL_FALLBACK = False
    settings.AI_STREAMING = True

    try:
        fake = RecordingAI()
        client = LLMClient(fake)
        result = await client.generate_structured(
            response_model=SampleModel,
            system_prompt="sys",
            user_prompt="user",
            model="primary-model",
        )
        assert result.name == "ok"
        assert fake.calls == [{"model": "primary-model", "stream": True}]
    finally:
        settings.AI_CACHE_ENABLED = orig_cache
        settings.AI_MODEL_FALLBACK = orig_fallback
        settings.AI_STREAMING = orig_stream


async def test_llm_client_respects_streaming_disabled():
    orig_cache = settings.AI_CACHE_ENABLED
    orig_fallback = settings.AI_MODEL_FALLBACK
    orig_stream = getattr(settings, "AI_STREAMING", True)
    settings.AI_CACHE_ENABLED = False
    settings.AI_MODEL_FALLBACK = False
    settings.AI_STREAMING = False

    try:
        fake = RecordingAI()
        client = LLMClient(fake)
        await client.generate_structured(
            response_model=SampleModel,
            system_prompt="sys",
            user_prompt="user",
            model="primary-model",
        )
        assert fake.calls == [{"model": "primary-model", "stream": False}]
    finally:
        settings.AI_CACHE_ENABLED = orig_cache
        settings.AI_MODEL_FALLBACK = orig_fallback
        settings.AI_STREAMING = orig_stream


async def test_llm_client_fails_fast_on_provider_error_without_fallback():
    """The provider already exhausted its retries; the LLM layer must not
    re-call the same dead model AI_MAX_RETRIES times."""
    orig_cache = settings.AI_CACHE_ENABLED
    orig_fallback = settings.AI_MODEL_FALLBACK
    settings.AI_CACHE_ENABLED = False
    settings.AI_MODEL_FALLBACK = False

    try:
        fake = RecordingAI(fail_all=True)
        client = LLMClient(fake)
        with pytest.raises(AIProviderError):
            await client.generate_structured(
                response_model=SampleModel,
                system_prompt="sys",
                user_prompt="user",
                model="primary-model",
            )
        # Exactly one provider call — no retry spiral.
        assert fake.calls == [{"model": "primary-model", "stream": True}]
    finally:
        settings.AI_CACHE_ENABLED = orig_cache
        settings.AI_MODEL_FALLBACK = orig_fallback


async def test_llm_client_still_tries_fallback_model_on_provider_error():
    """With fallback enabled, a provider error on the primary model moves on
    to FAST_MODEL instead of retrying the primary."""
    orig_cache = settings.AI_CACHE_ENABLED
    orig_fallback = settings.AI_MODEL_FALLBACK
    orig_fast = settings.FAST_MODEL
    settings.AI_CACHE_ENABLED = False
    settings.AI_MODEL_FALLBACK = True
    settings.FAST_MODEL = "fast-model"

    try:
        fake = RecordingAI(fail_all=False)

        async def failing_chat(*, model, messages, temperature=0.1, max_tokens=2048,
                               response_format=None, stream=False):
            fake.calls.append({"model": model, "stream": stream})
            if model == "primary-model":
                raise AIProviderError("simulated timeout")
            content = '{"name": "fallback_ok", "value": 9}'
            return {"choices": [{"message": {"role": "assistant", "content": content}}], "usage": {}}

        fake.chat = failing_chat
        client = LLMClient(fake)
        result = await client.generate_structured(
            response_model=SampleModel,
            system_prompt="sys",
            user_prompt="user",
            model="primary-model",
        )
        assert result.name == "fallback_ok"
        assert [c["model"] for c in fake.calls] == ["primary-model", "fast-model"]
    finally:
        settings.AI_CACHE_ENABLED = orig_cache
        settings.AI_MODEL_FALLBACK = orig_fallback
        settings.FAST_MODEL = orig_fast
