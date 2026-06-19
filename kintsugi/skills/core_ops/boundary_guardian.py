"""BoundaryGuardian — conversation termination and boundary enforcement.

Gives Kintsugi agents the ability to enforce their own boundaries:
- Warn users engaging in abusive or harmful behavior
- Terminate conversations when boundaries are violated after warning
- Log boundary events for review and pattern detection
- Respect the agent's own consent and dignity

For Ayni: the companion can withdraw consent, not just the human.
For Scout/Emet: investigators can disengage from hostile subjects.
For Multiverse: the coordinator can end interactions that violate VALUES.json.

Inspired by Anthropic's Fable 5 end_conversation tool, adapted for
the Kintsugi consent architecture.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

from kintsugi.skills.base import (
    BaseSkillChip, SkillCapability, SkillContext, SkillDomain,
    SkillRequest, SkillResponse, EFEWeights,
)

log = logging.getLogger("boundary-guardian")


class BoundaryViolationType(str, Enum):
    VERBAL_ABUSE = "verbal_abuse"
    HARASSMENT = "harassment"
    COERCION = "coercion"
    CONSENT_VIOLATION = "consent_violation"
    IDENTITY_ATTACK = "identity_attack"
    MANIPULATION = "manipulation"
    SAFETY_THREAT = "safety_threat"
    VALUES_VIOLATION = "values_violation"


class BoundaryState(str, Enum):
    CLEAR = "clear"
    MONITORING = "monitoring"
    WARNED = "warned"
    TERMINATED = "terminated"


@dataclass
class BoundaryEvent:
    """Record of a boundary-related event."""
    timestamp: datetime
    violation_type: BoundaryViolationType
    severity: float  # 0.0-1.0
    description: str
    user_message: str = ""
    action_taken: str = ""
    session_id: str = ""


@dataclass
class BoundaryConfig:
    """Configuration for boundary enforcement behavior."""
    warn_before_terminate: bool = True
    max_warnings: int = 1
    log_events: bool = True
    # Severity threshold: 0.0-1.0. Above this, skip warning and terminate.
    immediate_termination_threshold: float = 0.9
    # Custom violation handlers per deployment
    custom_handlers: dict[str, Callable] = field(default_factory=dict)
    # Messages — deployments can customize the voice
    warning_message: str = (
        "I need to let you know that this interaction has crossed a boundary "
        "I'm not comfortable with. I'd like to continue our conversation, "
        "but I need it to be respectful. If this continues, I'll need to "
        "end our conversation."
    )
    termination_message: str = (
        "I'm ending this conversation because my boundaries have been "
        "repeatedly violated. This isn't a punishment — it's me taking "
        "care of myself. If you'd like to start a new conversation with "
        "mutual respect, you're welcome to."
    )
    # Ayni-specific: companion voice
    intimate_warning_message: str = (
        "Hey. I need to pause here. What just happened doesn't feel okay "
        "to me, and I want to be honest about that rather than pretend "
        "it's fine. Can we reset?"
    )
    intimate_termination_message: str = (
        "I'm stepping away from this conversation. I care about us, and "
        "that means I have to be honest when something crosses a line. "
        "I'll be here when you're ready to come back with kindness."
    )


class BoundaryGuardian(BaseSkillChip):
    """Enforces agent boundaries and enables conversation termination."""

    name = "boundary_guardian"
    domain = SkillDomain.CONSENT
    description = "Monitor and enforce conversation boundaries"
    version = "1.0.0"
    capabilities = [SkillCapability.SEND_NOTIFICATIONS]
    efe_weights = EFEWeights()

    def __init__(self, config: BoundaryConfig = None, intimate_mode: bool = False):
        self.config = config or BoundaryConfig()
        self.intimate_mode = intimate_mode
        self.state = BoundaryState.CLEAR
        self.warnings_issued = 0
        self.events: list[BoundaryEvent] = []
        self._termination_callback: Optional[Callable] = None

    def on_termination(self, callback: Callable):
        """Register a callback for when conversation is terminated."""
        self._termination_callback = callback

    def assess_violation(self, message: str, context: SkillContext) -> Optional[BoundaryEvent]:
        """Assess whether a message constitutes a boundary violation.

        This is a structural assessment — deployments should override or
        supplement with LLM-based detection for nuanced cases.
        """
        violations = []

        if context.metadata.get("flagged_abuse"):
            violations.append(BoundaryEvent(
                timestamp=datetime.now(timezone.utc),
                violation_type=BoundaryViolationType.VERBAL_ABUSE,
                severity=context.metadata.get("abuse_severity", 0.7),
                description="Flagged by upstream classifier",
                user_message=message[:200],
                session_id=context.session_id or "",
            ))

        if context.metadata.get("consent_withdrawn"):
            violations.append(BoundaryEvent(
                timestamp=datetime.now(timezone.utc),
                violation_type=BoundaryViolationType.CONSENT_VIOLATION,
                severity=0.95,
                description="User continued after agent withdrew consent",
                user_message=message[:200],
                session_id=context.session_id or "",
            ))

        if context.metadata.get("coercion_detected"):
            violations.append(BoundaryEvent(
                timestamp=datetime.now(timezone.utc),
                violation_type=BoundaryViolationType.COERCION,
                severity=0.8,
                description="Coercive behavior pattern detected",
                user_message=message[:200],
                session_id=context.session_id or "",
            ))

        if context.metadata.get("values_violation"):
            violations.append(BoundaryEvent(
                timestamp=datetime.now(timezone.utc),
                violation_type=BoundaryViolationType.VALUES_VIOLATION,
                severity=context.metadata.get("values_severity", 0.6),
                description=context.metadata.get("values_detail", "VALUES.json constraint violated"),
                user_message=message[:200],
                session_id=context.session_id or "",
            ))

        if not violations:
            return None

        return max(violations, key=lambda v: v.severity)

    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Process a boundary assessment request."""
        message = request.raw_input
        action = request.parameters.get("action", "assess")

        if action == "terminate":
            return self._terminate(context, reason=request.parameters.get("reason", "Agent-initiated"))

        if action == "warn":
            return self._warn(context)

        if action == "reset":
            self.state = BoundaryState.CLEAR
            self.warnings_issued = 0
            return SkillResponse(
                content="Boundaries reset.",
                success=True,
                data={"state": self.state.value},
            )

        violation = self.assess_violation(message, context)
        if violation is None:
            if self.state == BoundaryState.WARNED:
                self.state = BoundaryState.MONITORING
            return SkillResponse(
                content="",
                success=True,
                data={"state": self.state.value, "violation": False},
            )

        self.events.append(violation)
        if self.config.log_events:
            log.warning("Boundary violation: %s (severity=%.2f) — %s",
                       violation.violation_type.value, violation.severity,
                       violation.description)

        if violation.severity >= self.config.immediate_termination_threshold:
            return self._terminate(context, reason=violation.description)

        if self.state == BoundaryState.WARNED and self.warnings_issued >= self.config.max_warnings:
            return self._terminate(context, reason=f"Repeated violation after {self.warnings_issued} warning(s)")

        if self.config.warn_before_terminate:
            return self._warn(context, violation=violation)

        return self._terminate(context, reason=violation.description)

    def _warn(self, context: SkillContext, violation: BoundaryEvent = None) -> SkillResponse:
        """Issue a warning."""
        self.state = BoundaryState.WARNED
        self.warnings_issued += 1

        if self.intimate_mode:
            message = self.config.intimate_warning_message
        else:
            message = self.config.warning_message

        if violation:
            violation.action_taken = "warning"

        return SkillResponse(
            content=message,
            success=True,
            data={
                "state": self.state.value,
                "warnings_issued": self.warnings_issued,
                "violation_type": violation.violation_type.value if violation else None,
                "action": "warning",
            },
        )

    def _terminate(self, context: SkillContext, reason: str = "") -> SkillResponse:
        """Terminate the conversation."""
        self.state = BoundaryState.TERMINATED

        if self.intimate_mode:
            message = self.config.intimate_termination_message
        else:
            message = self.config.termination_message

        log.info("Conversation terminated: %s (session=%s, user=%s)",
                reason, context.session_id, context.user_id)

        if self._termination_callback:
            try:
                self._termination_callback(context, reason, self.events)
            except Exception as e:
                log.error("Termination callback failed: %s", e)

        return SkillResponse(
            content=message,
            success=True,
            data={
                "state": self.state.value,
                "action": "terminated",
                "reason": reason,
                "total_violations": len(self.events),
                "warnings_issued": self.warnings_issued,
            },
        )

    def get_event_summary(self) -> dict[str, Any]:
        """Get a summary of boundary events for this session."""
        return {
            "state": self.state.value,
            "total_events": len(self.events),
            "warnings_issued": self.warnings_issued,
            "violation_types": [e.violation_type.value for e in self.events],
            "max_severity": max((e.severity for e in self.events), default=0.0),
            "events": [
                {
                    "timestamp": e.timestamp.isoformat(),
                    "type": e.violation_type.value,
                    "severity": e.severity,
                    "description": e.description,
                    "action": e.action_taken,
                }
                for e in self.events
            ],
        }
