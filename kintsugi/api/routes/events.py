"""Server-sent events stream of framework activity for the dashboard."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from kintsugi.agents.events import get_event_bus

router = APIRouter(prefix="/api/v1/events", tags=["events"])


@router.get("/recent")
async def recent_events(limit: int = 100, type_prefix: str | None = None) -> dict:
    bus = get_event_bus()
    return {"events": [e.to_dict() for e in bus.recent(limit=limit, type_prefix=type_prefix)]}


@router.get("/stream")
async def stream_events(request: Request) -> StreamingResponse:
    """SSE stream: one `data:` frame per framework event, 15s heartbeats."""
    bus = get_event_bus()

    async def generate():
        subscription = bus.subscribe()
        try:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(subscription.__anext__(), timeout=15.0)
                    yield f"data: {json.dumps(event.to_dict())}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                except StopAsyncIteration:
                    return
        finally:
            await subscription.aclose()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
