"""A settled need or offer (fulfilled, cancelled, expired) changes only by an admin (Vera's LOW, 2026-10-18), and an
unknown status is refused in words. Each test fails on the code before this change."""
from __future__ import annotations

import pytest

from kintsugi.skills import SkillContext, SkillRequest
from kintsugi.skills.community_aid import MutualAidCoordinatorChip


def ctx(user, role=None):
    return SkillContext(org_id="org_a", user_id=user, metadata={"role": role} if role else {})


async def post(chip, kind):
    if kind == "need":
        r = await chip.handle(SkillRequest(intent="need_post", raw_input="n", entities={
            "category": "food", "description": "Groceries", "location": "Arcata"}), ctx("alice"))
        return "need_id", r.data["need_id"]
    r = await chip.handle(SkillRequest(intent="offer_post", raw_input="o", entities={
        "categories": ["food"], "description": "Can bring groceries"}), ctx("alice"))
    return "offer_id", r.data["offer_id"]


async def change(chip, key, rid, new, user="alice", role=None):
    return await chip.handle(SkillRequest(intent="aid_status", raw_input="s", entities={key: rid, "new_status": new}),
                             ctx(user, role))


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["need", "offer"])
async def test_the_author_cant_turn_what_an_admin_cancelled_into_fulfilled(kind):
    chip = MutualAidCoordinatorChip()
    key, rid = await post(chip, kind)
    assert (await change(chip, key, rid, "cancelled", user="coordinator", role="admin")).success
    refused = await change(chip, key, rid, "fulfilled")
    assert refused.success is False and "already cancelled" in refused.content
    assert (await change(chip, key, rid, "pending", user="coordinator", role="admin")).success   # an admin may reopen


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["need", "offer"])
async def test_the_author_moves_freely_until_it_settles(kind):
    chip = MutualAidCoordinatorChip()
    key, rid = await post(chip, kind)
    for step in ("matched", "in_progress", "fulfilled"):
        assert (await change(chip, key, rid, step)).success, step
    assert (await change(chip, key, rid, "fulfilled")).success                    # the same status again is no change
    assert (await change(chip, key, rid, "pending")).success is False


@pytest.mark.asyncio
async def test_an_unknown_status_is_refused_in_words():
    chip = MutualAidCoordinatorChip()
    key, rid = await post(chip, "need")
    r = await change(chip, key, rid, "teleported")
    assert r.success is False and "Unknown status" in r.content and "pending" in r.content
