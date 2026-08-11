"""High-level LLM helpers.

Thin layer over :class:`app.ai.AIClient` that turns model output into validated
Pydantic models with retry-and-repair for structured (JSON) responses.

Adds:
- Exact response caching (hash of model + system_prompt + user_prompt + response_model)
- Optional semantic cache when embedding model is available
- Model fallback (delegated to NIMClient, but also handled here as safety net)
"""

from __future__ import annotations

import ast
import json
import logging
import re
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from app.ai.base import AIProviderError, create_ai_client
from app.ai.cache import get_global_cache, make_cache_key
from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class LLMClient:
    def __init__(self, ai_client=None) -> None:
        self.ai = ai_client or create_ai_client()
        # Cache singleton
        self._cache = get_global_cache()

    # ------------------------------------------------------------------
    async def generate_structured(
        self,
        *,
        response_model: Type[T],
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> T:
        """Request a structured JSON response validated against a Pydantic model."""
        model = model or settings.FAST_MODEL
        temp = settings.AI_TEMPERATURE if temperature is None else temperature
        tokens = settings.AI_MAX_TOKENS if max_tokens is None else max_tokens

        # --- Caching: exact hit before any AI call --------------------
        cache_enabled = bool(getattr(settings, "AI_CACHE_ENABLED", True))
        cache_key = ""
        if cache_enabled:
            cache_key = make_cache_key(
                model, response_model.__name__, system_prompt, user_prompt
            )
            # Exact cache lookup
            cached_val = self._cache.get(cache_key)
            if cached_val is not None:
                try:
                    logger.info(
                        "AI cache hit exact model=%s response=%s key=%s",
                        model,
                        response_model.__name__,
                        cache_key[:12],
                    )
                    return response_model.model_validate(cached_val)
                except Exception:
                    # Corrupted entry, evict
                    self._cache.delete(cache_key)

            # Optional semantic cache
            if getattr(settings, "AI_CACHE_SEMANTIC_ENABLED", False):
                try:
                    if getattr(settings, "EMBEDDING_MODEL", ""):
                        emb_model = settings.EMBEDDING_MODEL
                        # Embed the user prompt (sanitized context already)
                        q_embs = await self.ai.embed(emb_model, [user_prompt])
                        if q_embs:
                            threshold = float(
                                getattr(settings, "AI_CACHE_SEMANTIC_THRESHOLD", 0.9)
                            )
                            sem_val = self._cache.get_semantic(
                                q_embs[0], threshold=threshold, model=model
                            )
                            if sem_val is not None:
                                logger.info(
                                    "AI cache hit semantic model=%s response=%s sim>=%.2f",
                                    model,
                                    response_model.__name__,
                                    threshold,
                                )
                                return response_model.model_validate(sem_val)
                except Exception as exc:
                    # Degrade gracefully
                    logger.debug("Semantic cache lookup failed: %s", exc)

        schema = _json_schema(response_model)
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": user_prompt
                + "\n\nReturn ONLY valid JSON matching this schema:\n"
                + json.dumps(schema, indent=2),
            },
        ]

        last_error: str | None = None
        attempts = max(1, settings.AI_MAX_RETRIES)

        # For fallback handling at this layer, keep original model so we can
        # retry once with FAST_MODEL if primary fails (NIMClient already does
        # that, but we add extra safety).
        primary_model = model
        models_to_try = [primary_model]
        if getattr(settings, "AI_MODEL_FALLBACK", True):
            fast = getattr(settings, "FAST_MODEL", "")
            if fast and fast != primary_model:
                models_to_try.append(fast)

        last_ai_error: Exception | None = None

        for model_idx, try_model in enumerate(models_to_try):
            is_fallback = model_idx > 0
            # For fallback we only attempt once
            attempt_budget = 1 if is_fallback else attempts

            for attempt in range(attempt_budget):
                if last_error:
                    messages = messages[:1] + [
                        {
                            "role": "user",
                            "content": user_prompt
                            + "\n\nYour previous response failed JSON validation:\n"
                            + last_error
                            + "\n\nReturn ONLY valid JSON matching this schema:\n"
                            + json.dumps(schema, indent=2),
                        }
                    ]
                try:
                    data = await self.ai.chat(
                        model=try_model,
                        messages=messages,
                        temperature=temp,
                        max_tokens=tokens,
                        response_format={"type": "json_object"},
                    )
                except AIProviderError as exc:
                    last_ai_error = exc
                    logger.warning(
                        "LLMClient chat failed model=%s attempt=%s/%s fallback=%s err=%s",
                        try_model,
                        attempt + 1,
                        attempt_budget,
                        is_fallback,
                        str(exc)[:200],
                    )
                    # If not fallback yet, break inner loop to attempt fallback model
                    if not is_fallback and len(models_to_try) > 1:
                        break
                    # else continue retry
                    continue

                content = data["choices"][0]["message"]["content"]
                try:
                    parsed = _parse_json(content)
                except (json.JSONDecodeError, ValueError, SyntaxError) as exc:
                    last_error = f"Malformed JSON: {exc}"
                    logger.warning(
                        "Structured response failed JSON parsing (attempt %s/%s): %s",
                        attempt + 1,
                        attempt_budget,
                        exc,
                    )
                    continue

                try:
                    validated = response_model.model_validate(parsed)

                    # Cache successful result
                    if cache_enabled:
                        try:
                            # Store dict representation (not the Pydantic instance itself)
                            to_cache = validated.model_dump()
                            emb = None
                            # If semantic cache enabled, compute embedding for the request
                            if getattr(settings, "AI_CACHE_SEMANTIC_ENABLED", False):
                                try:
                                    if getattr(settings, "EMBEDDING_MODEL", ""):
                                        emb_model = settings.EMBEDDING_MODEL
                                        q_embs = await self.ai.embed(
                                            emb_model, [user_prompt]
                                        )
                                        if q_embs:
                                            emb = q_embs[0]
                                except Exception:
                                    emb = None
                            self._cache.set(
                                cache_key,
                                to_cache,
                                embedding=emb,
                                model=primary_model,
                            )
                            logger.debug(
                                "AI cache set model=%s key=%s",
                                primary_model,
                                cache_key[:12],
                            )
                        except Exception as exc:
                            logger.debug("Failed to write AI cache: %s", exc)

                    return validated
                except ValidationError as exc:
                    last_error = json.dumps(exc.errors()[:4])
                    logger.warning(
                        "Structured response failed validation (attempt %s/%s): %s",
                        attempt + 1,
                        attempt_budget,
                        exc.errors()[:2],
                    )
                    continue

            # Exhausted attempts for this model; if we have fallback left, log and continue
            if not is_fallback and len(models_to_try) > 1:
                logger.warning(
                    "LLMClient primary model %s failed, attempting fallback %s",
                    primary_model,
                    models_to_try[1],
                )
                # Reset last_error for fallback attempt? Keep it.
                continue

        # If we get here, all models failed
        if last_ai_error:
            raise last_ai_error
        raise AIProviderError(
            f"Could not obtain a valid {response_model.__name__} after {attempts} attempts"
        )


