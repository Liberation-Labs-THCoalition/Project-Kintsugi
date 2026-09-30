"""Agent fleet endpoints — spawn, inspect, and stop agent instances."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from kintsugi.agents.manager import get_agent_manager
from kintsugi.api.auth import Principal, require_admin, require_principal, resolve_org
from kintsugi.agents.personality import get_personality_registry

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


class SpawnRequest(BaseModel):
    personality: str = "default"
    org_id: str | None = None  # the key decides the org; a different value here is refused
    agent_id: str | None = None


class MessageRequest(BaseModel):
    message: str = Field(min_length=1)
    user_id: str = "api"
    context: dict[str, Any] = {}


def own_agent(agent_id: str, principal: Principal):
    """The agent, if it belongs to the caller's org. Another org's agent reads as not found, so ids don't leak."""
    try:
        agent = get_agent_manager().get(agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if agent.org_id != principal.org_id:
        raise HTTPException(status_code=404, detail=f"unknown agent {agent_id!r}")
    return agent


@router.get("")
async def list_agents(include_stopped: bool = False, principal: Principal = Depends(require_principal)) -> dict:
    manager = get_agent_manager()
    return {"agents": [a.describe() for a in manager.list(include_stopped=include_stopped)
                       if a.org_id == principal.org_id]}


@router.post("", status_code=201)
async def spawn_agent(body: SpawnRequest, principal: Principal = Depends(require_principal)) -> dict:
    manager = get_agent_manager()
    org_id = resolve_org(principal, body.org_id)
    try:
        agent = manager.spawn(
            personality=body.personality, org_id=org_id, agent_id=body.agent_id
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return agent.describe()


@router.get("/personalities")
async def list_personalities() -> dict:
    registry = get_personality_registry()
    return {"personalities": [p.to_dict() for p in registry.list()]}


@router.post("/personalities/reload", dependencies=[Depends(require_admin)])
async def reload_personalities() -> dict:
    registry = get_personality_registry()
    return {"loaded": registry.reload()}


@router.get("/{agent_id}")
async def get_agent(agent_id: str, principal: Principal = Depends(require_principal)) -> dict:
    agent = own_agent(agent_id, principal)
    detail = agent.describe()
    detail["personality_config"] = agent.personality.to_dict()
    return detail


@router.post("/{agent_id}/messages")
async def message_agent(agent_id: str, body: MessageRequest,
                        principal: Principal = Depends(require_principal)) -> dict:
    """One-shot message to an agent outside any session."""
    agent = own_agent(agent_id, principal)
    try:
        result = await agent.handle_message(
            body.message, user_id=body.user_id, context=body.context
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return result.to_dict()


@router.delete("/{agent_id}")
async def stop_agent(agent_id: str, principal: Principal = Depends(require_principal)) -> dict:
    own_agent(agent_id, principal)
    try:
        agent = get_agent_manager().stop(agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return agent.describe()
