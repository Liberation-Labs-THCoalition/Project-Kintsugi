"""Skill Chip: Housing Navigator

Domain: ADVOCACY
Spans: housing_database, voucher_tracker, landlord_registry, hud_api
EFE Profile: risk=0.33, ambiguity=0.34, epistemic=0.33
Description: Navigates housing resources, voucher programs, tenant rights, and eviction defense.

Housing Navigator skill chip for Kintsugi CMA.

Navigates housing resources, voucher programs, and tenant rights for
community members seeking stable housing. Tracks voucher waitlists,
maintains landlord accountability information, and provides eviction
defense resources.

Intents handled:
- housing_search: Search for available housing matching criteria
- voucher_status: Check housing voucher application status
- tenant_rights: Get tenant rights information for jurisdiction
- landlord_lookup: Look up landlord history and accountability info
- eviction_defense: Get eviction defense resources and support

Example:
    chip = HousingNavigatorChip()
    response = await chip.handle(
        SkillRequest(intent="housing_search", entities={"bedrooms": 2, "voucher_type": "HCV"}),
        context
    )
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

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


class VoucherType(str, Enum):
    """Types of housing vouchers supported."""
    HCV = "housing_choice_voucher"  # Section 8
    PBV = "project_based_voucher"
    VASH = "veterans_supportive_housing"
    FUP = "family_unification_program"
    EHV = "emergency_housing_voucher"
    RAD = "rental_assistance_demonstration"


class HousingStatus(str, Enum):
    """Status of housing units."""
    AVAILABLE = "available"
    PENDING = "pending"
    WAITLIST = "waitlist"
    OCCUPIED = "occupied"
    UNAVAILABLE = "unavailable"


@dataclass
class HousingUnit:
    """Represents an available housing unit."""
    unit_id: str
    address: str
    city: str
    state: str
    zip_code: str
    bedrooms: int
    bathrooms: float
    rent: float
    accepts_voucher: bool
    voucher_types: list[VoucherType]
    landlord_id: str
    amenities: list[str]
    accessibility: list[str]
    status: HousingStatus
    available_date: datetime | None = None
    utilities_included: list[str] = field(default_factory=list)


@dataclass
class VoucherApplication:
    """Tracks a voucher application status."""
    application_id: str
    voucher_type: VoucherType
    status: str
    applied_date: datetime
    waitlist_position: int | None
    estimated_wait: str | None
    last_updated: datetime
    next_steps: list[str]


@dataclass
class LandlordRecord:
    """Information about a landlord's history."""
    landlord_id: str
    name: str
    properties_count: int
    accepts_vouchers: bool
    complaint_count: int
    violation_count: int
    avg_response_time: str
    community_rating: float  # 1-5 scale
    voucher_friendly_rating: float
    notes: list[str]