def _parse_json(content: str) -> dict:
    content = content.strip()

    # 1. Direct JSON parse (fast path & preserves embedded markdown fences)
    try:
        res = json.loads(content, strict=False)
        if isinstance(res, dict):
            return res
    except (json.JSONDecodeError, TypeError):
        pass

    # 2. Direct Python-dict literal parse (single quotes, True/False/None)
    try:
        res = ast.literal_eval(content)
        if isinstance(res, dict):
            return res
    except (ValueError, SyntaxError, TypeError):
        pass

    # 3. If wrapped in outer markdown fence, extract block content
    if content.startswith("```"):
        first_newline = content.find("\n")
        if first_newline != -1:
            last_fence = content.rfind("```")
            if last_fence > first_newline:
                inner = content[first_newline + 1 : last_fence].strip()
                try:
                    res = json.loads(inner, strict=False)
                    if isinstance(res, dict):
                        return res
                except (json.JSONDecodeError, TypeError):
                    pass
                try:
                    res = ast.literal_eval(inner)
                    if isinstance(res, dict):
                        return res
                except (ValueError, SyntaxError, TypeError):
                    pass

    # 4. Extract outermost {...} to tolerate surrounding prose or fences
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = content[start : end + 1]
        try:
            res = json.loads(snippet, strict=False)
            if isinstance(res, dict):
                return res
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            res = ast.literal_eval(snippet)
            if isinstance(res, dict):
                return res
        except (ValueError, SyntaxError, TypeError):
            pass

    # Final attempt with standard json.loads so proper JSONDecodeError is raised if invalid
    return json.loads(content)


def _json_schema(model: Type[BaseModel]) -> dict:
    # A concise, LLM-friendly schema description.
    props: dict = {}
    for name, field in model.model_fields.items():
        props[name] = {
            "type": _field_type(field),
            "description": field.description or "",
        }
    return {
        "name": model.__name__,
        "type": "object",
        "properties": props,
        "required": [n for n, f in model.model_fields.items() if f.is_required()],
    }


def _field_type(field) -> str:
    ann = str(field.annotation).lower()
    if "float" in ann:
        return "number (0.0-1.0)"
    if "int" in ann:
        return "integer"
    if "bool" in ann:
        return "boolean"
    if "list" in ann:
        return "array"
    return "string"
