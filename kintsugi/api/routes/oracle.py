"""Oracle Loop endpoints: status, verdict history, and mode control.

Changing the mode or the hook endpoint is admin-only and audited (step 3). The endpoint is chosen by *name* from the
server-side allowlist ``settings.ORACLE_HOOK_ENDPOINTS``: the API can select a destination but never introduce a URL,
because every subsequent agent turn is posted to it (Vera's endpoint-hijack finding, 2026-09-29). Turning review off is
the quieter attack, so it is admin-only and audited too.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from kintsugi.api.auth import Principal, audit, require_admin
from kintsugi.config.settings import settings
from kintsugi.oracle.hooks import HTTPOracleHook
from kintsugi.oracle.monitor import get_oracle_monitor

router = APIRouter(prefix="/api/v1/oracle", tags=["oracle"])


class OracleModeRequest(BaseModel):
    mode: Literal["off", "observe", "enforce"]


class OracleEndpointRequest(BaseModel):
    name: str  # a key of ORACLE_HOOK_ENDPOINTS; empty string detaches all HTTP hooks


@router.get("/status")
async def oracle_status() -> dict:
    return get_oracle_monitor().status()


@router.get("/verdicts")
async def oracle_verdicts(limit: int = 50) -> dict:
    return {"verdicts": get_oracle_monitor().recent_verdicts(limit=limit)}


@router.get("/endpoints")
async def oracle_endpoints() -> dict:
    """The names an admin may select. URLs are not shown."""
    return {"endpoints": sorted(settings.ORACLE_HOOK_ENDPOINTS)}


@router.put("/mode")
async def set_oracle_mode(body: OracleModeRequest, principal: Principal = Depends(require_admin)) -> dict:
    monitor = get_oracle_monitor()
    old = monitor.mode
    audit(principal, "oracle.mode", old=old, new=body.mode)
    monitor.mode = body.mode
    return monitor.status()


@router.put("/endpoint")
async def set_oracle_endpoint(body: OracleEndpointRequest, principal: Principal = Depends(require_admin)) -> dict:
    """Attach (or, with an empty name, detach) the HTTP hook, by allowlisted name."""
    if body.name and body.name not in settings.ORACLE_HOOK_ENDPOINTS:
        raise HTTPException(status_code=422, detail=f"unknown Oracle endpoint name {body.name!r}")
    hook = HTTPOracleHook(settings.ORACLE_HOOK_ENDPOINTS[body.name]) if body.name else None  # validates the URL
    audit(principal, "oracle.endpoint", new=body.name or "(detached)")
    monitor = get_oracle_monitor()
    monitor.clear_hooks()
    if hook is not None:
        monitor.register_hook(hook)
    return monitor.status()
