"""Session endpoints — conversations bound to agent instances."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from kintsugi.agents.sessions import get_session_manager

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    agent_id: str | None = None  # attach to an existing agent...
    personality: str = "default"  # ...or spawn a fresh one with this personality
    org_id: str = "default"
    user_id: str = "api"


class SessionMessageRequest(BaseModel):
    message: str = Field(min_length=1)
    context: dict[str, Any] = {}


@router.get("")
async def list_sessions(include_closed: bool = False) -> dict:
    manager = get_session_manager()
    return {"sessions": [s.to_dict() for s in manager.list(include_closed=include_closed)]}


@router.post("", status_code=201)
async def create_session(body: CreateSessionRequest) -> dict:
    manager = get_session_manager()
    try:
        session = manager.create(
            agent_id=body.agent_id,
            personality=body.personality,
            org_id=body.org_id,
            user_id=body.user_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return session.to_dict()


@router.get("/{session_id}")
async def get_session(session_id: str) -> dict:
    try:
        return get_session_manager().get(session_id).to_dict(include_history=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{session_id}/messages")
async def send_message(session_id: str, body: SessionMessageRequest) -> dict:
    manager = get_session_manager()
    try:
        result = await manager.send_message(session_id, body.message, context=body.context)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return result.to_dict()


@router.delete("/{session_id}")
async def close_session(session_id: str) -> dict:
    try:
        return get_session_manager().close(session_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
