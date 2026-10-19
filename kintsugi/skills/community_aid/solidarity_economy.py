"""Skill Chip: Solidarity Economy

Domain: COMMUNITY
Spans: coop_registry, time_bank_ledger, cdfi_network, worker_owner_tools
EFE Profile: risk=0.33, ambiguity=0.34, epistemic=0.33
Description: Supports cooperative development, time banking, and alternative economy initiatives.

Solidarity Economy skill chip for Kintsugi CMA.

Supports cooperative development, time banking, and alternative economy
initiatives. Helps communities build worker-owned cooperatives, manage
time bank exchanges, and access Community Development Financial
Institutions (CDFIs) for alternative lending.

Intents handled:
- coop_start: Guide cooperative formation process
- coop_search: Search for existing cooperatives
- time_bank: Manage time bank credits and exchanges
- cdfi_loan: Find CDFI lending opportunities
- solidarity_resource: Get solidarity economy resources and templates

Example:
    chip = SolidarityEconomyChip()
    response = await chip.handle(
        SkillRequest(intent="coop_start", entities={"coop_type": "worker", "members": 5}),
        context
    )
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

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


class CoopType(str, Enum):
    """Types of cooperative structures."""
    WORKER = "worker_cooperative"
    CONSUMER = "consumer_cooperative"
    PRODUCER = "producer_cooperative"
    MULTI_STAKEHOLDER = "multi_stakeholder"
    HOUSING = "housing_cooperative"
    CREDIT_UNION = "credit_union"
    PLATFORM = "platform_cooperative"


class CoopStatus(str, Enum):
    """Status of cooperative development."""
    EXPLORING = "exploring"
    FORMING = "forming"
    INCORPORATED = "incorporated"
    OPERATING = "operating"
    ESTABLISHED = "established"


@dataclass
class Cooperative:
    """Information about a cooperative organization."""
    coop_id: str
    name: str
    coop_type: CoopType
    status: CoopStatus
    location: str
    members: int
    founded: int
    industry: str
    description: str
    contact: str
    website: str | None = None
    revenue: float | None = None
    accepting_members: bool = False


@dataclass
class TimeBankAccount:
    """Time bank account for tracking service credits."""
    account_id: str
    member_id: str
    balance_hours: float
    earned_total: float
    spent_total: float
    services_offered: list[str]
    services_needed: list[str]
    last_transaction: datetime | None = None


@dataclass
class TimeBankTransaction:
    """A time bank exchange transaction."""
    transaction_id: str
    provider_id: str
    recipient_id: str
    hours: float
    service: str
    description: str
    timestamp: datetime
    verified: bool = False


@dataclass
class CDFILoan:
    """Information about a CDFI loan product."""
    loan_id: str
    cdfi_name: str
    loan_type: str
    min_amount: float
    max_amount: float
    interest_rate: str
    term_months: int
    requirements: list[str]
    eligible_uses: list[str]
    location_served: str


class SolidarityEconomyChip(BaseSkillChip):
    """Support cooperative development, time banking, and alternative economies.

    This chip helps communities build economic alternatives by guiding
    cooperative formation, managing time bank exchanges, and connecting
    to CDFI lending resources. It provides governance templates and
    tracks time bank credits.

    Attributes:
        name: Unique chip identifier
        description: Human-readable description
        domain: COMMUNITY domain for collective economics
        efe_weights: High mission alignment for transformative work
        capabilities: READ_DATA, WRITE_DATA, FINANCIAL_OPERATIONS
        consensus_actions: Actions requiring approval
        required_spans: MCP tool spans needed
    """

    name = "solidarity_economy"
    description = "Support cooperative development, time banking, and alternative economies"
    domain = SkillDomain.COMMUNITY
    efe_weights = EFEWeights(
        mission_alignment=0.35,
        stakeholder_benefit=0.25,
        resource_efficiency=0.15,
        transparency=0.15,
        equity=0.10,
    )
    capabilities = [
        SkillCapability.READ_DATA,
        SkillCapability.WRITE_DATA,
        SkillCapability.FINANCIAL_OPERATIONS,
    ]
    consensus_actions = ["approve_coop_formation", "time_bank_withdrawal", "cdfi_loan_application"]
    # Consensus: which intents ask for which action, held before handle() runs (kintsugi/governance/consumer.py).
    consensus_intents = {"time_bank": "time_bank_withdrawal"}
    # Who approves (Vera, 10-18): money and private info take two people (FINANCIAL, PII); the rest one.
    consensus_categories = {"time_bank_withdrawal": "FINANCIAL"}
    consensus_no_step = {"time_bank_withdrawal": "no time-bank balance is changed"}
    consensus_when = {
        "time_bank": lambda r: r.entities.get("action") == "exchange" and (r.entities.get("hours") or 0) > 5,
    }
    consensus_unreachable = {
        "approve_coop_formation": (
            "advisory: coop_start returns a formation plan; its flag says this needs approval, and no intent "
            "performs it"
        ),
        "cdfi_loan_application": (
            "advisory: cdfi_loan returns a search of loans; its flag says this needs approval, and no intent "
            "performs it"
        ),
    }
    required_spans = ["coop_registry", "time_bank_ledger", "cdfi_network", "worker_owner_tools"]
    # Honest without its spans (kintsugi/skills/honesty.py): general formation guidance and real national networks,
    # but no invented co-op, balance, member, loan term or cost. A time-bank exchange records nothing, and says so.
    simulated = False

    # Time bank exchange rates (all services valued equally at 1 hour = 1 credit)
    TIME_BANK_RATE = 1.0

    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Route request to appropriate handler based on intent.

        Args:
            request: The skill request with intent and entities
            context: Execution context including org, user, BDI state

        Returns:
            SkillResponse with solidarity economy information
        """
        handlers = {
            "coop_start": self._handle_coop_start,
            "coop_search": self._handle_coop_search,
            "time_bank": self._handle_time_bank,
            "cdfi_loan": self._handle_cdfi_loan,
            "solidarity_resource": self._handle_solidarity_resource,
        }

        handler = handlers.get(request.intent)
        if not handler:
            return SkillResponse(
                content=f"Unknown intent: {request.intent}. Supported intents: {list(handlers.keys())}",
                success=False,
            )

        return await handler(request, context)

    async def _handle_coop_start(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Guide the cooperative formation process.

        Args:
            request: Request with coop type and founding info
            context: Execution context

        Returns:
            SkillResponse with formation guidance
        """
        coop_type = request.entities.get("coop_type", "worker")
        members = request.entities.get("members", 3)
        industry = request.entities.get("industry")
        state = request.entities.get("state")

        process = await self.start_coop_process(
            coop_type=coop_type,
            initial_members=members,
            industry=industry,
            state=state,
        )

        content = f"**Starting a {coop_type.title()} Cooperative**\n\n"
        content += f"Members: {members}\n"
        if industry:
            content += f"Industry: {industry}\n"
        content += "\n"

        content += "**Formation Steps:**\n"
        for i, step in enumerate(process["steps"], 1):
            content += f"{i}. {step['name']}\n"
            content += f"   {step['description']}\n"
            content += f"   Timeline: {step['timeline']}\n\n"

        content += "**Key Documents Needed:**\n"
        for doc in process["documents"]:
            content += f"- {doc}\n"

        content += "\n**Costs to budget for** (they vary a lot by state and business):\n"
        for cost_item in process["costs_to_budget"]:
            content += f"- {cost_item}\n"

        content += "\n**Support Resources:**\n"
        for resource in process["resources"]:
            content += f"- {resource['name']}: {resource['contact']}\n"

        return SkillResponse(
            content=content,
            success=True,
            data=process,
            requires_consensus=True,
            consensus_action="approve_coop_formation",
            suggestions=[
                "List the governance documents to prepare",
            ],
        )

    async def start_coop_process(
        self,
        coop_type: str,
        initial_members: int,
        industry: str | None,
        state: str | None,
    ) -> dict[str, Any]:
        """Create a cooperative formation process plan.

        Args:
            coop_type: Type of cooperative to form
            initial_members: Number of founding members
            industry: Industry sector
            state: State for incorporation

        Returns:
            Formation process plan with steps and resources
        """
        # In production, this would query worker_owner_tools span
        return {
            "coop_type": coop_type,
            "members": initial_members,
            "steps": [
                {
                    "name": "Feasibility Study",
                    "description": "Assess market demand, skills, and financial viability",
                    "timeline": "2-4 weeks",
                },
                {
                    "name": "Business Planning",
                    "description": "Develop business plan, financial projections, governance structure",
                    "timeline": "4-8 weeks",
                },
                {
                    "name": "Legal Formation",
                    "description": "Draft bylaws, articles of incorporation, operating agreement",
                    "timeline": "2-4 weeks",
                },
                {
                    "name": "Capitalization",
                    "description": "Secure member equity, loans, grants for startup capital",
                    "timeline": "4-12 weeks",
                },
                {
                    "name": "Launch",
                    "description": "File incorporation, open accounts, begin operations",
                    "timeline": "2-4 weeks",
                },
            ],
            "documents": [
                "Articles of Incorporation",
                "Bylaws",
                "Operating Agreement",
                "Member Equity Agreement",
                "Business Plan",
                "Financial Projections",
            ],
            "costs_to_budget": [
                "State filing fees for incorporation",
                "Legal help with bylaws and securities rules for member shares",
                "Business planning",
                "Startup capital",
            ],
            "resources": [
                {
                    "name": "US Federation of Worker Cooperatives",
                    "contact": "usworker.coop",
                },
                {
                    "name": "Democracy at Work Institute",
                    "contact": "institute.coop",
                },
                {
                    "name": "Local Cooperative Development Center",
                    "contact": "Contact your regional center",
                },
            ],
        }

    async def _handle_coop_search(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Search for existing cooperatives.

        Args:
            request: Request with search criteria
            context: Execution context

        Returns:
            SkillResponse with matching cooperatives
        """
        coop_type = request.entities.get("coop_type")
        industry = request.entities.get("industry")
        location = request.entities.get("location")
        accepting_members = request.entities.get("accepting_members", False)

        coops = await self.search_coops(
            coop_type=coop_type,
            industry=industry,
            location=location,
            accepting_members=accepting_members,
        )

        if not coops:
            return SkillResponse(
                content=(f"{not_connected('A cooperative registry', 'I can\'t search co-ops for you')} National "
                         "networks, like the US Federation of Worker Cooperatives (usworker.coop), can point you to "
                         "co-ops near you."),
                success=True,
                data={"coops": [], "connected": False},
                suggestions=[
                    "Get co-op formation steps",
                ],
            )

        content = f"**Found {len(coops)} Cooperatives**\n\n"
        for coop in coops:
            content += f"**{coop.name}**\n"
            content += f"- Type: {coop.coop_type.value.replace('_', ' ').title()}\n"
            content += f"- Industry: {coop.industry}\n"
            content += f"- Location: {coop.location}\n"
            content += f"- Members: {coop.members}\n"
            content += f"- Founded: {coop.founded}\n"
            if coop.accepting_members:
                content += "- **Currently Accepting Members**\n"
            content += f"- Contact: {coop.contact}\n\n"

        return SkillResponse(
            content=content,
            success=True,
            data={
                "coops": [
                    {"id": c.coop_id, "name": c.name, "type": c.coop_type.value}
                    for c in coops
                ],
            },
            suggestions=[
                "Get co-op formation steps",
            ],
        )

    async def search_coops(
        self,
        coop_type: str | None = None,
        industry: str | None = None,
        location: str | None = None,
        accepting_members: bool = False,
    ) -> list[Cooperative]:
        """Search the cooperative registry.

        Args:
            coop_type: Filter by cooperative type
            industry: Filter by industry sector
            location: Filter by geographic location
            accepting_members: Only show coops accepting new members

        Returns:
            List of matching cooperatives
        """
        # No coop_registry span is wired yet: there are no co-ops to list, and none is made up.
        sample_coops: list[Cooperative] = []

        results = sample_coops

        if accepting_members:
            results = [c for c in results if c.accepting_members]

        if location:
            results = [c for c in results if location.lower() in c.location.lower()]

        return results

    async def _handle_time_bank(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Manage time bank credits and exchanges.

        Args:
            request: Request with time bank action
            context: Execution context

        Returns:
            SkillResponse with time bank information
        """
        action = request.entities.get("action", "balance")
        hours = request.entities.get("hours")
        service = request.entities.get("service")
        recipient = request.entities.get("recipient")

        result = await self.manage_time_bank(
            action=action,
            user_id=context.user_id,
            hours=hours,
            service=service,
            recipient=recipient,
        )

        ledger_missing = not_connected("A time-bank ledger", "{}")
        if action == "balance":
            content = ledger_missing.format("I can't see anyone's balance") + " Ask your time bank's coordinator."
        elif action == "exchange":
            content = (f"**Time Bank Exchange**\n\nService: {service}\nHours: {hours}\nRecipient: {recipient}\n\n"
                       + ledger_missing.format("this exchange has not been recorded and no credits have moved")
                       + " Record it with your time bank's coordinator.")
        elif action == "browse":
            content = ledger_missing.format("I can't list the services members offer") + " Ask your time bank's coordinator."
        else:
            content = f"Action '{action}' not recognized. Try: balance, exchange, browse"

        return SkillResponse(
            content=content,
            success=True,
            data=result,
            requires_consensus=action == "exchange" and hours and hours > 5,
            consensus_action="time_bank_withdrawal" if action == "exchange" else None,
            suggestions=[],
        )

    async def manage_time_bank(
        self,
        action: str,
        user_id: str,
        hours: float | None = None,
        service: str | None = None,
        recipient: str | None = None,
    ) -> dict[str, Any]:
        """Manage time bank account and transactions.

        Args:
            action: Action to perform (balance, exchange, browse)
            user_id: User's account ID
            hours: Hours for exchange
            service: Service being exchanged
            recipient: Recipient of service

        Returns:
            Time bank operation result
        """
        # No time_bank_ledger span is wired yet: no balance, member or service is known, and nothing is recorded.
        if action == "exchange":
            return {"recorded": False, "connected": False, "hours": hours, "service": service,
                    "requires_approval": bool(hours and hours > 5)}
        if action in ("balance", "browse"):
            return {"connected": False}
        return {}

    async def _handle_cdfi_loan(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Find CDFI lending opportunities.

        Args:
            request: Request with loan criteria
            context: Execution context

        Returns:
            SkillResponse with CDFI loan options
        """
        loan_amount = request.entities.get("amount")
        loan_purpose = request.entities.get("purpose")
        location = request.entities.get("location")
        business_type = request.entities.get("business_type")

        loans = await self.find_cdfi_lending(
            amount=loan_amount,
            purpose=loan_purpose,
            location=location,
            business_type=business_type,
        )

        if not loans:
            return SkillResponse(
                content=("CDFIs (Community Development Financial Institutions) lend to communities banks underserve, "
                         "co-ops included.\n\n"
                         f"{not_connected('A CDFI directory', 'I can\'t list lenders, loans or terms')} The U.S. "
                         "Treasury's CDFI Fund lists certified CDFIs by state; ask each one for its current terms."),
                success=True,
                data={"loans": [], "connected": False},
                suggestions=[
                    "Get co-op formation steps",
                ],
            )

        content = "**CDFI Loan Opportunities**\n\n"
        content += (
            "*CDFIs provide affordable financing for communities underserved "
            "by traditional banks.*\n\n"
        )

        for loan in loans:
            content += f"**{loan.cdfi_name}**\n"
            content += f"- Loan Type: {loan.loan_type}\n"
            content += f"- Amount: ${loan.min_amount:,.0f} - ${loan.max_amount:,.0f}\n"
            content += f"- Interest Rate: {loan.interest_rate}\n"
            content += f"- Term: {loan.term_months} months\n"
            content += f"- Serves: {loan.location_served}\n"
            content += "- Eligible Uses:\n"
            for use in loan.eligible_uses[:3]:
                content += f"  - {use}\n"
            content += "\n"

        return SkillResponse(
            content=content,
            success=True,
            data={
                "loans": [
                    {"id": l.loan_id, "cdfi": l.cdfi_name, "max": l.max_amount}
                    for l in loans
                ],
            },
            requires_consensus=True,
            consensus_action="cdfi_loan_application",
            suggestions=[],
        )

    async def find_cdfi_lending(
        self,
        amount: float | None = None,
        purpose: str | None = None,
        location: str | None = None,
        business_type: str | None = None,
    ) -> list[CDFILoan]:
        """Find CDFI loan products matching criteria.

        Args:
            amount: Desired loan amount
            purpose: Loan purpose (startup, expansion, etc.)
            location: Geographic location
            business_type: Type of business (coop, nonprofit, etc.)

        Returns:
            List of matching CDFI loan products
        """
        # No cdfi_network span is wired yet: no lender, product or rate is listed, and none is made up (one invented
        # set of terms was given a real lender's name until 10-19).
        return []

    async def _handle_solidarity_resource(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Get solidarity economy resources and templates.

        Args:
            request: Request with resource type
            context: Execution context

        Returns:
            SkillResponse with resources
        """
        resource_type = request.entities.get("type", "general")

        resources = await self.get_solidarity_resources(resource_type)

        content = f"**Solidarity Economy Resources: {resource_type.title()}**\n\n"

        if resources.get("templates"):
            content += "**Documents a co-op usually needs** (no templates are included here):\n"
            for template in resources["templates"]:
                content += f"- {template['name']}: {template['description']}\n"
            content += "\n"

        if resources.get("organizations"):
            content += "**Organizations & Networks:**\n"
            for org in resources["organizations"]:
                content += f"- **{org['name']}**: {org['description']}\n"
                content += f"  Contact: {org['contact']}\n"
            content += "\n"

        if resources.get("education"):
            content += "**Worth looking for locally:**\n"
            for edu in resources["education"]:
                content += f"- {edu}\n"

        return SkillResponse(
            content=content,
            success=True,
            data=resources,
            suggestions=[
                "Get co-op formation steps",
            ],
        )

    async def get_solidarity_resources(
        self, resource_type: str
    ) -> dict[str, Any]:
        """Get solidarity economy resources.

        Args:
            resource_type: Type of resources needed

        Returns:
            Collection of solidarity economy resources
        """
        # In production, this would query multiple spans
        return {
            "type": resource_type,
            "templates": [
                {"name": "Bylaws", "description": "how members govern and vote"},
                {"name": "Operating agreement", "description": "how the business runs day to day"},
                {"name": "Member equity agreement", "description": "member buy-in and how surplus is divided"},
            ],
            "organizations": [
                {
                    "name": "US Federation of Worker Cooperatives",
                    "description": "National grassroots membership organization",
                    "contact": "usworker.coop",
                },
                {
                    "name": "New Economy Coalition",
                    "description": "Network building the solidarity economy",
                    "contact": "neweconomy.net",
                },
            ],
            "education": [
                "An introductory co-op course",
                "A guide to running a time bank",
                "A co-op incubator or development center near you",
            ],
        }

    async def get_bdi_context(
        self,
        beliefs: list[dict[str, Any]],
        desires: list[dict[str, Any]],
        intentions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Filter BDI context for solidarity economy information.

        Args:
            beliefs: Current belief state
            desires: Current desires/goals
            intentions: Current intentions/plans

        Returns:
            Filtered BDI state relevant to solidarity economy
        """
        economy_domains = {"cooperative", "time_bank", "cdfi", "solidarity", "mutual_aid"}

        return {
            "beliefs": [
                b for b in beliefs
                if b.get("domain") in economy_domains
                or b.get("type") in [
                    "coop_status",
                    "time_bank_balance",
                    "loan_status",
                    "economic_model",
                ]
            ],
            "desires": [
                d for d in desires
                if d.get("type") in [
                    "form_cooperative",
                    "join_time_bank",
                    "access_capital",
                    "economic_democracy",
                ]
            ],
            "intentions": [
                i for i in intentions
                if i.get("domain") in economy_domains
            ],
        }
