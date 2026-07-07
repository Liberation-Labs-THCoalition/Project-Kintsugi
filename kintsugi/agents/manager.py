"""Multi-agent coordination: spawn, track, and stop agent instances."""

from __future__ import annotations

import logging
from typing import Any

from kintsugi.agents.events import EventBus, get_event_bus
from kintsugi.agents.instance import AgentInstance, AgentState
from kintsugi.agents.personality import (
    AgentPersonality,
    PersonalityRegistry,
    get_personality_registry,
)

logger = logging.getLogger(__name__)


class AgentManager:
    """Registry of live agent instances for this process.

    Instances are cheap; the cap exists to keep a misbehaving client from
    exhausting the process, not because agents are expensive.
    """

    def __init__(
        self,
        personalities: PersonalityRegistry | None = None,
        event_bus: EventBus | None = None,
        max_agents: int = 64,
    ) -> None:
        self._agents: dict[str, AgentInstance] = {}
        self._personalities = personalities or get_personality_registry()
        self._events = event_bus or get_event_bus()
        self.max_agents = max_agents

    def spawn(
        self,
        personality: str | AgentPersonality = "default",
        org_id: str = "default",
        agent_id: str | None = None,
    ) -> AgentInstance:
        active = [a for a in self._agents.values() if a.state != AgentState.STOPPED]
        if len(active) >= self.max_agents:
            raise RuntimeError(f"agent limit reached ({self.max_agents})")

        if isinstance(personality, str):
            personality = self._personalities.get(personality)

        agent = AgentInstance(
            personality=personality,
            org_id=org_id,
            agent_id=agent_id,
            event_bus=self._events,
        )
        if agent.id in self._agents:
            raise ValueError(f"agent id {agent.id!r} already exists")
        self._agents[agent.id] = agent
        self._events.publish(
            "agent.spawned",
            {"personality": personality.name, "org_id": org_id},
            agent_id=agent.id,
        )
        logger.info("spawned agent %s (%s)", agent.id, personality.name)
        return agent

    def get(self, agent_id: str) -> AgentInstance:
        try:
            return self._agents[agent_id]
        except KeyError:
            raise KeyError(f"unknown agent {agent_id!r}") from None

    def list(self, include_stopped: bool = False) -> list[AgentInstance]:
        agents = list(self._agents.values())
        if not include_stopped:
            agents = [a for a in agents if a.state != AgentState.STOPPED]
        return sorted(agents, key=lambda a: a.created_at)

    def stop(self, agent_id: str) -> AgentInstance:
        agent = self.get(agent_id)
        agent.stop()
        return agent

    def remove(self, agent_id: str) -> None:
        agent = self._agents.pop(agent_id, None)
        if agent and agent.state != AgentState.STOPPED:
            agent.stop()

    def describe(self) -> dict[str, Any]:
        agents = self.list(include_stopped=True)
        return {
            "count": len([a for a in agents if a.state != AgentState.STOPPED]),
            "max_agents": self.max_agents,
            "agents": [a.describe() for a in agents],
        }


_manager: AgentManager | None = None


def get_agent_manager() -> AgentManager:
    """Global agent manager singleton."""
    global _manager
    if _manager is None:
        _manager = AgentManager()
    return _manager
