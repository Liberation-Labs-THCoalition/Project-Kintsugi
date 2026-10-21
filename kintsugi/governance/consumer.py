"""The consensus consumer: an action that needs consent is held before it happens, and runs once when approved.

Vera's re-check of 8e4fae5 (2026-10-18): nothing consumed consensus. `requires_consensus` was a membership test with no
caller, intent names never equalled action names (0 of 54), and several chips acted first and attached the flag after.
So the hold is not left to each chip. Each chip names which of its intents are which consensus action
(`consensus_intents`), and BaseSkillChip's handle() wrapper, which every path already goes through, holds a mapped
intent before the chip's own handle() runs: the request goes to the ConsensusGate, and nothing happens. When the
gate approves it, execute_approved() replays the stored request once, carrying a token only this module can mint; the
wrapper redeems the token (one use, this org, this action, this exact request) and lets the chip act.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from kintsugi.governance.consensus import MAX_RUN_ATTEMPTS, ConsentCategory, get_consensus_gate, payload_digest
from kintsugi.skills.base import (RESERVED_PARAMETERS, SkillContext, SkillRequest, SkillResponse, failure_reference,
                                  is_shell_capable)

logger = logging.getLogger(__name__)

CONSENT_TOKEN = "_consent_token"   # a context metadata key; routes build metadata themselves, so callers can't set it


@dataclass(frozen=True, eq=False)
class _Token:
    """Proof that this replay is the approved one. Compared by identity: only an object minted here can be in the live
    set, and JSON from a caller can never be one."""
    item_id: str
    org_id: str
    action: str
    digest: str


_live: set = set()
_lock = threading.Lock()


def is_token(value) -> bool:
    """Whether a value is a token this module minted (a caller's JSON can never be one)."""
    return isinstance(value, _Token)


def request_payload(chip_name: str, request, context, action: str) -> dict:
    """Everything needed to run the request later, and exactly what an approval is for."""
    return {
        "chip": chip_name,
        "action": action,
        "intent": request.intent,
        "entities": dict(request.entities or {}),
        "parameters": {k: v for k, v in (request.parameters or {}).items() if k not in RESERVED_PARAMETERS},
        "raw_input": request.raw_input,
        "user_id": context.user_id,
        "session_id": context.session_id,
        "platform": context.platform,
    }


def _category(chip, action: str) -> ConsentCategory:
    named = (getattr(chip, "consensus_categories", None) or {}).get(action)
    return ConsentCategory(named) if named else ConsentCategory.GENERAL


def _submit(chip, request, context, action: str):
    payload = request_payload(chip.name, request, context, action)
    from kintsugi.security.api_keys import person_of
    item = get_consensus_gate().submit(context.org_id, _category(chip, action), f"{chip.name}: {action}", payload,
                                       requester=context.user_id, requester_person=person_of(context.user_id))
    logger.info("held %s (%s) for consent as %s", chip.name, action, item.id)
    return item


def _held(chip, action: str, item, lead: str) -> SkillResponse:
    no_step = (getattr(chip, "consensus_no_step", None) or {}).get(action)
    note = (f" Approving it records the decision, but this skill has no step that carries it out yet ({no_step}), "
            f"so nothing will happen automatically." if no_step else "")
    now = chip.while_held(action) if hasattr(chip, "while_held") else ""
    note += f" {now}" if now else ""
    return SkillResponse(
        content=f"{lead}{note}",
        success=True,
        requires_consensus=True,
        consensus_action=action,
        data={"consent_id": item.id, "status": item.status.value, "action": action, "no_step": bool(no_step)},
        metadata={"held": True},
    )


def hold(chip, request, context, action: str) -> SkillResponse:
    """Submit the request to the gate instead of running it. Nothing the chip would do has happened."""
    item = _submit(chip, request, context, action)
    return _held(chip, action, item, f"This needs approval before it happens ({action}). Nothing has been done yet; "
                                     f"it's waiting for approval as request {item.id}.")


async def hold_and_alert(chip, request, context, action: str) -> SkillResponse:
    """hold(), and for an action the chip names in consensus_oncall (a raid report, a critical crisis alert), send the
    alert to whoever on call can be reached now (kintsugi/governance/oncall.py; Thomas, 2026-10-19). Only the wide
    broadcast waits for an admin; the on-call alert is not that broadcast and approves nothing."""
    kind = (getattr(chip, "consensus_oncall", None) or {}).get(action)
    if not kind:
        return hold(chip, request, context, action)
    from kintsugi.governance import oncall
    item = _submit(chip, request, context, action)
    message = chip.oncall_message(action, request) if hasattr(chip, "oncall_message") else f"{chip.name}: {action}"
    lead = (f"The wide broadcast needs an admin's approval before it goes out ({action}); it's waiting as request "
            f"{item.id}.")
    try:
        rec = await oncall.dispatch(context.org_id, item.id, kind, message, triggered_by=context.user_id)
    except Exception as exc:  # an unreadable roster holds, as before, and says so: it never passes for "sent"
        logger.warning("on-call dispatch for %s failed: %s", item.id, type(exc).__name__)
        response = _held(chip, action, item, f"{lead} The on-call list couldn't be read, so nobody has been alerted.")
        response.data["oncall"] = {"state": oncall.AlertState.HELD.value, "error": type(exc).__name__}
        return response
    response = _held(chip, action, item, f"{lead} {oncall.status_line(rec)}")
    response.data["oncall"] = oncall.public(rec)
    return response


def redeem(token, chip_name: str, request, context, action: str) -> bool:
    """Whether this call is the approved replay of exactly this request. A token is used up by the first look."""
    if not isinstance(token, _Token):
        return False
    with _lock:
        if token not in _live:
            return False
        _live.discard(token)
    return (token.org_id == context.org_id and token.action == action
            and token.digest == payload_digest(request_payload(chip_name, request, context, action)))


async def sweep_approved(registry=None) -> dict:
    """Run every approval a crash or restart left unrun, or expire it if it's older than the run window (Vera's
    review, 2026-10-18, item 1). Called when the server starts. Returns {"ran": [...], "expired": [...]}."""
    out = {"ran": [], "expired": []}
    for item in get_consensus_gate().approved_items():
        try:
            await execute_approved(item.id, item.org_id, registry)
            out["ran"].append(item.id)
        except ValueError as exc:
            logger.warning("approved %s not run: %s", item.id, exc)
            out["expired"].append(item.id)
    return out


async def execute_approved(item_id: str, org_id: str, registry=None) -> dict:
    """Run an approved item once. The gate marks it EXECUTED before it runs, so a second call, or a second worker,
    gets a refusal rather than a second run. Returns what the chip said, which is also kept on the item."""
    from kintsugi.skills.registry import get_registry

    gate = get_consensus_gate()
    item = gate.claim(item_id, org_id=org_id)
    p = item.action_payload
    chip = (registry or get_registry()).get(p["chip"])
    if chip is None:
        result = {"success": False, "content": f"the skill {p['chip']!r} is no longer available; nothing ran"}
    elif is_shell_capable(chip):
        # Consent doesn't lift the shell guard: re-enabling shell is its own decision, after audit.
        result = {"success": False, "content": "shell-capable skills stay disabled; nothing ran"}
    else:
        token = _Token(item.id, org_id, p["action"], item.payload_digest)
        request = SkillRequest(intent=p["intent"], entities=p["entities"], parameters=p["parameters"],
                               raw_input=p["raw_input"])
        context = SkillContext(org_id=org_id, user_id=p["user_id"], session_id=p["session_id"],
                               platform=p["platform"], metadata={CONSENT_TOKEN: token, "consent_id": item.id})
        with _lock:
            _live.add(token)
        raised = False
        try:
            response = await chip.handle(request, context)
        except Exception:
            raised = True
            ref = failure_reference(logger, f"approved item {item.id}")
            retry = " It can be retried once." if item.attempts < MAX_RUN_ATTEMPTS else ""
            response = SkillResponse(content=f"the approved action couldn't complete (error {ref}); nothing was "
                                             f"done.{retry}", success=False)
        finally:
            with _lock:
                _live.discard(token)
        result = {"success": response.success, "content": response.content, "data": response.data}
        if raised:
            gate.record_result(item.id, result, org_id=org_id, failed=True)
            return result
        if response.metadata.get("held") or response.requires_consensus:
            # The chip asked again instead of acting: it has no approved path for this action yet. Say so plainly
            # rather than report the action done.
            result = {"success": False, "data": response.data,
                      "content": f"approved, but {p['chip']} has no step that carries out {p['action']} yet; "
                                 "nothing ran"}
    gate.record_result(item.id, result, org_id=org_id)
    return result
