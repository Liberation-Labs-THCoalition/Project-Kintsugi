"""Skill Chip: Donor Stewardship

Domain: FUNDRAISING
Spans: crm_api, email_service, gift_tracking
EFE Profile: risk=0.3, ambiguity=0.3, epistemic=0.4
Description: Manages donor relationships, acknowledgments, cultivation planning, and giving analysis.

Donor Stewardship Skill Chip for Kintsugi CMA.

Manages donor relationships including acknowledgments, cultivation planning,
giving history analysis, and stewardship reporting. Prioritizes stakeholder
benefit and transparency in all donor interactions.

Example:
    chip = DonorStewardshipChip()
    request = SkillRequest(
        intent="donor_thank",
        entities={"donor_id": "donor_001", "gift_amount": 1000},
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
class DonorProfile:
    """Represents a donor's profile and preferences."""
    donor_id: str
    name: str
    email: str
    phone: str | None = None
    donor_level: str = "friend"  # friend, supporter, patron, benefactor, champion
    first_gift_date: datetime | None = None
    total_lifetime_giving: float = 0.0
    communication_preference: str = "email"  # email, mail, phone
    interests: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class Gift:
    """Represents a donation/gift."""
    gift_id: str
    donor_id: str
    amount: float
    gift_date: datetime
    gift_type: str  # one_time, recurring, in_kind, planned
    campaign: str | None = None
    designation: str = "unrestricted"
    acknowledged: bool = False
    acknowledgment_date: datetime | None = None


@dataclass
class CultivationActivity:
    """Represents a donor cultivation activity."""
    activity_id: str
    donor_id: str
    activity_type: str  # call, meeting, email, event, tour
    scheduled_date: datetime
    completed: bool = False
    notes: str = ""
    outcome: str | None = None


