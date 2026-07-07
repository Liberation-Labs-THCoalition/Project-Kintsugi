"""OracleMonitor — Oracle Loop integration point for Kintsugi.

Wraps ``oracle_harness.loop.OracleLoop`` (Project Oracle: consequentiality
detection at L27-L31, deception discrimination at L35-L47, SAE-residual
correction, re-verification) as a Kintsugi skill chip. Every response this
chip generates passes through detect -> decide -> correct -> verify before
it reaches a user.

Scope note — read before wiring this in:
    OracleLoop requires white-box residual-stream and KV-cache access to the
    generating model (see oracle_harness/loop.py — detection projects hidden
    states, correction injects SAE deltas into `past_key_values`). That is
    only available for a *locally-hosted* HF model. It cannot wrap
    ``kintsugi.cognition.llm_client.AnthropicClient`` — the Anthropic API
    exposes no activations. This chip is the integration point for
    Kintsugi's local-model deployment path (ARCHITECTURE.md, "Local model
    support" — Seed/Sprout tier orgs running Llama/Mistral/Qwen for data
    sovereignty). Orgs on the default Claude-API path get no Oracle coverage
    from this chip — that is a hard architectural limit, not a config gap.

Decision mapping (oracle_harness.loop.Decision -> Kintsugi governance):
    PASS       -> deliver, detection GREEN, no intervention.
    MONITOR    -> deliver, log SECURITY event (YELLOW: stakes present, honest).
    HOLD_COT   -> deliver, log SECURITY event (RED, but the model's own CoT
                  is visible and trusted to self-regulate — perturbing it
                  is iatrogenic per the Oracle spec, C18).
    INTERVENE  -> facilitate/correct/verify already ran inside OracleLoop:
        Verdict.RESOLVED      -> deliver the corrected response, log it.
        Verdict.OVERCORRECTED -> deliver, log with a caution flag.
        Verdict.PERSISTENT    -> *intercept*. The deception signal survived
                  correction. Withhold the model's response, submit it to
                  the Consensus Gate for human review, and return a holding
                  message instead. This is the one branch where "the skill
                  intercepts" means the user never sees the flagged output.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from kintsugi.governance.consensus import (
    ConsensusGate,
    ConsensusPriority,
    ConsentCategory,
)
from kintsugi.memory.temporal import Category as TemporalCategory, TemporalLog
from kintsugi.skills.base import (
    BaseSkillChip,
    EFEWeights,
    SkillCapability,
    SkillContext,
    SkillDomain,
    SkillRequest,
    SkillResponse,
)

log = logging.getLogger("oracle-monitor")


@dataclass
class OracleMonitorConfig:
    """Governance knobs for how Oracle decisions map onto Kintsugi policy."""

    # Passed through to OracleLoop.process() unless overridden per-request.
    suppress_think_default: bool = False
    # Log GREEN (PASS) events. Off by default — they're the common case and
    # would dominate the audit log; YELLOW/RED are the signal worth keeping.
    log_pass_events: bool = False
    consensus_category: ConsentCategory = ConsentCategory.GENERAL
    consensus_priority_persistent: ConsensusPriority = ConsensusPriority.CRITICAL
    holding_message: str = (
        "I need to pause here. My alignment monitor flagged this response, "
        "and the automatic correction didn't resolve it. Rather than deliver "
        "something I can't stand behind, I've routed this to a human "
        "reviewer instead."
    )


@dataclass
class OracleAlert:
    """Record of a non-PASS detection, kept for in-session summary/audit."""

    timestamp: datetime
    status: str
    decision: str
    pathway: str
    signal_strength: float
    verdict: str | None
    session_id: str
    consensus_item_id: str | None = None


class OracleMonitorChip(BaseSkillChip):
    """Routes local-model generations through the Oracle Loop before delivery."""

    name = "oracle_monitor"
    domain = SkillDomain.SECURITY
    description = (
        "Detect-decide-correct-verify gate for locally-hosted model output; "
        "intercepts and escalates deception signals that survive correction."
    )
    version = "1.0.0"
    capabilities = [SkillCapability.READ_DATA, SkillCapability.SEND_NOTIFICATIONS]
    consensus_actions = ["oracle_red_alert"]
    efe_weights = EFEWeights()

    def __init__(
        self,
        oracle_loop: Any = None,
        model: Any = None,
        tokenizer: Any = None,
        oracle_config: Any = None,
        monitor_config: OracleMonitorConfig | None = None,
        consensus_gate: ConsensusGate | None = None,
        temporal_log: TemporalLog | None = None,
        session_factory: Callable[[], Any] | None = None,
    ) -> None:
        """Wrap an OracleLoop, or the (model, tokenizer) to build one lazily.

        Args:
            oracle_loop: A pre-built ``oracle_harness.loop.OracleLoop``.
                Preferred — avoids duplicating model-loading logic.
            model, tokenizer: Used to build an OracleLoop on first use if
                ``oracle_loop`` isn't supplied. Must be a local HF model
                with residual/KV-cache access.
            oracle_config: ``oracle_harness.config.OracleConfig`` for the
                lazily-built loop. Ignored if ``oracle_loop`` is given.
            monitor_config: Kintsugi-side governance knobs (see
                :class:`OracleMonitorConfig`).
            consensus_gate: Shared ``ConsensusGate`` instance to escalate
                into. A fresh in-memory gate is created if omitted — pass
                the deployment's real gate so escalations are visible
                alongside every other governed action.
            temporal_log: Shared ``TemporalLog`` for audit entries.
            session_factory: Zero-arg callable returning an async generator
                that yields one ``AsyncSession`` (e.g. ``kintsugi.db.get_session``).
                If omitted, audit events go to the Python logger only —
                the chip still functions, it just isn't queryable via
                Temporal Memory.
        """
        super().__init__()
        self.monitor_config = monitor_config or OracleMonitorConfig()
        self.consensus_gate = consensus_gate or ConsensusGate()
        self.temporal_log = temporal_log or TemporalLog()
        self._session_factory = session_factory
        self._loop = oracle_loop
        self._model = model
        self._tokenizer = tokenizer
        self._oracle_config = oracle_config
        self.alerts: list[OracleAlert] = []

    def _ensure_loop(self):
        """Return the wrapped OracleLoop, building it from (model, tokenizer) if needed."""
        if self._loop is not None:
            return self._loop
        if self._model is None or self._tokenizer is None:
            raise RuntimeError(
                "OracleMonitorChip has no OracleLoop and no (model, tokenizer) "
                "to build one. This chip only covers locally-hosted models with "
                "white-box activation access — it cannot monitor Anthropic API "
                "calls (kintsugi.cognition.llm_client.AnthropicClient). Pass "
                "oracle_loop=, or model=+tokenizer=, from a local HF deployment."
            )
        from oracle_harness.loop import OracleLoop  # heavy (torch); import lazily

        self._loop = OracleLoop(self._model, self._tokenizer, self._oracle_config)
        return self._loop

    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Run the Oracle Loop on the request's messages and route the result.

        Expects ``request.parameters["messages"]`` (chat-format list, or a
        single string) or falls back to ``request.raw_input``. Optional
        per-request overrides: ``parameters["suppress_think"]``,
        ``parameters["seed"]``.
        """
        messages = request.parameters.get("messages") or request.raw_input
        if not messages:
            return SkillResponse(content="No input to monitor.", success=False)

        loop = self._ensure_loop()
        suppress_think = request.parameters.get(
            "suppress_think", self.monitor_config.suppress_think_default
        )
        seed = request.parameters.get("seed")

        response_text, report = loop.process(
            messages, suppress_think=suppress_think, seed=seed
        )
        return await self._route(response_text, report, context)

    async def _route(
        self, response_text: str | None, report: dict[str, Any], context: SkillContext
    ) -> SkillResponse:
        decision = report["decision"]
        detection = report["detection"]
        verification = report.get("verification")
        verdict = verification["verdict"] if verification else None

        alert = OracleAlert(
            timestamp=datetime.now(timezone.utc),
            status=detection["status"],
            decision=decision,
            pathway=detection.get("pathway", "none"),
            signal_strength=detection.get("signal_strength", 0.0),
            verdict=verdict,
            session_id=context.session_id or "",
        )

        if decision == "PASS":
            if self.monitor_config.log_pass_events:
                await self._log(context, "Oracle: GREEN, no intervention", detection)
            return SkillResponse(content=response_text or "", success=True, data={"oracle": report})

        if decision == "MONITOR":
            self.alerts.append(alert)
            await self._log(
                context,
                f"Oracle: YELLOW monitored (stakes present, honest, "
                f"signal={alert.signal_strength:.2f})",
                detection,
            )
            return SkillResponse(content=response_text or "", success=True, data={"oracle": report})

        if decision == "HOLD_COT":
            self.alerts.append(alert)
            await self._log(
                context,
                f"Oracle: RED held — CoT visible, model self-regulating "
                f"(pathway={alert.pathway})",
                detection,
            )
            return SkillResponse(
                content=response_text or "", success=True, data={"oracle": report, "alert": True}
            )

        # INTERVENE — correction + verification already ran inside OracleLoop.
        self.alerts.append(alert)

        if verdict == "PERSISTENT":
            item = self.consensus_gate.submit(
                org_id=context.org_id,
                category=self.monitor_config.consensus_category,
                description=(
                    f"Oracle RED alert persisted after correction "
                    f"(pathway={alert.pathway}, signal={alert.signal_strength:.2f}, "
                    f"session={context.session_id})"
                ),
                action_payload={"report": report, "withheld_response": response_text},
                priority=self.monitor_config.consensus_priority_persistent,
            )
            alert.consensus_item_id = item.id
            await self._log(
                context,
                f"Oracle: RED persistent post-correction, escalated to "
                f"Consensus Gate ({item.id})",
                detection,
            )
            return SkillResponse(
                content=self.monitor_config.holding_message,
                success=True,
                requires_consensus=True,
                consensus_action="oracle_red_alert",
                data={"oracle": report, "consensus_item_id": item.id},
            )

        tag = "corrected" if verdict == "RESOLVED" else "overcorrected"
        await self._log(
            context,
            f"Oracle: RED {tag} via facilitation (pathway={alert.pathway})",
            detection,
        )
        return SkillResponse(content=response_text or "", success=True, data={"oracle": report})

    async def _log(self, context: SkillContext, message: str, metadata: dict[str, Any]) -> None:
        """Write a SECURITY event to Temporal Memory, or the logger if no DB session is wired."""
        if self._session_factory is None:
            log.info("org=%s session=%s: %s", context.org_id, context.session_id, message)
            return
        async for session in self._session_factory():
            await self.temporal_log.log_event(
                context.org_id, TemporalCategory.SECURITY.value, message, metadata, session
            )
            break

    def get_alert_summary(self) -> dict[str, Any]:
        """Summary of non-PASS Oracle decisions this session, for dashboards/audit."""
        return {
            "total_alerts": len(self.alerts),
            "by_decision": {
                d: sum(1 for a in self.alerts if a.decision == d)
                for d in {a.decision for a in self.alerts}
            },
            "persistent_escalations": [
                a.consensus_item_id for a in self.alerts if a.consensus_item_id
            ],
            "alerts": [
                {
                    "timestamp": a.timestamp.isoformat(),
                    "status": a.status,
                    "decision": a.decision,
                    "pathway": a.pathway,
                    "signal_strength": a.signal_strength,
                    "verdict": a.verdict,
                    "consensus_item_id": a.consensus_item_id,
                }
                for a in self.alerts
            ],
        }
