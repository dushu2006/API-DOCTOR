from __future__ import annotations

from typing import Any

from app.integrations.base import LogProvider


class ManualLogProvider(LogProvider):
    provider = "manual"

    async def verify_connection(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "status": "connected",
            "logs_accessible": True,
            "message": "Manual log ingestion is available.",
        }

    async def get_services(self) -> list[dict[str, Any]]:
        return []

    async def get_logs(self, **kwargs) -> dict[str, Any]:
        raw_logs = kwargs.get("raw_logs") or kwargs.get("log_text") or ""
        return {
            "provider": self.provider,
            "status": "success",
            "logs": [{"message": raw_logs}] if raw_logs else [],
            "message": "Manual logs ready for diagnosis.",
            "logs_retrieved": 1 if raw_logs else 0,
        }
