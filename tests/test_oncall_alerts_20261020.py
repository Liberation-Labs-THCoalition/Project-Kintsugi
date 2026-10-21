"""On-call alerts (Thomas, 2026-10-19: an on-call group gets a raid or critical alert at once, and only the wide broadcast
waits for an admin). Vera's five tests (2026-10-19 18:37), each able to fail: no on-call named holds; an unreachable
on-call holds; no acknowledgement escalates on time; an acknowledgement stops the escalation; and the broadcast never
sends without an admin's approval in any branch. Then what the alert may carry, restarts, and the routes.
"""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path

import pytest

from kintsugi.config.settings import settings
from kintsugi.governance import oncall
from kintsugi.governance.consensus import ConsentStatus, get_consensus_gate
from kintsugi.security.api_keys import get_key_store
from kintsugi.skills.base import SkillContext, SkillRequest
from kintsugi.skills.community_aid.crisis_response import CrisisResponseChip
from kintsugi.skills.community_aid.rapid_response import RapidResponseChip

CONTACTS = {p: [{"channel": "signal", "address": f"+{p}"}] for p in ("alice", "bob", "carol", "dave", "zoe")}
DESCRIPTION = "at 123 Main St, the Lopez family"     # free text: must never reach a message


class FakeMessenger:
    def __init__(self):
        self.sent, self.fail = [], set()

    async def send(self, channel, address, text):
        self.sent.append((channel, address, text))
        return address not in self.fail

    def to(self, person):
        return [t for _, a, t in self.sent if a == f"+{person}"]


class Registry:
    def __init__(self, *chips):
        self.chips = {c.name: c for c in chips}

    def get(self, name):
        return self.chips.get(name)


@pytest.fixture
def messenger():
    m = FakeMessenger()
    oncall.set_messenger(m)
    yield m
    oncall.set_messenger(None)


@pytest.fixture
def people():
    """alice and bob are members (on call), carol and dave admins of org_a; zoe is an admin of org_b."""
    store = get_key_store()
    keys = {}
    for person, role, org in (("alice", "member", "org_a"), ("bob", "member", "org_a"),
                              ("carol", "admin", "org_a"), ("dave", "admin", "org_a"), ("zoe", "admin", "org_b")):
        rec, plaintext = store.create(org, role, person, person=person)
        keys[person] = (rec, {"Authorization": f"Bearer {plaintext}"})
    reporter, _ = store.create("org_a", "member", "reporter", person="rita")
    keys["rita"] = (reporter, None)
    return keys


def roster(on_call, window=300, org="org_a", contacts=CONTACTS):
    data = json.loads(Path(settings.ONCALL_FILE).read_text()) if Path(settings.ONCALL_FILE).exists() else {}
    data[org] = {"on_call": on_call, "contacts": contacts, "ack_window_seconds": window}
    Path(settings.ONCALL_FILE).write_text(json.dumps(data))


@pytest.fixture
def broadcasts(monkeypatch):
    """Counts the wide broadcast: the chip's send step, which only the approved replay may reach."""
    calls = []
    real = RapidResponseChip.send_raid_alert

    async def counted(self, *a, **k):
        calls.append(k)
        return await real(self, *a, **k)

    monkeypatch.setattr(RapidResponseChip, "send_raid_alert", counted)
    return calls


def raid(people, chip=None):
    chip = chip or RapidResponseChip()
    request = SkillRequest(intent="raid_alert", entities={"type": "ice_raid", "urgency": "critical",
                                                          "area": "Eastside, near the market", "description": DESCRIPTION})
    context = SkillContext(org_id="org_a", user_id=f"key:{people['rita'][0].id}")
    return asyncio.run(chip.handle(request, context))


def alert_of(resp):
    """The on-call part of a held response. A response without one isn't the hold (the chip ran instead)."""
    assert "oncall" in (resp.data or {}), f"not a held on-call response: {resp.content[:200]}"
    return resp.data["oncall"]


def record(resp):
    rec = oncall.get_alert("org_a", alert_of(resp).get("id", ""))
    assert rec is not None, "the alert record wasn't kept"
    return rec


def at(rec, seconds):
    return oncall._when(rec.deadline) + timedelta(seconds=seconds)


# ---- Vera's five ------------------------------------------------------------------------------------------------------

def test_no_on_call_named_holds_and_says_so(people, messenger, broadcasts):
    roster([])
    resp = raid(people)
    assert broadcasts == []
    assert resp.requires_consensus and resp.consensus_action == "activate_rapid_response"
    assert alert_of(resp)["state"] == "held" and alert_of(resp)["reached"] == []
    assert messenger.sent == []
    assert "No on-call people are named" in resp.content and "nobody has been alerted" in resp.content
    assert get_consensus_gate().get_item(resp.data["consent_id"], "org_a").status == ConsentStatus.PENDING
    assert broadcasts == []


def test_no_roster_at_all_holds(people, messenger, broadcasts):
    assert not Path(settings.ONCALL_FILE).exists()
    resp = raid(people)
    assert broadcasts == [] and alert_of(resp)["state"] == "held" and messenger.sent == []


