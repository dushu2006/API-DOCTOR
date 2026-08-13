"""AI provider abstraction.

The rest of the system talks only to :class:`AIClient`. NVIDIA NIM is the
production provider; additional providers can be added by implementing the
same interface and registering them in :func:`create_ai_client`. There is no
mock or demo provider — the application diagnoses with the real configured
models or it fails clearly.
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
    """Return the effective provider name without exposing configuration secrets.

    The application runs on the real NVIDIA NIM provider only. ``auto`` still
    resolves to ``nvidia``; anything else is a configuration error.
    """
    from app.core.config import settings

    configured = settings.AI_PROVIDER.strip().lower()
    if configured not in {"auto", "nvidia"}:
        raise ValueError("AI_PROVIDER must be one of: auto, nvidia")
    return "nvidia"


def create_ai_client() -> AIClient:
    """Factory — always build the real NVIDIA NIM client.

    There is intentionally no mock/demo fallback. If ``NVIDIA_API_KEY`` is not
    configured the client will fail loudly on the first request rather than
    silently produce a canned diagnosis.
    """
    from app.ai.nim_client import NIMClient
    from app.core.config import settings

    if not settings.has_nvidia:
        logger.error(
            "NVIDIA_API_KEY is not configured. The application will not be able "
            "to run AI diagnosis until a real API key is provided."
        )
    return NIMClient()
