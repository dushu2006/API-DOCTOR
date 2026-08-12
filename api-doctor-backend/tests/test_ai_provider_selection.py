"""AI-provider selection must be independent from sandbox execution mode."""

from __future__ import annotations

import pytest

from app.ai.base import create_ai_client, selected_ai_provider
from app.ai.mock_client import MockAIClient
from app.ai.nim_client import NIMClient
from app.core.config import settings


def test_local_sandbox_does_not_force_mock_ai(monkeypatch):
    monkeypatch.setattr(settings, "SANDBOX_MODE", "local")
    monkeypatch.setattr(settings, "AI_PROVIDER", "nvidia")
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "configured-test-key")

    assert selected_ai_provider() == "nvidia"
    assert isinstance(create_ai_client(), NIMClient)


def test_auto_provider_uses_visible_mock_fallback_without_key(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "auto")
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "")

    assert selected_ai_provider() == "mock"
    assert isinstance(create_ai_client(), MockAIClient)


def test_invalid_ai_provider_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "surprise")

    with pytest.raises(ValueError, match="AI_PROVIDER"):
        selected_ai_provider()
