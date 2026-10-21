"""On-call alerts: see one, and acknowledge it (kintsugi/governance/oncall.py; Vera's design, 2026-10-19).

Every call is the caller's org only; another org's alert reads as not found. An alert is visible to an admin, to the
person who raised it, and to the on-call people it reached; to anyone else in the org it reads as not found, since
it names people and an area. Only an on-call person it reached can acknowledge it, as themselves (the key's person).
Acknowledging approves nothing: the wide broadcast still waits for an admin in the consensus queue.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from kintsugi.api.auth import Principal, audit, require_principal
from kintsugi.governance import oncall
from kintsugi.security.api_keys import person_of

router = APIRouter(prefix="/api/v1/oncall", tags=["oncall"])


def _person(principal: Principal) -> str:
    """The key's person's name, or "" for a key that names no person (such a key can't be on call)."""
    who = person_of(f"key:{principal.key_id}")
    return who[len("person:"):] if who.startswith("person:") else ""


def _visible(rec, principal: Principal) -> bool:
    return (principal.is_admin or rec.triggered_by == f"key:{principal.key_id}"
            or (_person(principal) and _person(principal) in rec.reached))


@router.get("/{alert_id}")
async def get_alert(alert_id: str, principal: Principal = Depends(require_principal)) -> dict:
    rec = oncall.get_alert(principal.org_id, alert_id)
    if rec is None or not _visible(rec, principal):
        raise HTTPException(status_code=404, detail=f"unknown on-call alert {alert_id!r}")
    return {**oncall.public(rec), "status": oncall.status_line(rec)}


@router.post("/{alert_id}/ack")
async def acknowledge(alert_id: str, principal: Principal = Depends(require_principal)) -> dict:
    rec = oncall.get_alert(principal.org_id, alert_id)
    if rec is None or not _visible(rec, principal):
        raise HTTPException(status_code=404, detail=f"unknown on-call alert {alert_id!r}")
    person = _person(principal)
    try:
        rec = oncall.acknowledge(principal.org_id, alert_id, person)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    audit(principal, "oncall.ack", alert_id=alert_id, person=person, state=rec.state)
    return {**oncall.public(rec), "status": oncall.status_line(rec)}
