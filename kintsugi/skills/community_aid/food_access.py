"""Skill Chip: Food Access

Domain: MUTUAL_AID
Spans: pantry_network, snap_eligibility, meal_scheduler, inventory_system
EFE Profile: risk=0.33, ambiguity=0.34, epistemic=0.33
Description: Coordinates food pantries, SNAP assistance, and community meals for food-insecure members.

Food Access skill chip for Kintsugi CMA.

Coordinates food pantries, SNAP (food stamps) assistance, and community
meals for community members experiencing food insecurity. Provides
real-time pantry inventory and dietary restriction filtering.

Intents handled:
- pantry_find: Find nearby food pantries with availability
- snap_help: SNAP/food stamp eligibility and application help
- meal_schedule: Schedule community meal pickups or deliveries
- food_donate: Process food donations from community members
- nutrition_info: Provide nutrition information and dietary guidance

Example:
    chip = FoodAccessChip()
    response = await chip.handle(
        SkillRequest(intent="pantry_find", entities={"zip_code": "94612", "dietary": ["halal"]}),
        context
    )
"""

from dataclasses import dataclass, field
from datetime import datetime, time, timezone
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
from kintsugi.skills.base import consent_given


class DietaryRestriction(str, Enum):
    """Dietary restriction categories for filtering food sources."""
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"
    HALAL = "halal"
    KOSHER = "kosher"
    GLUTEN_FREE = "gluten_free"
    DAIRY_FREE = "dairy_free"
    NUT_FREE = "nut_free"
    LOW_SODIUM = "low_sodium"
    DIABETIC_FRIENDLY = "diabetic_friendly"


class PantryStatus(str, Enum):
    """Operating status of food pantries."""
    OPEN = "open"
    CLOSED = "closed"
    LOW_INVENTORY = "low_inventory"
    BY_APPOINTMENT = "by_appointment"
    SPECIAL_HOURS = "special_hours"


@dataclass
class FoodPantry:
    """Information about a food pantry location."""
    pantry_id: str
    name: str
    address: str
    city: str
    zip_code: str
    phone: str
    status: PantryStatus
    hours: dict[str, str]  # Day -> hours string
    dietary_options: list[DietaryRestriction]
    inventory_level: str  # high, medium, low
    next_restock: datetime | None
    requirements: list[str]  # ID, proof of address, etc.
    languages: list[str]
    distance_miles: float | None = None


@dataclass
class InventoryItem:
    """Food inventory item at a pantry."""
    item_id: str
    name: str
    category: str  # produce, protein, dairy, grains, etc.
    quantity: int
    unit: str
    dietary_tags: list[DietaryRestriction]
    expiration: datetime | None
    available: bool = True


@dataclass
class MealProgram:
    """Community meal program information."""
    program_id: str
    name: str
    location: str
    meal_type: str  # breakfast, lunch, dinner
    schedule: dict[str, str]  # Day -> time
    dietary_accommodations: list[DietaryRestriction]
    registration_required: bool
    delivery_available: bool
    capacity: int
    current_signups: int


