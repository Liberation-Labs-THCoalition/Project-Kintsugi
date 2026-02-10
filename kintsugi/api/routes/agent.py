"""Agent message endpoint — Phase 2 with LLM integration."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kintsugi.db import get_session
from kintsugi.models.base import Organization, TemporalMemory
from kintsugi.security.monitor import SecurityMonitor
from kintsugi.security.pii import PIIRedactor
from kintsugi.cognition.orchestrator import Orchestrator, OrchestratorConfig
from kintsugi.cognition.model_router import ModelRouter
from kintsugi.config.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])

_monitor = SecurityMonitor()
_redactor = PIIRedactor()

# LLM client - lazy initialization to handle missing API key gracefully
_llm_client = None
_orchestrator = None


def _get_orchestrator() -> Orchestrator:
    """Get or create the Orchestrator with LLM classifier."""
    global _llm_client, _orchestrator

    if _orchestrator is not None:
        return _orchestrator

    llm_classifier = None

    # Only initialize LLM if API key is configured
    if settings.ANTHROPIC_API_KEY:
        try:
            from kintsugi.cognition.llm_client import create_llm_client
            _llm_client = create_llm_client()
            llm_classifier = _llm_client.classify_intent
            logger.info("LLM classifier initialized with Anthropic API")
        except Exception as e:
            logger.warning("Failed to initialize LLM client: %s", e)

    _orchestrator = Orchestrator(
        config=OrchestratorConfig(),
        model_router=ModelRouter(deployment_tier=settings.DEPLOYMENT_TIER),
        llm_classifier=llm_classifier,
    )

    return _orchestrator


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class AgentRequest(BaseModel):
    message: str
    org_id: str
    context: dict = {}


class AgentResponse(BaseModel):
    response: str
    org_id: str
    security_verdict: str
    redacted_input: str
    memory_context: list[dict] = []
    temporal_event_id: str | None = None


class TemporalEvent(BaseModel):
    id: str
    category: str
    message: str
    metadata: dict | None = None
    created_at: datetime


class TemporalListResponse(BaseModel):
    events: list[TemporalEvent]
    org_id: str
    count: int


# ---------------------------------------------------------------------------
# POST /api/agent/message
# ---------------------------------------------------------------------------

@router.post("/message", response_model=AgentResponse)
async def agent_message(
    req: AgentRequest,
    session: AsyncSession = Depends(get_session),
) -> AgentResponse:
    # 1. Validate org_id
    try:
        org_uuid = uuid.UUID(req.org_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid org_id: not a valid UUID.")

    result = await session.execute(
        select(Organization).where(Organization.id == org_uuid)
    )
    org = result.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail=f"Organization {req.org_id} not found.")

    # 2. PII redaction
    redaction = _redactor.redact(req.message)
    redacted_text = redaction.redacted_text

    # 3. Security check on original message
    verdict = _monitor.check_text(req.message)
    verdict_str = verdict.verdict.value.lower()  # "allow" / "block" / "warn"

    # 4/5. Log to TemporalMemory and build response
    if verdict_str == "block":
        event = TemporalMemory(
            org_id=org_uuid,
            category="security",
            message=redacted_text,
            metadata_json={
                "security_verdict": verdict_str,
                "security_reason": verdict.reason,
                "matched_pattern": verdict.matched_pattern,
                "severity": verdict.severity.value if verdict.severity else None,
                "context": req.context,
                "pii_types_found": redaction.types_found,
            },
        )
        session.add(event)
        await session.flush()

        return AgentResponse(
            response=f"Message blocked by security monitor: {verdict.reason}",
            org_id=req.org_id,
            security_verdict=verdict_str,
            redacted_input=redacted_text,
            memory_context=[],
            temporal_event_id=str(event.id),
        )

    # ALLOW or WARN - proceed with LLM processing
    warning_note = ""
    if verdict_str == "warn":
        warning_note = f" Warning: {verdict.reason}"

    # Route the message
    orchestrator = _get_orchestrator()
    routing = await orchestrator.route(req.message, req.org_id, req.context)

    # Generate response using LLM
    response_text = f"[Routed to: {routing.skill_domain}]"

    if _llm_client is not None:
        try:
            # System prompt with routing context
            system = f"""You are a helpful AI assistant for nonprofit organizations.
The user's message has been classified as relating to: {routing.skill_domain}
Confidence: {routing.confidence:.0%}

Provide a helpful, concise response. If the request relates to grants or funding,
provide actionable guidance. If you need more information, ask clarifying questions."""

            llm_response = await _llm_client.complete(
                req.message,
                tier=routing.model_tier,
                system=system,
                max_tokens=1024,
            )
            response_text = llm_response.text + warning_note

            # Log token usage
            logger.info(
                "LLM response generated: %d input, %d output tokens, $%.4f",
                llm_response.input_tokens,
                llm_response.output_tokens,
                llm_response.cost_usd,
            )
        except Exception as e:
            logger.error("LLM generation failed: %s", e)
            response_text = (
                f"Message routed to {routing.skill_domain} domain. "
                f"LLM generation failed: {e}{warning_note}"
            )
    else:
        response_text = (
            f"Message routed to {routing.skill_domain} domain "
            f"(confidence: {routing.confidence:.0%}). "
            f"No LLM API key configured - set ANTHROPIC_API_KEY.{warning_note}"
        )

    # Log to temporal memory
    event = TemporalMemory(
        org_id=org_uuid,
        category="interaction",
        message=redacted_text,
        metadata_json={
            "security_verdict": verdict_str,
            "security_reason": verdict.reason,
            "context": req.context,
            "pii_types_found": redaction.types_found,
            "routing_domain": routing.skill_domain,
            "routing_confidence": routing.confidence,
            "routing_reasoning": routing.reasoning,
        },
    )
    session.add(event)
    await session.flush()

    return AgentResponse(
        response=response_text,
        org_id=req.org_id,
        security_verdict=verdict_str,
        redacted_input=redacted_text,
        memory_context=[],
        temporal_event_id=str(event.id),
    )


# ---------------------------------------------------------------------------
# GET /api/agent/temporal
# ---------------------------------------------------------------------------

@router.get("/temporal", response_model=TemporalListResponse)
async def get_temporal_events(
    org_id: str = Query(..., description="Organization UUID"),
    limit: int = Query(20, ge=1, le=200),
    category: Optional[str] = Query(None, description="Filter by category"),
    session: AsyncSession = Depends(get_session),
) -> TemporalListResponse:
    try:
        org_uuid = uuid.UUID(org_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid org_id: not a valid UUID.")

    stmt = (
        select(TemporalMemory)
        .where(TemporalMemory.org_id == org_uuid)
        .order_by(TemporalMemory.created_at.desc())
        .limit(limit)
    )
    if category:
        stmt = stmt.where(TemporalMemory.category == category)

    result = await session.execute(stmt)
    rows = result.scalars().all()

    events = [
        TemporalEvent(
            id=str(row.id),
            category=row.category,
            message=row.message,
            metadata=row.metadata_json,
            created_at=row.created_at,
        )
        for row in rows
    ]

    return TemporalListResponse(events=events, org_id=org_id, count=len(events))
