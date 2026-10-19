"""Vera's review of the consensus consumer (2026-10-18 18:09): items 1-4, each with tests that fail without the fix.

1. an approval can't strand: audited before it's committed, still withdrawable, runnable by a retry route or the
   startup sweep within a window, expired after it;
2. high-stakes holds need two people: every held action names its category;
3. no forged consent: the redeemed marker is the token itself, and agent_v2's metadata is an allowlist;
4. a membership renewal, which changes the tier and charges for it, is held.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from kintsugi.governance import consumer
from kintsugi.governance.consensus import ConsentCategory, ConsentStatus, ConsensusGate, get_consensus_gate
from kintsugi.skills.base import (CONSENT_REDEEMED, BaseSkillChip, SkillContext, SkillDomain, SkillRequest,
                                  SkillResponse, consent_given)

DONE = []


class Ledger(BaseSkillChip):
    name = "test_review_ledger"
    description = "pays out"
    domain = SkillDomain.OPERATIONS
    consensus_actions = ["disburse_funds"]
    consensus_intents = {"pay_out": "disburse_funds"}
    consensus_categories = {"disburse_funds": "GENERAL"}

    async def handle(self, request, context):
        DONE.append(request.entities.get("amount"))
        return SkillResponse(content="paid")


class Registry:
    def __init__(self, *chips):
        self.chips = {c.name: c for c in chips}

    def get(self, name):
        return self.chips.get(name)


@pytest.fixture(autouse=True)
def _clean():
    DONE.clear()
    yield
    DONE.clear()


def ctx(org="org_a", user="key:k-asker", **meta):
    return SkillContext(org_id=org, user_id=user, metadata=meta)


async def held(chip=None, org="org_a", user="key:k-asker"):
    r = await (chip or Ledger()).handle(SkillRequest(intent="pay_out", raw_input="pay", entities={"amount": 5}),
                                        ctx(org, user))
    return r.data["consent_id"]


# ---- 1. an approval can't strand ------------------------------------------------------------------------------------

def _client_and_keys(make_headers, monkeypatch, chip):
    from fastapi.testclient import TestClient
    from kintsugi.main import app
    from kintsugi.security.api_keys import get_key_store
    from kintsugi.skills import registry as registry_mod
    monkeypatch.setattr(registry_mod, "get_registry", lambda: Registry(chip))
    admin = make_headers("admin", "org_a", "approver")
    member = make_headers("member", "org_a", "asker")
    asker = next(r for r in get_key_store().list() if r.label == "asker")
    return TestClient(app, raise_server_exceptions=False), admin, member, f"key:{asker.id}"


@pytest.mark.asyncio
async def test_an_approval_whose_audit_cant_be_written_isnt_committed(make_headers, monkeypatch, tmp_path):
    from kintsugi.config.settings import settings
    chip = Ledger()
    client, admin, _, asker = _client_and_keys(make_headers, monkeypatch, chip)
    item_id = await held(chip, user=asker)
    blocked = tmp_path / "no-audit"
    blocked.mkdir()
    monkeypatch.setattr(settings, "AUDIT_LOG_FILE", str(blocked))        # a directory: the append fails
    r = client.post(f"/api/v1/consensus/{item_id}/approve", json={}, headers=admin)
    assert r.status_code == 500
    assert get_consensus_gate().get_item(item_id, org_id="org_a").status == ConsentStatus.PENDING and DONE == []


@pytest.mark.asyncio
async def test_a_stranded_approval_runs_once_through_the_retry_route(make_headers, monkeypatch):
    chip = Ledger()
    client, admin, member, asker = _client_and_keys(make_headers, monkeypatch, chip)
    item_id = await held(chip, user=asker)
    get_consensus_gate().approve(item_id, "key:k-admin", org_id="org_a")     # committed, then the process "died"
    assert client.post(f"/api/v1/consensus/{item_id}/run", headers=member).status_code == 403
    r = client.post(f"/api/v1/consensus/{item_id}/run", headers=admin)
    assert r.status_code == 200 and r.json()["item"]["status"] == "EXECUTED" and DONE == [5]
    assert client.post(f"/api/v1/consensus/{item_id}/run", headers=admin).status_code == 409 and DONE == [5]


@pytest.mark.asyncio
async def test_the_asker_can_withdraw_an_approval_that_hasnt_run(make_headers, monkeypatch):
    chip = Ledger()
    client, admin, member, asker = _client_and_keys(make_headers, monkeypatch, chip)
    item_id = await held(chip, user=asker)
    get_consensus_gate().approve(item_id, "key:k-admin", org_id="org_a")
    r = client.post(f"/api/v1/consensus/{item_id}/reject", json={"rationale": "no longer needed"}, headers=member)
    assert r.status_code == 200 and r.json()["item"]["status"] == "REJECTED"
    assert client.post(f"/api/v1/consensus/{item_id}/run", headers=admin).status_code == 409 and DONE == []


def test_an_approval_left_past_its_window_expires_instead_of_running():
    gate = ConsensusGate()
    item = gate.submit("org_a", ConsentCategory.GENERAL, "t", {"x": 1}, requester="key:k1")
    gate.approve(item.id, "key:k2", org_id="org_a")
    item.resolved_at = datetime.now(timezone.utc) - timedelta(hours=2)
    with pytest.raises(ValueError, match="not run within"):
        gate.claim(item.id, org_id="org_a")
    assert item.status == ConsentStatus.EXPIRED


def test_an_expired_approval_is_written_to_disk(tmp_path):
    path = tmp_path / "consent.json"
    gate = ConsensusGate(path=path)
    item = gate.submit("org_a", ConsentCategory.GENERAL, "t", {"x": 1}, requester="key:k1")
    gate.approve(item.id, "key:k2", org_id="org_a")
    import json
    rows = json.loads(path.read_text())
    rows[0]["resolved_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    path.write_text(json.dumps(rows))
    with pytest.raises(ValueError):
        gate.claim(item.id, org_id="org_a")
    assert ConsensusGate(path=path).get_item(item.id, org_id="org_a").status == ConsentStatus.EXPIRED


@pytest.mark.asyncio
async def test_the_startup_sweep_runs_fresh_approvals_and_expires_stale_ones():
    chip = Ledger()
    fresh, stale = await held(chip), await held(chip)
    gate = get_consensus_gate()
    gate.approve(fresh, "key:k-admin", org_id="org_a")
    gate.approve(stale, "key:k-admin", org_id="org_a")
    rows = gate._path.read_text()
    import json
    data = json.loads(rows)
    for d in data:
        if d["id"] == stale:
            d["resolved_at"] = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    gate._path.write_text(json.dumps(data))
    swept = await consumer.sweep_approved(Registry(chip))
    assert swept == {"ran": [fresh], "expired": [stale]} and DONE == [5]


@pytest.mark.asyncio
async def test_starting_the_app_runs_a_stranded_approval(monkeypatch):
    from fastapi.testclient import TestClient
    from kintsugi.main import app
    from kintsugi.skills import registry as registry_mod
    chip = Ledger()
    monkeypatch.setattr(registry_mod, "get_registry", lambda: Registry(chip))
    item_id = await held(chip)
    get_consensus_gate().approve(item_id, "key:k-admin", org_id="org_a")      # committed; then the server stopped
    with TestClient(app):                                                    # starting runs the lifespan
        pass
    assert get_consensus_gate().get_item(item_id, org_id="org_a").status == ConsentStatus.EXECUTED and DONE == [5]


# ---- 2. high-stakes holds need two people --------------------------------------------------------------------------

def _shipped():
    from tests.test_consensus_intent_maps_20261018 import CHIPS
    return CHIPS


def test_every_held_action_names_its_category():
    for cls in _shipped():
        for action in set(cls.consensus_intents.values()):
            named = cls.consensus_categories.get(action)
            assert named, f"{cls.__name__}: {action} has no category, so it would default to one approver"
            ConsentCategory(named)


HIGH_STAKES = re.compile(r"_funds\b|financ|invoice|refund|withdraw|tier|payment|share_\w*(info|data)|requester|tenant|donor")


def test_money_and_private_information_take_two_people():
    seen = set()
    for cls in _shipped():
        for action in set(cls.consensus_intents.values()):
            if HIGH_STAKES.search(action):
                seen.add(action)
                assert cls.consensus_categories[action] in ("FINANCIAL", "PII"), (cls.__name__, action)
    assert {"release_bail_funds", "time_bank_withdrawal", "create_invoice", "change_membership_tier",
            "share_requester_info"} <= seen


@pytest.mark.asyncio
async def test_a_bail_fund_release_waits_for_a_second_person():
    from kintsugi.skills.community_aid.rapid_response import RapidResponseChip
    r = await RapidResponseChip().handle(SkillRequest(intent="bail_request", raw_input="bail"), ctx())
    gate = get_consensus_gate()
    assert gate.get_item(r.data["consent_id"], org_id="org_a").category == ConsentCategory.FINANCIAL
    assert gate.approve(r.data["consent_id"], "key:k-a1", org_id="org_a").status == ConsentStatus.PENDING


# ---- 3. no forged consent -------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_callers_redeemed_flag_is_not_consent():
    assert consent_given(ctx(**{CONSENT_REDEEMED: True})) is False
    r = await Ledger().handle(SkillRequest(intent="pay_out", raw_input="pay", entities={"amount": 5}),
                              ctx(**{CONSENT_REDEEMED: True}))
    assert r.metadata.get("held") and DONE == []


def test_agent_v2_metadata_is_an_allowlist():
    from kintsugi.api.auth import Principal
    from kintsugi.api.metadata import trusted_metadata
    meta = trusted_metadata({"location": "Arcata", "_consent_redeemed": True, "consent_withdrawn": False,
                             "role": "admin", "user_id": "alice", "anything": 1},
                            Principal(org_id="org_a", key_id="k1", role="member"))
    assert meta == {"location": "Arcata", "role": "member", "claimed_user": "alice"}


def test_agent_v2_uses_the_allowlist():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "kintsugi" / "api" / "routes" / "agent_v2.py").read_text()
    assert "from kintsugi.api.metadata import trusted_metadata" in src and "dict(body_context" not in src


@pytest.mark.asyncio
async def test_a_chip_wrapped_twice_runs_once_when_approved():
    class Inner(Ledger):
        name = "test_review_inner"

    class Outer(Inner):
        name = "test_review_outer"

        async def handle(self, request, context):
            return await super().handle(request, context)
    chip = Outer()
    item_id = await held(chip)
    get_consensus_gate().approve(item_id, "key:k-admin", org_id="org_a")
    result = await consumer.execute_approved(item_id, "org_a", Registry(chip))
    assert result["success"] and DONE == [5]


# ---- 4. a renewal is held -------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_renewal_that_charges_for_a_tier_is_held_and_needs_two_people():
    from kintsugi.skills.programs_people.member_services import MemberServicesChip
    chip = MemberServicesChip()
    r = await chip.handle(SkillRequest(intent="membership_renew", raw_input="renew", entities={
        "member_id": "m-1", "tier": "gold"}), ctx())
    assert r.metadata.get("held") and r.consensus_action == "change_membership_tier"
    gate = get_consensus_gate()
    assert gate.approve(r.data["consent_id"], "key:k-a1", org_id="org_a").status == ConsentStatus.PENDING
    assert gate.approve(r.data["consent_id"], "key:k-a2", org_id="org_a").status == ConsentStatus.APPROVED
    result = await consumer.execute_approved(r.data["consent_id"], "org_a", Registry(chip))
    assert result["success"] and "processed successfully" in result["content"]
