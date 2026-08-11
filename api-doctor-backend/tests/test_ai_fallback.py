"""Tests for model fallback on timeout / failure."""

from __future__ import annotations

import httpx
import pytest

from app.ai.base import AIProviderError
from app.ai.nim_client import NIMClient
from app.agent.llm_client import LLMClient
from app.core.config import settings
from pydantic import BaseModel, Field


class SampleModel(BaseModel):
    name: str
    value: int = Field(..., ge=0)


class FakeAIWithFallback:
    """Simulates primary model failure then fallback success."""

    def __init__(self, fail_primary=True, fail_all_primary=False):
        self.calls: list[str] = []
        self.fail_primary = fail_primary
        self.fail_all_primary = fail_all_primary

    async def chat(self, *, model, messages, temperature=0.1, max_tokens=2048, response_format=None, stream=False):
        self.calls.append(model)
        # Simulate primary failure if configured
        if self.fail_all_primary and model == "primary-model":
            raise AIProviderError("simulated timeout on primary")
        if self.fail_primary and model == "primary-model" and len([c for c in self.calls if c == model]) == 1:
            raise AIProviderError("simulated timeout on primary")
        # Otherwise succeed
        return {"choices": [{"message": {"role": "assistant", "content": '{"name": "fallback_ok", "value": 10}'}}], "usage": {}}

    async def embed(self, model, texts):
        return [[0.0] * 4 for _ in texts]

    async def check_health(self):
        return True


async def test_llm_client_fallback_on_primary_failure():
    # Enable fallback and cache disabled for clarity
    orig_fallback = getattr(settings, "AI_MODEL_FALLBACK", True)
    orig_cache = getattr(settings, "AI_CACHE_ENABLED", True)
    orig_sem = getattr(settings, "AI_CACHE_SEMANTIC_ENABLED", False)
    orig_fast = settings.FAST_MODEL

    settings.AI_MODEL_FALLBACK = True
    settings.AI_CACHE_ENABLED = False
    settings.AI_CACHE_SEMANTIC_ENABLED = False
    settings.FAST_MODEL = "fast-model"

    try:
        fake = FakeAIWithFallback(fail_primary=True)
        client = LLMClient(fake)

        result = await client.generate_structured(
            response_model=SampleModel,
            system_prompt="sys",
            user_prompt="test fallback",
            model="primary-model",
        )
        assert result.name == "fallback_ok"
        # Should have tried primary then fallback
        assert "primary-model" in fake.calls
        assert "fast-model" in fake.calls
    finally:
        settings.AI_MODEL_FALLBACK = orig_fallback
        settings.AI_CACHE_ENABLED = orig_cache
        settings.AI_CACHE_SEMANTIC_ENABLED = orig_sem
        settings.FAST_MODEL = orig_fast


async def test_llm_client_no_fallback_when_disabled():
    orig_fallback = getattr(settings, "AI_MODEL_FALLBACK", True)
    orig_cache = getattr(settings, "AI_CACHE_ENABLED", True)
    settings.AI_MODEL_FALLBACK = False
    settings.AI_CACHE_ENABLED = False

    try:
        fake = FakeAIWithFallback(fail_primary=False, fail_all_primary=True)
        client = LLMClient(fake)

        with pytest.raises(AIProviderError):
            await client.generate_structured(
                response_model=SampleModel,
                system_prompt="sys",
                user_prompt="test no fallback",
                model="primary-model",
            )
        # Only primary tried (max_retries times)
        assert all(c == "primary-model" for c in fake.calls)
        assert len(fake.calls) >= 1
    finally:
        settings.AI_MODEL_FALLBACK = orig_fallback
        settings.AI_CACHE_ENABLED = orig_cache


# --- NIMClient low-level fallback test with mocked httpx -----------------


class DummyResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {"choices": [{"message": {"content": "{}"}}], "usage": {}}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://example.com")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self):
        return self._json


async def test_nim_client_fallback_on_timeout(monkeypatch):
    # Setup client with no real API key needed for mocked path
    # We will monkeypatch the client.post to raise Timeout then succeed

    orig_key = settings.NVIDIA_API_KEY
    orig_fallback = settings.AI_MODEL_FALLBACK
    orig_fast = settings.FAST_MODEL
    orig_req_timeout = getattr(settings, "AI_REQUEST_TIMEOUT_SECONDS", 35.0)
    orig_timeout = settings.AI_TIMEOUT_SECONDS
    orig_max_retries = settings.AI_MAX_RETRIES

    settings.NVIDIA_API_KEY = "test-key"
    settings.AI_MODEL_FALLBACK = True
    settings.FAST_MODEL = "fast-fallback-model"
    settings.AI_REQUEST_TIMEOUT_SECONDS = 1.0
    settings.AI_TIMEOUT_SECONDS = 5.0
    settings.AI_MAX_RETRIES = 1

    try:
        client = NIMClient()

        call_models = []

        async def mock_post(url, json=None, timeout=None):
            model_try = json.get("model") if json else "unknown"
            call_models.append(model_try)
            if model_try != settings.FAST_MODEL:
                # Simulate timeout on primary
                raise httpx.TimeoutException("simulated timeout")
            # Fallback succeeds
            return DummyResponse(
                json_data={
                    "choices": [{"message": {"role": "assistant", "content": '{"ok": true}'}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                    "model": model_try,
                }
            )

        monkeypatch.setattr(client.client, "post", mock_post)

        data = await client.chat(
            model="primary-model",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=10,
        )
        assert data["model"] == "fast-fallback-model"
        assert "primary-model" in call_models
        assert "fast-fallback-model" in call_models

        await client.close()
    finally:
        settings.NVIDIA_API_KEY = orig_key
        settings.AI_MODEL_FALLBACK = orig_fallback
        settings.FAST_MODEL = orig_fast
        settings.AI_REQUEST_TIMEOUT_SECONDS = orig_req_timeout
        settings.AI_TIMEOUT_SECONDS = orig_timeout
        settings.AI_MAX_RETRIES = orig_max_retries


async def test_nim_client_per_request_timeout_config():
    """Ensure request timeout is distinct from overall timeout."""
    orig_req = getattr(settings, "AI_REQUEST_TIMEOUT_SECONDS", 35.0)
    orig_overall = settings.AI_TIMEOUT_SECONDS

    settings.AI_REQUEST_TIMEOUT_SECONDS = 12.5
    settings.AI_TIMEOUT_SECONDS = 90.0

    try:
        client = NIMClient()
        assert client.request_timeout == 12.5
        assert client.timeout == 90.0
        assert client.request_timeout < client.timeout
        await client.close()
    finally:
        settings.AI_REQUEST_TIMEOUT_SECONDS = orig_req
        settings.AI_TIMEOUT_SECONDS = orig_overall
