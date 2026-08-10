"""Live agent-activity hub.

A tiny in-memory pub/sub used to stream incident progress to the dashboard via
Server-Sent Events. Replaceable by Redis/a DB-backed channel later.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict


class EventHub:
    def __init__(self) -> None:
        # incident_id -> set of asyncio.Queue
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def publish(self, incident_id: str, event: dict) -> None:
        event["ts"] = time.time()
        payload = json.dumps(event)
        async with self._lock:
            subs = list(self._subs.get(incident_id, ()))
        for q in subs:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # Drop oldest to keep the stream live.
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    pass

    def subscribe(self, incident_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subs[incident_id].add(q)
        return q

    def unsubscribe(self, incident_id: str, q: asyncio.Queue) -> None:
        self._subs[incident_id].discard(q)
        if not self._subs[incident_id]:
            self._subs.pop(incident_id, None)


event_hub = EventHub()


async def emit(incident_id: str, step: str, status: str, message: str = "") -> None:
    await event_hub.publish(
        incident_id,
        {"type": "progress", "step": step, "status": status, "message": message},
    )
