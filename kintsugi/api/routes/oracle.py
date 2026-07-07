"""Oracle Loop endpoints — status, verdict history, and mode control."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from kintsugi.oracle.hooks import HTTPOracleHook
from kintsugi.oracle.monitor import get_oracle_monitor

router = APIRouter(prefix="/api/v1/oracle", tags=["oracle"])


class OracleModeRequest(BaseModel):
    mode: Literal["off", "observe", "enforce"]


class OracleEndpointRequest(BaseModel):
    endpoint: str  # empty string detaches all HTTP hooks


@router.get("/status")
async def oracle_status() -> dict:
    return get_oracle_monitor().status()


@router.get("/verdicts")
async def oracle_verdicts(limit: int = 50) -> dict:
    return {"verdicts": get_oracle_monitor().recent_verdicts(limit=limit)}


@router.put("/mode")
async def set_oracle_mode(body: OracleModeRequest) -> dict:
    monitor = get_oracle_monitor()
    monitor.mode = body.mode
    return monitor.status()


@router.put("/endpoint")
async def set_oracle_endpoint(body: OracleEndpointRequest) -> dict:
    """Attach (or detach) the HTTP hook to a running Oracle harness."""
    monitor = get_oracle_monitor()
    monitor.clear_hooks()
    if body.endpoint:
        monitor.register_hook(HTTPOracleHook(body.endpoint))
    return monitor.status()
