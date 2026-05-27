"""Tests for Program Function intervention layer on skill chips."""

import asyncio
from datetime import datetime, timezone, timedelta

import pytest

from kintsugi.skills.base import (
    ActivationCondition,
    BaseSkillChip,
    InterventionAction,
    ProgramFunction,
    SkillCapability,
    SkillContext,
    SkillDomain,
    SkillRequest,
    SkillResponse,
)


class EchoChip(BaseSkillChip):
    name = "echo"
    description = "Echoes input for testing"
    domain = SkillDomain.OPERATIONS

    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        return SkillResponse(content=f"echo: {request.raw_input}")


def _ctx(**kwargs) -> SkillContext:
    defaults = {"org_id": "test-org", "user_id": "test-user"}
    defaults.update(kwargs)
    return SkillContext(**defaults)


def _always_true(ctx, state):
    return True


def _always_false(ctx, state):
    return False


def _state_has_error(ctx, state):
    return state.get("error") is True


def _modify_request(request, context, state):
    return SkillRequest(
        intent=request.intent,
        raw_input=f"[MODIFIED] {request.raw_input}",
        entities=request.entities,
    )


def _short_circuit(request, context, state):
    return SkillResponse(content="INTERCEPTED", success=True)


class TestActivationCondition:
    def test_basic_predicate(self):
        cond = ActivationCondition(
            name="test", description="always fires", predicate=_always_true
        )
        assert cond.predicate(_ctx(), {})

    def test_priority_default(self):
        cond = ActivationCondition(name="t", description="d", predicate=_always_true)
        assert cond.priority == 0

    def test_cooldown_default(self):
        cond = ActivationCondition(name="t", description="d", predicate=_always_true)
        assert cond.cooldown_seconds == 0.0


class TestProgramFunction:
    def test_should_fire_when_enabled(self):
        pf = ProgramFunction(
            condition=ActivationCondition(name="t", description="d", predicate=_always_true),
            intervention=InterventionAction(name="i", description="d", action=_modify_request),
        )
        assert pf.should_fire(_ctx(), {})

    def test_should_not_fire_when_disabled(self):
        pf = ProgramFunction(
            condition=ActivationCondition(name="t", description="d", predicate=_always_true),
            intervention=InterventionAction(name="i", description="d", action=_modify_request),
            enabled=False,
        )
        assert not pf.should_fire(_ctx(), {})

    def test_should_not_fire_when_predicate_false(self):
        pf = ProgramFunction(
            condition=ActivationCondition(name="t", description="d", predicate=_always_false),
            intervention=InterventionAction(name="i", description="d", action=_modify_request),
        )
        assert not pf.should_fire(_ctx(), {})

    def test_cooldown_prevents_rapid_fire(self):
        pf = ProgramFunction(
            condition=ActivationCondition(
                name="t", description="d", predicate=_always_true, cooldown_seconds=60.0
            ),
            intervention=InterventionAction(name="i", description="d", action=_modify_request),
            last_activated=datetime.now(timezone.utc),
        )
        assert not pf.should_fire(_ctx(), {})

    def test_cooldown_allows_after_expiry(self):
        pf = ProgramFunction(
            condition=ActivationCondition(
                name="t", description="d", predicate=_always_true, cooldown_seconds=1.0
            ),
            intervention=InterventionAction(name="i", description="d", action=_modify_request),
            last_activated=datetime.now(timezone.utc) - timedelta(seconds=5),
        )
        assert pf.should_fire(_ctx(), {})

    def test_fire_increments_count(self):
        pf = ProgramFunction(
            condition=ActivationCondition(name="t", description="d", predicate=_always_true),
            intervention=InterventionAction(name="i", description="d", action=_modify_request),
        )
        req = SkillRequest(intent="test", raw_input="hello")
        pf.fire(req, _ctx(), {})
        assert pf.activation_count == 1
        assert pf.last_activated is not None

    def test_fire_with_state_predicate(self):
        pf = ProgramFunction(
            condition=ActivationCondition(name="err", description="on error", predicate=_state_has_error),
            intervention=InterventionAction(name="fix", description="fix error", action=_short_circuit),
        )
        assert not pf.should_fire(_ctx(), {"error": False})
        assert pf.should_fire(_ctx(), {"error": True})


