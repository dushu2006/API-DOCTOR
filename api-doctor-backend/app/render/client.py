"""Render REST client.

Provides service/deployment/log information isolated behind a client layer so
the orchestrator never calls the Render API directly.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class RenderError(Exception):
    pass


class RenderClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        service_id: str | None = None,
    ) -> None:
        self.base_url = (base_url or settings.RENDER_API_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.RENDER_API_KEY
        self.service_id = service_id if service_id is not None else settings.RENDER_SERVICE_ID

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        if not self.api_key:
            raise RenderError("RENDER_API_KEY is not configured")
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.request(method, url, headers=self._headers, **kwargs)
        if resp.status_code >= 400:
            raise RenderError(
                f"Render API {method} {path} -> {resp.status_code}: {resp.text[:400]}"
            )
        if not resp.content:
            return {}
        return resp.json()

    # ------------------------------------------------------------------
    async def get_service(self, service_id: str | None = None) -> dict:
        sid = service_id or self.service_id
        return await self._request("GET", f"/services/{sid}")

    async def list_deployments(self, service_id: str | None = None, limit: int = 10) -> list[dict]:
        sid = service_id or self.service_id
        data = await self._request("GET", f"/services/{sid}/deploys?limit={limit}")
        return data  # type: ignore[return-value]

    async def get_deployment(self, deploy_id: str, service_id: str | None = None) -> dict:
        sid = service_id or self.service_id
        return await self._request("GET", f"/services/{sid}/deploys/{deploy_id}")

    async def get_logs(self, service_id: str | None = None, limit: int = 200) -> list[dict]:
        sid = service_id or self.service_id
        try:
            data = await self._request("GET", f"/services/{sid}/logs?limit={limit}")
            return data if isinstance(data, list) else []
        except RenderError:
            return []

    async def get_deployment_status(self, service_id: str | None = None) -> dict[str, Any]:
        deploys = await self.list_deployments(service_id=service_id, limit=1)
        if not deploys:
            return {"present": False, "status": "unknown"}
        dep = deploys[0]
        return {
            "present": True,
            "deploy_id": dep.get("id"),
            "status": dep.get("status"),
            "created_at": dep.get("createdAt"),
            "finished_at": dep.get("finishedAt"),
        }

    async def get_runtime_info(self, service_id: str | None = None) -> dict[str, Any]:
        service = await self.get_service(service_id)
        return {
            "service_id": service.get("id"),
            "service_name": service.get("name"),
            "service_url": service.get("serviceDetails", {}).get("url"),
            "auto_deploy": service.get("autoDeploy"),
            "repo": service.get("repo"),
            "branch": service.get("branch"),
        }
