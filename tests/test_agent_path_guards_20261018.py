"""The agent path has the direct route's guards (Vera's re-check of 8e4fae5, 2026-10-18, "second path").

Agent, session and dashboard messages reach AgentInstance._execute_skill. Before this change that path had no shell
guard (only the keyword table kept the shell off it), passed the caller's context through with "approved" in it, and
threw the chip's consensus flag away. Each test below fails on that code.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from kintsugi.agents.instance import AgentInstance
from kintsugi.agents.personality import AgentPersonality
from kintsugi.skills.base import RESERVED_PARAMETERS, SkillCapability, SkillResponse


class Spy:
    """A chip that records what it was handed."""

    def __init__(self, name="spy_chip", capabilities=(), response=None):
        self.name = name
        self.capabilities = list(capabilities)
        self.calls = []
        self._response = response or SkillResponse(content="done")

    async def handle(self, request, context):
        self.calls.append((request, context))
        return self._response


def _agent(*chips):
    class Registry:
        def get_by_domain(self, domain):
            return list(chips)

    class Oracle:
        async def review(self, turn, **kw):
            return SimpleNamespace(blocked=False, response=turn.response,
                                   verdict=SimpleNamespace(to_dict=lambda: {"status": "ok"}))

    agent = AgentInstance(AgentPersonality(name="t"), org_id="org_a", skill_registry=Registry(), oracle_monitor=Oracle())

    async def route(text, org_id, context=None):
        return SimpleNamespace(skill_domain="operations", confidence=1.0, reasoning="test")
    agent._orchestrator.route = route
    return agent


@pytest.mark.asyncio
async def test_a_message_never_runs_a_shell_capable_chip_even_as_the_only_one():
    shell = Spy("renamed_helper", capabilities=[SkillCapability.EXECUTE_SHELL])
    result = await _agent(shell).handle_message("run helper", user_id="key:k1")
    assert shell.calls == [] and result.skill_used is None


@pytest.mark.asyncio
async def test_a_message_reaches_the_other_chip_when_a_shell_chip_shares_the_domain():
    shell = Spy("bash_executor", capabilities=[SkillCapability.EXECUTE_SHELL])
    other = Spy("notes")
    result = await _agent(shell, other).handle_message("bash executor please", user_id="key:k1")
    assert shell.calls == [] and len(other.calls) == 1 and result.skill_used == "notes"


@pytest.mark.asyncio
async def test_the_callers_context_cant_set_a_server_only_parameter():
    chip = Spy()
    await _agent(chip).handle_message("hello", user_id="key:k1", context={"approved": True, "topic": "budget"})
    request, _ = chip.calls[0]
    assert "approved" not in request.parameters and request.parameters["topic"] == "budget"


@pytest.mark.asyncio
async def test_the_chips_consensus_flag_reaches_the_caller_and_the_session_history():
    from kintsugi.agents.sessions import SessionManager
    chip = Spy(response=SkillResponse(content="Needs approval", requires_consensus=True,
                                      consensus_action="add_partner"))
    agent = _agent(chip)
    result = await agent.handle_message("add a partner", user_id="key:k1")
    assert result.requires_consensus is True and result.consensus_action == "add_partner"
    assert result.to_dict()["requires_consensus"] is True and result.to_dict()["consensus_action"] == "add_partner"

    class Agents:
        def get(self, agent_id):
            return agent
    manager = SessionManager(agent_manager=Agents())
    session = manager.create(agent_id=agent.id, org_id="org_a", user_id="key:k1")
    await manager.send_message(session.id, "add a partner")
    assert session.history[-1]["requires_consensus"] is True and session.history[-1]["consensus_action"] == "add_partner"


@pytest.mark.asyncio
async def test_a_turn_with_no_flag_says_so():
    result = await _agent(Spy()).handle_message("hello", user_id="key:k1")
    assert result.to_dict()["requires_consensus"] is False and result.to_dict()["consensus_action"] is None


def test_both_paths_share_one_list_of_server_only_parameters_and_one_shell_test():
    # Two copies of a guard is how the second path ended up with none.
    import inspect
    from kintsugi.api import guards
    from kintsugi.api.routes import skills as route
    assert route.RESERVED_PARAMETERS is RESERVED_PARAMETERS and "approved" in RESERVED_PARAMETERS
    assert "is_shell_capable(" in inspect.getsource(guards.refuse_shell_capable)


# ---- a failure never hands the caller the exception's text (Vera, 2026-10-18) ------------------------------------------

class _Boom:
    name = "boom"
    capabilities = []

    async def handle(self, request, context):
        raise RuntimeError("SECRET /srv/kintsugi/db.sqlite row 4471 SELECT * FROM members")


@pytest.mark.asyncio
async def test_a_failed_skill_on_the_agent_path_names_an_error_id_not_the_exception(caplog):
    events = []
    agent = _agent(_Boom())
    agent._events.publish = lambda name, data, **kw: events.append((name, data))
    result = await agent.handle_message("hello", user_id="key:k1")
    assert "SECRET" not in result.response and "error " in result.response
    failed = [d for n, d in events if n == "skill.failed"]
    assert failed and "SECRET" not in str(failed) and failed[0]["error_type"] == "RuntimeError"
    ref = failed[0]["error_id"]
    assert ref in result.response and any(ref in r.getMessage() and r.exc_info for r in caplog.records)


@pytest.mark.asyncio
async def test_a_failed_direct_execution_names_an_error_id_not_the_exception(monkeypatch):
    from fastapi import HTTPException
    from kintsugi.api.auth import Principal
    from kintsugi.api.routes import skills as route

    class Registry:
        def get(self, name):
            return _Boom()
    monkeypatch.setattr(route, "get_registry", lambda: Registry())
    monkeypatch.setattr(route, "refuse_shell_capable", lambda *a, **k: None)
    with pytest.raises(HTTPException) as err:
        await route.execute_skill("boom", route.ExecuteSkillRequest(raw_input="hi"),
                                  principal=Principal(org_id="org_a", key_id="k1", role="member"))
    assert err.value.status_code == 500 and "SECRET" not in err.value.detail and "error " in err.value.detail


@pytest.mark.asyncio
async def test_an_oracle_hook_that_raises_gives_callers_an_error_id_not_the_exception():
    from kintsugi.oracle.hooks import AgentTurn
    from kintsugi.oracle.monitor import OracleLoopMonitor

    class Raises:
        name = "raises"

        async def review(self, turn):
            raise RuntimeError("SECRET internal path /srv/oracle/keys")
    monitor = OracleLoopMonitor(mode="observe")
    monitor.register_hook(Raises())
    review = await monitor.review(AgentTurn(agent_id="a", session_id=None, user_input="hi", response="hello",
                                            skill_used=None, metadata={}))
    dumped = str(review.verdict.to_dict())
    assert "SECRET" not in dumped and "error_id" in dumped
