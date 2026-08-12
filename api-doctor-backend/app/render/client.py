"""Render REST client and log retrieval service.

Provides service, deployment, and log information isolated behind a client layer so
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
    def is_configured(self) -> bool:
        return bool(self.api_key and self.service_id)

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        if not self.api_key:
            raise RenderError("Render integration is not configured: RENDER_API_KEY is missing.")
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
        if not sid:
            raise RenderError("Render integration is not configured: RENDER_SERVICE_ID is missing.")
        return await self._request("GET", f"/services/{sid}")

    async def list_deployments(self, service_id: str | None = None, limit: int = 10) -> list[dict]:
        sid = service_id or self.service_id
        if not sid:
            raise RenderError("Render integration is not configured: RENDER_SERVICE_ID is missing.")
        data = await self._request("GET", f"/services/{sid}/deploys?limit={limit}")
        return data  # type: ignore[return-value]

    async def get_deployment(self, deploy_id: str, service_id: str | None = None) -> dict:
        sid = service_id or self.service_id
        if not sid:
            raise RenderError("Render integration is not configured: RENDER_SERVICE_ID is missing.")
        return await self._request("GET", f"/services/{sid}/deploys/{deploy_id}")

    async def get_logs(self, service_id: str | None = None, limit: int = 200) -> list[dict]:
        sid = service_id or self.service_id
        if not self.api_key or not sid:
            logger.info("Render integration is not configured.")
            return []
        try:
            data = await self._request("GET", f"/services/{sid}/logs?limit={limit}")
            return data if isinstance(data, list) else []
        except Exception as exc:
            logger.warning("Failed to fetch Render logs: %s", exc)
            return []

    async def get_deployment_status(self, service_id: str | None = None) -> dict[str, Any]:
        sid = service_id or self.service_id
        if not self.api_key or not sid:
            return {"present": False, "status": "unconfigured", "message": "Render integration is not configured."}
        try:
            deploys = await self.list_deployments(service_id=sid, limit=1)
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
        except RenderError as exc:
            return {"present": False, "status": "error", "message": str(exc)}

    async def get_runtime_info(self, service_id: str | None = None) -> dict[str, Any]:
        sid = service_id or self.service_id
        if not self.api_key or not sid:
            return {"present": False, "message": "Render integration is not configured."}
        try:
            service = await self.get_service(sid)
            return {
                "present": True,
                "service_id": service.get("id"),
                "service_name": service.get("name"),
                "service_url": service.get("serviceDetails", {}).get("url"),
                "auto_deploy": service.get("autoDeploy"),
                "repo": service.get("repo"),
                "branch": service.get("branch"),
            }
        except RenderError as exc:
            return {"present": False, "message": str(exc)}
