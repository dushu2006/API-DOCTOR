"""AI response cache — exact + optional semantic.

- Exact cache: keyed by sha256(model + system_prompt + user_prompt + response_model).
  In-memory TTL LRU, no external services.
- Semantic cache (optional): if EMBEDDING_MODEL is configured and
  AI_CACHE_SEMANTIC_ENABLED=true, embed the request and return a cached
  response when cosine similarity is above threshold. Degrades gracefully if
  embeddings fail.

Secrets are never cached: the context builder sanitises payloads before they
reach the LLM, and this module only caches already-sanitised sanitized data.
"""

from __future__ import annotations

import hashlib
import math
import time
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def make_cache_key(*parts: str) -> str:
    """Deterministic sha256 of concatenated parts."""
    h = hashlib.sha256()
    for p in parts:
        if p is None:
            continue
        h.update(str(p).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


@dataclass
class _Entry:
    value: Any
    expiry: float
    embedding: list[float] | None = None
    model: str | None = None


class AIResponseCache:
    """In-memory TTL LRU cache with optional semantic lookup."""

    def __init__(self, max_size: int = 128, ttl_seconds: int = 3600) -> None:
        self.max_size = max_size
        self.ttl = ttl_seconds
        self._store: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Core exact cache
    # ------------------------------------------------------------------
    def get(self, key: str) -> Any | None:
        now = time.time()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.expiry < now:
                # expired
                del self._store[key]
                return None
            # LRU bump
            self._store.move_to_end(key)
            return entry.value

    def set(self, key: str, value: Any, *, embedding: list[float] | None = None, model: str | None = None) -> None:
        now = time.time()
        expiry = now + self.ttl
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = _Entry(value=value, expiry=expiry, embedding=embedding, model=model)
            # Evict oldest if over capacity
            while len(self._store) > self.max_size:
                self._store.popitem(last=False)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    # ------------------------------------------------------------------
    # Semantic cache helpers
    # ------------------------------------------------------------------
    def set_with_embedding(self, key: str, value: Any, embedding: list[float] | None, model: str | None = None) -> None:
        self.set(key, value, embedding=embedding, model=model)

    def get_semantic(
        self,
        query_embedding: list[float],
        threshold: float = 0.9,
        *,
        model: str | None = None,
    ) -> Any | None:
        """Return cached value whose embedding similarity exceeds threshold.

        If ``model`` is given, only entries for that model are considered (to
        avoid cross-task pollution, e.g. root-cause vs fix).
        """
        if not query_embedding:
            return None
        best: tuple[float, Any] | None = None
        now = time.time()
        with self._lock:
            # iterate snapshot to avoid holding lock during similarity? similarity is cheap.
            items = list(self._store.items())

        for _key, entry in items:
            if entry.expiry < now:
                continue
            if entry.embedding is None:
                continue
            if model is not None and entry.model is not None and entry.model != model:
                continue
            sim = _cosine(query_embedding, entry.embedding)
            if sim >= threshold:
                if best is None or sim > best[0]:
                    best = (sim, entry.value)

        if best:
            return best[1]
        return None

    def get_semantic_with_score(
        self,
        query_embedding: list[float],
        threshold: float = 0.9,
        *,
        model: str | None = None,
    ) -> tuple[float, Any] | None:
        best_score = -1.0
        best_val = None
        now = time.time()
        with self._lock:
            items = list(self._store.items())
        for _key, entry in items:
            if entry.expiry < now or entry.embedding is None:
                continue
            if model is not None and entry.model is not None and entry.model != model:
                continue
            sim = _cosine(query_embedding, entry.embedding)
            if sim >= threshold and sim > best_score:
                best_score = sim
                best_val = entry.value
        if best_val is not None:
            return best_score, best_val
        return None


# Global singleton (default size/ttl from settings when first imported, but
# mutable via settings changes; we lazily read settings in a helper).
_global_cache: AIResponseCache | None = None
_global_lock = threading.Lock()


def get_global_cache() -> AIResponseCache:
    global _global_cache
    if _global_cache is None:
        with _global_lock:
            if _global_cache is None:
                try:
                    from app.core.config import settings

                    max_size = int(getattr(settings, "AI_CACHE_MAX_SIZE", 128))
                    ttl = int(getattr(settings, "AI_CACHE_TTL_SECONDS", 3600))
                except Exception:
                    max_size = 128
                    ttl = 3600
                _global_cache = AIResponseCache(max_size=max_size, ttl_seconds=ttl)
    return _global_cache


# Convenience alias used by LLMClient
ai_cache = get_global_cache()


def clear_global_cache() -> None:
    get_global_cache().clear()