class HousingNavigatorChip(BaseSkillChip):
    """Navigate housing resources, voucher programs, and tenant rights.

    This chip helps community members find stable housing by searching
    available units, tracking voucher applications, providing tenant
    rights information, and maintaining landlord accountability records.

    Attributes:
        name: Unique chip identifier
        description: Human-readable description
        domain: ADVOCACY domain for housing rights
        efe_weights: Stakeholder-focused weights
        capabilities: READ_DATA, WRITE_DATA, EXTERNAL_API, PII_ACCESS
        consensus_actions: Actions requiring approval
        required_spans: MCP tool spans needed
    """

    name = "housing_navigator"
    description = "Navigate housing resources, voucher programs, and tenant rights"
    domain = SkillDomain.ADVOCACY
    efe_weights = EFEWeights(
        mission_alignment=0.25,
        stakeholder_benefit=0.40,
        resource_efficiency=0.10,
        transparency=0.15,
        equity=0.10,
    )
    capabilities = [
        SkillCapability.READ_DATA,
        SkillCapability.WRITE_DATA,
        SkillCapability.EXTERNAL_API,
        SkillCapability.PII_ACCESS,
    ]
    consensus_actions = ["submit_voucher_application", "share_tenant_data"]
    # Consensus: which intents ask for which action, held before handle() runs (kintsugi/governance/consumer.py).
    consensus_intents = {}
    consensus_unreachable = {
        "submit_voucher_application": (
            "no intent performs this yet: declared for a future one, so it can't happen ungated"
        ),
        "share_tenant_data": "no intent performs this yet: declared for a future one, so it can't happen ungated",
    }
    required_spans = ["housing_database", "voucher_tracker", "landlord_registry", "hud_api"]
    # Honest without its spans (kintsugi/skills/honesty.py): no listing, application, landlord record or hotline is
    # invented. Tenant law depends on the place, so it gives the questions to ask, not rules it can't know.
    simulated = False

    def __init__(self, contacts: dict[str, str] | None = None) -> None:
        super().__init__()
        # The deployment's own lines: housing_authority, eviction_legal_help, rental_assistance, tenant_union.
        self.contacts = dict(contacts or {})

    def _contact_lines(self, keys: list[tuple[str, str]]) -> str:
        lines = [f"- {label}: **{self.contacts[key]}**" for key, label in keys if self.contacts.get(key)]
        return "\n".join(lines) + "\n" if lines else ""

    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Route request to appropriate handler based on intent.

        Args:
            request: The skill request with intent and entities
            context: Execution context including org, user, BDI state

        Returns:
            SkillResponse with housing information
        """
        handlers = {
            "housing_search": self._handle_housing_search,
            "voucher_status": self._handle_voucher_status,
            "tenant_rights": self._handle_tenant_rights,
            "landlord_lookup": self._handle_landlord_lookup,
            "eviction_defense": self._handle_eviction_defense,
        }

        handler = handlers.get(request.intent)
        if not handler:
            return SkillResponse(
                content=f"Unknown intent: {request.intent}. Supported intents: {list(handlers.keys())}",
                success=False,
            )

        return await handler(request, context)

    async def _handle_housing_search(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Search for available housing matching criteria.

        Args:
            request: Request with housing search criteria
            context: Execution context

        Returns:
            SkillResponse with matching housing units
        """
        bedrooms = request.entities.get("bedrooms")
        max_rent = request.entities.get("max_rent")
        voucher_type = request.entities.get("voucher_type")
        city = request.entities.get("city")
        accessibility = request.entities.get("accessibility", [])

        units = await self.search_housing(
            bedrooms=bedrooms,
            max_rent=max_rent,
            voucher_type=voucher_type,
            city=city,
            accessibility=accessibility,
        )

        if not units:
            return SkillResponse(
                content=(f"{not_connected('A housing listings database', 'I can\'t search units for you')} "
                         "Your local housing authority can point you to landlords who accept vouchers. "
                         f"{US_REFERRALS}\n"
                         + self._contact_lines([("housing_authority", "Your housing authority"),
                                                ("tenant_union", "Your tenant union")])),
                success=True,
                data={"units": [], "connected": False},
                suggestions=[
                    "Get tenant rights questions to ask locally",
                    "Get eviction defense steps",
                ],
            )

        content = f"**Found {len(units)} Housing Options**\n\n"
        for unit in units:
            content += f"**{unit.address}, {unit.city}**\n"
            content += f"- Bedrooms: {unit.bedrooms} | Bathrooms: {unit.bathrooms}\n"
            content += f"- Rent: ${unit.rent:.0f}/month\n"
            content += f"- Vouchers Accepted: {', '.join(v.value for v in unit.voucher_types)}\n"
            if unit.accessibility:
                content += f"- Accessibility: {', '.join(unit.accessibility)}\n"
            content += f"- Status: {unit.status.value.title()}\n"
            if unit.available_date:
                content += f"- Available: {unit.available_date.strftime('%B %d, %Y')}\n"
            content += "\n"

        return SkillResponse(
            content=content,
            success=True,
            data={
                "units": [
                    {"id": u.unit_id, "address": u.address, "rent": u.rent}
                    for u in units
                ],
                "total_found": len(units),
            },
            suggestions=[
                "Get tenant rights questions to ask locally",
            ],
        )

    async def search_housing(
        self,
        bedrooms: int | None = None,
        max_rent: float | None = None,
        voucher_type: str | None = None,
        city: str | None = None,
        accessibility: list[str] | None = None,
    ) -> list[HousingUnit]:
        """Search the housing database for matching units.

        Args:
            bedrooms: Minimum number of bedrooms
            max_rent: Maximum monthly rent
            voucher_type: Required voucher acceptance
            city: City to search in
            accessibility: Required accessibility features

        Returns:
            List of matching housing units
        """
        # No housing_database or hud_api span is wired yet, so there are no units to list, and none is made up.
        sample_units: list[HousingUnit] = []

        # Filter based on criteria
        results = []
        for unit in sample_units:
            if bedrooms and unit.bedrooms < bedrooms:
                continue
            if max_rent and unit.rent > max_rent:
                continue
            if city and unit.city.lower() != city.lower():
                continue
            if accessibility:
                if not all(a in unit.accessibility for a in accessibility):
                    continue
            results.append(unit)

        return results

    async def _handle_voucher_status(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Check housing voucher application status.

        Args:
            request: Request with application ID or user context
            context: Execution context

        Returns:
            SkillResponse with voucher status information
        """
        application_id = request.entities.get("application_id")
        voucher_type = request.entities.get("voucher_type")

        status = await self.check_voucher_status(application_id, context.user_id)

        if not status:
            return SkillResponse(
                content=(f"{not_connected('A voucher tracker', 'I can\'t look up your application or waitlist position')} "
                         "Your local public housing agency can tell you both.\n\n"
                         "While you wait:\n"
                         "- Keep your contact information current with the agency\n"
                         "- Answer its mail promptly: missed letters can cost a place on the list\n"
                         "- Ask how soon income changes must be reported (each agency sets its own rule)\n"
                         + self._contact_lines([("housing_authority", "Your housing authority")])),
                success=True,
                data={"status": "not_connected", "connected": False, "application_id": application_id},
                suggestions=[
                    "Get tenant rights questions to ask locally",
                ],
            )

        content = f"**Voucher Application Status**\n\n"
        content += f"Application ID: {status.application_id}\n"
        content += f"Voucher Type: {status.voucher_type.value}\n"
        content += f"Status: **{status.status}**\n"
        content += f"Applied: {status.applied_date.strftime('%B %d, %Y')}\n"

        if status.waitlist_position:
            content += f"Waitlist Position: #{status.waitlist_position}\n"
        if status.estimated_wait:
            content += f"Estimated Wait: {status.estimated_wait}\n"

        content += f"\nLast Updated: {status.last_updated.strftime('%B %d, %Y')}\n"

        if status.next_steps:
            content += "\n**Next Steps:**\n"
            for step in status.next_steps:
                content += f"- {step}\n"

        return SkillResponse(
            content=content,
            success=True,
            data={
                "application_id": status.application_id,
                "status": status.status,
                "waitlist_position": status.waitlist_position,
            },
            suggestions=[
                "Get eviction defense steps",
            ],
        )

    async def check_voucher_status(
        self, application_id: str | None, user_id: str
    ) -> VoucherApplication | None:
        """Check the status of a voucher application.

        Args:
            application_id: Specific application to check
            user_id: User ID to look up applications for

        Returns:
            VoucherApplication if found, None otherwise
        """
        # No voucher_tracker span is wired yet: nothing is looked up, so nothing is returned.
        return None

    async def _handle_tenant_rights(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Get tenant rights information.

        Args:
            request: Request with jurisdiction info
            context: Execution context

        Returns:
            SkillResponse with tenant rights information
        """
        state = request.entities.get("state", "CA")
        city = request.entities.get("city")
        issue = request.entities.get("issue")

        rights_info = await self.get_tenant_rights(state, city, issue)

        place = city or state or "your area"
        content = f"**Tenant rights in {place}: questions to ask locally**\n\n"
        content += (f"Tenant law depends on your state and city. "
                    f"{not_connected('A jurisdiction database', f'I can\'t tell you which rules apply in {place}')} "
                    "Ask a local tenant organization or legal aid these:\n\n")
        for category, questions in rights_info.items():
            content += f"**{category}:**\n"
            for q in questions:
                content += f"- {q}\n"
            content += "\n"
        content += ("Wherever you live: keep copies of every notice, letter and text, and make repair requests in "
                    f"writing. {US_REFERRALS}\n")
        content += self._contact_lines([("tenant_union", "Your tenant union"),
                                        ("eviction_legal_help", "Legal help")])

        return SkillResponse(
            content=content,
            success=True,
            data={"questions": rights_info, "jurisdiction": city or state, "connected": False},
            suggestions=[
                "Get eviction defense steps",
            ],
        )

    async def get_tenant_rights(
        self, state: str, city: str | None, issue: str | None
    ) -> dict[str, list[str]]:
        """Look up tenant rights for a jurisdiction.

        Args:
            state: State for rights lookup
            city: City for local protections
            issue: Specific issue to focus on

        Returns:
            Dictionary of rights categories and specific rights
        """
        # No jurisdiction data is wired yet, so these are the questions whose answers differ by place, never answers.
        return {
            "Repairs": [
                "What repairs must my landlord make (heat, water, electricity, pests, mold), and how fast?",
                "How do I ask for repairs so it counts (in writing, to whom)?",
            ],
            "Rent": [
                "Does my city or state limit rent increases? (Many don't.)",
                "How much notice must I get before a rent increase?",
            ],
            "Entry": [
                "How much notice must my landlord give before entering, and when may they enter?",
            ],
            "Eviction and retaliation": [
                "Does my landlord need a legal reason (\"just cause\") to end my tenancy here?",
                "Am I protected from retaliation for reporting problems or organizing with neighbors?",
            ],
        }

    async def _handle_landlord_lookup(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Look up landlord accountability information.

        Args:
            request: Request with landlord or property info
            context: Execution context

        Returns:
            SkillResponse with landlord information
        """
        landlord_name = request.entities.get("landlord_name")
        property_address = request.entities.get("property_address")
        landlord_id = request.entities.get("landlord_id")

        record = await self.lookup_landlord(landlord_name, property_address, landlord_id)

        if not record:
            return SkillResponse(
                content=(f"{not_connected('A landlord registry', 'I have no record for this landlord')} "
                         "Your city or county may publish code-violation records, and local tenant unions often keep "
                         "their own notes on landlords.\n"
                         + self._contact_lines([("tenant_union", "Your tenant union")])),
                success=True,
                data={"connected": False, "landlord_id": None},
                suggestions=[
                    "Get tenant rights questions to ask locally",
                ],
            )

        content = f"**Landlord Information**\n\n"
        content += f"Name: {record.name}\n"
        content += f"Properties: {record.properties_count}\n"
        content += f"Accepts Vouchers: {'Yes' if record.accepts_vouchers else 'No'}\n\n"

        content += f"**Accountability Metrics:**\n"
        content += f"- Community Rating: {'*' * int(record.community_rating)} ({record.community_rating:.1f}/5)\n"
        content += f"- Voucher Friendly: {'*' * int(record.voucher_friendly_rating)} ({record.voucher_friendly_rating:.1f}/5)\n"
        content += f"- Complaints: {record.complaint_count}\n"
        content += f"- Code Violations: {record.violation_count}\n"
        content += f"- Avg Response Time: {record.avg_response_time}\n"

        if record.notes:
            content += "\n**Community Notes:**\n"
            for note in record.notes[:3]:  # Show first 3 notes
                content += f"- {note}\n"

        return SkillResponse(
            content=content,
            success=True,
            data={
                "landlord_id": record.landlord_id,
                "name": record.name,
                "rating": record.community_rating,
                "complaints": record.complaint_count,
            },
            suggestions=[
                "Get tenant rights questions to ask locally",
            ],
        )

    async def lookup_landlord(
        self,
        name: str | None,
        address: str | None,
        landlord_id: str | None,
    ) -> LandlordRecord | None:
        """Look up landlord accountability information.

        Args:
            name: Landlord name to search
            address: Property address to find landlord
            landlord_id: Direct landlord ID lookup

        Returns:
            LandlordRecord if found, None otherwise
        """
        # No landlord_registry span is wired yet: no record exists to return, and none is made up.
        return None

    async def _handle_eviction_defense(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Get eviction defense resources and support.

        Args:
            request: Request with eviction details
            context: Execution context

        Returns:
            SkillResponse with eviction defense resources
        """
        eviction_stage = request.entities.get("stage", "notice")
        location = request.entities.get("location")
        urgency = request.entities.get("urgency", "normal")

        resources = await self.get_eviction_resources(eviction_stage, location)

        content = "**Eviction Defense Resources**\n\n"

        if eviction_stage == "notice":
            content += (
                "You've received an eviction notice. Here's what to know:\n\n"
                "**Immediate Steps:**\n"
                "1. DO NOT ignore the notice\n"
                "2. Note all deadlines carefully\n"
                "3. Contact a tenant rights organization immediately\n"
                "4. Document everything in writing\n\n"
            )
        elif eviction_stage == "court":
            content += (
                "You have a court date. Critical steps:\n\n"
                "**Immediate Steps:**\n"
                "1. DO NOT miss your court date\n"
                "2. Seek legal representation immediately\n"
                "3. Gather all documentation\n"
                "4. Apply for emergency rental assistance if eligible\n\n"
            )

        content += "**Help:**\n"
        if resources:
            for resource in resources:
                content += f"- {resource['name']}: **{resource['contact']}**\n"
        else:
            content += (f"{not_connected('A local resource directory', 'I can\'t name a legal clinic or hotline near you')} "
                        "Call 211 and ask for eviction legal help and emergency rental assistance.\n")

        return SkillResponse(
            content=content,
            success=True,
            data={"resources": resources, "stage": eviction_stage},
            suggestions=[
                "Get tenant rights questions to ask locally",
            ],
        )

    async def get_eviction_resources(
        self, stage: str, location: str | None
    ) -> list[dict[str, Any]]:
        """Get eviction defense resources.

        Args:
            stage: Stage of eviction process
            location: Geographic location

        Returns:
            List of eviction defense resources
        """
        # Only the deployment's own lines: no housing_database span is wired yet, so no hotline or clinic is named.
        named = [("eviction_legal_help", "Eviction legal help"), ("rental_assistance", "Emergency rental assistance"),
                 ("tenant_union", "Your tenant union")]
        return [{"name": label, "contact": self.contacts[key]} for key, label in named if self.contacts.get(key)]

    async def get_bdi_context(
        self,
        beliefs: list[dict[str, Any]],
        desires: list[dict[str, Any]],
        intentions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Filter BDI context for housing-related information.

        Args:
            beliefs: Current belief state
            desires: Current desires/goals
            intentions: Current intentions/plans

        Returns:
            Filtered BDI state relevant to housing matters
        """
        housing_domains = {"housing", "tenant", "voucher", "eviction", "landlord"}

        return {
            "beliefs": [
                b for b in beliefs
                if b.get("domain") in housing_domains
                or b.get("type") in [
                    "housing_status",
                    "voucher_status",
                    "eviction_risk",
                    "rent_status",
                ]
            ],
            "desires": [
                d for d in desires
                if d.get("type") in [
                    "stable_housing",
                    "voucher_approval",
                    "eviction_defense",
                ]
            ],
            "intentions": [
                i for i in intentions
                if i.get("domain") in housing_domains
            ],
        }
