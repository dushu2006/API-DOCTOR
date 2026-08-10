"""Controlled agent tools.

Every tool the AI agent may invoke is defined here and validated by the backend
before execution. There is no unrestricted shell access — only these whitelisted,
parameter-checked operations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, str]  # name -> type hint
    required: list[str] = field(default_factory=list)
    handler: Callable[..., Awaitable[Any]] | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
                "required": t.required,
            }
            for t in self._tools.values()
        ]

    async def invoke(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None or tool.handler is None:
            return {"ok": False, "error": f"unknown tool: {name}"}
        # Validate required args & allowed keys.
        unknown = set(args) - set(tool.parameters)
        missing = set(tool.required) - set(args)
        if unknown:
            return {"ok": False, "error": f"unknown parameters: {sorted(unknown)}"}
        if missing:
            return {"ok": False, "error": f"missing required parameters: {sorted(missing)}"}
        try:
            result = await tool.handler(**args)
            return {"ok": True, "result": result}
        except Exception as exc:  # noqa: BLE001
            logger.exception("Tool %s failed", name)
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


tool_registry = ToolRegistry()
