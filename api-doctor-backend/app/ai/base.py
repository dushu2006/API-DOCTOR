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
    from app.ai.nim_client import NIMClient

    # Future providers can be selected here (e.g. OPENAI, ANTHROPIC) based on
    # an ``AI_PROVIDER`` setting. NVIDIA NIM is the initial default.
    return NIMClient()
