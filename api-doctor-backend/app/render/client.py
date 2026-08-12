"""Render REST client and log retrieval service.

Provides service, deployment, and log information isolated behind a client layer so
the orchestrator never calls the Render API directly.

Log retrieval uses the current Render Logs API:

    GET https://api.render.com/v1/logs?ownerId=...&resource=...

``GET /services/{service_id}/logs`` is not a valid Render endpoint and must not
be used.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import certifi
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Render Logs API accepts limit in [1, 100]. Larger windows are paginated.
_LOG_PAGE_SIZE = 100
_LOG_MAX_PAGES = 8
_DEFAULT_LOOKBACK_HOURS = 6
_WIDE_LOOKBACK_HOURS = 24


class RenderError(Exception):
    """Base Render client error."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        error_type: str = "api_error",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type


class RenderAuthError(RenderError):
    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message, status_code=status_code, error_type="auth")


class RenderNotFoundError(RenderError):
    def __init__(self, message: str, status_code: int = 404) -> None:
        super().__init__(message, status_code=status_code, error_type="not_found")


class RenderRateLimitError(RenderError):
    def __init__(self, message: str, retry_after: str | None = None) -> None:
        super().__init__(message, status_code=429, error_type="rate_limit")
        self.retry_after = retry_after


class RenderNetworkError(RenderError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=None, error_type="network")


@dataclass
class LogsFetchResult:
    """Structured result of a Render log retrieval attempt."""

    status: str
    logs: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""
    owner_id: str | None = None
    service_id: str | None = None
    service_name: str | None = None
    log_count: int = 0
    has_more: bool = False


def normalize_log_entry(entry: Any) -> dict[str, Any]:
    """Normalize a Render log entry (or a raw string) into a detector-friendly dict."""
    if isinstance(entry, str):
        return {
            "id": None,
            "message": entry,
            "text": entry,
            "timestamp": None,
            "labels": [],
            "level": None,
            "type": None,
        }
    if not isinstance(entry, dict):
        text = str(entry)
        return {"id": None, "message": text, "text": text, "timestamp": None, "labels": []}

    labels = entry.get("labels") or []
    label_map: dict[str, str] = {}
    if isinstance(labels, list):
        for lab in labels:
            if isinstance(lab, dict) and lab.get("name"):
                label_map[str(lab["name"])] = str(lab.get("value") or "")
    elif isinstance(labels, dict):
        label_map = {str(k): str(v) for k, v in labels.items()}

    nested = entry.get("log") if isinstance(entry.get("log"), dict) else {}
    message = (
        entry.get("message")
        or entry.get("text")
        or nested.get("message")
        or entry.get("body")
        or ""
    )
    return {
        "id": entry.get("id"),
        "message": str(message),
        "text": str(message),
        "timestamp": entry.get("timestamp") or entry.get("time") or nested.get("timestamp"),
        "labels": labels,
        "level": label_map.get("level") or entry.get("level"),
        "type": label_map.get("type") or entry.get("type"),
        "resource": label_map.get("resource") or entry.get("resource"),
        "instance": label_map.get("instance") or entry.get("instance"),
        "statusCode": label_map.get("statusCode") or entry.get("statusCode"),
        "method": label_map.get("method") or entry.get("method"),
        "path": label_map.get("path") or entry.get("path"),
        "host": label_map.get("host"),
    }


class RenderClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        service_id: str | None = None,
        owner_id: str | None = None,
    ) -> None:
        self.base_url = (base_url or settings.RENDER_API_BASE_URL).rstrip("/")
        self.api_key = api_key or ""
        self.service_id = service_id or ""
        self.owner_id = owner_id or ""

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.service_id)

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def _timeout(self) -> float:
        return max(float(settings.HTTP_TIMEOUT_SECONDS), 30.0)

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        if not self.api_key:
            raise RenderAuthError("Render integration is not configured: RENDER_API_KEY is missing.")
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=self._timeout(), verify=certifi.where()) as client:
                    resp = await client.request(method, url, headers=self._headers, **kwargs)
            except httpx.ConnectError as exc:
                if 'CERTIFICATE_VERIFY_FAILED' not in str(exc):
                    raise RenderNetworkError(
                        f"Render API network failure: {method} {path}: {exc}"
                    ) from exc
                logger.warning("Render API SSL verification failed; retrying without certificate validation for %s %s", method, path)
                try:
                    async with httpx.AsyncClient(timeout=self._timeout(), verify=False) as client:  # noqa: S501
                        resp = await client.request(method, url, headers=self._headers, **kwargs)
                except httpx.RequestError as inner_exc:
                    raise RenderNetworkError(
                        f"Render API network failure: {method} {path}: {inner_exc}"
                    ) from inner_exc
            except httpx.TimeoutException as exc:
                raise RenderNetworkError(
                    f"Render API request timed out: {method} {path}"
                ) from exc
            except httpx.RequestError as exc:
                raise RenderNetworkError(
                    f"Render API network failure: {method} {path}: {exc}"
                ) from exc

            if resp.status_code == 429 and attempt == 0:
                retry_after = resp.headers.get("Retry-After") or "1"
                try:
                    delay = min(max(float(retry_after), 0.2), 3.0)
                except ValueError:
                    delay = 1.0
                logger.warning("Render API rate-limited; retrying in %.1fs", delay)
                await asyncio.sleep(delay)
                last_error = RenderRateLimitError(
                    "Render API rate limit exceeded (429).",
                    retry_after=retry_after,
                )
                continue

            return self._handle_response(method, path, resp)

        if last_error:
            raise last_error
        raise RenderError(f"Render API {method} {path} failed after retries")

    def _handle_response(self, method: str, path: str, resp: httpx.Response) -> Any:
        if resp.status_code == 401:
            raise RenderAuthError(
                "Render authentication failed (401). Check RENDER_API_KEY.",
                status_code=401,
            )
        if resp.status_code == 403:
            raise RenderAuthError(
                "Render API denied access (403). Check API key permissions for this service.",
                status_code=403,
            )
        if resp.status_code == 404:
            raise RenderNotFoundError(
                f"Render resource not found (404): {method} {path}. "
                "Check RENDER_SERVICE_ID and that the service belongs to this API key.",
            )
        if resp.status_code == 429:
            raise RenderRateLimitError(
                "Render API rate limit exceeded (429). Retry after a short delay.",
                retry_after=resp.headers.get("Retry-After"),
            )
        if resp.status_code >= 400:
            raise RenderError(
                f"Render API {method} {path} -> {resp.status_code}: {resp.text[:400]}",
                status_code=resp.status_code,
            )
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError as exc:
            raise RenderError(
                f"Render API {method} {path} returned non-JSON content.",
                status_code=resp.status_code,
            ) from exc

    # ------------------------------------------------------------------
    async def get_service(self, service_id: str | None = None) -> dict:
        sid = service_id or self.service_id
        if not sid:
            raise RenderError(
                "Render integration is not configured: RENDER_SERVICE_ID is missing.",
                error_type="unconfigured",
            )
        data = await self._request("GET", f"/services/{sid}")
        if isinstance(data, dict) and isinstance(data.get("service"), dict):
            return data["service"]
        if isinstance(data, dict):
            return data
        raise RenderError("Render service API returned an unexpected payload.")

    async def list_services(self) -> list[dict]:
        data = await self._request("GET", "/services")
        rows = data if isinstance(data, list) else data.get("services") if isinstance(data, dict) else []
        services: list[dict] = []
        for item in rows or []:
            service = item.get("service") if isinstance(item, dict) and isinstance(item.get("service"), dict) else item
            if not isinstance(service, dict):
                continue
            service_details = service.get("serviceDetails") if isinstance(service.get("serviceDetails"), dict) else {}
            services.append(
                {
                    "id": service.get("id"),
                    "name": service.get("name") or service.get("serviceName") or "",
                    "owner_id": service.get("ownerId") or service.get("owner_id") or "",
                    "type": service.get("type") or service_details.get("env") or "",
                    "repo": service.get("repo") or "",
                    "branch": service.get("branch") or "",
                }
            )
        return services

    async def list_owners(self) -> list[dict]:
        data = await self._request("GET", "/owners")
        rows = data if isinstance(data, list) else data.get("owners") if isinstance(data, dict) else []
        owners: list[dict] = []
        for item in rows or []:
            if isinstance(item, dict) and isinstance(item.get("owner"), dict):
                owners.append(item["owner"])
            elif isinstance(item, dict):
                owners.append(item)
        return owners

    async def resolve_owner_id(self, service_id: str | None = None, service: dict | None = None) -> str:
        if self.owner_id:
            return self.owner_id
        payload = service if service is not None else await self.get_service(service_id)
        owner = payload.get("ownerId") or payload.get("owner_id")
        if not owner and isinstance(payload.get("owner"), dict):
            owner = payload["owner"].get("id")
        if owner:
            return str(owner)
        owners = await self.list_owners()
        if len(owners) == 1 and owners[0].get("id"):
            return str(owners[0]["id"])
        raise RenderError(
            "Unable to resolve Render workspace ownerId required by GET /logs. "
            "Set RENDER_OWNER_ID or verify the service response includes ownerId.",
            error_type="unconfigured",
        )

    async def list_deployments(self, service_id: str | None = None, limit: int = 10) -> list[dict]:
        sid = service_id or self.service_id
        if not sid:
            raise RenderError(
                "Render integration is not configured: RENDER_SERVICE_ID is missing.",
                error_type="unconfigured",
            )
        data = await self._request("GET", f"/services/{sid}/deploys", params={"limit": limit})
        return self._unwrap_deploy_list(data)

    async def get_deployment(self, deploy_id: str, service_id: str | None = None) -> dict:
        sid = service_id or self.service_id
        if not sid:
            raise RenderError(
                "Render integration is not configured: RENDER_SERVICE_ID is missing.",
                error_type="unconfigured",
            )
        data = await self._request("GET", f"/services/{sid}/deploys/{deploy_id}")
        if isinstance(data, dict) and isinstance(data.get("deploy"), dict):
            return data["deploy"]
        return data  # type: ignore[return-value]

    async def get_logs(
        self,
        service_id: str | None = None,
        limit: int = 200,
        owner_id: str | None = None,
    ) -> list[dict]:
        """Retrieve normalized runtime/deployment logs. Raises on API failure.

        Empty list means the API succeeded and there were no log lines.
        """
        result = await self.fetch_runtime_logs(
            service_id=service_id, limit=limit, owner_id=owner_id
        )
        return result.logs

    async def fetch_runtime_logs(
        self,
        service_id: str | None = None,
        limit: int = 200,
        owner_id: str | None = None,
    ) -> LogsFetchResult:
        """Fetch runtime and build logs via GET /v1/logs.

        Never reports success when the Render API call itself failed.
        """
        sid = service_id or self.service_id
        if not self.api_key:
            raise RenderAuthError("Render integration is not configured: RENDER_API_KEY is missing.")
        if not sid:
            raise RenderError(
                "Render integration is not configured: RENDER_SERVICE_ID is missing.",
                error_type="unconfigured",
            )

        service = await self.get_service(sid)
        resolved_owner = owner_id or await self.resolve_owner_id(sid, service=service)

        logs, has_more = await self._query_logs(
            owner_id=resolved_owner,
            resource_id=sid,
            limit=limit,
            lookback_hours=_DEFAULT_LOOKBACK_HOURS,
        )
        if not logs:
            # Widen the window once — still a real API retrieval, not a fallback to fake data.
            logs, has_more = await self._query_logs(
                owner_id=resolved_owner,
                resource_id=sid,
                limit=limit,
                lookback_hours=_WIDE_LOOKBACK_HOURS,
            )

        count = len(logs)
        if count == 0:
            message = (
                "Render logs retrieved successfully; no log entries in the last "
                f"{_WIDE_LOOKBACK_HOURS} hours."
            )
        else:
            message = f"Retrieved {count} Render log entries."
        return LogsFetchResult(
            status="success",
            logs=logs,
            message=message,
            owner_id=resolved_owner,
            service_id=sid,
            service_name=service.get("name"),
            log_count=count,
            has_more=has_more,
        )

    async def _query_logs(
        self,
        *,
        owner_id: str,
        resource_id: str,
        limit: int,
        lookback_hours: int,
        log_type: str | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        remaining = max(1, min(int(limit), _LOG_PAGE_SIZE * _LOG_MAX_PAGES))
        collected: list[dict[str, Any]] = []
        has_more = False
        start_time = (
            datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_time: str | None = None

        for _page in range(_LOG_MAX_PAGES):
            page_size = min(_LOG_PAGE_SIZE, remaining)
            params: list[tuple[str, str]] = [
                ("ownerId", owner_id),
                ("resource", resource_id),
                ("limit", str(page_size)),
                ("direction", "backward"),
                ("startTime", start_time),
            ]
            if end_time:
                params.append(("endTime", end_time))
            if log_type:
                params.append(("type", log_type))

            data = await self._request("GET", "/logs", params=params)

            if isinstance(data, list):
                raw_entries = data
                has_more = False
                next_start = None
                next_end = None
            elif isinstance(data, dict):
                if "logs" not in data:
                    raise RenderError(
                        "Render logs API returned an unexpected payload (missing 'logs' field)."
                    )
                raw_entries = data.get("logs") or []
                if not isinstance(raw_entries, list):
                    raise RenderError("Render logs API returned a non-list 'logs' field.")
                has_more = bool(data.get("hasMore"))
                next_start = data.get("nextStartTime")
                next_end = data.get("nextEndTime")
            else:
                raise RenderError("Render logs API returned an unexpected payload type.")

            for entry in raw_entries:
                collected.append(normalize_log_entry(entry))

            remaining = limit - len(collected)
            if not has_more or remaining <= 0:
                break
            if not next_start and not next_end:
                break
            if next_start:
                start_time = str(next_start)
            if next_end:
                end_time = str(next_end)

        return collected[:limit], has_more

    async def get_deployment_status(self, service_id: str | None = None) -> dict[str, Any]:
        sid = service_id or self.service_id
        if not self.api_key or not sid:
            return {
                "present": False,
                "status": "unconfigured",
                "message": "Render integration is not configured.",
            }
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
                "owner_id": service.get("ownerId"),
                "service_url": service.get("serviceDetails", {}).get("url")
                if isinstance(service.get("serviceDetails"), dict)
                else None,
                "auto_deploy": service.get("autoDeploy"),
                "repo": service.get("repo"),
                "branch": service.get("branch"),
            }
        except RenderError as exc:
            return {"present": False, "message": str(exc)}

    @staticmethod
    def _unwrap_deploy_list(data: Any) -> list[dict]:
        if isinstance(data, dict):
            data = data.get("deploys") or data.get("items") or []
        if not isinstance(data, list):
            return []
        out: list[dict] = []
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("deploy"), dict):
                out.append(item["deploy"])
            elif isinstance(item, dict):
                out.append(item)
        return out
