"""Agent fleet endpoints — spawn, inspect, and stop agent instances."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from kintsugi.agents.manager import get_agent_manager
from kintsugi.agents.personality import get_personality_registry

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


class SpawnRequest(BaseModel):
    personality: str = "default"
    org_id: str = "default"
    agent_id: str | None = None


class MessageRequest(BaseModel):
    message: str = Field(min_length=1)
    user_id: str = "api"
    context: dict[str, Any] = {}


@router.get("")
async def list_agents(include_stopped: bool = False) -> dict:
    manager = get_agent_manager()
    return {"agents": [a.describe() for a in manager.list(include_stopped=include_stopped)]}


@router.post("", status_code=201)
async def spawn_agent(body: SpawnRequest) -> dict:
    manager = get_agent_manager()
    try:
        agent = manager.spawn(
            personality=body.personality, org_id=body.org_id, agent_id=body.agent_id
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


@router.post("/personalities/reload")
async def reload_personalities() -> dict:
    registry = get_personality_registry()
    return {"loaded": registry.reload()}


@router.get("/{agent_id}")
async def get_agent(agent_id: str) -> dict:
    try:
        agent = get_agent_manager().get(agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    detail = agent.describe()
    detail["personality_config"] = agent.personality.to_dict()
    return detail


@router.post("/{agent_id}/messages")
async def message_agent(agent_id: str, body: MessageRequest) -> dict:
    """One-shot message to an agent outside any session."""
    try:
        agent = get_agent_manager().get(agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    try:
        result = await agent.handle_message(
            body.message, user_id=body.user_id, context=body.context
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return result.to_dict()


@router.delete("/{agent_id}")
async def stop_agent(agent_id: str) -> dict:
    try:
        agent = get_agent_manager().stop(agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return agent.describe()