class TestSkillChipWithPF:
    def test_register_program_function(self):
        chip = EchoChip()
        pf = ProgramFunction(
            condition=ActivationCondition(name="t", description="d", predicate=_always_true),
            intervention=InterventionAction(name="i", description="d", action=_modify_request),
        )
        chip.register_program_function(pf)
        assert len(chip.program_functions) == 1

    def test_evaluate_interventions_returns_triggered(self):
        chip = EchoChip()
        chip.register_program_function(ProgramFunction(
            condition=ActivationCondition(name="fires", description="d", predicate=_always_true),
            intervention=InterventionAction(name="i", description="d", action=_modify_request),
        ))
        chip.register_program_function(ProgramFunction(
            condition=ActivationCondition(name="silent", description="d", predicate=_always_false),
            intervention=InterventionAction(name="i2", description="d", action=_modify_request),
        ))
        triggered = chip.evaluate_interventions(_ctx(), {})
        assert len(triggered) == 1
        assert triggered[0].condition.name == "fires"

    def test_evaluate_returns_priority_sorted(self):
        chip = EchoChip()
        chip.register_program_function(ProgramFunction(
            condition=ActivationCondition(name="low", description="d", predicate=_always_true, priority=1),
            intervention=InterventionAction(name="i", description="d", action=_modify_request),
        ))
        chip.register_program_function(ProgramFunction(
            condition=ActivationCondition(name="high", description="d", predicate=_always_true, priority=10),
            intervention=InterventionAction(name="i2", description="d", action=_modify_request),
        ))
        triggered = chip.evaluate_interventions(_ctx(), {})
        assert triggered[0].condition.name == "high"
        assert triggered[1].condition.name == "low"

    def test_handle_with_interventions_modifies_request(self):
        chip = EchoChip()
        chip.register_program_function(ProgramFunction(
            condition=ActivationCondition(name="mod", description="d", predicate=_always_true),
            intervention=InterventionAction(
                name="prefix", description="d", action=_modify_request, modifies_request=True
            ),
        ))
        req = SkillRequest(intent="test", raw_input="hello")
        resp = asyncio.get_event_loop().run_until_complete(
            chip.handle_with_interventions(req, _ctx())
        )
        assert resp.content == "echo: [MODIFIED] hello"

    def test_handle_with_interventions_short_circuits(self):
        chip = EchoChip()
        chip.register_program_function(ProgramFunction(
            condition=ActivationCondition(name="block", description="d", predicate=_always_true),
            intervention=InterventionAction(
                name="intercept", description="d", action=_short_circuit, modifies_request=False
            ),
        ))
        req = SkillRequest(intent="test", raw_input="hello")
        resp = asyncio.get_event_loop().run_until_complete(
            chip.handle_with_interventions(req, _ctx())
        )
        assert resp.content == "INTERCEPTED"

    def test_handle_without_interventions_passes_through(self):
        chip = EchoChip()
        req = SkillRequest(intent="test", raw_input="hello")
        resp = asyncio.get_event_loop().run_until_complete(
            chip.handle_with_interventions(req, _ctx())
        )
        assert resp.content == "echo: hello"

    def test_get_info_includes_program_functions(self):
        chip = EchoChip()
        chip.register_program_function(ProgramFunction(
            condition=ActivationCondition(name="cond1", description="d", predicate=_always_true),
            intervention=InterventionAction(name="act1", description="d", action=_modify_request),
        ))
        info = chip.get_info()
        assert len(info["program_functions"]) == 1
        assert info["program_functions"][0]["condition"] == "cond1"
        assert info["program_functions"][0]["intervention"] == "act1"

    def test_conditional_intervention_on_error_state(self):
        chip = EchoChip()
        chip.register_program_function(ProgramFunction(
            condition=ActivationCondition(name="err", description="on error", predicate=_state_has_error),
            intervention=InterventionAction(
                name="fix", description="error handler", action=_short_circuit, modifies_request=False
            ),
        ))
        req = SkillRequest(intent="test", raw_input="hello")

        resp_ok = asyncio.get_event_loop().run_until_complete(
            chip.handle_with_interventions(req, _ctx(), state={"error": False})
        )
        assert resp_ok.content == "echo: hello"

        resp_err = asyncio.get_event_loop().run_until_complete(
            chip.handle_with_interventions(req, _ctx(), state={"error": True})
        )
        assert resp_err.content == "INTERCEPTED"
