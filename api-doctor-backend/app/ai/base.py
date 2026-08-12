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


def create_ai_client() -> AIClient:
    """Factory — pick a concrete provider from configuration."""
    # Default to NVIDIA NIM but fall back to a local mock client if the
    # provider is unavailable (useful for development and CI without keys).
    from app.ai.nim_client import NIMClient
    from app.ai.mock_client import MockAIClient

    from app.core.config import settings

    # If running in a local sandbox (developer environment), prefer the
    # mock client to avoid external API calls and rate limits.
    # Prefer the explicit environment variable first so a restarted or
    # externally-launched process that sets `SANDBOX_MODE` at runtime will
    # reliably prefer the MockAIClient (avoids stale/cached settings).
    import os

    env_sandbox = os.getenv("SANDBOX_MODE")
    if env_sandbox and env_sandbox.lower() == "local":
        logger.info("SANDBOX_MODE=local (env): using MockAIClient")
        return MockAIClient()

    if getattr(settings, "SANDBOX_MODE", "docker") == "local":
        logger.info("SANDBOX_MODE=local (settings): using MockAIClient")
        return MockAIClient()

    # Otherwise, use the real NIM client when an API key is configured,
    # fall back to the mock client if initialization fails.
    try:
        if settings.has_nvidia:
            return NIMClient()
        else:
            logger.warning("NVIDIA API key not configured; using MockAIClient")
            return MockAIClient()
    except Exception:
        logger.exception("Failed to initialize NIMClient; using MockAIClient")
        return MockAIClient()
