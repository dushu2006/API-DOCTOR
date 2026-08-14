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
from typing import Any, Type, TypeVar

from pydantic import BaseModel, ValidationError

from app.ai.base import AIProviderError, create_ai_client
from app.ai.cache import get_global_cache, make_cache_key
from app.core.config import settings


def _is_schema_echo(obj: dict, expected_name: str | None = None) -> bool:
    """Detect when the model echoed the JSON schema definition itself.

    The schema we send has shape:
        {\"name\": \"FixProposal\", \"type\": \"object\", \"properties\": {\"summary\": {\"type\": ...}}, \"required\": [...]}
    An instance should NEVER contain a top-level 'properties' dict whose values
    look like field definitions. Treat such objects as malformed so the retry
    logic kicks in with a stronger anti-echo instruction.
    """
    if not isinstance(obj, dict):
        return False
    if "properties" not in obj:
        return False
    props = obj["properties"]
    if not isinstance(props, dict) or not props:
        return False
    # Heuristic: property values are dicts containing 'type'/'description'
    looks_like_field_def = 0
    for v in props.values():
        if isinstance(v, dict) and ("type" in v or "description" in v):
            looks_like_field_def += 1
    if looks_like_field_def == 0:
        return False
    # If it also has 'type' == 'object' or 'name' matching expected model, it's almost certainly the schema
    if obj.get("type") == "object":
        return True
    if expected_name and obj.get("name") == expected_name:
        return True
    if "required" in obj and isinstance(obj["required"], list):
        return True
    # Fallback: if at least half the values look like field defs, call it schema echo
    return looks_like_field_def >= max(1, len(props) // 2)

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
        # Build a more explicit prompt that forbids echoing the schema definition.
        # Previous models (e.g. nemotron-3.5-lightning) were returning the schema
        # object itself (name/properties/type) instead of an instance, which then
        # failed Pydantic validation with missing 'summary'. Stating the rule
        # explicitly reduces that failure mode.
        schema_instruction = (
            "You MUST return a JSON object that is an INSTANCE matching the schema described below, "
            "NOT the schema definition itself.\n"
            "The object must have ONLY the fields listed in 'required' / 'properties' with real values.\n"
            "Do NOT include top-level keys like 'properties', 'name', or 'type' unless they are defined "
            "as fields in the schema properties. Do NOT wrap the instance in any extra explanation.\n"
            "Schema (for reference):\n" + json.dumps(schema, indent=2)
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": user_prompt + "\n\n" + schema_instruction,
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
                    # On retries, restate the anti-echo rule explicitly so the model
                    # does not keep returning the schema definition.
                    repair_instruction = (
                        f"Your previous response failed JSON validation:\n{last_error}\n\n"
                        "Return ONLY a valid JSON INSTANCE (with real field values) matching the schema below, "
                        "NOT the schema definition itself. Do NOT include 'properties' or 'name' keys at top level.\n"
                        f"Schema:\n{json.dumps(schema, indent=2)}"
                    )
                    messages = messages[:1] + [
                        {
                            "role": "user",
                            "content": user_prompt + "\n\n" + repair_instruction,
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

                content = _choice_content(data)
                if not content:
                    last_error = (
                        "Empty assistant content (reasoning-only or truncated response)"
                    )
                    logger.warning(
                        "Structured response empty content (attempt %s/%s) model=%s",
                        attempt + 1,
                        attempt_budget,
                        try_model,
                    )
                    continue
                try:
                    parsed = _parse_json(content, expected_name=response_model.__name__)
                except (json.JSONDecodeError, ValueError, SyntaxError, TypeError) as exc:
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

                # Hard reject if the model echoed the schema definition itself.
                if _is_schema_echo(parsed, expected_name=response_model.__name__):
                    last_error = (
                        f"Returned the JSON schema definition itself instead of an instance: "
                        f"top-level keys {list(parsed.keys())}. "
                        "Return an object with real field values like summary, files_changed, etc. "
                        "Do NOT include 'properties' or 'name'."
                    )
                    logger.warning(
                        "Structured response was schema echo (attempt %s/%s) model=%s\\n"
                        "RAW CONTENT: %s",
                        attempt + 1,
                        attempt_budget,
                        try_model,
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


def _choice_content(data: dict) -> str:
    """Best-effort assistant text from an OpenAI-shaped chat response.

    Reasoning models often return ``content: null`` and put the answer in
    ``reasoning_content`` / ``reasoning``. Never raise on a missing field —
    an empty string is a retryable parse failure, not a pipeline crash.
    """
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message") or choices[0].get("delta") or {}
    if not isinstance(message, dict):
        return ""
    for key in ("content", "reasoning_content", "reasoning"):
        val = message.get(key)
        if isinstance(val, str) and val.strip():
            return val
        if isinstance(val, list):
            parts = [
                part.get("text", "")
                for part in val
                if isinstance(part, dict) and part.get("text")
            ]
            joined = "".join(parts)
            if joined.strip():
                return joined
    return ""


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


def _parse_json(content: str, expected_name: str | None = None) -> dict:
    if not isinstance(content, str):
        content = "" if content is None else str(content)
    content = _THINK_BLOCK.sub("", content).strip()
    # Truncated reasoning traces leave an unclosed <think> ... with the JSON
    # object after it (or nothing). Drop the dangling prefix so candidates
    # can still be recovered.
    content = re.sub(
        r"<think>.*?(?=\{|$)", "", content, flags=re.DOTALL | re.IGNORECASE
    ).strip()
    content = _repair_html_entities(content)

    def _is_acceptable(obj: dict) -> bool:
        # Filter out schema-echo objects immediately in the fast paths.
        if _is_schema_echo(obj, expected_name=expected_name):
            return False
        return True

    # 1. Direct JSON parse (fast path & preserves embedded markdown fences)
    try:
        res = json.loads(content, strict=False)
        if isinstance(res, dict) and _is_acceptable(res):
            return res
    except (json.JSONDecodeError, TypeError):
        pass

    # 2. Direct Python-dict literal parse (single quotes, True/False/None or true/false/null)
    dict_res = _parse_dict_literal(content)
    if dict_res is not None and _is_acceptable(dict_res):
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
                    if isinstance(res, dict) and _is_acceptable(res):
                        return res
                except (json.JSONDecodeError, TypeError):
                    pass
                dict_inner = _parse_dict_literal(inner)
                if dict_inner is not None and _is_acceptable(dict_inner):
                    return dict_inner

    # 4. Scan each balanced object rather than spanning the first and last
    # brace in the entire response.  A reasoning/prose prefix can contain its
    # own JSON-like object before the final structured answer.
    parsed_candidates: list[dict] = []
    for candidate in _extract_json_candidates(content):
        parsed = _parse_object(candidate)
        if parsed is not None and _is_acceptable(parsed):
            parsed_candidates.append(parsed)

    # Prefer a substantive object that is not a schema echo.
    # Keep a one-key fallback for response models that legitimately have only one field.
    for parsed in parsed_candidates:
        if len(parsed) > 1:
            return parsed
    if parsed_candidates:
        return parsed_candidates[0]

    # If we filtered everything as schema echo, try to surface a clear error.
    # Check if any candidate was a schema echo to give a better message.
    all_candidates_raw: list[dict] = []
    for candidate in _extract_json_candidates(content):
        parsed = _parse_object(candidate)
        if parsed is not None:
            all_candidates_raw.append(parsed)
    for raw in all_candidates_raw:
        if _is_schema_echo(raw, expected_name=expected_name):
            raise ValueError(
                f"Model returned JSON schema definition instead of instance (keys={list(raw.keys())})"
            )

    # Final attempt with standard json.loads so proper JSONDecodeError is raised if invalid
    try:
        final = json.loads(content)
        if isinstance(final, dict) and _is_schema_echo(final, expected_name=expected_name):
            raise ValueError(
                f"Model returned JSON schema definition instead of instance (keys={list(final.keys())})"
            )
        return final
    except json.JSONDecodeError:
        # Some models substitute HTML entities for JSON-unsafe characters
        # instead of properly escaping them -- recover and retry once.
        repaired = _repair_html_entities(content)
        try:
            final2 = json.loads(repaired)
            if isinstance(final2, dict) and _is_schema_echo(final2, expected_name=expected_name):
                raise ValueError(
                    f"Model returned JSON schema definition instead of instance (keys={list(final2.keys())})"
                )
            return final2
        except json.JSONDecodeError:
            dict_repaired = _parse_dict_literal(repaired)
            if dict_repaired is not None:
                if _is_schema_echo(dict_repaired, expected_name=expected_name):
                    raise ValueError(
                        f"Model returned JSON schema definition instead of instance (keys={list(dict_repaired.keys())})"
                    )
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
