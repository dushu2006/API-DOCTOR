from __future__ import annotations

from app.integrations.base import LogProvider
from app.integrations.manual_provider import ManualLogProvider
from app.integrations.render_provider import RenderLogProvider
from app.projects.store import project_store


def get_log_provider(project_id: str, provider: str | None = None) -> LogProvider:
    provider_name = (provider or project_store.resolve_render(project_id).get("provider") or "manual").lower()
    if provider_name == "render":
        render = project_store.resolve_render(project_id)
        return RenderLogProvider(
            api_key=render.get("api_key", ""),
            service_id=render.get("service_id", ""),
            owner_id=render.get("owner_id", ""),
        )
    return ManualLogProvider()
