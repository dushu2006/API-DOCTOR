"""High-level LLM helpers.

Thin layer over :class:`app.ai.AIClient` that turns model output into validated
Pydantic models with retry-and-repair for structured (JSON) responses.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from app.ai.base import AIProviderError, create_ai_client
from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class LLMClient:
    def __init__(self, ai_client=None) -> None:
        self.ai = ai_client or create_ai_client()

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
        for attempt in range(attempts):
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
                    model=model,
                    messages=messages,
                    temperature=temp,
                    max_tokens=tokens,
                    response_format={"type": "json_object"},
                )
            except AIProviderError:
                raise
            content = data["choices"][0]["message"]["content"]
            parsed = _parse_json(content)
            try:
                return response_model.model_validate(parsed)
            except ValidationError as exc:
                last_error = json.dumps(exc.errors()[:4])
                logger.warning(
                    "Structured response failed validation (attempt %s/%s): %s",
                    attempt + 1, attempts, exc.errors()[:2],
                )
                continue
        raise AIProviderError(f"Could not obtain a valid {response_model.__name__} after {attempts} attempts")


def _parse_json(content: str) -> dict:
    content = content.strip()
    block = _JSON_BLOCK.search(content)
    if block:
        content = block.group(1).strip()
    # Tolerate surrounding prose by extracting the outermost {...}.
    if not content.startswith("{"):
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            content = content[start : end + 1]
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
