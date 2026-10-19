"""The consensus consumer (Vera's re-check of 8e4fae5, 2026-10-18: "nothing consumes consensus").

An intent a chip maps to a consensus action is held before the chip runs, on every path; the gate is bound to its org
and its requester, refuses an approval after the timeout, has no auto-approve, keeps its items on disk, and runs an
approved item once. Each test fails on the code before this change.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from kintsugi.governance import consumer
from kintsugi.governance.consensus import ConsentCategory, ConsentStatus, ConsensusGate, get_consensus_gate
from kintsugi.skills.base import BaseSkillChip, SkillContext, SkillDomain, SkillRequest, SkillResponse

DONE = []      # what the test chip actually did: (org, amount)


class Ledger(BaseSkillChip):
    name = "test_consensus_ledger"
    description = "a test chip that pays out"
    domain = SkillDomain.OPERATIONS
    simulated = False  # a test fixture whose responses are exactly what it did
    consensus_actions = ["disburse_funds"]
    consensus_intents = {"pay_out": "disburse_funds"}

    async def handle(self, request, context):
        if request.intent == "pay_out":
            DONE.append((context.org_id, request.entities.get("amount")))
            return SkillResponse(content=f"paid {request.entities.get('amount')}")
        return SkillResponse(content="balance: 10")


class Registry:
    def __init__(self, *chips):
        self.chips = {c.name: c for c in chips}

    def get(self, name):
        return self.chips.get(name)


def ctx(org="org_a", user="key:k-asker", **meta):
    return SkillContext(org_id=org, user_id=user, metadata=meta)


def pay(amount=40, approved=None):
    params = {"approved": approved} if approved is not None else {}
    return SkillRequest(intent="pay_out", raw_input="pay", entities={"amount": amount}, parameters=params)


@pytest.fixture(autouse=True)
def _clean():
    DONE.clear()
    yield
    DONE.clear()


# ---- the hold -------------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_mapped_intent_is_held_and_nothing_happens():
    r = await Ledger().handle(pay(), ctx())
    assert DONE == []
    assert r.requires_consensus and r.consensus_action == "disburse_funds" and r.data["status"] == "PENDING"
    item = get_consensus_gate().get_item(r.data["consent_id"], org_id="org_a")
    assert item.requester == "key:k-asker" and item.action_payload["entities"] == {"amount": 40}


@pytest.mark.asyncio
async def test_an_unmapped_intent_runs_as_before():
    r = await Ledger().handle(SkillRequest(intent="balance", raw_input="b"), ctx())
    assert r.content == "balance: 10" and not r.requires_consensus


@pytest.mark.asyncio
async def test_a_caller_cant_pass_as_approved():
    # Not with the old parameter, and not with a token in the metadata it doesn't hold.
    r = await Ledger().handle(pay(approved=True), ctx(**{consumer.CONSENT_TOKEN: "approved", "consent_id": "x"}))
    assert DONE == [] and r.requires_consensus
    assert "approved" not in get_consensus_gate().get_item(r.data["consent_id"], org_id="org_a").action_payload[
        "parameters"]


# ---- approval and the single run ------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_an_approved_item_runs_once_exactly_as_asked():
    chip = Ledger()
    r = await chip.handle(pay(40), ctx())
    gate = get_consensus_gate()
    gate.approve(r.data["consent_id"], "key:k-admin", org_id="org_a")
    result = await consumer.execute_approved(r.data["consent_id"], "org_a", Registry(chip))
    assert result["success"] and DONE == [("org_a", 40)]
    assert gate.get_item(r.data["consent_id"], org_id="org_a").status == ConsentStatus.EXECUTED
    with pytest.raises(ValueError, match="not approved"):
        await consumer.execute_approved(r.data["consent_id"], "org_a", Registry(chip))
    assert DONE == [("org_a", 40)]


@pytest.mark.asyncio
async def test_a_token_works_once_and_only_for_its_own_request():
    chip = Ledger()
    r = await chip.handle(pay(40), ctx())
    item_id = r.data["consent_id"]
    get_consensus_gate().approve(item_id, "key:k-admin", org_id="org_a")
    item = get_consensus_gate().claim(item_id, org_id="org_a")
    token = consumer._Token(item.id, "org_a", "disburse_funds", item.payload_digest)
    with consumer._lock:
        consumer._live.add(token)
    # a different amount under the same token is refused, and that look used the token up
    refused = await chip.handle(pay(4000), ctx(**{consumer.CONSENT_TOKEN: token}))
    assert refused.requires_consensus and DONE == []
    again = await chip.handle(pay(40), ctx(**{consumer.CONSENT_TOKEN: token}))
    assert again.requires_consensus and DONE == []


@pytest.mark.asyncio
async def test_the_asker_cant_approve_and_another_org_cant_see():
    r = await Ledger().handle(pay(), ctx(user="key:k-asker"))
    gate = get_consensus_gate()
    with pytest.raises(ValueError, match="can't approve"):
        gate.approve(r.data["consent_id"], "key:k-asker", org_id="org_a")
    with pytest.raises(ValueError, match="No consent item"):
        gate.approve(r.data["consent_id"], "key:k-other-admin", org_id="org_b")
    assert gate.list_pending("org_b") == [] and gate.get_item(r.data["consent_id"], org_id="org_b") is None


def test_an_approval_after_the_timeout_is_refused():
    gate = ConsensusGate()
    item = gate.submit("org_a", ConsentCategory.GENERAL, "t", {}, requester="key:k1")
    item.created_at = datetime.now(timezone.utc) - timedelta(hours=25)
    with pytest.raises(ValueError, match="EXPIRED"):
        gate.approve(item.id, "key:k2", org_id="org_a")
    assert item.status == ConsentStatus.EXPIRED


def test_a_financial_action_needs_two_different_people():
    gate = ConsensusGate()
    item = gate.submit("org_a", ConsentCategory.FINANCIAL, "t", {}, requester="key:k1")
    assert gate.approve(item.id, "key:k2", org_id="org_a").status == ConsentStatus.PENDING
    assert gate.approve(item.id, "key:k2", org_id="org_a").status == ConsentStatus.PENDING
    assert gate.approve(item.id, "key:k3", org_id="org_a").status == ConsentStatus.APPROVED


def test_items_survive_a_restart_and_a_second_worker_sees_the_claim(tmp_path):
    path = tmp_path / "consent.json"
    one = ConsensusGate(path=path)
    item = one.submit("org_a", ConsentCategory.GENERAL, "t", {"x": 1}, requester="key:k1")
    one.approve(item.id, "key:k2", org_id="org_a")
    two = ConsensusGate(path=path)                         # another process, or after a restart
    assert two.get_item(item.id, org_id="org_a").status == ConsentStatus.APPROVED
    two.claim(item.id, org_id="org_a")
    with pytest.raises(ValueError, match="not approved"):
        one.claim(item.id, org_id="org_a")                 # the first worker reads the file, not its old copy


def test_an_item_changed_after_it_was_asked_for_cant_run(tmp_path):
    import json
    path = tmp_path / "consent.json"
    gate = ConsensusGate(path=path)
    item = gate.submit("org_a", ConsentCategory.GENERAL, "t", {"amount": 40}, requester="key:k1")
    gate.approve(item.id, "key:k2", org_id="org_a")
    rows = json.loads(path.read_text())
    rows[0]["action_payload"]["amount"] = 4000
    path.write_text(json.dumps(rows))
    with pytest.raises(ValueError, match="changed after"):
        gate.claim(item.id, org_id="org_a")


# ---- every path goes through the hold ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_direct_route_and_an_agent_both_get_the_hold(monkeypatch):
    from types import SimpleNamespace
    from kintsugi.agents.instance import AgentInstance
    from kintsugi.agents.personality import AgentPersonality
    from kintsugi.api.auth import Principal
    from kintsugi.api.routes import skills as route
    chip = Ledger()
    monkeypatch.setattr(route, "get_registry", lambda: Registry(chip))
    monkeypatch.setattr(route, "refuse_shell_capable", lambda *a, **k: None)
    out = await route.execute_skill("test_consensus_ledger", route.ExecuteSkillRequest(
        intent="pay_out", raw_input="pay", entities={"amount": 5}),
        principal=Principal(org_id="org_a", key_id="k1", role="member"))
    assert out["requires_consensus"] and DONE == []

    class Reg:
        def get_by_domain(self, domain):
            return [chip]

    class Oracle:
        async def review(self, turn, **kw):
            return SimpleNamespace(blocked=False, response=turn.response,
                                   verdict=SimpleNamespace(to_dict=lambda: {"status": "ok"}))
    agent = AgentInstance(AgentPersonality(name="t"), org_id="org_a", skill_registry=Reg(), oracle_monitor=Oracle())

    async def route_to(text, org_id, context=None):
        return SimpleNamespace(skill_domain="operations", confidence=1.0, reasoning="test")
    agent._orchestrator.route = route_to
    monkeypatch.setattr(AgentInstance, "_choose_intent", staticmethod(lambda chip, message, domain: "pay_out"))
    turn = await agent.handle_message("pay out 5", user_id="key:k1")
    assert turn.requires_consensus and turn.consensus_action == "disburse_funds" and DONE == []
    assert len(get_consensus_gate().list_pending("org_a")) == 2


# ---- the routes ------------------------------------------------------------------------------------------------------

def test_the_routes_list_approve_run_once_and_refuse_the_asker(make_headers, monkeypatch):
    from fastapi.testclient import TestClient
    from kintsugi.main import app
    from kintsugi.skills import registry as registry_mod
    chip = Ledger()
    monkeypatch.setattr(registry_mod, "get_registry", lambda: Registry(chip))
    member = make_headers("member", "org_a", "asker")
    admin = make_headers("admin", "org_a", "approver")
    other = make_headers("admin", "org_b", "elsewhere")
    client = TestClient(app)
    import asyncio
    asker_key = client.get("/api/v1/consensus/pending", headers=member)     # warm: the key exists
    assert asker_key.status_code == 200 and asker_key.json() == {"pending": []}
    from kintsugi.security.api_keys import get_key_store
    asker = next(r for r in get_key_store().list() if r.label == "asker")
    held = asyncio.run(chip.handle(pay(7), ctx(user=f"key:{asker.id}")))
    item_id = held.data["consent_id"]
    assert [i["id"] for i in client.get("/api/v1/consensus/pending", headers=member).json()["pending"]] == [item_id]
    assert client.get("/api/v1/consensus/pending", headers=other).json() == {"pending": []}
    assert client.post(f"/api/v1/consensus/{item_id}/approve", json={}, headers=other).status_code == 404
    assert client.post(f"/api/v1/consensus/{item_id}/approve", json={}, headers=member).status_code == 403
    r = client.post(f"/api/v1/consensus/{item_id}/approve", json={"rationale": "ok"}, headers=admin)
    assert r.status_code == 200 and r.json()["result"]["success"] and DONE == [("org_a", 7)]
    assert r.json()["item"]["status"] == "EXECUTED"
    assert client.post(f"/api/v1/consensus/{item_id}/approve", json={}, headers=admin).status_code == 409
    assert DONE == [("org_a", 7)]


def test_the_asker_can_withdraw_and_others_in_the_org_cant(make_headers):
    from fastapi.testclient import TestClient
    from kintsugi.main import app
    from kintsugi.security.api_keys import get_key_store
    import asyncio
    member = make_headers("member", "org_a", "asker")
    bystander = make_headers("member", "org_a", "bystander")
    asker = next(r for r in get_key_store().list() if r.label == "asker")
    held = asyncio.run(Ledger().handle(pay(7), ctx(user=f"key:{asker.id}")))
    client = TestClient(app)
    item_id = held.data["consent_id"]
    assert client.post(f"/api/v1/consensus/{item_id}/reject", json={}, headers=bystander).status_code == 403
    r = client.post(f"/api/v1/consensus/{item_id}/reject", json={"rationale": "never mind"}, headers=member)
    assert r.status_code == 200 and r.json()["item"]["status"] == "REJECTED"


@pytest.mark.asyncio
async def test_approval_of_a_chip_with_no_step_for_the_action_says_nothing_ran():
    class AsksAgain(BaseSkillChip):
        name = "test_consensus_asks_again"
        description = "flags without acting, even when approved"
        domain = SkillDomain.OPERATIONS
        consensus_actions = ["send_mass_email"]
        consensus_intents = {"blast": "send_mass_email"}

        async def handle(self, request, context):
            return SkillResponse(content="needs approval", requires_consensus=True, consensus_action="send_mass_email")
    chip = AsksAgain()
    r = await chip.handle(SkillRequest(intent="blast", raw_input="b"), ctx())
    get_consensus_gate().approve(r.data["consent_id"], "key:k-admin", org_id="org_a")
    result = await consumer.execute_approved(r.data["consent_id"], "org_a", Registry(chip))
    assert result["success"] is False and "no step that carries out send_mass_email" in result["content"]


# ---- Vera's three "act, then flag" cases: held, nothing done; approved, done once ------------------------------------

async def _approve_and_run(chip, held, org="org_a"):
    get_consensus_gate().approve(held.data["consent_id"], "key:k-admin", org_id=org)
    return await consumer.execute_approved(held.data["consent_id"], org, Registry(chip))


@pytest.mark.asyncio
async def test_a_partner_agreement_stores_no_partner_until_approved():
    from kintsugi.skills.base import org_scope
    from kintsugi.skills.community_aid.resource_redistribution import ResourceRedistributionChip
    chip = ResourceRedistributionChip()
    req = SkillRequest(intent="partner_connect", raw_input="partner", entities={
        "action": "add", "partner_name": "Riverside Pantry", "contact_email": "x@example.org", "is_mou": True})
    held = await chip.handle(req, ctx())
    with org_scope("org_a"):
        assert len(chip._partners) == 0 and held.metadata.get("held")
    result = await _approve_and_run(chip, held)
    with org_scope("org_a"):
        assert len(chip._partners) == 1
    assert result["success"] and "nothing ran" not in result["content"]


@pytest.mark.asyncio
async def test_a_raid_alert_notifies_nobody_until_approved():
    from kintsugi.skills.community_aid.rapid_response import RapidResponseChip
    chip = RapidResponseChip()
    held = await chip.handle(SkillRequest(intent="raid_alert", raw_input="raid", entities={
        "general_area": "Downtown"}), ctx())
    assert "nobody has been alerted" not in held.content and held.metadata.get("held")
    result = await _approve_and_run(chip, held)
    # The approved run is the chip's own step; with no alert network connected, it says nobody was alerted.
    assert "nobody has been alerted" in result["content"] and result["data"]["sent"] is False


@pytest.mark.asyncio
async def test_onboarding_completion_is_held_and_never_reported_done_without_an_hr_system():
    from kintsugi.skills.programs_people.staff_onboarding import StaffOnboardingChip
    chip = StaffOnboardingChip()
    held = await chip.handle(SkillRequest(intent="onboard_complete", raw_input="done", entities={
        "employee_id": "e-1", "force_complete": True}), ctx())
    assert "ompleted" not in held.content and held.metadata.get("held")
    result = await _approve_and_run(chip, held)
    # approval can't make a record exist: no HR system is connected (10-19)
    assert not result["success"] and "no step that carries out" in result["content"], result
    assert "ompleted" not in result["content"] and "acknowledged" not in result["content"]


# ---- the edges of the hold and the token ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_predicate_that_fails_holds_rather_than_runs():
    class Fragile(BaseSkillChip):
        name = "test_consensus_fragile"
        description = "a predicate that raises"
        domain = SkillDomain.OPERATIONS
        consensus_actions = ["disburse_funds"]
        consensus_intents = {"pay_out": "disburse_funds"}
        consensus_when = {"pay_out": lambda r: r.entities["missing"] > 1}

        async def handle(self, request, context):
            DONE.append("ran")
            return SkillResponse(content="ran")
    r = await Fragile().handle(pay(), ctx())
    assert r.metadata.get("held") and DONE == []


@pytest.mark.asyncio
@pytest.mark.parametrize("org,action", [("org_b", "disburse_funds"), ("org_a", "another_action")])
async def test_a_token_for_another_org_or_action_is_refused(org, action):
    chip = Ledger()
    held = await chip.handle(pay(40), ctx(org=org))
    item = get_consensus_gate().get_item(held.data["consent_id"], org_id=org)
    token = consumer._Token(item.id, "org_a" if org == "org_b" else org, action, item.payload_digest)
    with consumer._lock:
        consumer._live.add(token)
    again = await chip.handle(pay(40), ctx(org=org, **{consumer.CONSENT_TOKEN: token}))
    assert again.metadata.get("held") and DONE == []


@pytest.mark.asyncio
async def test_consent_never_runs_a_shell_capable_chip():
    from kintsugi.skills.base import SkillCapability

    class Shellish(BaseSkillChip):
        name = "test_consensus_shellish"
        description = "shell-capable, with a gated intent"
        domain = SkillDomain.OPERATIONS
        capabilities = [SkillCapability.EXECUTE_SHELL]
        consensus_actions = ["shell_execute"]
        consensus_intents = {"run": "shell_execute"}

        async def handle(self, request, context):
            DONE.append("shell ran")
            return SkillResponse(content="ran")
    chip = Shellish()
    held = await chip.handle(SkillRequest(intent="run", raw_input="ls"), ctx())
    get_consensus_gate().approve(held.data["consent_id"], "key:k-admin", org_id="org_a")
    result = await consumer.execute_approved(held.data["consent_id"], "org_a", Registry(chip))
    assert result["success"] is False and "shell" in result["content"] and DONE == []


@pytest.mark.asyncio
async def test_an_invoice_is_financial_and_needs_two_people():
    from kintsugi.skills.core_ops.finance_assistant import FinanceAssistantChip
    held = await FinanceAssistantChip().handle(SkillRequest(intent="invoice_create", raw_input="invoice", entities={
        "client_name": "Riverside Co-op", "amount": 1200}), ctx())
    gate = get_consensus_gate()
    item = gate.get_item(held.data["consent_id"], org_id="org_a")
    assert item.category == ConsentCategory.FINANCIAL
    assert gate.approve(item.id, "key:k-admin", org_id="org_a").status == ConsentStatus.PENDING


@pytest.mark.asyncio
async def test_an_approved_action_that_fails_names_an_error_id_not_the_exception():
    class Breaks(BaseSkillChip):
        name = "test_consensus_breaks"
        description = "fails when it runs"
        domain = SkillDomain.OPERATIONS
        consensus_actions = ["disburse_funds"]
        consensus_intents = {"pay_out": "disburse_funds"}

        async def handle(self, request, context):
            raise RuntimeError("SECRET connection string postgres://kintsugi:pw@db")
    chip = Breaks()
    held = await chip.handle(pay(), ctx())
    get_consensus_gate().approve(held.data["consent_id"], "key:k-admin", org_id="org_a")
    result = await consumer.execute_approved(held.data["consent_id"], "org_a", Registry(chip))
    assert result["success"] is False and "SECRET" not in result["content"] and "error " in result["content"]
    assert "SECRET" not in str(get_consensus_gate().get_item(held.data["consent_id"], org_id="org_a").result)