class DonorStewardshipChip(BaseSkillChip):
    """Manage donor relationships, acknowledgments, and cultivation.

    This chip supports fundraising staff in building and maintaining
    donor relationships through timely acknowledgments, strategic
    cultivation, giving analysis, and personalized stewardship.

    Intents:
        donor_thank: Generate thank you acknowledgment
        donor_profile: Retrieve or update donor profile
        giving_history: Analyze donor giving history
        cultivation_plan: Create cultivation plan
        stewardship_report: Generate stewardship report

    Example:
        >>> chip = DonorStewardshipChip()
        >>> request = SkillRequest(intent="donor_profile", entities={"donor_id": "donor_001"})
        >>> response = await chip.handle(request, context)
        >>> print(response.data["profile"]["donor_level"])
    """

    name = "donor_stewardship"
    description = "Manage donor relationships, acknowledgments, and cultivation"
    version = "1.0.0"
    domain = SkillDomain.FUNDRAISING

    efe_weights = EFEWeights(
        mission_alignment=0.20,
        stakeholder_benefit=0.35,
        resource_efficiency=0.15,
        transparency=0.20,
        equity=0.10,
    )

    capabilities = [
        SkillCapability.READ_DATA,
        SkillCapability.WRITE_DATA,
        SkillCapability.SEND_NOTIFICATIONS,
        SkillCapability.PII_ACCESS,
    ]

    consensus_actions = ["send_acknowledgment", "update_donor_level", "share_donor_data"]
    # Consensus: which intents ask for which action, held before handle() runs (kintsugi/governance/consumer.py).
    consensus_intents = {}
    consensus_unreachable = {
        "send_acknowledgment": (
            "advisory: donor_thank returns a drafted acknowledgment; its flag says this needs approval, and no "
            "intent performs it"
        ),
        "update_donor_level": "no intent performs this yet: declared for a future one, so it can't happen ungated",
        "share_donor_data": "no intent performs this yet: declared for a future one, so it can't happen ungated",
    }

    required_spans = ["crm_api", "email_service", "gift_tracking"]
    # Honest without its spans (kintsugi/skills/honesty.py): no donor, gift, figure or analysis is invented. A thank-you
    # is a draft built from what it was given, with [bracketed] gaps for the rest; it never asserts a tax fact it
    # wasn't told, and it isn't sent. Profiles, giving analysis and reports say no donor database is connected.
    simulated = False
    NO_CRM = not_connected("A donor database", "{}")

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
            "donor_thank": self._generate_thank_you,
            "donor_profile": self._get_donor_profile,
            "giving_history": self._analyze_giving,
            "cultivation_plan": self._create_cultivation_plan,
            "stewardship_report": self._generate_stewardship_report,
        }

        handler = handlers.get(intent)
        if not handler:
            return SkillResponse(
                content=f"Unknown intent '{intent}' for donor stewardship.",
                success=False,
                suggestions=[
                    "Try 'donor_thank' to generate acknowledgment",
                    "Try 'donor_profile' to view donor information",
                    "Try 'cultivation_plan' to plan donor engagement",
                ],
            )

        return await handler(request, context, bdi)

    async def get_bdi_context(
        self,
        beliefs: list[dict[str, Any]],
        desires: list[dict[str, Any]],
        intentions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Filter BDI state for donor stewardship context.

        Extracts beliefs about donor relationships, giving patterns,
        and cultivation priorities.
        """
        fundraising_beliefs = [
            b for b in beliefs
            if b.get("domain") in ("fundraising", "donors", "giving")
            or b.get("type") in ("donor_relationship", "giving_capacity", "cultivation_stage")
        ]

        stewardship_desires = [
            d for d in desires
            if d.get("type") in ("increase_retention", "upgrade_donors", "build_relationships")
            or d.get("domain") == "fundraising"
        ]

        return {
            "beliefs": fundraising_beliefs,
            "desires": stewardship_desires,
            "intentions": intentions,
        }

    async def _generate_thank_you(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """Generate personalized thank you acknowledgment.

        Creates tax-deductible receipt and personalized thank you message
        based on gift amount and donor history.
        """
        donor_id = request.entities.get("donor_id", "")
        gift_amount = request.entities.get("gift_amount", 0)
        gift_type = request.entities.get("gift_type", "one_time")
        designation = request.entities.get("designation", "unrestricted")
        include_impact = request.entities.get("include_impact", True)

        donor_name = request.entities.get("donor_name") or "[Donor name]"
        org_name = request.entities.get("org_name") or "[Organization name]"
        # Goods or services given in return: only what we're told. Unknown is a gap to fill, never "none".
        returned_value = request.entities.get("goods_or_services_value")

        if gift_amount >= 10000:
            tier, signatory = "champion", "Board Chair"
        elif gift_amount >= 5000:
            tier, signatory = "benefactor", "Executive Director"
        elif gift_amount >= 1000:
            tier, signatory = "patron", "Development Director"
        else:
            tier, signatory = "supporter", "Development Team"

        if returned_value is None:
            statement = ("[State whether any goods or services were given in return for this gift and, if so, a "
                         "good-faith estimate of their value.]")
            deductible = None
        elif returned_value == 0:
            statement = f"No goods or services were provided in exchange for this gift of ${gift_amount:,.2f}."
            deductible = gift_amount
        else:
            statement = (f"In return for this gift of ${gift_amount:,.2f}, goods or services worth about "
                         f"${returned_value:,.2f} were provided.")
            deductible = max(0, gift_amount - returned_value)

        acknowledgment = {
            "donor_id": donor_id,
            "gift_amount": gift_amount,
            "gift_type": gift_type,
            "designation": designation,
            "tier": tier,
            "tax_deductible_amount": deductible,
            "receipt": {
                "organization_name": org_name,
                "ein": "[EIN]",
                "address": "[Organization address]",
                "statement": statement,
            },
            "letter": {
                "salutation": f"Dear {donor_name},",
                "opening": f"Thank you for your generous gift of ${gift_amount:,.2f} to support our mission.",
                "impact_statement": ("[One specific result of your work this gift supports, in your own numbers.]"
                                     if include_impact else None),
                "closing": "With gratitude,",
                "signatory": signatory,
            },
            "sent": False,
        }

        note = (" For a gift of $250 or more, US tax rules require the receipt to say whether goods or services "
                "were given in return." if gift_amount >= 250 else "")
        requires_approval = self.requires_consensus("send_acknowledgment")
        return SkillResponse(
            content=(f"Drafted a {tier}-level thank-you for a ${gift_amount:,.2f} gift. Not sent: fill the "
                     f"[bracketed] parts and review it first.{note}"),
            success=True,
            data={"acknowledgment": acknowledgment},
            requires_consensus=requires_approval,
            consensus_action="send_acknowledgment" if requires_approval else None,
            suggestions=["Draft a cultivation plan for this donor"],
        )

    async def _get_donor_profile(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """Retrieve or update donor profile information.

        Returns comprehensive donor profile including giving history,
        engagement, and preferences.
        """
        donor_id = request.entities.get("donor_id", "")
        update_fields = request.entities.get("update", {})

        return SkillResponse(
            content=self.NO_CRM.format(f"I can't look up {donor_id or 'that donor'}'s profile or gifts"),
            success=True,
            data={"profile": None, "connected": False},
            suggestions=["Draft a thank-you letter"],
        )

    async def _analyze_giving(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """Analyze donor giving patterns and trends.

        Provides insights into giving behavior, retention, and upgrade
        potential.
        """
        donor_id = request.entities.get("donor_id", "")
        analysis_type = request.entities.get("analysis_type", "comprehensive")
        time_period = request.entities.get("period", "all_time")

        return SkillResponse(
            content=self.NO_CRM.format(f"I have no gifts to analyse for {donor_id or 'that donor'}"),
            success=True,
            data={"giving_analysis": None, "connected": False},
            suggestions=["Draft a cultivation plan for this donor"],
        )

    async def _create_cultivation_plan(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """Create donor cultivation plan.

        Develops strategic plan for donor engagement and solicitation.
        """
        donor_id = request.entities.get("donor_id", "")
        goal = request.entities.get("goal", "major_gift")
        target_amount = request.entities.get("target_amount", 5000)
        timeline_months = request.entities.get("timeline_months", 6)

        now = datetime.now(timezone.utc)

        # Build cultivation activities
        activities = [
            CultivationActivity(
                activity_id=f"act_{uuid4().hex[:8]}",
                donor_id=donor_id,
                activity_type="call",
                scheduled_date=now + timedelta(days=7),
                notes="Thank you call for recent gift, mention impact",
            ),
            CultivationActivity(
                activity_id=f"act_{uuid4().hex[:8]}",
                donor_id=donor_id,
                activity_type="email",
                scheduled_date=now + timedelta(days=30),
                notes="Share a program story that fits their interests",
            ),
            CultivationActivity(
                activity_id=f"act_{uuid4().hex[:8]}",
                donor_id=donor_id,
                activity_type="tour",
                scheduled_date=now + timedelta(days=60),
                notes="Site visit to see programs in action",
            ),
            CultivationActivity(
                activity_id=f"act_{uuid4().hex[:8]}",
                donor_id=donor_id,
                activity_type="event",
                scheduled_date=now + timedelta(days=90),
                notes="Invite to donor appreciation event",
            ),
            CultivationActivity(
                activity_id=f"act_{uuid4().hex[:8]}",
                donor_id=donor_id,
                activity_type="meeting",
                scheduled_date=now + timedelta(days=120),
                notes="Personal meeting with ED to discuss giving",
            ),
            CultivationActivity(
                activity_id=f"act_{uuid4().hex[:8]}",
                donor_id=donor_id,
                activity_type="call",
                scheduled_date=now + timedelta(days=150),
                notes=f"Solicitation call for ${target_amount:,.0f} gift",
            ),
        ]

        cultivation_plan = {
            "plan_id": f"cult_{uuid4().hex[:8]}",
            "donor_id": donor_id,
            "created_at": now.isoformat(),
            "goal": goal,
            "target_amount": target_amount,
            "timeline_months": timeline_months,
            "target_ask_date": (now + timedelta(days=timeline_months * 30)).isoformat(),
            "strategy": {
                "approach": "relationship-based cultivation",
                "key_messages": [
                    "Impact of their past support",
                    "[Their interests, from your records]",
                    "Opportunity for deeper engagement",
                ],
                "involvement_opportunities": [
                    "Program committee participation",
                    "Event hosting",
                    "Peer-to-peer fundraising",
                ],
            },
            "activities": [
                {
                    "activity_id": a.activity_id,
                    "type": a.activity_type,
                    "suggested_date": a.scheduled_date.isoformat(),
                    "notes": a.notes,
                    "completed": a.completed,
                }
                for a in activities
            ],
            "milestones": [
                {"milestone": "Initial thank you contact", "target_date": (now + timedelta(days=7)).isoformat()},
                {"milestone": "Engagement touchpoint", "target_date": (now + timedelta(days=30)).isoformat()},
                {"milestone": "In-person visit", "target_date": (now + timedelta(days=60)).isoformat()},
                {"milestone": "Solicitation meeting", "target_date": (now + timedelta(days=150)).isoformat()},
            ],
            "suggested_owner": "Development Director",
            "saved": False,
        }

        return SkillResponse(
            content=(f"Draft {timeline_months}-month cultivation plan toward a ${target_amount:,.0f} "
                     f"{goal.replace('_', ' ')}, with {len(activities)} suggested touchpoints. "
                     f"{not_connected('A calendar', 'nothing has been saved or scheduled')}"),
            success=True,
            data={"cultivation_plan": cultivation_plan},
            suggestions=["Would you like to adjust the timeline?"],
        )

    async def _generate_stewardship_report(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """Generate stewardship report for donors or leadership.

        Creates report on donor engagement, retention, and stewardship
        activities.
        """
        report_type = request.entities.get("report_type", "summary")
        period = request.entities.get("period", "quarterly")
        donor_segment = request.entities.get("segment", "all")

        return SkillResponse(
            content=self.NO_CRM.format(f"I have no donors or gifts to report on for the {period} {report_type}"),
            success=True,
            data={"stewardship_report": None, "connected": False},
            suggestions=[],
        )
