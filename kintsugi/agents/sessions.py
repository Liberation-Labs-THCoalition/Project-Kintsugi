"""Session management for the framework API.

A session is one conversation bound to one agent instance. Sessions are
in-memory (the temporal memory layer persists what matters long-term);
they hold bounded history for the API and dashboard.
"""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from kintsugi.agents.events import EventBus, get_event_bus
from kintsugi.agents.instance import TurnResult
from kintsugi.agents.manager import AgentManager, get_agent_manager


@dataclass
class Session:
    agent_id: str
    id: str = field(default_factory=lambda: f"sess-{uuid.uuid4().hex[:10]}")
    org_id: str = "default"
    user_id: str = "api"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    closed: bool = False
    history: deque = field(default_factory=lambda: deque(maxlen=200))

    def record(self, message: str, result: TurnResult) -> None:
        self.history.append(
            {
                "role": "user",
                "content": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        self.history.append(
            {
                "role": "agent",
                "content": result.response,
                "turn_id": result.turn_id,
                "skill_used": result.skill_used,
                "oracle_status": result.oracle.get("status"),
                "blocked": result.blocked,
                "timestamp": result.timestamp.isoformat(),
            }
        )

    def to_dict(self, include_history: bool = False) -> dict[str, Any]:
        data = {
            "id": self.id,
            "agent_id": self.agent_id,
            "org_id": self.org_id,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat(),
            "closed": self.closed,
            "turns": len(self.history) // 2,
        }
        if include_history:
            data["history"] = list(self.history)
        return data


class SessionManager:
    """Tracks sessions and dispatches messages to their agents."""

    def __init__(
        self,
        agent_manager: AgentManager | None = None,
        event_bus: EventBus | None = None,
        max_sessions: int = 500,
    ) -> None:
        self._sessions: dict[str, Session] = {}
        self._agents = agent_manager or get_agent_manager()
        self._events = event_bus or get_event_bus()
        self.max_sessions = max_sessions

    def create(
        self,
        agent_id: str | None = None,
        personality: str = "default",
        org_id: str = "default",
        user_id: str = "api",
    ) -> Session:
        """Create a session, spawning a fresh agent if none was given."""
        if len([s for s in self._sessions.values() if not s.closed]) >= self.max_sessions:
            raise RuntimeError(f"session limit reached ({self.max_sessions})")

        if agent_id is None:
            agent = self._agents.spawn(personality=personality, org_id=org_id)
            agent_id = agent.id
        else:
            self._agents.get(agent_id)  # validate

        session = Session(agent_id=agent_id, org_id=org_id, user_id=user_id)
        self._sessions[session.id] = session
        self._events.publish(
            "session.created", {"user_id": user_id}, agent_id=agent_id, session_id=session.id
        )
        return session

    def get(self, session_id: str) -> Session:
        try:
            return self._sessions[session_id]
        except KeyError:
            raise KeyError(f"unknown session {session_id!r}") from None

    def list(self, include_closed: bool = False) -> list[Session]:
        sessions = list(self._sessions.values())
        if not include_closed:
            sessions = [s for s in sessions if not s.closed]
        return sorted(sessions, key=lambda s: s.created_at)

    def close(self, session_id: str) -> Session:
        session = self.get(session_id)
        session.closed = True
        self._events.publish(
            "session.closed", {}, agent_id=session.agent_id, session_id=session.id
        )
        return session

    async def send_message(
        self, session_id: str, message: str, context: dict[str, Any] | None = None
    ) -> TurnResult:
        session = self.get(session_id)
        if session.closed:
            raise RuntimeError(f"session {session_id} is closed")
        agent = self._agents.get(session.agent_id)
        result = await agent.handle_message(
            message,
            session_id=session.id,
            user_id=session.user_id,
            context=context,
        )
        session.record(message, result)
        return result


_sessions: SessionManager | None = None


def get_session_manager() -> SessionManager:
    """Global session manager singleton."""
    global _sessions
    if _sessions is None:
        _sessions = SessionManager()
    return _sessions
