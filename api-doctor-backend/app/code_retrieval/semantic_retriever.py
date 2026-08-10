"""Semantic code retrieval (optional).

Uses the configured embedding model through the AI provider to rank candidate
files by relevance to the failure. If no embedding model is configured (or the
call fails) this degrades gracefully to the traceback-based ranking and never
blocks the pipeline.
"""

from __future__ import annotations

from app.code_retrieval.local_retriever import CodeSnippet, LocalRetriever
from app.core.config import settings


class SemanticRetriever:
    def __init__(self, local: LocalRetriever | None = None, ai_client=None) -> None:
        self.local = local or LocalRetriever()
        self.ai = ai_client

    def enabled(self) -> bool:
        if not settings.EMBEDDING_MODEL:
            return False
        if self.ai is None:
            return False
        return True

    async def rerank(
        self, candidates: list[CodeSnippet], query: str
    ) -> list[CodeSnippet]:
        """Re-rank candidates by embedding similarity (best-effort)."""
        if not self.enabled():
            return candidates
        try:
            texts = [f"{c['path']}\n{c['content'][:800]}" for c in candidates]
            query_vec = await self.ai.embed(query)
            doc_vecs = await self.ai.embed(texts)
        except Exception:
            return candidates

        def sim(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            na = sum(x * x for x in a) ** 0.5
            nb = sum(x * x for x in b) ** 0.5
            return dot / (na * nb) if na and nb else 0.0

        scored = sorted(
            zip(candidates, doc_vecs),
            key=lambda pair: sim(query_vec, pair[1]),
            reverse=True,
        )
        return [c for c, _ in scored]