class FoodAccessChip(BaseSkillChip):
    """Coordinate food pantries, SNAP assistance, and community meals.

    This chip helps community members access food resources by finding
    nearby pantries with real-time inventory, assisting with SNAP
    applications, and coordinating community meal programs.

    Attributes:
        name: Unique chip identifier
        description: Human-readable description
        domain: MUTUAL_AID domain for direct assistance
        efe_weights: High stakeholder benefit focus
        capabilities: READ_DATA, WRITE_DATA, SCHEDULE_TASKS, EXTERNAL_API
        consensus_actions: Actions requiring approval
        required_spans: MCP tool spans needed
    """

    name = "food_access"
    description = "Coordinate food pantries, SNAP assistance, and community meals"
    domain = SkillDomain.MUTUAL_AID
    efe_weights = EFEWeights(
        mission_alignment=0.25,
        stakeholder_benefit=0.40,
        resource_efficiency=0.15,
        transparency=0.10,
        equity=0.10,
    )
    capabilities = [
        SkillCapability.READ_DATA,
        SkillCapability.WRITE_DATA,
        SkillCapability.SCHEDULE_TASKS,
        SkillCapability.EXTERNAL_API,
    ]
    consensus_actions = ["approve_food_distribution", "partner_food_share"]
    # Consensus: which intents ask for which action, held before handle() runs (kintsugi/governance/consumer.py).
    consensus_intents = {"food_donate": "approve_food_distribution"}
    # Who approves (Vera, 10-18): money and private info take two people (FINANCIAL, PII); the rest one.
    consensus_categories = {"approve_food_distribution": "GENERAL"}
    consensus_when = {
        "food_donate": lambda r: (r.entities.get("quantity") or 0) > 100,
    }
    consensus_unreachable = {
        "partner_food_share": "no intent performs this yet: declared for a future one, so it can't happen ungated",
    }
    required_spans = ["pantry_network", "snap_eligibility", "meal_scheduler", "inventory_system"]
    # Honest without its spans (kintsugi/skills/honesty.py): no pantry, meal program, pickup or drop-off is invented,
    # and no SNAP verdict is given from stale limits. (The FY2024 table and a made-up benefit formula were removed
    # 10-19: limits change every October and differ by state, and a stale "may not qualify" can stop someone applying.)
    simulated = False

    def __init__(self, contacts: dict[str, str] | None = None) -> None:
        super().__init__()
        # The deployment's own lines: food_pantry_line, meal_program_line, donation_line, snap_help_line.
        self.contacts = dict(contacts or {})

    def _line(self, key: str, label: str) -> str:
        return f"{label}: **{self.contacts[key]}**\n" if self.contacts.get(key) else ""

    def while_held(self, action: str) -> str:
        if action == "approve_food_distribution":
            return (f"{not_connected('An inventory system', 'approving this records nothing and schedules no pickup')} "
                    "Contact your food bank directly to arrange a large donation.")
        return ""

    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Route request to appropriate handler based on intent.

        Args:
            request: The skill request with intent and entities
            context: Execution context including org, user, BDI state

        Returns:
            SkillResponse with food access information
        """
        handlers = {
            "pantry_find": self._handle_pantry_find,
            "snap_help": self._handle_snap_help,
            "meal_schedule": self._handle_meal_schedule,
            "food_donate": self._handle_food_donate,
            "nutrition_info": self._handle_nutrition_info,
        }

        handler = handlers.get(request.intent)
        if not handler:
            return SkillResponse(
                content=f"Unknown intent: {request.intent}. Supported intents: {list(handlers.keys())}",
                success=False,
            )

        return await handler(request, context)

    async def _handle_pantry_find(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Find nearby food pantries with availability.

        Args:
            request: Request with location and dietary requirements
            context: Execution context

        Returns:
            SkillResponse with matching pantries
        """
        zip_code = request.entities.get("zip_code")
        city = request.entities.get("city")
        dietary = request.entities.get("dietary", [])
        max_distance = request.entities.get("max_distance", 5.0)

        pantries = await self.find_pantries(
            zip_code=zip_code,
            city=city,
            dietary_needs=dietary,
            max_distance=max_distance,
        )

        if not pantries:
            return SkillResponse(
                content=(f"{not_connected('A food pantry directory', 'I can\'t list pantries near you')} "
                         "Call 211 and ask which pantries are open near you today, and what to bring.\n"
                         + self._line("food_pantry_line", "Your organization's food line")),
                success=True,
                data={"pantries": [], "connected": False},
                suggestions=[
                    "Get help applying for SNAP",
                ],
            )

        content = f"**Found {len(pantries)} Food Pantries**\n\n"
        for pantry in pantries:
            status_icon = "Open" if pantry.status == PantryStatus.OPEN else pantry.status.value.title()
            content += f"**{pantry.name}** ({status_icon})\n"
            content += f"- Address: {pantry.address}, {pantry.city}\n"
            content += f"- Phone: {pantry.phone}\n"
            if pantry.distance_miles:
                content += f"- Distance: {pantry.distance_miles:.1f} miles\n"
            content += f"- Inventory: {pantry.inventory_level.title()}\n"
            if pantry.dietary_options:
                content += f"- Dietary Options: {', '.join(d.value for d in pantry.dietary_options)}\n"
            if pantry.requirements:
                content += f"- Requirements: {', '.join(pantry.requirements)}\n"
            content += "\n"

        return SkillResponse(
            content=content,
            success=True,
            data={
                "pantries": [
                    {
                        "id": p.pantry_id,
                        "name": p.name,
                        "status": p.status.value,
                        "distance": p.distance_miles,
                    }
                    for p in pantries
                ],
                "total_found": len(pantries),
            },
            suggestions=[
                "Get help applying for SNAP",
            ],
        )

    async def find_pantries(
        self,
        zip_code: str | None = None,
        city: str | None = None,
        dietary_needs: list[str] | None = None,
        max_distance: float = 5.0,
    ) -> list[FoodPantry]:
        """Search for food pantries matching criteria.

        Args:
            zip_code: ZIP code to search near
            city: City to search in
            dietary_needs: Required dietary accommodations
            max_distance: Maximum distance in miles

        Returns:
            List of matching food pantries
        """
        # No pantry_network span is wired yet: there are no pantries to list, and none is made up.
        sample_pantries: list[FoodPantry] = []

        # Filter by distance
        results = [p for p in sample_pantries if (p.distance_miles or 0) <= max_distance]

        # Filter by dietary needs
        if dietary_needs:
            needed = set(dietary_needs)
            results = [
                p for p in results
                if needed.issubset({d.value for d in p.dietary_options})
            ]

        return results

    async def _handle_snap_help(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Help with SNAP eligibility and applications.

        Args:
            request: Request with household info
            context: Execution context

        Returns:
            SkillResponse with SNAP information
        """
        action = request.entities.get("action", "eligibility")
        household_size = request.entities.get("household_size")
        monthly_income = request.entities.get("monthly_income")

        content = ""
        if action == "eligibility" and household_size and monthly_income:
            content = (f"{not_connected('A SNAP eligibility service', 'I can\'t check your numbers against this year\'s limits')} "
                       "Limits change every October and differ by state, and many states use higher ones. Your "
                       "state's SNAP website can screen you in minutes. Apply even if you're unsure: only the state "
                       "decides.\n\n")
        content += self._get_snap_overview() + self._line("snap_help_line", "\nHelp applying")

        return SkillResponse(
            content=content,
            success=True,
            data={
                "action": action,
                "household_size": household_size,
                "income": monthly_income,
                "eligibility": None,
                "connected": False,
            },
            suggestions=[
                "Find food pantries",
            ],
        )

    def _get_snap_overview(self) -> str:
        """Get general SNAP program information."""
        return (
            "**SNAP (Supplemental Nutrition Assistance Program)**\n\n"
            "SNAP helps low-income individuals and families buy nutritious food.\n\n"
            "**How to Apply:**\n"
            "1. Apply online at your state's SNAP website\n"
            "2. Visit your local SNAP office\n"
            "3. Get help from a community organization\n\n"
            "**What You'll Need:**\n"
            "- Proof of identity\n"
            "- Proof of income\n"
            "- Social Security numbers for the household members who are applying (members who aren't applying "
            "don't have to give one or their immigration status)\n"
            "- Proof of housing costs\n"
        )

    async def _handle_meal_schedule(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Schedule community meal pickups or deliveries.

        Args:
            request: Request with meal preferences
            context: Execution context

        Returns:
            SkillResponse with meal scheduling info
        """
        action = request.entities.get("action", "find")
        meal_type = request.entities.get("meal_type")
        location = request.entities.get("location")
        dietary = request.entities.get("dietary", [])
        delivery = request.entities.get("delivery", False)

        programs = await self.schedule_meal_pickup(
            meal_type=meal_type,
            location=location,
            dietary_needs=dietary,
            needs_delivery=delivery,
        )

        if not programs:
            return SkillResponse(
                content=(f"{not_connected('A meal program directory', 'I can\'t list community meals near you')} "
                         "Call 211 and ask about free community meals; for older or homebound people, ask about "
                         "home-delivered meals (such as Meals on Wheels).\n"
                         + self._line("meal_program_line", "Your organization's meal line")),
                success=True,
                data={"programs": [], "connected": False},
                suggestions=[
                    "Find food pantries",
                ],
            )

        content = f"**Community Meal Programs**\n\n"
        for program in programs:
            content += f"**{program.name}**\n"
            content += f"- Location: {program.location}\n"
            content += f"- Meal: {program.meal_type.title()}\n"
            if program.delivery_available:
                content += "- Delivery Available\n"
            content += f"- Schedule:\n"
            for day, time_str in program.schedule.items():
                content += f"  - {day}: {time_str}\n"
            if program.registration_required:
                content += "- Registration Required\n"
            spots = program.capacity - program.current_signups
            content += f"- Spots Available: {spots}\n\n"

        return SkillResponse(
            content=content,
            success=True,
            data={
                "programs": [
                    {"id": p.program_id, "name": p.name, "meal": p.meal_type}
                    for p in programs
                ],
            },
            suggestions=[
                "Find food pantries",
            ],
        )

    async def schedule_meal_pickup(
        self,
        meal_type: str | None = None,
        location: str | None = None,
        dietary_needs: list[str] | None = None,
        needs_delivery: bool = False,
    ) -> list[MealProgram]:
        """Find and schedule community meal pickups.

        Args:
            meal_type: Type of meal (breakfast, lunch, dinner)
            location: Preferred location
            dietary_needs: Dietary accommodations needed
            needs_delivery: Whether delivery is required

        Returns:
            List of matching meal programs
        """
        # No meal_scheduler span is wired yet: there are no programs to list, and none is made up.
        programs: list[MealProgram] = []

        # Filter by delivery requirement
        if needs_delivery:
            programs = [p for p in programs if p.delivery_available]

        # Filter by meal type
        if meal_type:
            programs = [p for p in programs if p.meal_type == meal_type]

        return programs

    async def _handle_food_donate(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Process food donations from community members.

        Args:
            request: Request with donation details
            context: Execution context

        Returns:
            SkillResponse with donation processing info
        """
        donation_type = request.entities.get("type", "food")
        items = request.entities.get("items", [])
        quantity = request.entities.get("quantity")
        pickup_needed = request.entities.get("pickup", False)

        result = await self.process_donation(
            donation_type=donation_type,
            items=items,
            quantity=quantity,
            pickup_needed=pickup_needed,
            donor_id=context.user_id,
        )

        content = "**Thank you for offering to donate.**\n\n"
        content += (f"{not_connected('An inventory system', 'this offer has not been recorded or sent to anyone')}"
                    + (" No pickup has been scheduled." if pickup_needed else "") + "\n\n")
        line = self.contacts.get("donation_line")
        content += (f"To donate, contact your organization's donation line: **{line}**.\n" if line else
                    "To donate, contact your local food bank or pantry directly (211 can tell you which are near).\n")
        content += ("Most pantries take unopened, unexpired non-perishables; ask yours what else it accepts, and "
                    "whether it can pick up.\n")

        return SkillResponse(
            content=content,
            success=True,
            data=result,
            requires_consensus=bool(result.get("large_donation")) and not consent_given(context),
            consensus_action=("approve_food_distribution" if result.get("large_donation") and not consent_given(context)
                              else None),
            suggestions=[
                "Find food pantries",
            ],
        )

    async def process_donation(
        self,
        donation_type: str,
        items: list[str],
        quantity: int | None,
        pickup_needed: bool,
        donor_id: str,
    ) -> dict[str, Any]:
        """Process a food donation.

        Args:
            donation_type: Type of donation
            items: List of items being donated
            quantity: Approximate quantity
            pickup_needed: Whether pickup is requested
            donor_id: ID of the donor

        Returns:
            Donation processing result
        """
        # No inventory_system span is wired yet: nothing is recorded, scheduled or sent.
        return {
            "recorded": False,
            "connected": False,
            "pickup_scheduled": False,
            "large_donation": bool(quantity and quantity > 100),
        }

    async def _handle_nutrition_info(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Provide nutrition information and dietary guidance.

        Args:
            request: Request with nutrition query
            context: Execution context

        Returns:
            SkillResponse with nutrition information
        """
        topic = request.entities.get("topic", "general")
        dietary = request.entities.get("dietary", [])

        info = await self.get_nutrition_info(topic, dietary)

        content = f"**Nutrition Information: {topic.title()}**\n\n"
        content += info["overview"] + "\n\n"

        if info.get("tips"):
            content += "**Helpful Tips:**\n"
            for tip in info["tips"]:
                content += f"- {tip}\n"

        if info.get("resources"):
            content += "\n**Worth asking about locally:**\n"
            for resource in info["resources"]:
                content += f"- {resource}\n"

        return SkillResponse(
            content=content,
            success=True,
            data={"topic": topic, "info": info},
            suggestions=[
                "Find food pantries",
            ],
        )

    async def get_nutrition_info(
        self, topic: str, dietary: list[str]
    ) -> dict[str, Any]:
        """Get nutrition information for a topic.

        Args:
            topic: Nutrition topic
            dietary: Specific dietary considerations

        Returns:
            Nutrition information and tips
        """
        # In production, this could integrate with nutrition APIs
        return {
            "topic": topic,
            "overview": (
                "Good nutrition is essential for health and wellbeing. "
                "Focus on fruits, vegetables, whole grains, and lean proteins. "
                "Limit processed foods, added sugars, and excessive sodium."
            ),
            "tips": [
                "Plan meals ahead to save money and reduce waste",
                "Buy seasonal produce for better prices",
                "Cook in batches and freeze portions",
                "Read nutrition labels to make informed choices",
                "Stay hydrated with water instead of sugary drinks",
            ],
            "resources": [
                "SNAP-Ed nutrition classes (free for SNAP recipients)",
                "Community cooking workshops",
                "Local Extension office nutrition programs",
            ],
        }

    async def get_bdi_context(
        self,
        beliefs: list[dict[str, Any]],
        desires: list[dict[str, Any]],
        intentions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Filter BDI context for food access related information.

        Args:
            beliefs: Current belief state
            desires: Current desires/goals
            intentions: Current intentions/plans

        Returns:
            Filtered BDI state relevant to food access
        """
        food_domains = {"food", "nutrition", "snap", "pantry", "hunger"}

        return {
            "beliefs": [
                b for b in beliefs
                if b.get("domain") in food_domains
                or b.get("type") in [
                    "food_security_status",
                    "snap_status",
                    "dietary_needs",
                    "pantry_visit",
                ]
            ],
            "desires": [
                d for d in desires
                if d.get("type") in [
                    "food_access",
                    "snap_enrollment",
                    "nutrition_improvement",
                ]
            ],
            "intentions": [
                i for i in intentions
                if i.get("domain") in food_domains
            ],
        }
