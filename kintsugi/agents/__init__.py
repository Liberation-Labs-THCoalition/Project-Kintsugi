"""Multi-agent framework layer: personalities, instances, sessions, events."""

from kintsugi.agents.events import EventBus, FrameworkEvent, get_event_bus
from kintsugi.agents.instance import AgentInstance, AgentState, TurnResult
from kintsugi.agents.manager import AgentManager, get_agent_manager
from kintsugi.agents.personality import (
    AgentPersonality,
    PersonalityRegistry,
    SafetyConfig,
    get_personality_registry,
)
from kintsugi.agents.sessions import Session, SessionManager, get_session_manager

__all__ = [
    "AgentInstance",
    "AgentManager",
    "AgentPersonality",
    "AgentState",
    "EventBus",
    "FrameworkEvent",
    "PersonalityRegistry",
    "SafetyConfig",
    "Session",
    "SessionManager",
    "TurnResult",
    "get_agent_manager",
    "get_event_bus",
    "get_personality_registry",
    "get_session_manager",
]
