from __future__ import annotations

from typing import Any

from app.integrations.base import LogProvider
from app.render.client import RenderClient, RenderError


class RenderLogProvider(LogProvider):
    provider = "render"

    def __init__(self, *, api_key: str, service_id: str = "", owner_id: str = "") -> None:
        self.client = RenderClient(api_key=api_key, service_id=service_id, owner_id=owner_id)

    async def verify_connection(self) -> dict[str, Any]:
        service = await self.client.get_service(self.client.service_id)
        owner_id = await self.client.resolve_owner_id(self.client.service_id, service=service)
        fetch = await self.client.fetch_runtime_logs(
            service_id=self.client.service_id,
            owner_id=owner_id,
            limit=25,
        )
        return {
            "provider": self.provider,
            "status": "connected",
            "service": {
                "service_id": fetch.service_id,
                "service_name": fetch.service_name,
                "owner_id": fetch.owner_id,
            },
            "logs_accessible": True,
            "logs_retrieved": fetch.log_count,
            "message": fetch.message,
        }

    async def get_services(self) -> list[dict[str, Any]]:
        return await self.client.list_services()

    async def get_logs(self, **kwargs) -> dict[str, Any]:
        fetch = await self.client.fetch_runtime_logs(
            service_id=kwargs.get("service_id") or self.client.service_id,
            owner_id=kwargs.get("owner_id") or self.client.owner_id,
            limit=int(kwargs.get("limit") or 200),
        )
        return {
            "provider": self.provider,
            "status": fetch.status,
            "logs": fetch.logs,
            "message": fetch.message,
            "service_id": fetch.service_id,
            "service_name": fetch.service_name,
            "owner_id": fetch.owner_id,
            "logs_retrieved": fetch.log_count,
        }

    async def safe_verify(self) -> dict[str, Any]:
        try:
            return await self.verify_connection()
        except RenderError as exc:
            return {
                "provider": self.provider,
                "status": "error",
                "logs_accessible": False,
                "message": str(exc),
                "error_type": exc.error_type,
                "http_status": exc.status_code,
            }
