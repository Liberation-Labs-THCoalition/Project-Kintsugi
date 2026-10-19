"""Vera's follow-ons from her review of the consensus consumer (2026-10-18 18:09), each with a test that fails without
its fix: one person's two keys count once; mass notices count per requester per day; "all" reaches every volunteer;
a hold says when approval can't carry anything out; members don't see private payloads; a failed run gets one retry;
a damaged consent row doesn't take the gate down; the dashboard acts as the admin's key; the personality field that
nothing reads is gone from shipped files.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import pytest

from kintsugi.governance import consumer
from kintsugi.governance.consensus import (ConsentCategory, ConsentStatus, ConsensusGate, get_consensus_gate)
from kintsugi.skills.base import BaseSkillChip, SkillContext, SkillDomain, SkillRequest, SkillResponse

RUNS = []


class Registry:
    def __init__(self, *chips):
        self.chips = {c.name: c for c in chips}

    def get(self, name):
        return self.chips.get(name)


@pytest.fixture(autouse=True)
def _clean():
    RUNS.clear()
    yield
    RUNS.clear()


def ctx(org="org_a", user="key:k-asker"):
    return SkillContext(org_id=org, user_id=user)


# ---- one person, two keys -------------------------------------------------------------------------------------------

def test_the_askers_second_key_cant_approve_and_one_persons_keys_count_once():
    from kintsugi.security.api_keys import get_key_store, person_of
    store = get_key_store()
    a1, _ = store.create("org_a", "admin", "dana's laptop", person="dana")
    a2, _ = store.create("org_a", "admin", "dana's phone", person="dana")
    e1, _ = store.create("org_a", "admin", "eli 1", person="eli")
    e2, _ = store.create("org_a", "admin", "eli 2", person="eli")
    gate = ConsensusGate()
    asked = gate.submit("org_a", ConsentCategory.GENERAL, "t", {}, requester=f"key:{a1.id}",
                        requester_person=person_of(f"key:{a1.id}"))
    with pytest.raises(ValueError, match="can't approve"):
        gate.approve(asked.id, f"key:{a2.id}", org_id="org_a", approver_person=person_of(f"key:{a2.id}"))
    money = gate.submit("org_a", ConsentCategory.FINANCIAL, "t", {}, requester="key:k-other")
    gate.approve(money.id, f"key:{e1.id}", org_id="org_a", approver_person=person_of(f"key:{e1.id}"))
    assert gate.approve(money.id, f"key:{e2.id}", org_id="org_a",
                        approver_person=person_of(f"key:{e2.id}")).status == ConsentStatus.PENDING


def test_keys_that_name_no_person_stay_separate_people():
    from kintsugi.security.api_keys import get_key_store, person_of
    k1, _ = get_key_store().create("org_a", "admin", "one")
    k2, _ = get_key_store().create("org_a", "admin", "two")
    assert person_of(f"key:{k1.id}") != person_of(f"key:{k2.id}")
    assert person_of(f"key:{k1.id}") == f"key:{k1.id}"


def test_the_approve_route_counts_people(make_headers):
    from fastapi.testclient import TestClient
    from kintsugi.main import app
    from kintsugi.security.api_keys import get_key_store
    store = get_key_store()
    asker, _ = store.create("org_a", "member", "asker", person="dana")
    admin_key = make_headers("admin", "org_a", "dana-admin")
    rec = next(r for r in store.list() if r.label == "dana-admin")
    store.set_person(rec.id, "dana")
    item = get_consensus_gate().submit("org_a", ConsentCategory.GENERAL, "t", {"x": 1},
                                       requester=f"key:{asker.id}", requester_person="person:dana")
    r = TestClient(app).post(f"/api/v1/consensus/{item.id}/approve", json={}, headers=admin_key)
    assert r.status_code == 409 and "can't approve" in r.json()["detail"]


# ---- mass notices, per requester per day -----------------------------------------------------------------------------

def _notify(ids, user="key:k-asker"):
    from kintsugi.skills.core_ops.volunteer_coordinator import VolunteerCoordinatorChip
    return VolunteerCoordinatorChip, SkillRequest(intent="volunteer_notify", raw_input="n",
                                                  entities={"volunteer_ids": ids, "message": "Shift moved"}), ctx(user=user)


@pytest.mark.asyncio
async def test_batches_of_ten_add_up_to_a_mass_notice():
    from kintsugi.skills.base import org_scope
    cls, req, c = _notify(["vol_001"] * 10)
    chip = cls()
    first = await chip.handle(req, c)
    assert not first.metadata.get("held") and first.data["sent"] == 10   # recorded by the chip itself
    _, one_more, _ = _notify(["vol_001"])
    assert (await chip.handle(one_more, c)).metadata.get("held")
    _, other, other_ctx = _notify(["vol_001"], user="key:k-someone-else")
    assert not (await chip.handle(other, other_ctx)).metadata.get("held")
    with org_scope("org_a"):                                    # a day later, the count starts again
        chip._notified["key:k-asker"] = [((datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(), 10)]
    assert not (await chip.handle(one_more, c)).metadata.get("held")


@pytest.mark.asyncio
async def test_one_persons_two_keys_share_one_mass_limit():
    from kintsugi.security.api_keys import get_key_store
    store = get_key_store()
    k1, _ = store.create("org_a", "member", "fran's laptop", person="fran")
    k2, _ = store.create("org_a", "member", "fran's phone", person="fran")
    cls, req, c = _notify(["vol_001"] * 6, user=f"key:{k1.id}")
    chip = cls()
    assert not (await chip.handle(req, c)).metadata.get("held")
    _, again, other_key = _notify(["vol_001"] * 6, user=f"key:{k2.id}")
    assert (await chip.handle(again, other_key)).metadata.get("held")      # 12 > 10, across both keys


@pytest.mark.asyncio
async def test_a_notice_to_all_reaches_every_volunteer_once_approved():
    cls, req, c = _notify("all")
    chip = cls()
    held = await chip.handle(req, c)
    get_consensus_gate().approve(held.data["consent_id"], "key:k-admin", org_id="org_a")
    result = await consumer.execute_approved(held.data["consent_id"], "org_a", Registry(chip))
    everyone = await chip._get_all_volunteers("org_a")
    assert result["data"]["total"] == len(everyone) and result["data"]["failed"] == 0


# ---- a hold says when approval can't carry anything out --------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_hold_for_an_action_with_no_step_says_nothing_will_happen():
    from kintsugi.skills.programs_people.board_liaison import BoardLiaisonChip
    held = await BoardLiaisonChip().handle(SkillRequest(intent="resolution_track", raw_input="r",
                                                        entities={"action": "create"}), ctx())
    assert held.metadata.get("held") and held.data["no_step"] is True
    assert "nothing will happen automatically" in held.content


# ---- members don't see private payloads ------------------------------------------------------------------------------

def test_only_admins_and_the_asker_see_the_payload(make_headers):
    from fastapi.testclient import TestClient
    from kintsugi.main import app
    from kintsugi.security.api_keys import get_key_store
    asker_h = make_headers("member", "org_a", "asker")
    other_h = make_headers("member", "org_a", "bystander")
    admin_h = make_headers("admin", "org_a", "admin")
    asker = next(r for r in get_key_store().list() if r.label == "asker")
    item = get_consensus_gate().submit("org_a", ConsentCategory.PII, "share", {
        "chip": "mutual_aid_coordinator", "action": "share_requester_info", "intent": "match_request",
        "entities": {"phone": "SECRET 555-0100"}}, requester=f"key:{asker.id}")
    client = TestClient(app)
    seen = {who: client.get(f"/api/v1/consensus/{item.id}", headers=h).json()
            for who, h in (("asker", asker_h), ("bystander", other_h), ("admin", admin_h))}
    assert "SECRET" in json.dumps(seen["asker"]) and "SECRET" in json.dumps(seen["admin"])
    assert "SECRET" not in json.dumps(seen["bystander"]) and seen["bystander"]["action_payload"]["action"] == \
        "share_requester_info"
    pending = client.get("/api/v1/consensus/pending", headers=other_h).json()["pending"]
    assert pending and "SECRET" not in json.dumps(pending)


# ---- a failed run gets one retry -------------------------------------------------------------------------------------

class Flaky(BaseSkillChip):
    name = "test_followons_flaky"
    description = "raises until told otherwise"
    domain = SkillDomain.OPERATIONS
    consensus_actions = ["disburse_funds"]
    consensus_intents = {"pay_out": "disburse_funds"}
    consensus_categories = {"disburse_funds": "GENERAL"}
    fail_times = 1

    async def handle(self, request, context):
        RUNS.append(1)
        if len(RUNS) <= type(self).fail_times:
            raise RuntimeError("upstream down")
        return SkillResponse(content="paid")


async def _held_flaky(chip):
    r = await chip.handle(SkillRequest(intent="pay_out", raw_input="p", entities={"amount": 1}), ctx())
    get_consensus_gate().approve(r.data["consent_id"], "key:k-admin", org_id="org_a")
    return r.data["consent_id"]


@pytest.mark.asyncio
async def test_a_run_that_raises_is_failed_and_can_be_retried_once():
    chip = Flaky()
    item_id = await _held_flaky(chip)
    first = await consumer.execute_approved(item_id, "org_a", Registry(chip))
    item = get_consensus_gate().get_item(item_id, org_id="org_a")
    assert first["success"] is False and item.status == ConsentStatus.FAILED and "retried once" in first["content"]
    second = await consumer.execute_approved(item_id, "org_a", Registry(chip))
    assert second["success"] and get_consensus_gate().get_item(item_id, org_id="org_a").status == ConsentStatus.EXECUTED
    assert len(RUNS) == 2


@pytest.mark.asyncio
async def test_a_second_failure_is_final():
    chip = Flaky()
    type(chip).fail_times = 5
    try:
        item_id = await _held_flaky(chip)
        await consumer.execute_approved(item_id, "org_a", Registry(chip))
        await consumer.execute_approved(item_id, "org_a", Registry(chip))
        with pytest.raises(ValueError, match="one retry is used"):
            await consumer.execute_approved(item_id, "org_a", Registry(chip))
        assert len(RUNS) == 2
    finally:
        type(chip).fail_times = 1


@pytest.mark.asyncio
async def test_no_token_outlives_its_run():
    chip = Flaky()
    item_id = await _held_flaky(chip)
    await consumer.execute_approved(item_id, "org_a", Registry(chip))       # raises inside
    assert consumer._live == set()
    await consumer.execute_approved(item_id, "org_a", Registry(chip))       # succeeds
    assert consumer._live == set()


# ---- a damaged row doesn't take the gate down ------------------------------------------------------------------------

def test_one_damaged_row_is_kept_aside_and_the_gate_still_works(tmp_path, caplog):
    path = tmp_path / "consent.json"
    gate = ConsensusGate(path=path)
    good = gate.submit("org_a", ConsentCategory.GENERAL, "t", {"x": 1}, requester="key:k1")
    rows = json.loads(path.read_text())
    rows.append({"id": "broken", "org_id": "org_b", "status": "NOT A STATUS"})
    path.write_text(json.dumps(rows))
    with caplog.at_level(logging.WARNING):
        assert [i.id for i in gate.list_pending("org_a")] == [good.id]
        gate.approve(good.id, "key:k2", org_id="org_a")                     # a write keeps the damaged row
    assert any(r["id"] == "broken" for r in json.loads(path.read_text()))
    assert any("unreadable row" in r.getMessage() for r in caplog.records)


def test_a_file_that_isnt_json_refuses(tmp_path):
    path = tmp_path / "consent.json"
    path.write_text("[{not json")
    with pytest.raises(ValueError):
        ConsensusGate(path=path).list_pending("org_a")


def test_writes_reach_the_disk(tmp_path, monkeypatch):
    import os
    synced = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(fd), real(fd)))
    ConsensusGate(path=tmp_path / "consent.json").submit("org_a", ConsentCategory.GENERAL, "t", {}, requester="k")
    assert len(synced) >= 2                                                  # the file, then the folder


# ---- the dashboard acts as the admin's key ---------------------------------------------------------------------------

def test_the_dashboard_chat_acts_as_the_admins_key_in_their_org(make_headers):
    from fastapi.testclient import TestClient
    from kintsugi.agents.sessions import get_session_manager
    from kintsugi.main import app
    from kintsugi.security.api_keys import get_key_store
    headers = make_headers("admin", "org_dash", "dash-admin")
    rec = next(r for r in get_key_store().list() if r.label == "dash-admin")
    TestClient(app).post("/dashboard/actions/chat", data={"message": "hello", "personality": "default"},
                         headers=headers)
    mine = [s for s in get_session_manager().list() if s.user_id == f"key:{rec.id}"]
    assert mine and all(s.org_id == "org_dash" for s in mine)


# ---- the personality field nothing reads -----------------------------------------------------------------------------

def test_shipped_personalities_declare_no_consent_and_a_declaration_is_warned_about(caplog):
    from pathlib import Path
    from kintsugi.agents import personality as pmod
    shipped = Path(pmod.__file__).resolve().parents[1] / "config" / "personalities"
    assert not any("consensus_actions" in p.read_text() for p in shipped.iterdir() if p.is_file())
    with caplog.at_level(logging.WARNING):
        assert pmod._unread_consensus_actions("old", {"consensus_actions": ["external_send"]}) == ["external_send"]
    assert any("nothing reads" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_the_run_discards_its_token_even_for_a_chip_that_never_redeems_it():
    # A plain object in the registry has no BaseSkillChip wrapper, so nothing redeems (and spends) the token: only
    # execute_approved's finally can (Vera: nothing caught that finally going missing).
    class Bare:
        name = "test_followons_bare"
        capabilities = []

        async def handle(self, request, context):
            return SkillResponse(content="done")
    item = get_consensus_gate().submit("org_a", ConsentCategory.GENERAL, "t", {
        "chip": "test_followons_bare", "action": "x", "intent": "x", "entities": {}, "parameters": {},
        "raw_input": "x", "user_id": "key:k1", "session_id": None, "platform": "api"}, requester="key:k1")
    get_consensus_gate().approve(item.id, "key:k-admin", org_id="org_a")
    await consumer.execute_approved(item.id, "org_a", Registry(Bare()))
    assert consumer._live == set()



@pytest.mark.asyncio
async def test_a_hold_records_the_asker_as_a_person_so_their_other_key_cant_approve():
    from kintsugi.security.api_keys import get_key_store, person_of
    store = get_key_store()
    laptop, _ = store.create("org_a", "admin", "dana laptop", person="dana")
    phone, _ = store.create("org_a", "admin", "dana phone", person="dana")
    held = await Flaky().handle(SkillRequest(intent="pay_out", raw_input="p", entities={"amount": 1}),
                                ctx(user=f"key:{laptop.id}"))
    item = get_consensus_gate().get_item(held.data["consent_id"], org_id="org_a")
    assert item.requester_person == "person:dana"
    with pytest.raises(ValueError, match="can't approve"):
        get_consensus_gate().approve(item.id, f"key:{phone.id}", org_id="org_a",
                                     approver_person=person_of(f"key:{phone.id}"))


def test_a_bystander_doesnt_see_what_an_executed_action_returned(make_headers):
    from fastapi.testclient import TestClient
    from kintsugi.main import app
    other_h = make_headers("member", "org_a", "bystander-2")
    gate = get_consensus_gate()
    item = gate.submit("org_a", ConsentCategory.GENERAL, "t", {"chip": "c", "action": "a", "intent": "i"},
                       requester="key:k-someone")
    gate.approve(item.id, "key:k-admin", org_id="org_a")
    gate.claim(item.id, org_id="org_a")
    gate.record_result(item.id, {"content": "SECRET contact: 555-0100"}, org_id="org_a")
    seen = TestClient(app).get(f"/api/v1/consensus/{item.id}", headers=other_h).json()
    assert seen["result"] is None and "SECRET" not in json.dumps(seen)
