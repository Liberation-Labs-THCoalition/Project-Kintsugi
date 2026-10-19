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

from kintsugi.governance.consensus import ConsentCategory, payload_digest, get_consensus_gate
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


def hold(chip, request, context, action: str) -> SkillResponse:
    """Submit the request to the gate instead of running it. Nothing the chip would do has happened."""
    payload = request_payload(chip.name, request, context, action)
    item = get_consensus_gate().submit(context.org_id, _category(chip, action), f"{chip.name}: {action}", payload,
                                       requester=context.user_id)
    logger.info("held %s (%s) for consent as %s", chip.name, action, item.id)
    return SkillResponse(
        content=(f"This needs approval before it happens ({action}). Nothing has been done yet; it's waiting for "
                 f"approval as request {item.id}."),
        success=True,
        requires_consensus=True,
        consensus_action=action,
        data={"consent_id": item.id, "status": item.status.value, "action": action},
        metadata={"held": True},
    )


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
        try:
            response = await chip.handle(request, context)
        except Exception:
            ref = failure_reference(logger, f"approved item {item.id}")
            response = SkillResponse(content=f"the approved action couldn't complete (error {ref})", success=False)
        finally:
            with _lock:
                _live.discard(token)
        result = {"success": response.success, "content": response.content, "data": response.data}
        if response.metadata.get("held") or response.requires_consensus:
            # The chip asked again instead of acting: it has no approved path for this action yet. Say so plainly
            # rather than report the action done.
            result = {"success": False, "data": response.data,
                      "content": f"approved, but {p['chip']} has no step that carries out {p['action']} yet; "
                                 "nothing ran"}
    gate.record_result(item.id, result, org_id=org_id)
    return result
