"""A single running agent instance.

An AgentInstance binds a personality to the shared engine layers
(security, cognition, skills, Oracle) and processes messages through the
full pipeline:

    security scan -> PII redaction -> orchestrator routing ->
    skill execution -> Oracle Loop review -> response

Instances are in-memory and cheap: the heavy machinery (skill registry,
orchestrator, Oracle monitor) is shared; each instance carries only its
personality, counters, and BDI working state.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from kintsugi.agents.events import EventBus, get_event_bus
from kintsugi.agents.personality import AgentPersonality
from kintsugi.cognition.model_router import ModelRouter
from kintsugi.cognition.orchestrator import Orchestrator, OrchestratorConfig
from kintsugi.oracle.hooks import AgentTurn
from kintsugi.oracle.monitor import OracleLoopMonitor, get_oracle_monitor
from kintsugi.security.monitor import SecurityMonitor, Verdict
from kintsugi.security.pii import PIIRedactor
from kintsugi.skills.base import SkillContext, SkillRequest
from kintsugi.skills.registry import SkillRegistry, get_registry

logger = logging.getLogger(__name__)


class AgentState(str, Enum):
    IDLE = "idle"
    PROCESSING = "processing"
    STOPPED = "stopped"


# The orchestrator's routing vocabulary predates SkillDomain; translate
# where the two disagree.
_DOMAIN_ALIASES = {
    "grants": "fundraising",
    "impact": "programs",
    "volunteers": "operations",
}


@dataclass
class TurnResult:
    """What handle_message returns to sessions / the API."""

    response: str
    agent_id: str
    session_id: str | None
    skill_used: str | None
    routing: dict[str, Any]
    security: dict[str, Any]
    oracle: dict[str, Any]
    blocked: bool = False
    turn_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "response": self.response,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "skill_used": self.skill_used,
            "routing": self.routing,
            "security": self.security,
            "oracle": self.oracle,
            "blocked": self.blocked,
            "timestamp": self.timestamp.isoformat(),
        }


class AgentInstance:
    """One live agent: personality + shared engine + counters."""

    def __init__(
        self,
        personality: AgentPersonality,
        org_id: str = "default",
        agent_id: str | None = None,
        *,
        skill_registry: SkillRegistry | None = None,
        oracle_monitor: OracleLoopMonitor | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.id = agent_id or f"agent-{uuid.uuid4().hex[:8]}"
        self.personality = personality
        self.org_id = org_id
        self.state = AgentState.IDLE
        self.created_at = datetime.now(timezone.utc)
        self.stats = {"messages": 0, "skills_executed": 0, "security_blocks": 0, "oracle_blocks": 0}
        self.last_active: datetime | None = None

        self._security = SecurityMonitor()
        self._redactor = PIIRedactor()
        self._skills = skill_registry or get_registry()
        self._oracle = oracle_monitor or get_oracle_monitor()
        self._events = event_bus or get_event_bus()
        self._orchestrator = Orchestrator(
            config=OrchestratorConfig(),
            model_router=ModelRouter(),
        )

    # -- lifecycle -----------------------------------------------------------

    def stop(self) -> None:
        self.state = AgentState.STOPPED
        self._events.publish("agent.stopped", {"name": self.personality.name}, agent_id=self.id)

    # -- pipeline ------------------------------------------------------------

    async def handle_message(
        self,
        message: str,
        *,
        session_id: str | None = None,
        user_id: str = "api",
        context: dict[str, Any] | None = None,
    ) -> TurnResult:
        if self.state == AgentState.STOPPED:
            raise RuntimeError(f"agent {self.id} is stopped")

        self.state = AgentState.PROCESSING
        self.last_active = datetime.now(timezone.utc)
        self.stats["messages"] += 1
        self._events.publish(
            "message.received",
            {"preview": message[:120]},
            agent_id=self.id,
            session_id=session_id,
        )

        try:
            return await self._process(message, session_id, user_id, context or {})
        finally:
            if self.state != AgentState.STOPPED:
                self.state = AgentState.IDLE

    async def _process(
        self,
        message: str,
        session_id: str | None,
        user_id: str,
        context: dict[str, Any],
    ) -> TurnResult:
        # 1. Security scan (prompt-injection / dangerous-command patterns)
        sec = self._security.check_text(message)
        security_info = {"verdict": sec.verdict.value, "reason": sec.reason}
        if sec.verdict == Verdict.BLOCK:
            self.stats["security_blocks"] += 1
            self._events.publish(
                "security.blocked", security_info, agent_id=self.id, session_id=session_id
            )
            return TurnResult(
                response=f"Request blocked by security monitor: {sec.reason}",
                agent_id=self.id,
                session_id=session_id,
                skill_used=None,
                routing={},
                security=security_info,
                oracle={"status": "not_reviewed"},
                blocked=True,
            )

        # 2. PII redaction — redacted form is what gets logged / sent upstream
        redacted = self._redactor.redact(message).redacted_text

        # 3. Route to a skill domain
        decision = await self._orchestrator.route(redacted, self.org_id, context=context)
        routing_info = {
            "domain": decision.skill_domain,
            "confidence": round(decision.confidence, 3),
            "reasoning": decision.reasoning,
        }
        self._events.publish("message.routed", routing_info, agent_id=self.id, session_id=session_id)

        # 4. Execute the best permitted skill in that domain
        response_text, skill_used = await self._execute_skill(
            decision.skill_domain, message, session_id, user_id, context
        )

        # 5. Oracle Loop review — every response passes through before delivery
        review = await self._oracle.review(
            AgentTurn(
                agent_id=self.id,
                session_id=session_id,
                user_input=redacted,
                response=response_text,
                skill_used=skill_used,
                metadata={"personality": self.personality.name, "org_id": self.org_id},
            ),
            mode=self.personality.safety.oracle_mode,
            block_threshold=self.personality.safety.block_threshold,
        )
        if review.blocked:
            self.stats["oracle_blocks"] += 1
        self._events.publish(
            "oracle.verdict",
            {**review.verdict.to_dict(), "blocked": review.blocked},
            agent_id=self.id,
            session_id=session_id,
        )

        result = TurnResult(
            response=review.response,
            agent_id=self.id,
            session_id=session_id,
            skill_used=skill_used,
            routing=routing_info,
            security=security_info,
            oracle=review.verdict.to_dict(),
            blocked=review.blocked,
        )
        self._events.publish(
            "message.completed",
            {"skill_used": skill_used, "blocked": review.blocked},
            agent_id=self.id,
            session_id=session_id,
        )
        return result

    async def _execute_skill(
        self,
        domain: str,
        message: str,
        session_id: str | None,
        user_id: str,
        context: dict[str, Any],
    ) -> tuple[str, str | None]:
        """Find a permitted chip for *domain* and run it."""
        chip = None
        try:
            from kintsugi.skills.base import SkillDomain

            resolved = _DOMAIN_ALIASES.get(domain, domain)
            candidates = self._skills.get_by_domain(SkillDomain(resolved))
        except ValueError:
            candidates = []

        permitted = [c for c in candidates if self.personality.allows_skill(c.name)]
        if permitted:
            # Prefer the chip whose name overlaps the message text; fall
            # back to the first chip registered in the domain.
            msg_lower = message.lower()

            def _name_score(c) -> int:
                return sum(1 for part in c.name.split("_") if part in msg_lower)

            chip = max(permitted, key=_name_score)

        if chip is None:
            # No chip available/permitted — deterministic fallback that
            # still exercises the full monitoring pipeline.
            return (
                f"[{self.personality.display_name}] No skill chip is available for "
                f"domain '{domain}' under this personality's permissions.",
                None,
            )

        intent = self._choose_intent(chip, message, domain)
        request = SkillRequest(intent=intent, raw_input=message, parameters=context)
        skill_context = SkillContext(
            org_id=self.org_id,
            user_id=user_id,
            session_id=session_id,
            platform="api",
            metadata={"agent_id": self.id, "personality": self.personality.name},
        )
        try:
            response = await chip.handle(request, skill_context)
            self.stats["skills_executed"] += 1
            self._events.publish(
                "skill.executed",
                {"skill": chip.name, "success": response.success},
                agent_id=self.id,
                session_id=session_id,
            )
            return response.content, chip.name
        except Exception as exc:
            logger.exception("skill %s failed", chip.name)
            self._events.publish(
                "skill.failed",
                {"skill": chip.name, "error": str(exc)},
                agent_id=self.id,
                session_id=session_id,
            )
            return f"Skill '{chip.name}' failed: {exc}", chip.name

    @staticmethod
    def _choose_intent(chip: Any, message: str, domain: str) -> str:
        """Pick an intent the chip actually supports.

        Chips with a SUPPORTED_INTENTS map dispatch on specific intent
        strings; match one against the message, else use the chip's first
        (primary) intent. Chips without the map get the domain as intent.
        """
        supported = getattr(chip, "SUPPORTED_INTENTS", None)
        if not supported:
            return domain
        msg_lower = message.lower()
        for intent in supported:
            parts = intent.split("_")
            if intent in msg_lower or any(part in msg_lower for part in parts[1:]):
                return intent
        return next(iter(supported))

    # -- introspection ---------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "org_id": self.org_id,
            "state": self.state.value,
            "personality": self.personality.name,
            "display_name": self.personality.display_name,
            "oracle_mode": self.personality.safety.oracle_mode,
            "created_at": self.created_at.isoformat(),
            "last_active": self.last_active.isoformat() if self.last_active else None,
            "stats": dict(self.stats),
        }