def test_an_unreachable_on_call_holds_and_a_removed_person_isnt_contacted(people, messenger, broadcasts):
    """Named isn't reachable: alice was removed (her key revoked), bob's send fails, erin has a key but no contact,
    and fred was never in the deployment."""
    get_key_store().create("org_a", "member", "erin", person="erin")
    roster(["alice", "bob", "erin", "fred"])
    get_key_store().revoke(people["alice"][0].id)
    messenger.fail.add("+bob")
    resp = raid(people)
    rec = record(resp)
    assert rec.state == "held" and rec.reached == []
    assert rec.not_reached == {"alice": oncall.NOT_IN_DEPLOYMENT, "bob": oncall.NOT_DELIVERED,
                               "erin": oncall.NO_CONTACT, "fred": oncall.NOT_IN_DEPLOYMENT}
    assert messenger.to("alice") == []                       # removed: never even tried
    assert len(messenger.to("bob")) == 1                     # tried, not delivered, not counted
    assert "None of the 4 on-call people could be reached" in resp.content
    assert "nobody has been alerted" in resp.content and "bob: no message could be delivered" in resp.content
    assert broadcasts == []


def test_no_acknowledgement_escalates_on_time_to_every_admin_at_once(people, messenger, broadcasts):
    roster(["alice"], window=300)
    resp = raid(people)
    rec = record(resp)
    assert rec.state == "sent" and rec.reached == ["alice"]
    assert oncall._when(rec.deadline) - oncall._when(rec.created_at) == timedelta(seconds=300)
    assert asyncio.run(oncall.tick(now=at(rec, -1))) == []
    assert messenger.to("carol") == [] and messenger.to("dave") == []
    escalated = asyncio.run(oncall.tick(now=at(rec, 0)))
    assert [r.id for r in escalated] == [rec.id]
    assert len(messenger.to("carol")) == 1 and len(messenger.to("dave")) == 1      # both, in the one tick
    assert messenger.to("zoe") == []                                              # another org's admin: never
    rec = record(resp)
    assert rec.state == "escalated" and rec.admins_reached == ["carol", "dave"]
    assert get_consensus_gate().get_item(rec.consent_id, "org_a").status == ConsentStatus.ESCALATED
    assert "every admin was asked (carol, dave reached)" in oncall.status_line(rec)
    assert asyncio.run(oncall.tick(now=at(rec, 600))) == []                      # once, not every tick
    assert len(messenger.to("carol")) == 1
    assert broadcasts == []


def test_an_acknowledgement_stops_the_escalation(people, messenger, broadcasts):
    roster(["alice", "bob"])
    rec = record(raid(people))
    with pytest.raises(PermissionError):
        oncall.acknowledge("org_a", rec.id, "carol")                              # carol wasn't sent it
    rec = oncall.acknowledge("org_a", rec.id, "alice", now=at(rec, -200))
    assert rec.state == "acknowledged" and rec.acknowledged_by == "alice"
    assert asyncio.run(oncall.tick(now=at(rec, 600))) == []
    assert messenger.to("carol") == [] and messenger.to("dave") == []
    assert record_state(rec) == "acknowledged"
    assert "Acknowledged by alice" in oncall.status_line(oncall.get_alert("org_a", rec.id))
    assert broadcasts == []


def record_state(rec):
    return oncall.get_alert("org_a", rec.id).state


def test_the_broadcast_never_sends_without_an_admins_approval_in_any_branch(people, messenger, broadcasts,
                                                                             monkeypatch):
    from fastapi.testclient import TestClient
    from kintsugi.main import app
    from kintsugi.skills import registry as registry_mod

    chip = RapidResponseChip()
    monkeypatch.setattr(registry_mod, "get_registry", lambda: Registry(chip))
    client = TestClient(app)
    items = {}
    roster([])
    items["held"] = raid(people, chip)
    roster(["alice"])
    items["acknowledged"] = raid(people, chip)
    oncall.acknowledge("org_a", record(items["acknowledged"]).id, "alice")
    items["escalated"] = raid(people, chip)
    asyncio.run(oncall.tick(now=at(record(items["escalated"]), 1)))
    items["sent"] = raid(people, chip)                        # after the tick, so it is still waiting
    assert {k: (record(v).state) for k, v in items.items()} == {k: k for k in items}
    assert broadcasts == []                                   # four branches, no broadcast
    for branch, resp in items.items():
        item = get_consensus_gate().get_item(resp.data["consent_id"], "org_a")
        assert item.status in (ConsentStatus.PENDING, ConsentStatus.ESCALATED), branch
        member = client.post(f"/api/v1/consensus/{item.id}/approve", json={}, headers=people["alice"][1])
        assert member.status_code == 403, branch               # on call isn't admin: an acknowledgement approves nothing
    assert broadcasts == []
    for n, (branch, resp) in enumerate(items.items(), start=1):
        ok = client.post(f"/api/v1/consensus/{resp.data['consent_id']}/approve", json={}, headers=people["carol"][1])
        assert ok.status_code == 200, branch
        assert len(broadcasts) == n, branch                    # an admin's approval, and only that, runs it once


