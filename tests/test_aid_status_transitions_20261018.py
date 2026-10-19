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
    assert refused.success is False and "admin cancelled this" in refused.content
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


# ---- an author reopens what they cancelled themselves; an admin's cancellation stays the admin's (Vera, 10-18) ------

@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["need", "offer"])
async def test_the_author_reopens_their_own_cancellation(kind):
    chip = MutualAidCoordinatorChip()
    key, rid = await post(chip, kind)
    assert (await change(chip, key, rid, "cancelled")).success
    assert (await change(chip, key, rid, "pending")).success                   # their own change of mind
    assert (await change(chip, key, rid, "cancelled")).success


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["need", "offer"])
async def test_an_admins_cancellation_is_reopened_only_by_an_admin(kind):
    chip = MutualAidCoordinatorChip()
    key, rid = await post(chip, kind)
    assert (await change(chip, key, rid, "cancelled", user="coordinator", role="admin")).success
    refused = await change(chip, key, rid, "pending")
    assert refused.success is False and "admin cancelled this" in refused.content
    assert (await change(chip, key, rid, "pending", user="coordinator", role="admin")).success


@pytest.mark.asyncio
async def test_an_author_cancellation_reopened_then_cancelled_by_an_admin_is_the_admins():
    chip = MutualAidCoordinatorChip()
    key, rid = await post(chip, "need")
    assert (await change(chip, key, rid, "cancelled")).success
    assert (await change(chip, key, rid, "pending")).success
    assert (await change(chip, key, rid, "cancelled", user="coordinator", role="admin")).success
    assert (await change(chip, key, rid, "pending")).success is False


@pytest.mark.asyncio
async def test_fulfilled_stays_admin_only_even_for_the_author():
    chip = MutualAidCoordinatorChip()
    key, rid = await post(chip, "need")
    assert (await change(chip, key, rid, "fulfilled")).success
    assert (await change(chip, key, rid, "pending")).success is False


def test_the_rule_itself_refuses_a_non_author_and_a_settled_status_that_isnt_a_cancellation():
    # Each layer on its own: today the route's author check and the reset on reopen also cover these.
    from types import SimpleNamespace
    from kintsugi.skills.community_aid.mutual_aid_coordinator import AidStatus, _next_status
    member = ctx("bystander")
    cancelled_by_author = SimpleNamespace(status=AidStatus.CANCELLED, cancelled_by="author")
    assert _next_status(cancelled_by_author, "pending", member, is_author=False)[0] is None
    assert _next_status(cancelled_by_author, "pending", member, is_author=True)[0] == AidStatus.PENDING
    stale = SimpleNamespace(status=AidStatus.FULFILLED, cancelled_by="author")
    assert _next_status(stale, "pending", member, is_author=True)[0] is None


@pytest.mark.asyncio
async def test_reopening_clears_who_cancelled():
    from kintsugi.skills.base import org_scope
    chip = MutualAidCoordinatorChip()
    key, rid = await post(chip, "need")
    await change(chip, key, rid, "cancelled")
    await change(chip, key, rid, "pending")
    with org_scope("org_a"):
        assert chip._needs[rid].cancelled_by is None
