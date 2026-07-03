"""Dashboard routes: full page + htmx partials + form actions."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from kintsugi.agents.manager import get_agent_manager
from kintsugi.agents.personality import get_personality_registry
from kintsugi.agents.sessions import get_session_manager
from kintsugi.oracle.monitor import get_oracle_monitor
from kintsugi.skills.registry import get_registry

logger = logging.getLogger(__name__)

_here = Path(__file__).resolve().parent
static_dir = _here / "static"
templates = Jinja2Templates(directory=str(_here / "templates"))

router = APIRouter(prefix="/dashboard", tags=["dashboard"], include_in_schema=False)

# The dashboard's own chat sessions, one per personality, created lazily.
_chat_sessions: dict[str, str] = {}


def _context(request: Request) -> dict:
    manager = get_agent_manager()
    sessions = get_session_manager()
    oracle = get_oracle_monitor()
    return {
        "request": request,
        "agents": [a.describe() for a in manager.list()],
        "sessions": [s.to_dict() for s in sessions.list()],
        "oracle": oracle.status(),
        "verdicts": oracle.recent_verdicts(limit=10)[::-1],
        "skills": get_registry().list_all(),
        "personalities": [p.to_dict() for p in get_personality_registry().list()],
    }


@router.get("", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", _context(request))


@router.get("/partials/agents", response_class=HTMLResponse)
async def partial_agents(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "partials/agents.html", _context(request))


@router.get("/partials/sessions", response_class=HTMLResponse)
async def partial_sessions(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "partials/sessions.html", _context(request))


@router.get("/partials/oracle", response_class=HTMLResponse)
async def partial_oracle(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "partials/oracle.html", _context(request))


@router.get("/partials/skills", response_class=HTMLResponse)
async def partial_skills(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "partials/skills.html", _context(request))


@router.post("/actions/spawn", response_class=HTMLResponse)
async def action_spawn(request: Request, personality: str = Form("default")) -> HTMLResponse:
    try:
        get_agent_manager().spawn(personality=personality)
    except Exception as exc:
        logger.warning("dashboard spawn failed: %s", exc)
    return templates.TemplateResponse(request, "partials/agents.html", _context(request))


@router.post("/actions/stop/{agent_id}", response_class=HTMLResponse)
async def action_stop(request: Request, agent_id: str) -> HTMLResponse:
    try:
        get_agent_manager().stop(agent_id)
    except KeyError:
        pass
    return templates.TemplateResponse(request, "partials/agents.html", _context(request))


@router.post("/actions/oracle-mode", response_class=HTMLResponse)
async def action_oracle_mode(request: Request, mode: str = Form("observe")) -> HTMLResponse:
    if mode in ("off", "observe", "enforce"):
        get_oracle_monitor().mode = mode
    return templates.TemplateResponse(request, "partials/oracle.html", _context(request))


@router.post("/actions/chat", response_class=HTMLResponse)
async def action_chat(
    request: Request,
    message: str = Form(...),
    personality: str = Form("default"),
) -> HTMLResponse:
    sessions = get_session_manager()
    turn = None
    error = None
    try:
        session_id = _chat_sessions.get(personality)
        if session_id is None or session_id not in {s.id for s in sessions.list()}:
            session = sessions.create(personality=personality, user_id="dashboard")
            _chat_sessions[personality] = session.id
            session_id = session.id
        turn = (await sessions.send_message(session_id, message)).to_dict()
    except Exception as exc:
        logger.warning("dashboard chat failed: %s", exc)
        error = str(exc)
    ctx = _context(request)
    ctx.update({"turn": turn, "error": error, "sent_message": message})
    return templates.TemplateResponse(request, "partials/chat_turn.html", ctx)
