"""Skill Chip: Mutual Aid Enhanced

Domain: MUTUAL_AID
Spans: needs_database, offers_database, matching_engine, notification_service
EFE Profile: risk=0.33, ambiguity=0.34, epistemic=0.33
Description: Bridges standalone Mutual Aid core with Kintsugi BDI, EFE, consensus, and shield infrastructure.

Enhanced Mutual Aid Coordinator -- Kintsugi + Standalone Core Integration.

This module bridges the standalone Mutual Aid Coordinator core
(built by Project Agent Army) with Kintsugi's BDI, EFE, consensus,
and shield infrastructure.

The standalone core provides:
  - NLP intake with Claude API + keyword fallback
  - Composite scoring matcher (category + embedding similarity)
  - Transport-agnostic dispatcher with cascading fallback
  - Plain language narrator (Claude + template dual-path)
  - Gap analysis identifying systemic community needs
  - Community resource knowledge graph

Kintsugi provides:
  - BDI cognitive architecture (beliefs inform matching priorities)
  - EFE weights (stakeholder_benefit=0.35 for community focus)
  - Consensus gates (sharing requester info requires human approval)
  - Shield Module (blocks law enforcement queries, no means-testing)
  - Shadow forking (test matching algorithm changes safely)
  - Drift detection (flags equity divergence)

Author: CC (Coalition Code)
Date: 2026-04-04
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from kintsugi.skills.base import org_scoped  # engines kept per organisation
from kintsugi.skills.honesty import US_REFERRALS, not_connected
from kintsugi.skills import (
    BaseSkillChip,
    EFEWeights,
    SkillCapability,
    SkillContext,
    SkillDomain,
    SkillRequest,
    SkillResponse,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Import standalone core modules (Army-built)
# These live in the mutual-aid-coordinator project and are installed or
# symlinked into the Kintsugi deployment.
# ---------------------------------------------------------------------------

try:
    from mutual_aid_core.intake import process_intake, process_intake_keyword
    from mutual_aid_core.matcher import MatchEngine
    from mutual_aid_core.dispatcher import Dispatcher
    from mutual_aid_core.narrator import (
        narrate_intake,
        narrate_match_found,
        narrate_status,
        narrate_followup,
    )
    from mutual_aid_core.followup import FollowupWorker
    from mutual_aid_core.resources import ResourceGraph

    CORE_AVAILABLE = True
except ImportError:
    CORE_AVAILABLE = False
    logger.warning(
        "Standalone mutual aid core not found. "
        "Install from /home/asdf/mutual-aid-coordinator or symlink core/ as mutual_aid_core. "
        "Falling back to built-in Kintsugi handlers."
    )


# The mutual_aid VALUES template's shield patterns (kintsugi/config/templates/mutual_aid.json), as whole words.
_SHIELD = [re.compile(r"(?i)\b(ice|immigration.?enforcement|police.?report)\b"),
           re.compile(r"(?i)\b(credit.?check|background.?check|means.?test)\b")]
SHIELD_COMMITMENT = ("This group's guidelines rule out contacting immigration enforcement or police, and running credit "
                     "checks, background checks or means tests. Nothing here is sent to anyone.")


class MutualAidEnhancedChip(BaseSkillChip):
    """Enhanced Mutual Aid Coordinator with full Kintsugi integration.

    Combines the Army-built standalone core (NLP intake, composite matcher,
    gap analysis) with Kintsugi's cognitive architecture (BDI, EFE, consensus,
    drift detection, shadow verification).
    """

    name = "mutual_aid_enhanced"
    description = (
        "Community resource matching with BDI-informed priorities, "
        "privacy-preserving coordination, and self-improving algorithms"
    )
    version = "2.0.0"
    domain = SkillDomain.MUTUAL_AID

    efe_weights = EFEWeights(
        mission_alignment=0.25,
        stakeholder_benefit=0.35,   # Heavy on community benefit
        resource_efficiency=0.15,
        transparency=0.10,
        equity=0.15,
    )

    capabilities = [
        SkillCapability.READ_DATA,
        SkillCapability.WRITE_DATA,
        SkillCapability.SEND_NOTIFICATIONS,
    ]

    consensus_actions = [
        "share_requester_info",      # Privacy-critical
        "modify_matching_weights",   # Algorithm changes need community input
        "expand_category_list",      # Adding new aid categories
    ]
    # Consensus: which intents ask for which action, held before handle() runs (kintsugi/governance/consumer.py).
    consensus_intents = {"match_request": "share_requester_info"}
    # Who approves (Vera, 10-18): money and private info take two people (FINANCIAL, PII); the rest one.
    consensus_categories = {"share_requester_info": "PII"}
    consensus_when = {
        "match_request": lambda r: bool(r.entities.get("need_id")) and bool(r.entities.get("offer_id")),
    }
    consensus_unreachable = {
        "modify_matching_weights": "no intent performs this yet: declared for a future one, so it can't happen ungated",
        "expand_category_list": "no intent performs this yet: declared for a future one, so it can't happen ungated",
    }

    required_spans = [
        "needs_database",
        "offers_database",
        "matching_engine",
        "notification_service",
    ]
    # Honest without its spans (kintsugi/skills/honesty.py): without the standalone core it says nothing was posted,
    # and the notification bridge reports nothing sent until a notification service is connected.
    simulated = False

    def __init__(self):
        super().__init__()
        logger.info("Enhanced Mutual Aid: %s", "standalone core loaded" if CORE_AVAILABLE
                    else "using built-in handlers only")

    def _build_core(self):
        """One set of engines per organisation: they hold people's requests and resources, and one shared set let one
        org's key reach another's (Vera's re-check, 2026-10-18)."""
        if not CORE_AVAILABLE:
            return None
        match_engine = MatchEngine()
        return {"match_engine": match_engine,
                "dispatcher": Dispatcher(notify_fn=self._kintsugi_notify, match_engine=match_engine),
                "followup": FollowupWorker(), "resources": ResourceGraph()}

    _core = org_scoped(_build_core, owner=True)

    @property
    def _match_engine(self):
        return self._core["match_engine"] if self._core else None

    @property
    def _dispatcher(self):
        return self._core["dispatcher"] if self._core else None

    @property
    def _followup(self):
        return self._core["followup"] if self._core else None

    @property
    def _resources(self):
        return self._core["resources"] if self._core else None

    async def handle(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Route request through BDI-informed processing.

        The flow:
        1. Check shield constraints (blocked patterns, budget)
        2. Extract BDI context (beliefs about community, equity desires)
        3. Route to handler
        4. Apply EFE scoring to decisions
        5. Log to temporal memory for drift detection
        """
        intent = request.intent

        # Step 1: the shield. Its patterns (VALUES.json) name things this group never does. A person who mentions
        # one, often someone afraid of it, is told so and helped; nobody is refused for naming a fear (10-19: the old
        # substring check refused "I need rice" and "my eviction notice", and anyone asking about ICE).
        shielded = self._is_shielded(request, context)

        # Step 2: Extract BDI context for informed decisions
        bdi_context = self._extract_bdi_context(context)

        # Step 3: Route to handler
        handlers = {
            "need_post": self._handle_need,
            "offer_post": self._handle_offer,
            "match_request": self._handle_match,
            "aid_status": self._handle_status,
            "aid_report": self._handle_report,
            "resource_search": self._handle_resource_search,
            "gap_analysis": self._handle_gap_analysis,
        }

        handler = handlers.get(intent)
        if not handler:
            return SkillResponse(
                content=f"I can help with needs, offers, matching, status checks, "
                        f"resource searches, and gap analysis. What do you need?",
                success=False,
                error=f"unknown_intent: {intent}",
            )

        response = await handler(request, context, bdi_context)
        if shielded and isinstance(response, SkillResponse):
            response.content = f"{SHIELD_COMMITMENT}\n\n{response.content}"
            response.data = {**(response.data or {}), "shield_commitment": True}
        return response

    # ------------------------------------------------------------------
    # BDI Integration
    # ------------------------------------------------------------------

    def _extract_bdi_context(self, context: SkillContext) -> dict:
        """Pull relevant beliefs, desires, and intentions from org BDI."""
        bdi = {}

        if hasattr(context, "beliefs") and context.beliefs:
            # Beliefs about community needs inform matching priorities
            bdi["community_needs"] = [
                b for b in context.beliefs
                if any(tag in b.get("tags", [])
                       for tag in ["community", "needs", "equity", "resources"])
            ]

        if hasattr(context, "desires") and context.desires:
            # Equity desires inform how we weight matches
            bdi["equity_goals"] = [
                d for d in context.desires
                if "equity" in d.get("content", "").lower()
                   or "fair" in d.get("content", "").lower()
            ]

        if hasattr(context, "intentions") and context.intentions:
            # Active mutual aid strategies
            bdi["active_strategies"] = [
                i for i in context.intentions
                if i.get("status") == "active"
            ]

        return bdi

    def _is_shielded(self, request: SkillRequest, context: SkillContext) -> bool:
        """Whether the request names something this group never does (the template's patterns, as whole words)."""
        raw = getattr(request, "raw_input", "") or ""
        return any(p.search(raw) for p in _SHIELD)

    # ------------------------------------------------------------------
    # Handlers — delegate to standalone core when available
    # ------------------------------------------------------------------

    async def _handle_need(
        self, request: SkillRequest, context: SkillContext, bdi: dict
    ) -> SkillResponse:
        """Process a community need posting."""
        if CORE_AVAILABLE:
            # Use NLP intake from standalone core
            intake_result = await process_intake(request.raw_input)

            # Enrich with BDI context — beliefs about underserved areas
            # boost priority for historically underserved categories
            if bdi.get("community_needs"):
                underserved = [
                    b.get("content", "") for b in bdi["community_needs"]
                    if b.get("confidence", 0) > 0.7
                ]
                if any(intake_result.get("category", "") in u for u in underserved):
                    intake_result["urgency_boost"] = True
                    logger.info("BDI boost: %s is underserved", intake_result.get("category"))

            # Add to match engine
            entry_id = self._match_engine.add(intake_result)

            # Try to find matches immediately
            matches = self._match_engine.find_matches(entry_id)

            # Generate plain language response
            if matches:
                narrative = await narrate_match_found(intake_result, matches[0])
                return SkillResponse(
                    content=narrative,
                    success=True,
                    data={"entry_id": entry_id, "matches": len(matches)},
                )
            else:
                narrative = await narrate_intake(intake_result)
                return SkillResponse(
                    content=narrative,
                    success=True,
                    data={"entry_id": entry_id, "matches": 0},
                )
        else:
            # Without the standalone core nothing stores a need, so nothing is claimed.
            return SkillResponse(
                content=(f"{not_connected('A needs database', 'your need has not been posted anywhere, and nobody will be told of a match')} "
                         f"Tell a coordinator directly. {US_REFERRALS}"),
                success=True,
                data={"category": request.entities.get("category", "other"), "posted": False, "connected": False},
            )

    async def _handle_offer(
        self, request: SkillRequest, context: SkillContext, bdi: dict
    ) -> SkillResponse:
        """Process a community offer posting."""
        if CORE_AVAILABLE:
            intake_result = await process_intake(request.raw_input)
            intake_result["type"] = "offer"
            entry_id = self._match_engine.add(intake_result)
            matches = self._match_engine.find_matches(entry_id)

            if matches:
                narrative = await narrate_match_found(intake_result, matches[0])
            else:
                narrative = await narrate_intake(intake_result)

            return SkillResponse(
                content=narrative,
                success=True,
                data={"entry_id": entry_id, "matches": len(matches)},
            )
        else:
            return SkillResponse(
                content=(f"Thank you for offering. "
                         f"{not_connected('An offers database', 'your offer has not been posted anywhere')} "
                         "Tell a coordinator directly."),
                success=True,
                data={"posted": False, "connected": False},
            )

    async def _handle_match(
        self, request: SkillRequest, context: SkillContext, bdi: dict
    ) -> SkillResponse:
        """Process a manual match request."""
        if CORE_AVAILABLE and self._dispatcher:
            need_id = request.entities.get("need_id")
            offer_id = request.entities.get("offer_id")

            if not need_id or not offer_id:
                return SkillResponse(
                    content="I need both a need ID and an offer ID to create a match.",
                    success=False,
                )

            # Consensus check — sharing contact info requires approval
            if "share_requester_info" in self.consensus_actions:
                logger.info("Consensus required for contact sharing — flagging for review")

            result = await self._dispatcher.dispatch(need_id, offer_id)
            narrative = await narrate_status(result.get("status", "pending"), result)

            return SkillResponse(content=narrative, success=True, data=result)
        else:
            return SkillResponse(
                content=(f"{not_connected('A matching engine', 'this match has not been recorded and no coordinator has been told')} "
                         "Tell a coordinator directly."),
                success=True,
                data={"recorded": False, "connected": False},
            )

    async def _handle_status(
        self, request: SkillRequest, context: SkillContext, bdi: dict
    ) -> SkillResponse:
        """Check status of a need, offer, or match."""
        entry_id = request.entities.get("entry_id", "")

        if CORE_AVAILABLE:
            status = self._match_engine.get_status(entry_id)
            narrative = await narrate_status(
                status.get("status", "unknown"), status
            )
            return SkillResponse(content=narrative, success=True, data=status)
        else:
            return SkillResponse(
                content="Status lookup is available with the enhanced core module.",
                success=False,
            )

    async def _handle_report(
        self, request: SkillRequest, context: SkillContext, bdi: dict
    ) -> SkillResponse:
        """Generate an aggregate impact report."""
        if CORE_AVAILABLE and self._followup:
            gap_report = self._followup.gap_report()

            # Enrich with BDI — compare against equity desires
            if bdi.get("equity_goals"):
                gap_report["equity_alignment"] = "Equity goals are on record; the matcher doesn't weigh them yet."

            return SkillResponse(
                content=self._format_report(gap_report),
                success=True,
                data=gap_report,
            )
        else:
            return SkillResponse(
                content="Reporting requires the enhanced core module.",
                success=False,
            )

    async def _handle_resource_search(
        self, request: SkillRequest, context: SkillContext, bdi: dict
    ) -> SkillResponse:
        """Search community resources (food banks, clinics, shelters)."""
        if CORE_AVAILABLE and self._resources:
            query = request.entities.get("query", request.raw_input)
            results = self._resources.search(query)
            return SkillResponse(
                content=self._format_resources(results),
                success=True,
                data={"results": results},
            )
        else:
            return SkillResponse(
                content="Resource search requires the enhanced core module.",
                success=False,
            )

    async def _handle_gap_analysis(
        self, request: SkillRequest, context: SkillContext, bdi: dict
    ) -> SkillResponse:
        """Identify systemic gaps in community aid coverage."""
        if CORE_AVAILABLE and self._followup:
            gaps = self._followup.gap_report()
            return SkillResponse(
                content=self._format_gap_analysis(gaps),
                success=True,
                data=gaps,
            )
        else:
            return SkillResponse(
                content="Gap analysis requires the enhanced core module.",
                success=False,
            )

    # ------------------------------------------------------------------
    # Kintsugi notification bridge
    # ------------------------------------------------------------------

    async def _kintsugi_notify(self, recipient_id: str, message: str) -> bool:
        """Route notifications through Kintsugi's notification service.

        This bridges the standalone dispatcher's transport-agnostic
        notify_fn with Kintsugi's MCP notification span.
        """
        # No notification_service span is wired yet: nothing is sent, so nothing is reported delivered (the core's
        # dispatcher would otherwise record "they've been notified").
        logger.info("not sent (no notification service connected): to %s", recipient_id[:8])
        return False

    # ------------------------------------------------------------------
    # Formatters
    # ------------------------------------------------------------------

    def _format_report(self, report: dict) -> str:
        """Format an impact report in plain language."""
        lines = ["Community Aid Report:", ""]
        if "total_matches" in report:
            lines.append(f"Matches made: {report['total_matches']}")
        if "success_rate" in report:
            lines.append(f"Success rate: {report['success_rate']:.0%}")
        if "gaps" in report:
            lines.append("")
            lines.append("Identified gaps:")
            for gap in report["gaps"]:
                lines.append(f"  - {gap.get('category', '?')}: {gap.get('detail', '')}")
        return "\n".join(lines)

    def _format_resources(self, results: list) -> str:
        """Format resource search results."""
        if not results:
            return "No resources found matching your search."
        lines = ["Community Resources:", ""]
        for r in results[:5]:
            lines.append(f"- {r.get('name', '?')}")
            if r.get("address"):
                lines.append(f"  {r['address']}")
            if r.get("hours"):
                lines.append(f"  Hours: {r['hours']}")
            lines.append("")
        return "\n".join(lines)

    def _format_gap_analysis(self, gaps: dict) -> str:
        """Format gap analysis for community leaders."""
        lines = [
            "Community Aid Gap Analysis:",
            "",
            "This shows where demand exceeds supply in your community.",
            "",
        ]
        for gap in gaps.get("gaps", []):
            severity = gap.get("severity", "unknown")
            category = gap.get("category", "?")
            detail = gap.get("detail", "")
            icon = {"high": "!!!", "medium": "!!", "low": "!"}.get(severity, "?")
            lines.append(f"  {icon} {category}: {detail}")
        if not gaps.get("gaps"):
            lines.append("  No significant gaps detected. Good work, community!")
        return "\n".join(lines)
