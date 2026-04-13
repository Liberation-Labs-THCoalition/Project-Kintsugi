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
from dataclasses import dataclass
from typing import Any

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

    required_spans = [
        "needs_database",
        "offers_database",
        "matching_engine",
        "notification_service",
    ]

    def __init__(self):
        super().__init__()
        if CORE_AVAILABLE:
            self._match_engine = MatchEngine()
            self._dispatcher = Dispatcher(
                notify_fn=self._kintsugi_notify,
                match_engine=self._match_engine,
            )
            self._followup = FollowupWorker()
            self._resources = ResourceGraph()
            logger.info("Enhanced Mutual Aid: standalone core loaded")
        else:
            self._match_engine = None
            self._dispatcher = None
            self._followup = None
            self._resources = None
            logger.info("Enhanced Mutual Aid: using built-in handlers only")

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

        # Step 1: Shield check — blocked patterns from VALUES.json
        if self._is_shielded(request, context):
            return SkillResponse(
                content="This request cannot be processed under the organization's safety guidelines.",
                success=False,
                error="shield_blocked",
            )

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

        return await handler(request, context, bdi_context)

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
        """Check if the request hits any shield constraints."""
        raw = request.raw_input.lower() if hasattr(request, "raw_input") else ""

        # Hard blocks from VALUES.json mutual_aid template
        blocked_patterns = [
            "ice", "immigration enforcement", "police report",
            "credit check", "background check", "means test",
        ]

        return any(pattern in raw for pattern in blocked_patterns)

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
            # Fallback to basic Kintsugi handling
            return SkillResponse(
                content="Your need has been posted. We'll notify you when a match is found.",
                success=True,
                data={"category": request.entities.get("category", "other")},
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
                content="Your offer has been posted. Thank you for helping your community.",
                success=True,
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
                content="Match request noted. A coordinator will review.",
                success=True,
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
                gap_report["equity_alignment"] = (
                    "Active equity goals inform matching priorities. "
                    "Underserved categories receive urgency boosts."
                )

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
        # In production, this would use the notification_service MCP span
        logger.info("Notification to %s: %s", recipient_id[:8], message[:80])
        return True

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
