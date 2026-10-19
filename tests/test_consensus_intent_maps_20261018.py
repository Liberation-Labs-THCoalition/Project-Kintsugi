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
import re

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
REASON = re.compile(r"^(no intent (performs|publishes|sends)|advisory: (?P<intent>\w+) returns|shell-capable chips "
                    r"are refused)")
MAPPED = [(cls, intent, action) for cls in CHIPS for intent, action in sorted(cls.consensus_intents.items())]


def test_the_walk_finds_the_chips():
    assert len(CHIPS) >= 20 and len(MAPPED) >= 11


@pytest.mark.parametrize("cls", CHIPS, ids=lambda c: c.__name__)
def test_every_declared_action_is_mapped_from_an_intent_or_explained(cls):
    mapped = set(cls.consensus_intents.values())
    assert mapped <= set(cls.consensus_actions), f"mapped but not declared: {mapped - set(cls.consensus_actions)}"
    # A reason in a known shape, not any string (Vera, 10-18 follow-ons): an advisory reason names a real intent.
    src = inspect.getsource(inspect.getmodule(cls))
    for action, why in cls.consensus_unreachable.items():
        m = REASON.match(str(why))
        assert m, f"{action}: {why!r} isn't a recognised reason"
        if m.group("intent"):
            assert f'"{m.group("intent")}"' in src, f"{action}: advisory names {m.group('intent')}, which isn't an intent"
    assert not set(cls.consensus_unreachable) & mapped, "an action can't be both mapped and unreachable"
    missing = set(cls.consensus_actions) - mapped - set(cls.consensus_unreachable)
    assert not missing, f"declared, and no intent reaches it, and no reason given: {sorted(missing)}"


