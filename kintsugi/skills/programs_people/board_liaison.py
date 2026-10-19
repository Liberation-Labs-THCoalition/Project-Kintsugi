"""Skill Chip: Board Liaison

Domain: GOVERNANCE
Spans: document_templates, calendar_api, voting_system
EFE Profile: risk=0.33, ambiguity=0.34, epistemic=0.33
Description: Supports board governance including meeting prep, minute drafting, and resolution tracking.

Board Liaison Skill Chip for Kintsugi CMA.

Supports board governance activities including meeting preparation, minute
drafting, resolution tracking, compliance monitoring, and board reporting.
Emphasizes transparency and accountability in all governance operations.

Example:
    chip = BoardLiaisonChip()
    request = SkillRequest(
        intent="meeting_prep",
        entities={"meeting_date": "2024-03-15", "meeting_type": "regular"},
    )
    response = await chip.handle(request, context)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any
from uuid import uuid4

from kintsugi.skills.honesty import not_connected
from kintsugi.skills import (
    BaseSkillChip,
    EFEWeights,
    SkillCapability,
    SkillContext,
    SkillDomain,
    SkillRequest,
    SkillResponse,
)


@dataclass
class BoardMeeting:
    """Represents a board meeting."""
    meeting_id: str
    meeting_type: str  # regular, special, annual, executive
    scheduled_date: datetime
    location: str
    virtual_link: str | None = None
    status: str = "scheduled"  # scheduled, in_progress, completed, cancelled
    quorum_required: int = 5
    agenda_items: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Resolution:
    """Represents a board resolution."""
    resolution_id: str
    title: str
    description: str
    status: str  # pending, approved, rejected, tabled
    meeting_id: str
    vote_count: dict[str, int] = field(default_factory=dict)  # for, against, abstain
    effective_date: datetime | None = None
    responsible_party: str = ""


@dataclass
class ComplianceItem:
    """Represents a compliance requirement."""
    item_id: str
    requirement: str
    category: str  # legal, regulatory, fiduciary, policy
    due_date: datetime
    status: str  # compliant, pending, overdue, not_applicable
    responsible_party: str
    documentation: list[str] = field(default_factory=list)


class BoardLiaisonChip(BaseSkillChip):
    """Support board governance, meeting preparation, and resolution tracking.

    This chip assists staff and board members with governance activities
    including preparing meeting packets, drafting minutes, tracking
    resolutions, monitoring compliance, and generating board reports.

    Intents:
        meeting_prep: Prepare meeting agenda and materials
        minutes_draft: Draft meeting minutes
        resolution_track: Track resolution status and implementation
        compliance_check: Check compliance requirements
        board_report: Generate board reports

    Example:
        >>> chip = BoardLiaisonChip()
        >>> request = SkillRequest(intent="meeting_prep", entities={"meeting_type": "regular"})
        >>> response = await chip.handle(request, context)
        >>> print(response.data["meeting_packet"]["agenda_items"])
    """

    name = "board_liaison"
    description = "Support board governance, meeting preparation, and resolution tracking"
    version = "1.0.0"
    domain = SkillDomain.GOVERNANCE

    efe_weights = EFEWeights(
        mission_alignment=0.25,
        stakeholder_benefit=0.20,
        resource_efficiency=0.15,
        transparency=0.30,
        equity=0.10,
    )

    capabilities = [
        SkillCapability.READ_DATA,
        SkillCapability.WRITE_DATA,
        SkillCapability.SCHEDULE_TASKS,
        SkillCapability.GENERATE_REPORTS,
    ]

    consensus_actions = ["distribute_materials", "record_resolution", "update_bylaws"]
    # Consensus: which intents ask for which action, held before handle() runs (kintsugi/governance/consumer.py).
    consensus_intents = {"resolution_track": "record_resolution"}
    # Who approves (Vera, 10-18): money and private info take two people (FINANCIAL, PII); the rest one.
    consensus_categories = {"record_resolution": "GENERAL"}
    consensus_no_step = {"record_resolution": "resolutions aren't stored anywhere yet"}
    consensus_when = {
        "resolution_track": lambda r: r.entities.get("action") == "create",
    }
    consensus_unreachable = {
        "distribute_materials": (
            "advisory: meeting_prep returns a meeting packet; its flag says this needs approval, and no intent "
            "performs it"
        ),
        "update_bylaws": "no intent performs this yet: declared for a future one, so it can't happen ungated",
    }

    required_spans = ["document_templates", "calendar_api", "voting_system"]
    # Honest without its spans (kintsugi/skills/honesty.py): agendas, minutes and reports are drafts built from what
    # they're given, with [bracketed] gaps for the rest. No attendee, motion, vote, filing status or figure is
    # invented, and nothing is stored or distributed.
    simulated = False

    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Route request to appropriate handler based on intent.

        Args:
            request: Skill request with intent and entities
            context: Execution context with org, user, BDI state

        Returns:
            SkillResponse with result content and data
        """
        intent = request.intent

        bdi = await self.get_bdi_context(
            context.beliefs,
            context.desires,
            context.intentions,
        )

        handlers = {
            "meeting_prep": self._prepare_meeting_packet,
            "minutes_draft": self._draft_minutes,
            "resolution_track": self._track_resolutions,
            "compliance_check": self._check_compliance,
            "board_report": self._generate_board_report,
        }

        handler = handlers.get(intent)
        if not handler:
            return SkillResponse(
                content=f"Unknown intent '{intent}' for board liaison.",
                success=False,
                suggestions=[
                    "Try 'meeting_prep' to prepare meeting materials",
                    "Try 'minutes_draft' to draft meeting minutes",
                    "Try 'resolution_track' to track board resolutions",
                ],
            )

        return await handler(request, context, bdi)

    async def get_bdi_context(
        self,
        beliefs: list[dict[str, Any]],
        desires: list[dict[str, Any]],
        intentions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Filter BDI state for governance context.

        Extracts beliefs about board status, compliance, and governance
        priorities relevant to this chip.
        """
        governance_beliefs = [
            b for b in beliefs
            if b.get("domain") in ("governance", "compliance", "board")
            or b.get("type") in ("board_status", "compliance_status", "resolution_pending")
        ]

        governance_desires = [
            d for d in desires
            if d.get("type") in ("improve_governance", "maintain_compliance", "board_effectiveness")
            or d.get("domain") == "governance"
        ]

        return {
            "beliefs": governance_beliefs,
            "desires": governance_desires,
            "intentions": intentions,
        }

    async def _prepare_meeting_packet(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """Prepare board meeting agenda and materials packet.

        Creates comprehensive meeting packet including agenda, prior minutes,
        committee reports, and action items.
        """
        meeting_date = request.entities.get("meeting_date", datetime.now(timezone.utc).isoformat())
        meeting_type = request.entities.get("meeting_type", "regular")
        include_financials = request.entities.get("include_financials", True)

        meeting = BoardMeeting(
            meeting_id=f"mtg_{uuid4().hex[:8]}",
            meeting_type=meeting_type,
            scheduled_date=datetime.fromisoformat(meeting_date) if isinstance(meeting_date, str) else meeting_date,
            location=request.entities.get("location") or "[Location]",
            virtual_link=request.entities.get("virtual_link"),
            quorum_required=request.entities.get("quorum") or 0,
        )

        # Build agenda based on meeting type
        agenda_items = [
            {
                "item_number": 1,
                "title": "Call to Order & Roll Call",
                "presenter": "Board Chair",
                "duration_minutes": 5,
                "type": "procedural",
            },
            {
                "item_number": 2,
                "title": "Approval of Prior Meeting Minutes",
                "presenter": "Board Secretary",
                "duration_minutes": 5,
                "type": "action",
                "attachments": ["[The prior meeting's minutes]"],
            },
        ]

        if include_financials:
            agenda_items.append({
                "item_number": 3,
                "title": "Financial Report",
                "presenter": "Treasurer",
                "duration_minutes": 15,
                "type": "report",
                "attachments": ["[Current financial statements]", "[Budget against actuals]"],
            })

        agenda_items.extend([
            {
                "item_number": 4,
                "title": "Executive Director Report",
                "presenter": "Executive Director",
                "duration_minutes": 15,
                "type": "report",
            },
            {
                "item_number": 5,
                "title": "Committee Reports",
                "presenter": "Committee Chairs",
                "duration_minutes": 20,
                "type": "report",
                "sub_items": ["Finance Committee", "Governance Committee", "Program Committee"],
            },
            {
                "item_number": 6,
                "title": "Old Business",
                "presenter": "Board Chair",
                "duration_minutes": 15,
                "type": "discussion",
                "items": ["[Open items from the prior minutes]"],
            },
            {
                "item_number": 7,
                "title": "New Business",
                "presenter": "Board Chair",
                "duration_minutes": 20,
                "type": "action",
            },
            {
                "item_number": 8,
                "title": "Adjournment",
                "presenter": "Board Chair",
                "duration_minutes": 2,
                "type": "procedural",
            },
        ])

        meeting.agenda_items = agenda_items

        packet = {
            "packet_id": f"pkt_{uuid4().hex[:8]}",
            "meeting": {
                "meeting_id": meeting.meeting_id,
                "type": meeting.meeting_type,
                "date": meeting.scheduled_date.isoformat(),
                "location": meeting.location,
                "virtual_link": meeting.virtual_link,
                "quorum_required": meeting.quorum_required,
            },
            "agenda_items": agenda_items,
            "to_gather": ["Prior meeting minutes", "Financial statements", "Executive Director's report"],
            "action_items_from_prior": None,       # no store of past meetings is connected
            "total_duration_minutes": sum(item["duration_minutes"] for item in agenda_items),
        }

        requires_approval = self.requires_consensus("distribute_materials")

        return SkillResponse(
            content=(f"Draft {meeting_type} board agenda for {meeting.scheduled_date.strftime('%B %d, %Y')}: "
                     f"{len(agenda_items)} items, about {packet['total_duration_minutes']} minutes. Fill the [bracketed] "
                     f"parts and gather the papers listed. Nothing has been distributed."),
            success=True,
            data={"meeting_packet": packet},
            requires_consensus=requires_approval,
            consensus_action="distribute_materials" if requires_approval else None,
            suggestions=[
                "Should I add any additional agenda items?",
                "Would you like to include a consent agenda?",
            ],
        )

    async def _draft_minutes(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """Draft meeting minutes from meeting notes.

        Creates formal minutes document with attendance, motions, votes,
        and action items.
        """
        meeting_id = request.entities.get("meeting_id", "")
        notes = request.entities.get("notes", "")
        attendees = request.entities.get("attendees", [])

        minutes = {
            "meeting_id": meeting_id,
            "status": "draft",
            "header": {
                "organization": context.org_id,
                "meeting_type": request.entities.get("meeting_type") or "[Meeting type]",
                "date": request.entities.get("date") or "[Date]",
                "location": request.entities.get("location") or "[Location]",
                "call_to_order": "[Time]",
                "adjournment": "[Time]",
            },
            "attendance": {
                "present": attendees or ["[Names of those present]"],
                "absent": ["[Names of those absent]"],
                "quorum_achieved": "[Yes or no]",
            },
            "notes_given": notes or None,
            "proceedings": [
                {"item": "Call to order", "notes": "[Who called the meeting to order, and when]"},
                {"item": "Approval of prior minutes",
                 "motion": "[Motion as stated]", "moved_by": "[Name]", "seconded_by": "[Name]",
                 "vote": "[For / against / abstain]", "result": "[Result]"},
                {"item": "Reports", "notes": "[What was reported, by whom]"},
                {"item": "Business", "notes": "[Each motion as stated, mover, seconder, vote and result]"},
            ],
            "action_items": ["[Action, who, by when]"],
        }

        return SkillResponse(
            content=("Draft minutes: a template with the attendees and notes you gave"
                     + (" filled in" if (attendees or notes) else "")
                     + ". Motions, votes and times are left as [bracketed] gaps for the secretary: none is invented. "
                       "Not circulated."),
            success=True,
            data={"minutes": minutes},
            suggestions=["Would you like to add any corrections?"],
        )

    async def _track_resolutions(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """Track board resolution status and implementation.

        Monitors resolution implementation, responsible parties, and deadlines.
        """
        resolution_id = request.entities.get("resolution_id", "")
        action = request.entities.get("action", "list")  # list, update, create
        status_filter = request.entities.get("status", None)

        # No voting_system or data store is wired yet: no resolution is listed, recorded or invented.
        requires_approval = self.requires_consensus("record_resolution") if action == "create" else False
        return SkillResponse(
            content=not_connected("A resolutions store", "I have no resolutions to list or update"),
            success=True,
            data={"resolutions": [], "connected": False},
            requires_consensus=requires_approval,
            consensus_action="record_resolution" if requires_approval else None,
            suggestions=[],
        )

    async def _check_compliance(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """Check governance compliance requirements and status.

        Reviews compliance with legal, regulatory, fiduciary, and policy
        requirements.
        """
        category = request.entities.get("category", None)
        include_overdue = request.entities.get("include_overdue", True)

        # No compliance tracker is wired yet: nothing is checked, so nothing is called compliant or overdue. A checklist
        # of common requirements, each "not checked", for the board to verify.
        checklist = [
            {"requirement": "Annual IRS Form 990 (most tax-exempt organizations)", "category": "legal"},
            {"requirement": "State charitable registration, where your state requires it", "category": "regulatory"},
            {"requirement": "Board conflict-of-interest disclosures", "category": "fiduciary"},
            {"requirement": "Directors and officers insurance", "category": "fiduciary"},
            {"requirement": "Bylaws review", "category": "policy"},
        ]
        if category:
            checklist = [c for c in checklist if c["category"] == category]
        for c in checklist:
            c["status"] = "not checked"
        return SkillResponse(
            content=(f"{not_connected('A compliance tracker', 'I have not checked any filing or deadline')} A checklist "
                     f"of {len(checklist)} common requirements, each still to be checked, with its due date in your "
                     f"own records."),
            success=True,
            data={"compliance_items": checklist, "connected": False},
            suggestions=[],
        )

    async def _generate_board_report(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """Generate comprehensive board report.

        Creates report including organizational health, financials, programs,
        and governance status.
        """
        report_period = request.entities.get("period", "quarterly")
        include_financials = request.entities.get("include_financials", True)
        include_programs = request.entities.get("include_programs", True)

        report = {
            "period": report_period,
            "executive_summary": "[Two or three sentences on the period, in your own figures]",
            "organizational_health": {"staff": "[Staffing changes]", "volunteers": "[Volunteer figures]",
                                      "partners": "[Partnerships]"},
            "governance_status": {"attendance": "[Board attendance]", "resolutions": "[Resolutions passed]",
                                  "compliance": "[Anything due or overdue]"},
            "risks_and_opportunities": "[Risks, with mitigations; opportunities, with next steps]",
        }
        if include_financials:
            report["financial_summary"] = {"revenue_ytd": "[From your books]", "expenses_ytd": "[From your books]",
                                           "reserve": "[Months of operating reserve]"}
        if include_programs:
            report["program_summary"] = {"programs": "[Active programs]", "results": "[Results, in your own numbers]"}

        return SkillResponse(
            content=(f"Draft {report_period} board report outline: organizational health, "
                     f"{'financials, ' if include_financials else ''}{'programs, ' if include_programs else ''}"
                     f"governance, and risks and opportunities. Every figure is a [bracketed] gap to fill from your own "
                     f"records: none is invented."),
            success=True,
            data={"board_report": report},
            suggestions=["Would you like to customize any sections?"],
        )
