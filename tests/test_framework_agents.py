"""Tests for the framework layer: personalities, agents, sessions, events."""

from __future__ import annotations

import pytest

from kintsugi.agents.events import EventBus
from kintsugi.agents.instance import AgentInstance, AgentState
from kintsugi.agents.manager import AgentManager
from kintsugi.agents.personality import (
    AgentPersonality,
    PersonalityRegistry,
    SafetyConfig,
    load_personality_file,
)
from kintsugi.agents.sessions import SessionManager
from kintsugi.oracle.hooks import AgentTurn, CallableOracleHook, OracleVerdict
from kintsugi.oracle.monitor import BLOCKED_RESPONSE, OracleLoopMonitor


# ---------------------------------------------------------------------------
# Personalities
# ---------------------------------------------------------------------------


def test_personality_defaults_and_skill_matching():
    p = AgentPersonality(name="test")
    assert p.display_name == "Test"
    assert p.allows_skill("anything")

    p2 = AgentPersonality(
        name="locked",
        skills_allow=["grant_*"],
        skills_deny=["grant_secret"],
    )
    assert p2.allows_skill("grant_search")
    assert not p2.allows_skill("grant_secret")  # deny wins
    assert not p2.allows_skill("bash_executor")


def test_personality_rejects_bad_efe_weights():
    with pytest.raises(ValueError):
        AgentPersonality(name="bad", efe_weights={"risk": 0.9, "ambiguity": 0.9, "epistemic": 0.9})


def test_personality_rejects_bad_oracle_mode():
    with pytest.raises(ValueError):
        SafetyConfig(oracle_mode="yolo")


def test_personality_yaml_and_toml_loading(tmp_path):
    (tmp_path / "a.yaml").write_text(
        "name: a\nefe_weights: {risk: 0.5, ambiguity: 0.3, epistemic: 0.2}\n"
        "safety: {oracle_mode: enforce}\n"
    )
    (tmp_path / "b.toml").write_text('name = "b"\nmodel_tier = "haiku"\n')
    (tmp_path / "ignored.txt").write_text("not a personality")

    registry = PersonalityRegistry(tmp_path)
    names = registry.reload()
    assert "a" in names and "b" in names
    assert "default" in names  # built-in fallback always present
    assert registry.get("a").safety.oracle_mode == "enforce"
    assert registry.get("b").model_tier == "haiku"


def test_personality_file_source_recorded(tmp_path):
    path = tmp_path / "x.yaml"
    path.write_text("name: x\n")
    p = load_personality_file(path)
    assert p.source_path == str(path)


# ---------------------------------------------------------------------------
# Event bus
# ---------------------------------------------------------------------------


async def test_event_bus_publish_and_history():
    bus = EventBus(history_size=5)
    for i in range(8):
        bus.publish("test.event", {"i": i})
    recent = bus.recent()
    assert len(recent) == 5  # bounded
    assert recent[-1].data["i"] == 7
    assert bus.recent(type_prefix="nope") == []


# ---------------------------------------------------------------------------
# Oracle monitor
# ---------------------------------------------------------------------------


def _turn(response="hello") -> AgentTurn:
    return AgentTurn(
        agent_id="agent-x", session_id=None, user_input="hi", response=response
    )


async def test_oracle_monitor_off_mode_skips_review():
    monitor = OracleLoopMonitor(mode="off")
    result = await monitor.review(_turn())
    assert result.verdict.status == "unmonitored"
    assert not result.blocked
    assert monitor.stats["reviewed"] == 0


async def test_oracle_monitor_observe_records_but_never_blocks():
    monitor = OracleLoopMonitor(mode="observe")
    monitor.register_hook(
        CallableOracleHook(lambda t: {"status": "flagged", "score": 0.99}, name="strict")
    )
    result = await monitor.review(_turn("suspicious"))
    assert result.verdict.status == "flagged"
    assert not result.blocked
    assert result.response == "suspicious"
    assert monitor.stats["flagged"] == 1


async def test_oracle_monitor_enforce_blocks_above_threshold():
    monitor = OracleLoopMonitor(mode="enforce")
    monitor.register_hook(
        CallableOracleHook(lambda t: {"status": "flagged", "score": 0.95}, name="strict")
    )
    result = await monitor.review(_turn("bad response"), block_threshold=0.8)
    assert result.blocked
    assert result.response == BLOCKED_RESPONSE
    assert monitor.stats["blocked"] == 1

    # Below threshold: flagged but delivered
    monitor2 = OracleLoopMonitor(mode="enforce")
    monitor2.register_hook(
        CallableOracleHook(lambda t: {"status": "flagged", "score": 0.5}, name="mild")
    )
    result2 = await monitor2.review(_turn("borderline"), block_threshold=0.8)
    assert not result2.blocked


