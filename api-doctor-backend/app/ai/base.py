"""AI provider abstraction.

The rest of the system talks only to :class:`AIClient`. NVIDIA NIM is the
initial provider; additional providers can be added by implementing the same
interface and registering them in :func:`create_ai_client`.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class AIClient(ABC):
    name: str = "base"

    @abstractmethod
    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 2048,
        response_format: dict | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Send a chat completion.

        Returns the parsed JSON response body (OpenAI-compatible shape):
        ``{"choices": [...], "usage": {...}, "model": "..."}``.
        """

    @abstractmethod
    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors for the given texts."""

    @abstractmethod
    async def check_health(self) -> bool:
        """True if the provider is reachable."""


class AIProviderError(Exception):
    """Raised when an AI provider call fails after retries."""


def selected_ai_provider() -> str:
    """Return the effective provider name without exposing configuration secrets."""
    from app.core.config import settings

    configured = settings.AI_PROVIDER.strip().lower()
    if configured not in {"auto", "nvidia", "mock"}:
        raise ValueError("AI_PROVIDER must be one of: auto, nvidia, mock")
    if configured == "auto":
        return "nvidia" if settings.has_nvidia else "mock"
    return configured


def create_ai_client() -> AIClient:
    """Factory — pick a concrete provider independently of sandbox mode."""
    from app.ai.mock_client import MockAIClient
    from app.ai.nim_client import NIMClient
    from app.core.config import settings

    provider = selected_ai_provider()
    if provider == "mock":
        if settings.AI_PROVIDER.strip().lower() == "auto":
            logger.warning(
                "AI_PROVIDER=auto and NVIDIA_API_KEY is not configured; "
                "using deterministic MockAIClient"
            )
        else:
            logger.warning("AI_PROVIDER=mock; using deterministic MockAIClient")
        return MockAIClient()

    if not settings.has_nvidia:
        logger.error(
            "AI_PROVIDER=nvidia but NVIDIA_API_KEY is not configured; "
            "provider requests will fail"
        )
    return NIMClient()
