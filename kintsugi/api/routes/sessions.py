"""Session endpoints — conversations bound to agent instances."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from kintsugi.agents.sessions import get_session_manager
from kintsugi.api.auth import Principal, require_principal, resolve_org
from kintsugi.api.routes.fleet import own_agent

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    agent_id: str | None = None  # attach to an existing agent...
    personality: str = "default"  # ...or spawn a fresh one with this personality
    org_id: str | None = None  # the key decides the org; a different value here is refused
    user_id: str = "api"  # audit metadata; grants nothing


class SessionMessageRequest(BaseModel):
    message: str = Field(min_length=1)
    context: dict[str, Any] = {}


def own_session(session_id: str, principal: Principal):
    """The session, if it belongs to the caller's org; another org's reads as not found."""
    try:
        session = get_session_manager().get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if session.org_id != principal.org_id:
        raise HTTPException(status_code=404, detail=f"unknown session {session_id!r}")
    return session


@router.get("")
async def list_sessions(include_closed: bool = False, principal: Principal = Depends(require_principal)) -> dict:
    manager = get_session_manager()
    return {"sessions": [s.to_dict() for s in manager.list(include_closed=include_closed)
                         if s.org_id == principal.org_id]}


@router.post("", status_code=201)
async def create_session(body: CreateSessionRequest, principal: Principal = Depends(require_principal)) -> dict:
    manager = get_session_manager()
    org_id = resolve_org(principal, body.org_id)
    if body.agent_id is not None:
        own_agent(body.agent_id, principal)   # attaching to another org's agent reads as not found
    try:
        session = manager.create(
            agent_id=body.agent_id,
            personality=body.personality,
            org_id=org_id,
            user_id=body.user_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return session.to_dict()


@router.get("/{session_id}")
async def get_session(session_id: str, principal: Principal = Depends(require_principal)) -> dict:
    return own_session(session_id, principal).to_dict(include_history=True)


@router.post("/{session_id}/messages")
async def send_message(session_id: str, body: SessionMessageRequest,
                       principal: Principal = Depends(require_principal)) -> dict:
    manager = get_session_manager()
    own_session(session_id, principal)
    try:
        result = await manager.send_message(session_id, body.message, context=body.context)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return result.to_dict()


@router.delete("/{session_id}")
async def close_session(session_id: str, principal: Principal = Depends(require_principal)) -> dict:
    own_session(session_id, principal)
    try:
        return get_session_manager().close(session_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
