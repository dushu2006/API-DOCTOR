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
import html as _html
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
# Reasoning models may prepend internal reasoning before their final response.  Do
# not let JSON-like examples or notes in that block become the structured result.
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


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

        # Stream by default: with a slow provider the first tokens arrive
        # quickly and the connection stays alive while generation continues,
        # instead of tripping a fixed read timeout on long responses.
        stream = bool(getattr(settings, "AI_STREAMING", True))

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
                        stream=stream,
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
                    # The provider already exhausted its own retries (bounded
                    # by the overall AI_TIMEOUT_SECONDS budget) and any fallback
                    # model it was configured with. Re-calling the same model
                    # here would just burn the same budget again, so break out
                    # and let the outer loop try the fallback model — or fail
                    # fast if there is none.
                    break

                content = data["choices"][0]["message"]["content"]
                try:
                    parsed = _parse_json(content)
                except (json.JSONDecodeError, ValueError, SyntaxError) as exc:
                    last_error = f"Malformed JSON: {exc}"
                    logger.warning(
                        "Structured response failed JSON parsing (attempt %s/%s): %s\n"
                        "RAW CONTENT: %s",
                        attempt + 1,
                        attempt_budget,
                        exc,
                        content[:2000],
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
                        "Structured response failed validation (attempt %s/%s): %s\n"
                        "RAW CONTENT: %s",
                        attempt + 1,
                        attempt_budget,
                        exc.errors()[:2],
                        content[:2000],
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


def _extract_json_candidates(content: str) -> list[str]:
    """Return balanced top-level object candidates, without matching braces in strings."""
    candidates: list[str] = []
    depth = 0
    start: int | None = None
    in_string = False
    escaped = False

    for index, char in enumerate(content):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(content[start : index + 1])
                start = None

    # Reasoning fragments tend to be small; prefer a complete, larger response.
    return sorted(candidates, key=len, reverse=True)


def _repair_html_entities(content: str) -> str:
    # Some models substitute HTML entities for JSON-unsafe characters
    # instead of properly escaping them -- recover and retry once.
    repaired = (
        content.replace("&#13;&#10;", "\\n")
        .replace("&#x0D;&#x0A;", "\\n")
        .replace("&#10;", "\\n")
        .replace("&#x0A;", "\\n")
        .replace("&#x0a;", "\\n")
        .replace("&#13;", "")
        .replace("&#x0D;", "")
        .replace("&#x0d;", "")
        .replace("&quot;", '\\"')
        .replace("&#34;", '\\"')
        .replace("&#x22;", '\\"')
    )
    return _html.unescape(repaired)


def _safe_eval_ast(node: ast.AST) -> Any:
    """Safely evaluate an AST node into Python primitives, accepting JSON-style booleans/null."""
    if isinstance(node, ast.Dict):
        return {_safe_eval_ast(k): _safe_eval_ast(v) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.List):
        return [_safe_eval_ast(elt) for elt in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_safe_eval_ast(elt) for elt in node.elts)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in ("true", "True"):
            return True
        if node.id in ("false", "False"):
            return False
        if node.id in ("null", "None"):
            return None
        raise ValueError(f"Unsupported identifier: {node.id}")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        val = _safe_eval_ast(node.operand)
        return -val if isinstance(node.op, ast.USub) else val
    raise ValueError(f"Unsupported AST node: {type(node)}")


def _parse_dict_literal(text: str) -> dict | None:
    """Parse Python dict literals with support for single quotes and JSON literals (true/false/null)."""
    try:
        res = ast.literal_eval(text)
        if isinstance(res, dict):
            return res
    except (ValueError, SyntaxError, TypeError):
        pass

    try:
        tree = ast.parse(text.strip(), mode="eval")
        res = _safe_eval_ast(tree.body)
        if isinstance(res, dict):
            return res
    except Exception:
        pass
    return None


def _parse_object(value: str) -> dict | None:
    """Parse a JSON object, accepting Python dict literals as a compatibility fallback."""
    try:
        result = json.loads(value, strict=False)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, TypeError):
        pass

    result = _parse_dict_literal(value)
    if result is not None:
        return result

    try:
        repaired = _repair_html_entities(value)
        if repaired != value:
            result = json.loads(repaired, strict=False)
            if isinstance(result, dict):
                return result
            result = _parse_dict_literal(repaired)
            if result is not None:
                return result
    except (json.JSONDecodeError, TypeError):
        pass

    return None


def _parse_json(content: str) -> dict:
    content = _THINK_BLOCK.sub("", content).strip()
    content = _repair_html_entities(content)

    # 1. Direct JSON parse (fast path & preserves embedded markdown fences)
    try:
        res = json.loads(content, strict=False)
        if isinstance(res, dict):
            return res
    except (json.JSONDecodeError, TypeError):
        pass

    # 2. Direct Python-dict literal parse (single quotes, True/False/None or true/false/null)
    dict_res = _parse_dict_literal(content)
    if dict_res is not None:
        return dict_res

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
                dict_inner = _parse_dict_literal(inner)
                if dict_inner is not None:
                    return dict_inner

    # 4. Scan each balanced object rather than spanning the first and last
    # brace in the entire response.  A reasoning/prose prefix can contain its
    # own JSON-like object before the final structured answer.
    parsed_candidates: list[dict] = []
    for candidate in _extract_json_candidates(content):
        parsed = _parse_object(candidate)
        if parsed is not None:
            parsed_candidates.append(parsed)

    # Prefer a substantive object.  Keep a one-key fallback for response
    # models that legitimately have only one field.
    for parsed in parsed_candidates:
        if len(parsed) > 1:
            return parsed
    if parsed_candidates:
        return parsed_candidates[0]

    # Final attempt with standard json.loads so proper JSONDecodeError is raised if invalid
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Some models substitute HTML entities for JSON-unsafe characters
        # instead of properly escaping them -- recover and retry once.
        repaired = _repair_html_entities(content)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            dict_repaired = _parse_dict_literal(repaired)
            if dict_repaired is not None:
                return dict_repaired
            raise


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
