"""NVIDIA NIM client.

Speaks the OpenAI-compatible HTTP API exposed by NVIDIA NIM
(``https://integrate.api.nvidia.com/v1``) using httpx. Supports configurable
model, temperature, max tokens, timeouts, retries, structured responses and
streaming, plus automatic fallback to FAST_MODEL on timeout/failure.

The API key never leaves the backend.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from app.ai.base import AIProviderError, AIClient
from app.core.config import settings

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class NIMClient(AIClient):
    name = "nvidia-nim"

    def __init__(self) -> None:
        self.base_url = settings.NVIDIA_BASE_URL.rstrip("/")
        self.api_key = settings.NVIDIA_API_KEY
        # Overall timeout (kept for backwards compat) but per-request timeout
        # uses AI_REQUEST_TIMEOUT_SECONDS for fail-fast behaviour.
        self.timeout = settings.AI_TIMEOUT_SECONDS
        # Per-attempt timeout, distinct from overall AI_TIMEOUT_SECONDS.
        self.request_timeout = getattr(settings, "AI_REQUEST_TIMEOUT_SECONDS", 35.0)
        self.max_retries = settings.AI_MAX_RETRIES
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            # Use overall timeout as client-level default; per-request we
            # override with request_timeout for fast failure.
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
    async def _single_chat_request(
        self,
        *,
        model: str,
        payload: dict[str, Any],
        timeout: float,
        stream: bool,
        url: str,
    ) -> dict[str, Any]:
        if stream:
            return await self._stream_chat(url, payload, model, timeout=timeout)

        resp = await self.client.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

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

        base_payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            base_payload["response_format"] = response_format

        url = f"{self.base_url}/chat/completions"

        # Build fallback chain: primary -> FAST_MODEL (once) if enabled.
        fallback_enabled = bool(getattr(settings, "AI_MODEL_FALLBACK", True))
        fast_model = getattr(settings, "FAST_MODEL", "")
        models_to_try: list[str] = [model]
        if fallback_enabled and fast_model and fast_model != model:
            models_to_try.append(fast_model)

        # Overall wall-clock budget across every attempt and fallback model.
        # A slow or hung endpoint must fail fast with a clear error instead
        # of silently burning minutes of wall-clock time per retry.
        overall_budget = max(1.0, float(self.timeout))
        deadline = time.perf_counter() + overall_budget

        last_exc: Exception | None = None
        overall_start = time.perf_counter()

        for model_idx, try_model in enumerate(models_to_try):
            is_fallback = model_idx > 0
            # For fallback we attempt only once (spec); primary uses max_retries.
            attempts = 1 if is_fallback else max(1, self.max_retries)

            # Payload with current model
            payload = {**base_payload, "model": try_model}

            for attempt in range(attempts):
                # Enforce the overall budget before spending another attempt.
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    raise AIProviderError(
                        f"AI chat timed out after {overall_budget:.0f}s "
                        f"(AI_TIMEOUT_SECONDS budget) trying {models_to_try}"
                    ) from last_exc

                per_attempt_timeout = min(self.request_timeout, remaining)
                try:
                    start = time.perf_counter()
                    data = await self._single_chat_request(
                        model=try_model,
                        payload=payload,
                        timeout=per_attempt_timeout,
                        stream=stream,
                        url=url,
                    )
                    duration = time.perf_counter() - start
                    total_duration = time.perf_counter() - overall_start
                    usage = data.get("usage", {})

                    if is_fallback:
                        logger.warning(
                            "AI fallback succeeded: primary=%s fallback=%s duration_s=%.2f total_s=%.2f",
                            model,
                            try_model,
                            duration,
                            total_duration,
                        )
                    else:
                        logger.info(
                            "AI chat model=%s tokens_in=%s tokens_out=%s duration_s=%.2f",
                            try_model,
                            usage.get("prompt_tokens"),
                            usage.get("completion_tokens"),
                            duration,
                        )
                    return data

                except httpx.TimeoutException as exc:
                    last_exc = exc
                    logger.warning(
                        "AI chat timeout model=%s attempt=%s/%s timeout=%.1fs err=%s",
                        try_model,
                        attempt + 1,
                        attempts,
                        per_attempt_timeout,
                        type(exc).__name__,
                    )
                    if attempt + 1 < attempts:
                        # exponential backoff
                        await asyncio.sleep(min(0.5 * (2 ** attempt), 4.0))
                        continue
                    # attempt exhausted for this model, break to maybe fallback
                    break

                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    body_snip = exc.response.text[:300] if hasattr(exc.response, "text") else ""
                    last_exc = AIProviderError(
                        f"NVIDIA NIM chat failed ({status}): {body_snip}"
                    )
                    logger.warning(
                        "AI chat HTTP error model=%s attempt=%s/%s status=%s",
                        try_model,
                        attempt + 1,
                        attempts,
                        status,
                    )
                    if status in RETRYABLE_STATUS and attempt + 1 < attempts:
                        await asyncio.sleep(min(0.5 * (2 ** attempt), 4.0))
                        continue
                    break

                except AIProviderError as exc:
                    last_exc = exc
                    logger.warning(
                        "AI provider error model=%s attempt=%s/%s err=%s",
                        try_model,
                        attempt + 1,
                        attempts,
                        str(exc)[:300],
                    )
                    if attempt + 1 < attempts:
                        await asyncio.sleep(min(0.5 * (2 ** attempt), 2.0))
                        continue
                    break

                except Exception as exc:  # noqa: BLE001
                    last_exc = AIProviderError(f"Unexpected AI error: {exc}")
                    logger.warning(
                        "AI chat unexpected error model=%s attempt=%s/%s err=%s",
                        try_model,
                        attempt + 1,
                        attempts,
                        type(exc).__name__,
                    )
                    break

            # If we are here, current model exhausted. If fallback chain remains, log.
            if not is_fallback and len(models_to_try) > 1:
                logger.warning(
                    "AI primary model %s failed (%s); attempting fallback %s",
                    model,
                    type(last_exc).__name__ if last_exc else "unknown",
                    models_to_try[1],
                )
                # continue loop to try fallback
            else:
                # no more models
                break

        # All models exhausted
        elapsed = time.perf_counter() - overall_start
        err_msg = (
            f"AI chat failed after trying {models_to_try} "
            f"(elapsed {elapsed:.1f}s): {last_exc}"
        )
        raise AIProviderError(err_msg) from last_exc

    async def _stream_chat(self, url: str, payload: dict, model: str, timeout: float | None = None) -> dict[str, Any]:
        full_text: list[str] = []
        usage: dict[str, Any] = {}
        t = timeout or self.request_timeout
        try:
            async with self.client.stream("POST", url, json={**payload, "stream": True}, timeout=t) as resp:
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
        except httpx.TimeoutException as exc:
            # Re-raise so chat() treats it like any other request timeout
            # (logs, backs off, and can still fall back to FAST_MODEL).
            raise exc
        content = "".join(full_text)
        return {
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": usage,
            "model": model,
        }

    # ------------------------------------------------------------------
    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise AIProviderError("NVIDIA_API_KEY is not configured")
        url = f"{self.base_url}/embeddings"
        # Use per-request timeout for embeddings as well (fail fast)
        timeout = self.request_timeout
        attempts = max(1, self.max_retries)
        last_exc: Exception | None = None

        for attempt in range(attempts):
            try:
                resp = await self.client.post(
                    url, json={"model": model, "input": texts}, timeout=timeout
                )
                resp.raise_for_status()
                data = resp.json()
                return [item["embedding"] for item in data.get("data", [])]
            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning(
                    "AI embeddings timeout model=%s attempt=%s/%s",
                    model,
                    attempt + 1,
                    attempts,
                )
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue
                raise AIProviderError(f"NVIDIA NIM embeddings timed out") from exc
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code in RETRYABLE_STATUS and attempt + 1 < attempts:
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue
                raise AIProviderError(
                    f"NVIDIA NIM embeddings failed ({exc.response.status_code}): {exc.response.text[:500]}"
                ) from exc

        raise AIProviderError(f"Embeddings failed after {attempts} attempts: {last_exc}") from last_exc

    # ------------------------------------------------------------------
    async def check_health(self) -> bool:
        try:
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
