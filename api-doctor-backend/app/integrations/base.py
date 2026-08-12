from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LogProvider(ABC):
    provider: str = "manual"

    @abstractmethod
    async def verify_connection(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def get_services(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def get_logs(self, **kwargs) -> dict[str, Any]:
        raise NotImplementedError

    def normalize_logs(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        logs = payload.get("logs") or []
        return logs if isinstance(logs, list) else []