# ---- what goes out, and to whom --------------------------------------------------------------------------------------

def test_the_on_call_message_carries_kind_urgency_and_area_never_the_description(people, messenger):
    roster(["alice"])
    raid(people)
    (text,) = messenger.to("alice")
    assert "ice raid" in text and "critical" in text and "Eastside, near the market" in text
    assert "123 Main" not in text and "Lopez" not in text
    assert oncall.general_area("x" * 200).endswith("…") and len(oncall.general_area("x" * 200)) == oncall.AREA_CHARS
    assert oncall.general_area("  ") == "not given"


def test_a_partial_reach_names_who_has_it_and_who_doesnt(people, messenger):
    roster(["alice", "bob"])
    messenger.fail.add("+bob")
    resp = raid(people)
    assert "Sent to on-call: alice." in resp.content and "Not reached: bob: no message could be delivered" in resp.content
    assert "every admin is asked to approve the broadcast" in resp.content


def test_an_unreadable_roster_holds_and_says_so(people, messenger, broadcasts):
    Path(settings.ONCALL_FILE).write_text("{not json")
    resp = raid(people)
    assert resp.requires_consensus and alert_of(resp)["state"] == "held"
    assert "couldn't be read" in resp.content and "nobody has been alerted" in resp.content
    assert messenger.sent == [] and broadcasts == []


def test_a_window_that_isnt_a_positive_integer_is_refused(people, messenger):
    for bad in (0, -5, "300", True, 1.5):
        roster(["alice"], window=bad)
        resp = raid(people)
        assert alert_of(resp)["state"] == "held" and "couldn't be read" in resp.content, bad
    assert messenger.sent == []


def test_a_critical_crisis_alert_reaches_on_call_and_a_lesser_one_doesnt(people, messenger):
    roster(["alice"])
    chip = CrisisResponseChip()
    context = SkillContext(org_id="org_a", user_id=f"key:{people['rita'][0].id}")
    lesser = asyncio.run(chip.handle(SkillRequest(intent="crisis_alert", entities={"severity": "high"}), context))
    assert "oncall" not in (lesser.data or {}) and messenger.sent == []
    critical = asyncio.run(chip.handle(SkillRequest(intent="crisis_alert", entities={
        "severity": "critical", "crisis_type": "natural_disaster", "location": "river flats",
        "description": DESCRIPTION}), context))
    assert critical.requires_consensus and alert_of(critical)["state"] == "sent"
    (text,) = messenger.to("alice")
    assert "natural disaster" in text and "critical" in text and "river flats" in text and "Lopez" not in text


# ---- restarts ----------------------------------------------------------------------------------------------------------

def test_an_escalation_survives_a_restart(people, messenger, monkeypatch):
    roster(["alice"])
    rec = record(raid(people))
    monkeypatch.setattr(oncall, "_store", None)              # a new process: only the file remains
    assert [r.id for r in asyncio.run(oncall.tick(now=at(rec, 5)))] == [rec.id]
    assert len(messenger.to("carol")) == 1 and len(messenger.to("dave")) == 1


def test_a_crash_between_claiming_and_sending_is_retried(people, messenger):
    roster(["alice"])
    rec = record(raid(people))
    with oncall.get_alert_store().txn() as records:          # claimed, then the process died before any send
        records[rec.id].state, records[rec.id].escalated_at = "escalated", rec.deadline
    assert [r.id for r in asyncio.run(oncall.tick(now=at(rec, 5)))] == [rec.id]
    assert oncall.get_alert("org_a", rec.id).admins_reached == ["carol", "dave"]
    assert asyncio.run(oncall.tick(now=at(rec, 60))) == []


# ---- the routes ----------------------------------------------------------------------------------------------------------

def test_the_ack_route_lets_only_a_reached_on_call_person_acknowledge(people, messenger):
    from fastapi.testclient import TestClient
    from kintsugi.main import app

    roster(["alice"])
    rec = record(raid(people))
    client = TestClient(app)
    assert client.post(f"/api/v1/oncall/{rec.id}/ack", headers=people["bob"][1]).status_code == 404   # not his
    assert client.post(f"/api/v1/oncall/{rec.id}/ack", headers=people["carol"][1]).status_code == 403  # admin, not on call
    assert client.post(f"/api/v1/oncall/{rec.id}/ack", headers=people["zoe"][1]).status_code == 404    # other org
    ok = client.post(f"/api/v1/oncall/{rec.id}/ack", headers=people["alice"][1])
    assert ok.status_code == 200 and ok.json()["state"] == "acknowledged" and "Acknowledged by alice" in ok.json()["status"]
    seen = client.get(f"/api/v1/oncall/{rec.id}", headers=people["carol"][1])
    assert seen.status_code == 200 and seen.json()["acknowledged_by"] == "alice"
