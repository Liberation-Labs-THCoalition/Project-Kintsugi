"""Every chip's consensus actions are reachable through an explicit intent map, and every entry dispatches.

Vera's re-check (2026-10-18): 54 actions declared, 26 raised, none of the 11 high-stakes ones gated, and 0 of 54 intent
names equal to an action name, so `if chip.requires_consensus(request.intent)` would have blocked nothing while the
suite stayed green. These tests walk every shipped chip: a declared action is mapped from an intent or explained, a
raised action is declared, and each mapped intent is held, then, once approved, reaches a handler of its chip.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil

import pytest

import kintsugi.skills
from kintsugi.governance import consumer
from kintsugi.governance.consensus import get_consensus_gate
from kintsugi.skills.base import BaseSkillChip, SkillContext, SkillRequest


def _shipped_chips():
    for mod in pkgutil.walk_packages(kintsugi.skills.__path__, "kintsugi.skills."):
        importlib.import_module(mod.name)
    seen, stack = [], list(BaseSkillChip.__subclasses__())
    while stack:
        cls = stack.pop()
        stack.extend(cls.__subclasses__())
        if cls.__module__.startswith("kintsugi.skills.") and not inspect.isabstract(cls) and cls not in seen:
            seen.append(cls)
    return sorted(seen, key=lambda c: c.__name__)


CHIPS = _shipped_chips()
MAPPED = [(cls, intent, action) for cls in CHIPS for intent, action in sorted(cls.consensus_intents.items())]


def test_the_walk_finds_the_chips():
    assert len(CHIPS) >= 20 and len(MAPPED) >= 11


@pytest.mark.parametrize("cls", CHIPS, ids=lambda c: c.__name__)
def test_every_declared_action_is_mapped_from_an_intent_or_explained(cls):
    mapped = set(cls.consensus_intents.values())
    assert mapped <= set(cls.consensus_actions), f"mapped but not declared: {mapped - set(cls.consensus_actions)}"
    assert all(str(why).strip() for why in cls.consensus_unreachable.values())
    assert not set(cls.consensus_unreachable) & mapped, "an action can't be both mapped and unreachable"
    missing = set(cls.consensus_actions) - mapped - set(cls.consensus_unreachable)
    assert not missing, f"declared, and no intent reaches it, and no reason given: {sorted(missing)}"


@pytest.mark.parametrize("cls", CHIPS, ids=lambda c: c.__name__)
def test_every_action_a_chip_raises_is_declared(cls):
    tree = ast.parse(inspect.getsource(inspect.getmodule(cls)))
    raised = {kw.value.value for node in ast.walk(tree) if isinstance(node, ast.Call)
              for kw in node.keywords if kw.arg == "consensus_action" and isinstance(kw.value, ast.Constant)
              and isinstance(kw.value.value, str)}
    owners = {c for c in CHIPS if c.__module__ == cls.__module__}
    declared = set().union(*(set(c.consensus_actions) for c in owners))
    assert raised <= declared, f"raised but not declared: {sorted(raised - declared)}"


class _Registry:
    def __init__(self, chip):
        self.chip = chip

    def get(self, name):
        return self.chip if name == self.chip.name else None


# What a request that asks for the act looks like, where the chip only sometimes asks (its own condition, mirrored by
# its consensus_when); unconditional intents ask with no entities at all.
ASKS = {
    ("BoardLiaisonChip", "resolution_track"): {"action": "create"},
    ("CoalitionBuilderChip", "campaign_coordinate"): {"is_launch": True},
    ("CommunityAssetMapperChip", "asset_map"): {"share_publicly": True},
    ("CrisisResponseChip", "crisis_alert"): {"severity": "critical"},
    ("FinanceAssistantChip", "invoice_create"): {"client_name": "Riverside Co-op", "amount": 1200},
    ("FoodAccessChip", "food_donate"): {"quantity": 500},
    ("ImpactAuditorChip", "impact_report"): {"report_type": "funder", "submit": True},
    ("KnowYourRightsChip", "legal_clinic"): {"action": "schedule"},
    ("MemberServicesChip", "member_communicate"): {"bulk": True},
    ("MutualAidCoordinatorChip", "match_request"): {"confirm_match_id": "m-1"},
    ("MutualAidEnhancedChip", "match_request"): {"need_id": "n-1", "offer_id": "o-1"},
    ("ResourceRedistributionChip", "partner_connect"): {"action": "add", "partner_name": "P", "is_mou": True},
    ("SolidarityEconomyChip", "time_bank"): {"action": "exchange", "hours": 8},
    ("VolunteerCoordinatorChip", "volunteer_notify"): {"volunteer_ids": "all", "message": "Shift moved to 3pm"},
}
# Chips whose handler, approved, still has nothing that carries the act out: approval must say "nothing ran", never
# report it done. Every other mapped intent acts once approved, without asking again.
NO_STEP = {
    ("BoardLiaisonChip", "resolution_track"), ("KnowYourRightsChip", "legal_clinic"),
    ("MutualAidCoordinatorChip", "match_request"), ("ImpactAuditorChip", "impact_report"),
    ("SolidarityEconomyChip", "time_bank"), ("FinanceAssistantChip", "invoice_create"),
    ("MemberServicesChip", "member_communicate"),
}


def test_every_conditional_intent_has_an_example_that_asks():
    conditional = {(c.__name__, i) for c in CHIPS for i in (c.consensus_when or {})}
    assert conditional == set(ASKS)
    assert NO_STEP <= {(c.__name__, i) for c, i, _ in MAPPED}


@pytest.mark.asyncio
@pytest.mark.parametrize("cls,intent,action", MAPPED, ids=lambda v: getattr(v, "__name__", v))
async def test_each_mapped_intent_is_held_then_dispatched_once_approved(cls, intent, action):
    chip = cls()
    ctx = SkillContext(org_id="org_maps", user_id="key:k-asker")
    asks = ASKS.get((cls.__name__, intent), {})
    held = await chip.handle(SkillRequest(intent=intent, raw_input=f"test {intent}", entities=dict(asks)), ctx)
    assert held.requires_consensus and held.metadata.get("held") and held.consensus_action == action
    item_id = held.data["consent_id"]
    if get_consensus_gate().approve(item_id, "key:k-a1", org_id="org_maps").status.value == "PENDING":
        get_consensus_gate().approve(item_id, "key:k-a2", org_id="org_maps")   # FINANCIAL and PII take two
    result = await consumer.execute_approved(item_id, "org_maps", _Registry(chip))
    assert "Unknown intent" not in str(result["content"]), result
    if (cls.__name__, intent) in NO_STEP:
        assert result["success"] is False, result          # "no step", or the chip's own refusal: never "done"
    else:
        # it ran (the chip's own answer, which may be its own refusal), and didn't ask again
        assert "nothing ran" not in result["content"], result


@pytest.mark.asyncio
@pytest.mark.parametrize("key", sorted(ASKS), ids=lambda k: f"{k[0]}-{k[1]}")
async def test_a_conditional_intent_that_doesnt_ask_runs_as_before(key):
    cls = next(c for c in CHIPS if c.__name__ == key[0])
    r = await cls().handle(SkillRequest(intent=key[1], raw_input="test"), SkillContext(org_id="org_maps", user_id="u"))
    assert not r.metadata.get("held")
