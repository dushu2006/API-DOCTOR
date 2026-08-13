"""AI-provider selection must be independent from sandbox execution mode."""

from __future__ import annotations

import pytest

from app.ai.base import create_ai_client, selected_ai_provider
from app.ai.nim_client import NIMClient
from app.core.config import settings


def test_selection_resolves_to_real_nvidia_provider(monkeypatch):
    monkeypatch.setattr(settings, "SANDBOX_MODE", "local")
    monkeypatch.setattr(settings, "AI_PROVIDER", "nvidia")
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "configured-test-key")

    assert selected_ai_provider() == "nvidia"
    assert isinstance(create_ai_client(), NIMClient)


def test_auto_provider_resolves_to_nvidia_without_fake_fallback(monkeypatch):
    """There is no mock/demo fallback: ``auto`` always means the real provider.

    Even without an API key the factory still returns the real NIM client
    (which will fail loudly on the first real request) instead of silently
    producing a canned diagnosis.
    """
    monkeypatch.setattr(settings, "AI_PROVIDER", "auto")
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "")

    assert selected_ai_provider() == "nvidia"
    assert isinstance(create_ai_client(), NIMClient)


def test_invalid_ai_provider_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "mock")

    with pytest.raises(ValueError, match="AI_PROVIDER"):
        selected_ai_provider()
