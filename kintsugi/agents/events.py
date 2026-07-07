"""In-process event bus for the framework layer.

Every observable action in the framework — agent spawn, message handling,
skill execution, Oracle verdicts — is published here. The dashboard's SSE
stream and the WebSocket layer subscribe to it; so can plugins.

Deliberately process-local: multi-node deployments should bridge this to
Redis/NATS via a MiddlewarePlugin rather than complicating the core.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

_seq = itertools.count(1)


@dataclass
class FrameworkEvent:
    """A single observable event in the framework."""

    type: str  # e.g. "agent.spawned", "message.completed", "oracle.verdict"
    data: dict[str, Any] = field(default_factory=dict)
    agent_id: str | None = None
    session_id: str | None = None
    seq: int = field(default_factory=lambda: next(_seq))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "type": self.type,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
        }


class EventBus:
    """Asyncio pub/sub with a bounded replay buffer.

    Subscribers each get their own queue; slow subscribers drop oldest
    events rather than blocking publishers.
    """

    def __init__(self, history_size: int = 500, queue_size: int = 256) -> None:
        self._history: deque[FrameworkEvent] = deque(maxlen=history_size)
        self._subscribers: set[asyncio.Queue[FrameworkEvent]] = set()
        self._queue_size = queue_size

    def publish(
        self,
        type: str,
        data: dict[str, Any] | None = None,
        *,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> FrameworkEvent:
        event = FrameworkEvent(
            type=type, data=data or {}, agent_id=agent_id, session_id=session_id
        )
        self._history.append(event)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop oldest for this subscriber; never block a publisher.
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):  # pragma: no cover - race window
                    pass
        return event

    def recent(self, limit: int = 100, type_prefix: str | None = None) -> list[FrameworkEvent]:
        events = list(self._history)
        if type_prefix:
            events = [e for e in events if e.type.startswith(type_prefix)]
        return events[-limit:]

    async def subscribe(self) -> AsyncIterator[FrameworkEvent]:
        queue: asyncio.Queue[FrameworkEvent] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Global event bus singleton."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
