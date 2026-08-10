"""NVIDIA NIM client.

Speaks the OpenAI-compatible HTTP API exposed by NVIDIA NIM
(``https://integrate.api.nvidia.com/v1``) using httpx. Supports configurable
model, temperature, max tokens, timeouts, retries, structured responses and
streaming. The API key never leaves the backend.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.ai.base import AIProviderError, AIClient
from app.core.config import settings

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS
    return False


class NIMClient(AIClient):
    name = "nvidia-nim"

    def __init__(self) -> None:
        self.base_url = settings.NVIDIA_BASE_URL.rstrip("/")
        self.api_key = settings.NVIDIA_API_KEY
        self.timeout = settings.AI_TIMEOUT_SECONDS
        self.max_retries = settings.AI_MAX_RETRIES
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers=self._headers(),
            )
        return self._client

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    @retry(
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException, AIProviderError)),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        stop=stop_after_attempt(settings.AI_MAX_RETRIES),
        reraise=True,
    )
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
        if not self.api_key:
            raise AIProviderError("NVIDIA_API_KEY is not configured")

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        start = time.perf_counter()
        url = f"{self.base_url}/chat/completions"

        if stream:
            return await self._stream_chat(url, payload, model)

        try:
            resp = await self.client.post(url, json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500]
            raise AIProviderError(
                f"NVIDIA NIM chat failed ({exc.response.status_code}): {body}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise AIProviderError(f"NVIDIA NIM chat timed out after {self.timeout}s") from exc

        data = resp.json()
        duration = time.perf_counter() - start
        usage = data.get("usage", {})
        logger.info(
            "AI chat model=%s tokens_in=%s tokens_out=%s duration_s=%.2f",
            model, usage.get("prompt_tokens"), usage.get("completion_tokens"), duration,
        )
        return data

    async def _stream_chat(self, url: str, payload: dict, model: str) -> dict[str, Any]:
        full_text: list[str] = []
        usage: dict[str, Any] = {}
        async with self.client.stream("POST", url, json={**payload, "stream": True}) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise AIProviderError(
                    f"NVIDIA NIM streaming chat failed ({resp.status_code}): {body[:500]!r}"
                )
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                try:
                    obj = json.loads(chunk)
                except json.JSONDecodeError:
                    continue
                delta = obj.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content")
                if content:
                    full_text.append(content)
                if obj.get("usage"):
                    usage = obj["usage"]
        content = "".join(full_text)
        return {
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": usage,
            "model": model,
        }

    # ------------------------------------------------------------------
    @retry(
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException, AIProviderError)),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        stop=stop_after_attempt(settings.AI_MAX_RETRIES),
        reraise=True,
    )
    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise AIProviderError("NVIDIA_API_KEY is not configured")
        url = f"{self.base_url}/embeddings"
        try:
            resp = await self.client.post(url, json={"model": model, "input": texts})
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise AIProviderError(
                f"NVIDIA NIM embeddings failed ({exc.response.status_code}): {exc.response.text[:500]}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise AIProviderError(f"NVIDIA NIM embeddings timed out") from exc
        data = resp.json()
        return [item["embedding"] for item in data.get("data", [])]

    # ------------------------------------------------------------------
    async def check_health(self) -> bool:
        try:
            # A minimal completion probes connectivity without requiring the key.
            data = await asyncio.wait_for(
                self.chat(
                    model=settings.FAST_MODEL,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1,
                ),
                timeout=min(self.timeout, 30),
            )
            return bool(data.get("choices"))
        except Exception:
            return False
