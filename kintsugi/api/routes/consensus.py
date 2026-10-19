"""Consent for held actions: list what's waiting, approve, reject (Vera's re-check, 2026-10-18).

Every call is the caller's org only; another org's item reads as not found. Approving needs an admin key, and the
key that asked for an action can't approve it. Rejecting needs an admin key, or the key that asked (withdrawing
its own). When an approval completes an item, it runs once, here, and the result comes back.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from kintsugi.api.auth import Principal, audit, require_principal
from kintsugi.governance.consensus import ConsentStatus, get_consensus_gate
from kintsugi.governance.consumer import execute_approved

router = APIRouter(prefix="/api/v1/consensus", tags=["consensus"])


class Decision(BaseModel):
    rationale: str = ""


def _who(principal: Principal) -> str:
    return f"key:{principal.key_id}"       # the same form the routes give chips as the acting user


@router.get("/pending")
async def pending(principal: Principal = Depends(require_principal)) -> dict:
    return {"pending": [i.to_dict() for i in get_consensus_gate().list_pending(principal.org_id)]}


@router.get("/{item_id}")
async def get_item(item_id: str, principal: Principal = Depends(require_principal)) -> dict:
    item = get_consensus_gate().get_item(item_id, org_id=principal.org_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"unknown consent item {item_id!r}")
    return item.to_dict()


@router.post("/{item_id}/approve")
async def approve(item_id: str, body: Decision, principal: Principal = Depends(require_principal)) -> dict:
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="approving an action needs an admin key")
    gate = get_consensus_gate()
    if gate.get_item(item_id, org_id=principal.org_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown consent item {item_id!r}")
    # The audit record is written before the approval is committed: if it can't be written, nothing is approved, so
    # an approval can't exist without its record (Vera's review, 2026-10-18, item 1).
    audit(principal, "consensus.approve", item=item_id)
    try:
        item = gate.approve(item_id, _who(principal), body.rationale, org_id=principal.org_id)
    except ValueError as exc:
        raise HTTPException(status_code=404 if "No consent item" in str(exc) else 409, detail=str(exc))
    out = {"item": item.to_dict(), "result": None}
    if item.status == ConsentStatus.APPROVED:
        out["result"] = await execute_approved(item_id, principal.org_id)
        out["item"] = gate.get_item(item_id, org_id=principal.org_id).to_dict()
    return out


@router.post("/{item_id}/run")
async def run(item_id: str, principal: Principal = Depends(require_principal)) -> dict:
    """Run an approved item that didn't run (a crash or restart between approval and running). Within the run window
    it runs once; after it, it expires and has to be asked for again."""
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="running an approved action needs an admin key")
    gate = get_consensus_gate()
    if gate.get_item(item_id, org_id=principal.org_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown consent item {item_id!r}")
    audit(principal, "consensus.run", item=item_id)
    try:
        result = await execute_approved(item_id, principal.org_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"item": gate.get_item(item_id, org_id=principal.org_id).to_dict(), "result": result}


@router.post("/{item_id}/reject")
async def reject(item_id: str, body: Decision, principal: Principal = Depends(require_principal)) -> dict:
    gate = get_consensus_gate()
    item = gate.get_item(item_id, org_id=principal.org_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"unknown consent item {item_id!r}")
    if not principal.is_admin and item.requester != _who(principal):
        raise HTTPException(status_code=403, detail="rejecting needs an admin key, or the key that asked")
    try:
        item = gate.reject(item_id, _who(principal), body.rationale, org_id=principal.org_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    audit(principal, "consensus.reject", item=item_id)
    return {"item": item.to_dict()}