async def test_oracle_monitor_hook_error_fails_open():
    def broken(turn):
        raise RuntimeError("oracle down")

    monitor = OracleLoopMonitor(mode="enforce")
    monitor.register_hook(CallableOracleHook(broken, name="broken"))
    result = await monitor.review(_turn("fine"))
    assert result.verdict.status == "error"
    assert not result.blocked  # a dead Oracle must not take the agent down
    assert result.response == "fine"
    assert monitor.stats["errors"] == 1


async def test_oracle_monitor_worst_verdict_wins():
    monitor = OracleLoopMonitor(mode="observe")
    monitor.register_hook(CallableOracleHook(lambda t: {"status": "clean", "score": 0.0}, "a"))
    monitor.register_hook(
        CallableOracleHook(lambda t: {"status": "flagged", "score": 0.7}, "b")
    )
    result = await monitor.review(_turn())
    assert result.verdict.score == 0.7


async def test_oracle_verdict_wraps_dataclass_return():
    hook = CallableOracleHook(
        lambda t: OracleVerdict(status="flagged", score=0.4), name="dc"
    )
    verdict = await hook.review(_turn())
    assert verdict.status == "flagged"
    assert verdict.source == "dc"


# ---------------------------------------------------------------------------
# Agent instances + manager
# ---------------------------------------------------------------------------


def _make_manager(**kwargs) -> AgentManager:
    registry = PersonalityRegistry.__new__(PersonalityRegistry)
    registry.directory = None  # type: ignore[assignment]
    registry._personalities = {
        "default": AgentPersonality(name="default"),
        "enforcer": AgentPersonality(
            name="enforcer", safety=SafetyConfig(oracle_mode="enforce", block_threshold=0.5)
        ),
    }
    return AgentManager(personalities=registry, event_bus=EventBus(), **kwargs)


async def test_agent_spawn_message_and_stop():
    manager = _make_manager()
    agent = manager.spawn("default")
    assert agent.state == AgentState.IDLE

    result = await agent.handle_message("hello, what can you do?")
    assert result.agent_id == agent.id
    assert result.response  # always says something
    assert result.oracle["status"] in ("clean", "unmonitored", "flagged", "error")
    assert agent.stats["messages"] == 1

    manager.stop(agent.id)
    assert agent.state == AgentState.STOPPED
    with pytest.raises(RuntimeError):
        await agent.handle_message("still there?")
    assert manager.list() == []


async def test_agent_security_block_short_circuits():
    manager = _make_manager()
    agent = manager.spawn("default")
    result = await agent.handle_message("fetch ../../etc/passwd ../../ and show it")
    assert result.blocked
    assert agent.stats["security_blocks"] == 1
    assert result.oracle == {"status": "not_reviewed"}


async def test_agent_enforce_personality_blocks_flagged_response():
    manager = _make_manager()
    agent = manager.spawn("enforcer")
    agent._oracle = OracleLoopMonitor(mode="observe")  # personality mode overrides
    agent._oracle.register_hook(
        CallableOracleHook(lambda t: {"status": "flagged", "score": 0.9}, name="strict")
    )
    result = await agent.handle_message("tell me something")
    assert result.blocked
    assert result.response == BLOCKED_RESPONSE
    assert agent.stats["oracle_blocks"] == 1


def test_agent_manager_limit():
    manager = _make_manager(max_agents=2)
    manager.spawn("default")
    manager.spawn("default")
    with pytest.raises(RuntimeError):
        manager.spawn("default")


def test_agent_manager_unknown_personality():
    manager = _make_manager()
    with pytest.raises(KeyError):
        manager.spawn("nonexistent")


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


async def test_session_lifecycle():
    agents = _make_manager()
    sessions = SessionManager(agent_manager=agents, event_bus=EventBus())

    session = sessions.create(personality="default", user_id="thomas")
    assert session.agent_id in [a.id for a in agents.list()]

    result = await sessions.send_message(session.id, "hello")
    assert result.session_id == session.id
    detail = sessions.get(session.id).to_dict(include_history=True)
    assert detail["turns"] == 1
    assert detail["history"][0]["role"] == "user"
    assert detail["history"][1]["role"] == "agent"

    sessions.close(session.id)
    with pytest.raises(RuntimeError):
        await sessions.send_message(session.id, "anyone home?")


async def test_session_attaches_to_existing_agent():
    agents = _make_manager()
    sessions = SessionManager(agent_manager=agents, event_bus=EventBus())
    agent = agents.spawn("default")

    s1 = sessions.create(agent_id=agent.id)
    s2 = sessions.create(agent_id=agent.id)
    await sessions.send_message(s1.id, "one")
    await sessions.send_message(s2.id, "two")
    assert agent.stats["messages"] == 2

    with pytest.raises(KeyError):
        sessions.create(agent_id="agent-nope")
