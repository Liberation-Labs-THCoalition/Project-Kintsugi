"""Skill Chip: Member Services

Domain: MEMBER_SERVICES
Spans: membership_db, payment_processor, email_service
EFE Profile: risk=0.33, ambiguity=0.34, epistemic=0.33
Description: Manages membership tracking, renewals, benefits, and member communications.

Member Services Skill Chip for Kintsugi CMA.

Manages membership tracking, renewals, benefits, and communications.
Prioritizes stakeholder benefit while maintaining efficient membership
operations and transparent communications.

Example:
    chip = MemberServicesChip()
    request = SkillRequest(
        intent="member_lookup",
        entities={"member_id": "mem_001"},
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
class Member:
    """Represents a member record."""
    member_id: str
    name: str
    email: str
    phone: str | None = None
    membership_tier: str = "basic"  # basic, silver, gold, platinum
    status: str = "active"  # active, lapsed, pending, cancelled
    join_date: datetime | None = None
    expiration_date: datetime | None = None
    auto_renew: bool = False
    payment_method: str | None = None
    communication_preferences: dict[str, bool] = field(default_factory=dict)


@dataclass
class MembershipTier:
    """Represents a membership tier with benefits."""
    tier_id: str
    name: str
    annual_fee: float
    benefits: list[str]
    description: str


@dataclass
class MemberCommunication:
    """Represents a member communication record."""
    communication_id: str
    member_id: str
    communication_type: str  # email, mail, sms
    subject: str
    status: str  # sent, pending, failed
    sent_at: datetime | None = None


class MemberServicesChip(BaseSkillChip):
    """Manage membership tracking, renewals, benefits, and communications.

    This chip supports member services staff in managing the full
    membership lifecycle including lookups, renewals, benefits
    information, communications, and reporting.

    Intents:
        member_lookup: Look up member information
        membership_renew: Process membership renewal
        benefits_info: Provide membership benefits information
        member_communicate: Send member communications
        membership_report: Generate membership reports

    Example:
        >>> chip = MemberServicesChip()
        >>> request = SkillRequest(intent="member_lookup", entities={"member_id": "mem_001"})
        >>> response = await chip.handle(request, context)
        >>> print(response.data["member"]["membership_tier"])
    """

    name = "member_services"
    description = "Manage membership tracking, renewals, benefits, and communications"
    version = "1.0.0"
    domain = SkillDomain.MEMBER_SERVICES

    efe_weights = EFEWeights(
        mission_alignment=0.20,
        stakeholder_benefit=0.35,
        resource_efficiency=0.20,
        transparency=0.15,
        equity=0.10,
    )

    capabilities = [
        SkillCapability.READ_DATA,
        SkillCapability.WRITE_DATA,
        SkillCapability.SEND_NOTIFICATIONS,
        SkillCapability.PII_ACCESS,
    ]

    consensus_actions = ["change_membership_tier", "process_refund", "bulk_communication"]
    # Consensus: which intents ask for which action, held before handle() runs (kintsugi/governance/consumer.py).
    # A renewal charges the fee of whatever tier it names, without checking the member's current tier, so every renewal
    # can change the tier and charge for it (Vera, 10-18, item 4): held.
    consensus_intents = {"member_communicate": "bulk_communication", "membership_renew": "change_membership_tier"}
    # Who approves (Vera, 10-18): money and private info take two people (FINANCIAL, PII); the rest one.
    consensus_categories = {"bulk_communication": "EXTERNAL_COMMS", "change_membership_tier": "FINANCIAL"}
    consensus_no_step = {"bulk_communication": "nothing sends member messages",
                         "change_membership_tier": "no payment processor is connected, so nothing is charged"}
    consensus_when = {
        "member_communicate": lambda r: bool(r.entities.get("bulk", False)),
        # an unknown tier gets the chip's own refusal at once, not a wait for two approvers
        "membership_renew": "_asks_renewal",
    }
    consensus_unreachable = {
        "process_refund": "no intent performs this yet: declared for a future one, so it can't happen ungated",
    }

    required_spans = ["membership_db", "payment_processor", "email_service"]

    # Honesty (kintsugi/skills/honesty.py): no member, payment, message or report is invented. The tiers below are an
    # EXAMPLE catalogue, so the chip stays in Sample mode until a deployment passes its own:
    # MemberServicesChip(tiers={...}). Renewals take no payment (no payment processor is connected) and say so.
    def __init__(self, tiers: dict | None = None) -> None:
        super().__init__()
        if tiers is not None:
            self._tiers = dict(tiers)
            self.simulated = False            # the organization's own catalogue: nothing here is sample any more

    def _asks_renewal(self, request, context) -> bool:
        return request.entities.get("tier", "basic") in self._tiers

    # An example membership catalogue (not any organization's): replaced by MemberServicesChip(tiers=...).
    _tiers = {
        "basic": MembershipTier(
            tier_id="tier_basic",
            name="Basic",
            annual_fee=50.0,
            benefits=[
                "Monthly newsletter",
                "Discounted event tickets",
                "Member directory access",
            ],
            description="Entry-level membership with core benefits",
        ),
        "silver": MembershipTier(
            tier_id="tier_silver",
            name="Silver",
            annual_fee=100.0,
            benefits=[
                "All Basic benefits",
                "Quarterly member events",
                "Early event registration",
                "10% program discount",
            ],
            description="Enhanced membership with additional perks",
        ),
        "gold": MembershipTier(
            tier_id="tier_gold",
            name="Gold",
            annual_fee=250.0,
            benefits=[
                "All Silver benefits",
                "Free event tickets (2 per year)",
                "Annual recognition in publications",
                "Exclusive networking events",
                "20% program discount",
            ],
            description="Premium membership with exclusive access",
        ),
        "platinum": MembershipTier(
            tier_id="tier_platinum",
            name="Platinum",
            annual_fee=500.0,
            benefits=[
                "All Gold benefits",
                "VIP event access",
                "Board committee participation opportunity",
                "Personal concierge service",
                "Name on donor wall",
                "50% program discount",
            ],
            description="Top-tier membership with maximum benefits",
        ),
    }

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
            "member_lookup": self._lookup_member,
            "membership_renew": self._process_renewal,
            "benefits_info": self._get_benefits,
            "member_communicate": self._send_communication,
            "membership_report": self._generate_membership_report,
        }

        handler = handlers.get(intent)
        if not handler:
            return SkillResponse(
                content=f"Unknown intent '{intent}' for member services.",
                success=False,
                suggestions=[
                    "Try 'member_lookup' to find a member",
                    "Try 'membership_renew' to process renewal",
                    "Try 'benefits_info' for membership benefits",
                ],
            )

        return await handler(request, context, bdi)

    async def get_bdi_context(
        self,
        beliefs: list[dict[str, Any]],
        desires: list[dict[str, Any]],
        intentions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Filter BDI state for member services context.

        Extracts beliefs about membership, engagement, and retention
        priorities.
        """
        member_beliefs = [
            b for b in beliefs
            if b.get("domain") in ("membership", "community", "engagement")
            or b.get("type") in ("member_status", "retention_risk", "engagement_level")
        ]

        service_desires = [
            d for d in desires
            if d.get("type") in ("increase_retention", "grow_membership", "improve_satisfaction")
            or d.get("domain") == "member_services"
        ]

        return {
            "beliefs": member_beliefs,
            "desires": service_desires,
            "intentions": intentions,
        }

    async def _lookup_member(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """Look up member information and history.

        Returns comprehensive member profile with engagement history.
        """
        member_id = request.entities.get("member_id", "")
        email = request.entities.get("email", "")
        name = request.entities.get("name", "")

        # No membership_db span is wired yet: no member is looked up, and none is made up.
        who = member_id or email or name or "that member"
        return SkillResponse(
            content=not_connected("A member database", f"I can't look up {who}"),
            success=True,
            data={"member": None, "connected": False},
            suggestions=["Show membership tiers"],
        )

    async def _process_renewal(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """Process membership renewal or new membership.

        Handles payment processing and membership period extension.
        """
        member_id = request.entities.get("member_id", "")
        tier = request.entities.get("tier", "basic")
        payment_method = request.entities.get("payment_method", "credit_card")
        auto_renew = request.entities.get("auto_renew", False)
        is_new = request.entities.get("is_new", False)

        if tier not in self._tiers:
            return SkillResponse(
                content=f"Invalid membership tier '{tier}'. Available tiers: {', '.join(self._tiers.keys())}",
                success=False,
            )

        tier_info = self._tiers[tier]
        action_type = "New membership" if is_new else "Renewal"
        # No payment_processor or membership_db span is wired yet: nothing is charged and no membership changes. The
        # approved run asks again, so the consumer records "no step" (consensus_no_step) instead of a success.
        return SkillResponse(
            content=(f"{action_type} not processed: "
                     f"{not_connected('A payment processor', 'no payment was taken and the membership has not changed')} "
                     f"{tier_info.name} is ${tier_info.annual_fee:.2f} a year"
                     + (" (example tier: your organization's own tiers aren't configured)." if self.simulated else ".")),
            success=False,
            data={"renewal": {"member_id": member_id, "tier": tier, "processed": False, "charged": False,
                              "auto_renew_requested": auto_renew}},
            requires_consensus=True,
            consensus_action="change_membership_tier",
            suggestions=["Show membership tiers"],
        )

    async def _get_benefits(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """Provide membership benefits information.

        Returns detailed benefits comparison across tiers.
        """
        tier = request.entities.get("tier", None)
        compare = request.entities.get("compare", True)

        if tier and tier in self._tiers:
            # Return specific tier information
            tier_info = self._tiers[tier]
            benefits_data = {
                "requested_tier": tier,
                "tier_info": {
                    "name": tier_info.name,
                    "annual_fee": tier_info.annual_fee,
                    "benefits": tier_info.benefits,
                    "description": tier_info.description,
                },
            }

            # The next tier up by fee, whatever the organization calls its tiers (the example names were hard-coded)
            tier_order = sorted(self._tiers, key=lambda name: self._tiers[name].annual_fee)
            if tier_order.index(tier) + 1 < len(tier_order):
                next_tier = tier_order[tier_order.index(tier) + 1]
                next_tier_info = self._tiers[next_tier]

                benefits_data["upgrade_option"] = {
                    "next_tier": next_tier,
                    "additional_fee": next_tier_info.annual_fee - tier_info.annual_fee,
                    "additional_benefits": [
                        b for b in next_tier_info.benefits
                        if b not in tier_info.benefits and not b.startswith("All")
                    ],
                }

            return SkillResponse(
                content=f"{tier_info.name} membership: ${tier_info.annual_fee:.2f}/year with "
                        f"{len(tier_info.benefits)} benefits.",
                success=True,
                data={"benefits": benefits_data},
                suggestions=[
                    "Compare all tiers",
                ],
            )

        # Return comparison of all tiers
        comparison = {
            "tiers": [
                {
                    "tier_id": info.tier_id,
                    "name": info.name,
                    "annual_fee": info.annual_fee,
                    "benefits": info.benefits,
                    "description": info.description,
                    "value_highlight": self._get_value_highlight(name),
                }
                for name, info in self._tiers.items()
            ],
            "comparison_matrix": {
                "Newsletter": {"basic": True, "silver": True, "gold": True, "platinum": True},
                "Event discounts": {"basic": True, "silver": True, "gold": True, "platinum": True},
                "Member directory": {"basic": True, "silver": True, "gold": True, "platinum": True},
                "Quarterly events": {"basic": False, "silver": True, "gold": True, "platinum": True},
                "Early registration": {"basic": False, "silver": True, "gold": True, "platinum": True},
                "Program discounts": {"basic": "0%", "silver": "10%", "gold": "20%", "platinum": "50%"},
                "Free event tickets": {"basic": False, "silver": False, "gold": "2/year", "platinum": "Unlimited"},
                "VIP access": {"basic": False, "silver": False, "gold": False, "platinum": True},
                "Board participation": {"basic": False, "silver": False, "gold": False, "platinum": True},
            },
        }

        return SkillResponse(
            content=f"Membership benefits comparison across {len(self._tiers)} tiers.",
            success=True,
            data={"benefits_comparison": comparison},
            suggestions=[
                "Would you like details on a specific tier?",
            ],
        )

    def _get_value_highlight(self, tier_name: str) -> str:
        """Get value proposition highlight for a tier."""
        highlights = {
            "basic": "Entry level",
            "silver": "Adds member events and early registration",
            "gold": "Adds free tickets and recognition",
            "platinum": "Every benefit",
        }
        return highlights.get(tier_name, "")

    async def _send_communication(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """Send communication to member(s).

        Handles individual and bulk member communications.
        """
        member_id = request.entities.get("member_id", "")
        communication_type = request.entities.get("type", "email")
        subject = request.entities.get("subject", "")
        template = request.entities.get("template", "general")
        is_bulk = request.entities.get("bulk", False)
        segment = request.entities.get("segment", "all_active")

        now = datetime.now(timezone.utc)

        # Communication templates
        templates = {
            "renewal_reminder": {
                "subject": "Your Membership Renewal is Coming Up",
                "preview": "Your membership expires soon. Renew today to keep your benefits.",
            },
            "welcome": {
                "subject": "Welcome to Our Community!",
                "preview": "Thank you for joining. Here's everything you need to get started.",
            },
            "benefits_update": {
                "subject": "New Member Benefits Available",
                "preview": "We've added exciting new benefits to your membership.",
            },
            "event_invitation": {
                "subject": "You're Invited: Exclusive Member Event",
                "preview": "Join us for a special event just for members.",
            },
            "general": {
                "subject": subject or "Message from Our Organization",
                "preview": "Important information for our valued members.",
            },
        }

        selected_template = templates.get(template, templates["general"])

        if is_bulk:
            # No membership_db span: the segment's size isn't known, and nothing is sent (consensus_no_step).
            communication_data = {
                "type": "bulk",
                "communication_type": communication_type,
                "template": template,
                "subject": selected_template["subject"],
                "preview": selected_template["preview"],
                "segment": segment,
                "recipient_count": None,
                "sent": False,
            }
            requires_approval = self.requires_consensus("bulk_communication")
            return SkillResponse(
                content=(f"Draft bulk {communication_type} to the '{segment}' segment. Subject: "
                         f"'{selected_template['subject']}'. "
                         f"{not_connected('A member database and an email service', 'I can\'t count the recipients or send it')}"),
                success=True,
                data={"communication": communication_data},
                requires_consensus=requires_approval,
                consensus_action="bulk_communication" if requires_approval else None,
                suggestions=[],
            )

        # Individual: drafted, not sent (no email_service span is wired yet).
        communication_data = {
            "member_id": member_id,
            "type": "individual",
            "communication_type": communication_type,
            "template": template,
            "subject": selected_template["subject"],
            "sent": False,
        }
        return SkillResponse(
            content=(f"Draft {communication_type} to member {member_id}. Subject: '{selected_template['subject']}'. "
                     f"{not_connected('An email service', 'it has not been sent')}"),
            success=True,
            data={"communication": communication_data},
            suggestions=[],
        )

    async def _generate_membership_report(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """Generate membership analytics and reports.

        Creates comprehensive membership statistics and trends.
        """
        report_type = request.entities.get("report_type", "summary")
        period = request.entities.get("period", "monthly")
        # No membership_db span is wired yet: no count, revenue, retention or trend is known, and none is made up.
        return SkillResponse(
            content=not_connected("A member database", f"I have no members to report on for the {period} {report_type}"),
            success=True,
            data={"membership_report": None, "connected": False},
            suggestions=["Show membership tiers"],
        )