def _values(expr) -> set:
    """The strings an expression can evaluate to: a constant, either branch of `a if cond else b`, any operand of
    `a or b`. The condition itself isn't a value."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return {expr.value}
    if isinstance(expr, ast.IfExp):
        return _values(expr.body) | _values(expr.orelse)
    if isinstance(expr, ast.BoolOp):
        return set().union(*(_values(v) for v in expr.values))
    return set()


@pytest.mark.parametrize("cls", CHIPS, ids=lambda c: c.__name__)
def test_every_action_a_chip_raises_is_declared(cls):
    tree = ast.parse(inspect.getsource(inspect.getmodule(cls)))
    # Every string anywhere in a consensus_action= expression, so `"x" if cond else None` counts too (Vera: the
    # constant-only walk missed 13 of 26 conditional raise sites).
    raised = {name for node in ast.walk(tree) if isinstance(node, ast.Call)
              for kw in node.keywords if kw.arg == "consensus_action" for name in _values(kw.value)}
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
    ("MemberServicesChip", "membership_renew"): {"member_id": "m-1", "tier": "gold"},
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
    ("MemberServicesChip", "member_communicate"), ("MemberServicesChip", "membership_renew"),
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


# Where an empty request would ask (a renewal defaults to the basic tier), the request that doesn't.
DOESNT_ASK = {("MemberServicesChip", "membership_renew"): {"member_id": "m-1", "tier": "no-such-tier"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("key", sorted(ASKS), ids=lambda k: f"{k[0]}-{k[1]}")
async def test_a_conditional_intent_that_doesnt_ask_runs_as_before(key):
    cls = next(c for c in CHIPS if c.__name__ == key[0])
    r = await cls().handle(SkillRequest(intent=key[1], raw_input="test", entities=dict(DOESNT_ASK.get(key, {}))),
                           SkillContext(org_id="org_maps", user_id="u"))
    assert not r.metadata.get("held")



def test_the_no_step_list_is_what_the_chips_declare():
    declared = {(cls.__name__, intent) for cls, intent, action in MAPPED if action in cls.consensus_no_step}
    assert declared == NO_STEP


async def _a_real_match():
    """A need, an offer and the match between them, so confirming reaches the chip's own step."""
    from kintsugi.skills.community_aid.mutual_aid_coordinator import MutualAidCoordinatorChip
    chip = MutualAidCoordinatorChip()
    c = SkillContext(org_id="org_maps", user_id="key:k-asker")
    need = await chip.handle(SkillRequest(intent="need_post", raw_input="n", entities={
        "category": "food", "description": "Groceries", "location": "Arcata"}), c)
    await chip.handle(SkillRequest(intent="offer_post", raw_input="o", entities={
        "categories": ["food"], "description": "Can bring groceries", "location": "Arcata"}), c)
    found = await chip.handle(SkillRequest(intent="match_request", raw_input="m",
                                           entities={"need_id": need.data["need_id"]}), c)
    return chip, found.data["matches"][0]["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("cls,intent,action", MAPPED, ids=lambda v: getattr(v, "__name__", v))
async def test_approval_asks_again_exactly_where_the_chip_says_it_has_no_step(cls, intent, action):
    entities = dict(ASKS.get((cls.__name__, intent), {}))
    chip = cls()
    if (cls.__name__, intent) == ("MutualAidCoordinatorChip", "match_request"):
        chip, entities["confirm_match_id"] = await _a_real_match()
    if (cls.__name__, intent) == ("StaffOnboardingChip", "onboard_complete"):
        entities["force_complete"] = True
    ctx = SkillContext(org_id="org_maps", user_id="key:k-asker")
    held = await chip.handle(SkillRequest(intent=intent, raw_input="t", entities=entities), ctx)
    gate = get_consensus_gate()
    if gate.approve(held.data["consent_id"], "key:k-a1", org_id="org_maps").status.value == "PENDING":
        gate.approve(held.data["consent_id"], "key:k-a2", org_id="org_maps")
    result = await consumer.execute_approved(held.data["consent_id"], "org_maps", _Registry(chip))
    assert ("no step that carries out" in result["content"]) == (action in cls.consensus_no_step), result


# Each predicate at its edge: the request just short of asking, and the one that asks (Vera: nothing pinned these).
BOUNDARIES = [
    ("FoodAccessChip", "food_donate", {"quantity": 100}, {"quantity": 101}),
    ("SolidarityEconomyChip", "time_bank", {"action": "exchange", "hours": 5}, {"action": "exchange", "hours": 6}),
    ("SolidarityEconomyChip", "time_bank", {"action": "balance", "hours": 9}, {"action": "exchange", "hours": 9}),
    ("VolunteerCoordinatorChip", "volunteer_notify", {"volunteer_ids": ["vol_001"] * 10, "message": "m"},
     {"volunteer_ids": ["vol_001"] * 11, "message": "m"}),
    ("CrisisResponseChip", "crisis_alert", {"severity": "high"}, {"severity": "critical"}),
    ("FinanceAssistantChip", "invoice_create", {"client_name": "Co-op"}, {"client_name": "Co-op", "amount": 1}),
    ("ResourceRedistributionChip", "partner_connect", {"action": "list", "is_mou": True},
     {"action": "add", "partner_name": "P", "is_mou": True}),
    ("ImpactAuditorChip", "impact_report", {"report_type": "funder"}, {"report_type": "funder", "submit": True}),
    ("MemberServicesChip", "membership_renew", {"tier": "no-such-tier"}, {"tier": "gold"}),
    ("MemberServicesChip", "member_communicate", {"bulk": False}, {"bulk": True}),
    ("CoalitionBuilderChip", "campaign_coordinate", {"is_launch": False}, {"is_launch": True}),
    ("CommunityAssetMapperChip", "asset_map", {"share_publicly": False}, {"share_publicly": True}),
    ("KnowYourRightsChip", "legal_clinic", {"action": "find"}, {"action": "schedule"}),
    ("MutualAidCoordinatorChip", "match_request", {"need_id": "n-1"}, {"confirm_match_id": "m-1"}),
    ("MutualAidEnhancedChip", "match_request", {"need_id": "n-1"}, {"need_id": "n-1", "offer_id": "o-1"}),
    ("BoardLiaisonChip", "resolution_track", {"action": "list"}, {"action": "create"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("name,intent,short,asks", BOUNDARIES, ids=lambda v: v if isinstance(v, str) else "")
async def test_each_predicate_holds_from_its_edge_and_not_before(name, intent, short, asks):
    cls = next(c for c in CHIPS if c.__name__ == name)
    c = SkillContext(org_id="org_edges", user_id="key:k-edge")
    below = await cls().handle(SkillRequest(intent=intent, raw_input="t", entities=dict(short)), c)
    at = await cls().handle(SkillRequest(intent=intent, raw_input="t", entities=dict(asks)), c)
    assert not below.metadata.get("held") and at.metadata.get("held")
