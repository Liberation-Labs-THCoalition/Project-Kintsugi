"""Records inside chips are one organisation's alone (Vera's re-check of 8e4fae5, 2026-10-18: HIGH, reproduced).

Before: one chip instance per process held its records in class-level dicts, nothing was filtered by org, and per-user
lookups trusted the user_id the caller sent. org_b, claiming user_id "alice", read org_a/alice's need (description,
location, status); org_b cancelled it by id; need ids leaked across orgs through the offer-to-needs listing; crisis
incidents were visible across orgs. Each test below fails on that code.
"""
from __future__ import annotations

import inspect

import pytest

from kintsugi.skills import SkillContext, SkillRequest
from kintsugi.skills.base import BaseSkillChip, ChipStorageError, org_scope
from kintsugi.skills.community_aid import CrisisResponseChip, MutualAidCoordinatorChip


def ctx(org, user, role=None):
    return SkillContext(org_id=org, user_id=user, metadata={"role": role} if role else {})


async def post_need(chip, org="org_a", user="alice"):
    r = await chip.handle(SkillRequest(intent="need_post", raw_input="I need groceries",
                                       entities={"category": "food", "description": "Groceries for a family of 4",
                                                 "location": "Arcata"}), ctx(org, user))
    assert r.success, r.content
    return r.data["need_id"]


async def status(chip, need_id, org, user, new_status=None, role=None):
    entities = {"need_id": need_id, **({"new_status": new_status} if new_status else {})}
    return await chip.handle(SkillRequest(intent="aid_status", raw_input="status", entities=entities),
                             ctx(org, user, role))


@pytest.mark.asyncio
async def test_another_org_claiming_the_same_user_id_reads_nothing():
    chip = MutualAidCoordinatorChip()
    need_id = await post_need(chip)
    r = await status(chip, need_id, org="org_b", user="alice")
    assert r.success is False and "not found" in r.content
    assert "Groceries" not in repr(r.data) and "Arcata" not in repr(r.data)


@pytest.mark.asyncio
async def test_another_org_cannot_cancel_by_id():
    chip = MutualAidCoordinatorChip()
    need_id = await post_need(chip)
    r = await status(chip, need_id, org="org_b", user="mallory", new_status="cancelled")
    assert r.success is False
    mine = await status(chip, need_id, org="org_a", user="alice")
    assert mine.success and mine.data["status"] != "cancelled"


@pytest.mark.asyncio
async def test_within_an_org_only_the_author_or_an_admin_changes_a_need():
    chip = MutualAidCoordinatorChip()
    need_id = await post_need(chip)
    assert (await status(chip, need_id, "org_a", "mallory", new_status="cancelled")).success is False
    assert (await status(chip, need_id, "org_a", "alice", new_status="cancelled")).success is True
    other = await post_need(chip)
    assert (await status(chip, other, "org_a", "coordinator", new_status="cancelled", role="admin")).success is True


@pytest.mark.asyncio
async def test_need_ids_dont_leak_through_the_offer_listing():
    chip = MutualAidCoordinatorChip()
    need_id = await post_need(chip)
    r = await chip.handle(SkillRequest(intent="offer_post", raw_input="I can help",
                                       entities={"categories": ["food"], "description": "Can bring groceries",
                                                 "location": "Arcata"}), ctx("org_b", "bob"))
    assert need_id not in repr(r.data) and need_id[:8] not in r.content


@pytest.mark.asyncio
async def test_crisis_incidents_are_one_orgs_alone():
    chip = CrisisResponseChip()
    a = await chip.handle(SkillRequest(intent="crisis_alert", raw_input="Flood on 5th street",
                                       entities={"crisis_type": "natural_disaster", "location": "5th street",
                                                 "description": "Flooding"}), ctx("org_a", "alice"))
    with org_scope("org_a"):
        assert len(chip._incidents) == 1
    with org_scope("org_b"):
        assert len(chip._incidents) == 0
    assert a.success


def test_chip_records_are_unreachable_with_no_org_in_scope():
    chip = MutualAidCoordinatorChip()
    with pytest.raises(ChipStorageError):
        chip._needs
    with pytest.raises(ChipStorageError):
        with org_scope(""):
            pass


def test_every_chip_runs_its_handle_inside_its_org():
    # Structural guard: a chip added later gets the wrapper too, so its records are scoped without anyone remembering.
    import kintsugi.skills.community_aid, kintsugi.skills.core_ops, kintsugi.skills.programs_people  # noqa: F401
    seen = 0
    stack = list(BaseSkillChip.__subclasses__())
    while stack:
        cls = stack.pop()
        stack.extend(cls.__subclasses__())
        if "handle" in cls.__dict__ and not inspect.isabstract(cls):
            assert getattr(cls.__dict__["handle"], "_org_scoped", False), cls.__name__
            seen += 1
    assert seen >= 10


@pytest.mark.asyncio
async def test_the_api_acts_as_the_key_never_the_body_user(monkeypatch):
    # skills.py said user_id "grants nothing", then passed it into the chip's context, where chips match records to it.
    from kintsugi.api.auth import Principal
    from kintsugi.api.routes import skills as route
    from kintsugi.skills.base import SkillResponse
    seen = {}

    class Spy:
        name = "spy"

        async def handle(self, request, context):
            seen["user"], seen["meta"] = context.user_id, dict(context.metadata)
            return SkillResponse(content="ok")

    class Registry:
        def get(self, name):
            return Spy()

    monkeypatch.setattr(route, "get_registry", lambda: Registry())
    monkeypatch.setattr(route, "refuse_shell_capable", lambda *a, **k: None)
    body = route.ExecuteSkillRequest(raw_input="hi", user_id="alice")
    await route.execute_skill("spy", body, principal=Principal(org_id="org_b", key_id="k-mallory", role="member"))
    assert seen["user"] == "key:k-mallory"
    assert seen["meta"]["role"] == "member" and seen["meta"]["claimed_user"] == "alice"


@pytest.mark.asyncio
async def test_within_an_org_only_the_author_or_an_admin_changes_an_offer():
    chip = MutualAidCoordinatorChip()
    r = await chip.handle(SkillRequest(intent="offer_post", raw_input="I can help",
                                       entities={"categories": ["food"], "description": "Groceries"}), ctx("org_a", "bob"))
    offer_id = r.data["offer_id"]

    async def change(user, role=None):
        return await chip.handle(SkillRequest(intent="aid_status", raw_input="s",
                                              entities={"offer_id": offer_id, "new_status": "cancelled"}),
                                 ctx("org_a", user, role))
    assert (await change("mallory")).success is False
    assert (await change("bob")).success is True
