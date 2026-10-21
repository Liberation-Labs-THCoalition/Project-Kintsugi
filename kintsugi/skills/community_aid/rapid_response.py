"""Skill Chip: Rapid Response

Domain: ADVOCACY
Spans: alert_network, bail_fund, legal_hotline, safe_location_db
EFE Profile: risk=0.33, ambiguity=0.34, epistemic=0.33
Description: Coordinates rapid response networks for ICE raids, bail funds, and community emergencies.

Rapid Response skill chip for Kintsugi CMA.

Coordinates rapid response networks for ICE raids, bail funds, and
community emergencies. Manages encrypted communications with verified
responders and maintains operational security protocols.

CRITICAL: Privacy and security are paramount in this chip. Sensitive
location data is NOT logged. All communications should use encrypted
channels when possible.

Intents handled:
- raid_alert: Report ICE or police activity (the deployment's on-call people get it at once, if any are named and
  reachable; the wide broadcast is held for an admin's approval, and sends through an alert network once one is
  connected). Entities: type, urgency, area (a neighbourhood or cross streets, not a home address), description (kept with the request, never sent to
  on-call)
- bail_request: Ask for bail fund support (held for two approvers; reaches a bail fund once one is connected)
- legal_hotline: Give the deployment's legal hotline
- safe_location: Point to the deployment's safe-location line (never addresses)
- response_debrief: Conduct post-response debriefs

None of its spans is wired yet. Until one is, it says plainly that nobody was alerted and nothing was sent, gives only
the lines a deployment configured (RapidResponseChip(contacts={...})), and otherwise points to 211. It invents no
number, place, count or promise (kintsugi/skills/honesty.py).

Example:
    chip = RapidResponseChip()
    response = await chip.handle(
        SkillRequest(intent="legal_hotline", entities={"urgency": "emergency"}),
        context
    )
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
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
from kintsugi.governance.oncall import general_area
from kintsugi.skills.base import consent_given
from kintsugi.skills.honesty import NOBODY_CONTACTED, not_connected


class AlertType(str, Enum):
    """Types of rapid response alerts."""
    ICE_RAID = "ice_raid"
    POLICE_ACTIVITY = "police_activity"
    WORKPLACE_RAID = "workplace_raid"
    TRAFFIC_CHECKPOINT = "checkpoint"
    COMMUNITY_EMERGENCY = "community_emergency"
    MEDICAL_EMERGENCY = "medical_emergency"


class UrgencyLevel(str, Enum):
    """Urgency levels for rapid response."""
    CRITICAL = "critical"  # Immediate response needed
    URGENT = "urgent"      # Response within 30 minutes
    STANDARD = "standard"  # Response within hours
    INFO = "info"         # Information only, no response needed


class ResponderStatus(str, Enum):
    """Status of verified responders."""
    AVAILABLE = "available"
    RESPONDING = "responding"
    UNAVAILABLE = "unavailable"
    STANDBY = "standby"


@dataclass
class RapidAlert:
    """A rapid response alert."""
    alert_id: str
    alert_type: AlertType
    urgency: UrgencyLevel
    description: str
    # NOTE: Location info intentionally vague for security
    general_area: str  # Neighborhood/area only, no specific addresses logged
    timestamp: datetime
    verified: bool
    responders_notified: int
    active: bool = True
    sent: bool = False  # True only when a connected alert network took it


@dataclass
class Responder:
    """A verified rapid response volunteer."""
    responder_id: str
    name: str  # First name only for privacy
    roles: list[str]
    languages: list[str]
    status: ResponderStatus
    last_active: datetime
    trainings_completed: list[str]
    # No location data stored for responders


@dataclass
class BailRequest:
    """A bail fund request (sensitive data minimized)."""
    request_id: str
    urgency: UrgencyLevel
    amount_needed: float
    status: str
    created: datetime
    # No identifying information stored here - linked via secure system


@dataclass
class SafeLocation:
    """A safe location for emergencies (details provided securely)."""
    location_id: str
    location_type: str  # sanctuary, legal_aid, medical, etc.
    general_area: str  # Neighborhood only
    services: list[str]
    languages: list[str]
    hours: str
    contact_method: str  # How to get specific address securely


class RapidResponseChip(BaseSkillChip):
    """Coordinate rapid response networks for emergencies.

    This chip manages rapid response communications for ICE raids,
    bail fund requests, and community emergencies. It prioritizes
    operational security and privacy - sensitive location data is
    never logged or stored.

    SECURITY PRINCIPLES:
    - No specific addresses logged
    - No identifying information stored unnecessarily
    - Encrypted communications preferred
    - Verified responder network
    - Operational security protocols enforced

    Attributes:
        name: Unique chip identifier
        description: Human-readable description
        domain: ADVOCACY domain for community defense
        efe_weights: Mission and stakeholder focused
        capabilities: READ_DATA, WRITE_DATA, SEND_NOTIFICATIONS, PII_ACCESS
        consensus_actions: Actions requiring approval
        required_spans: MCP tool spans needed
    """

    name = "rapid_response"
    description = "Coordinate rapid response networks for ICE raids, bail funds, and emergencies"
    domain = SkillDomain.ADVOCACY
    efe_weights = EFEWeights(
        mission_alignment=0.35,
        stakeholder_benefit=0.35,
        resource_efficiency=0.10,
        transparency=0.10,
        equity=0.10,
    )
    capabilities = [
        SkillCapability.READ_DATA,
        SkillCapability.WRITE_DATA,
        SkillCapability.SEND_NOTIFICATIONS,
        SkillCapability.PII_ACCESS,
    ]
    consensus_actions = ["activate_rapid_response", "release_bail_funds", "share_location_alert"]
    # Consensus: which intents ask for which action, held before handle() runs (kintsugi/governance/consumer.py).
    consensus_intents = {"raid_alert": "activate_rapid_response", "bail_request": "release_bail_funds"}
    # Who approves (Vera, 10-18): money and private info take two people (FINANCIAL, PII); the rest one.
    consensus_categories = {"activate_rapid_response": "EXTERNAL_COMMS", "release_bail_funds": "FINANCIAL"}
    # A raid report reaches the on-call people at once; only the wide broadcast waits (Thomas, 2026-10-19).
    consensus_oncall = {"activate_rapid_response": "raid"}
    consensus_unreachable = {
        "share_location_alert": (
            "advisory: safe_location returns a configured line, never addresses; its flag says this needs approval, "
            "and no intent performs it"
        ),
    }
    required_spans = ["alert_network", "bail_fund", "legal_hotline", "safe_location_db"]
    # Honest without its spans (kintsugi/skills/honesty.py): with nothing connected it says nobody was alerted, gives
    # only the lines a deployment configured, and invents no number, place or promise.
    simulated = False

    # Where to send someone when nothing is connected. US-wide (211) and safe to say during a raid: no police number.
    NO_LINE = "If you don't know one, call 211 and ask for immigrant legal services or a bail fund."
    RIGHTS = (
        "**Your rights (US):**\n"
        "- You have the right to remain silent\n"
        "- You have the right to speak to a lawyer\n"
        "- Do not sign anything you don't understand\n"
    )

    def __init__(self, contacts: dict[str, str] | None = None) -> None:
        super().__init__()
        # The deployment's own lines: rapid_response_hotline, legal_hotline, bail_fund, safe_location_line. A missing
        # one is said to be missing, never filled in.
        self.contacts = dict(contacts or {})

    def _line(self, key: str, what: str) -> str:
        number = self.contacts.get(key)
        return f"Contact {what} directly: **{number}**." if number else f"Contact {what} directly. {self.NO_LINE}"

    def while_held(self, action: str) -> str:
        if action == "activate_rapid_response":
            return (f"{not_connected('A rapid response network', 'approving this will not alert anyone')} "
                    f"If people need help now, don't wait. "
                    f"{self._line('rapid_response_hotline', 'your rapid response hotline')}")
        if action == "release_bail_funds":
            return (f"{not_connected('A bail fund', 'approving this will not move money or reach a coordinator')} "
                    f"{self._line('bail_fund', 'your local bail fund')}")
        return ""

    def oncall_message(self, action: str, request: SkillRequest) -> str:
        """What the on-call people are told: the kind, urgency and general area as reported, never the description,
        which may hold an address or a name."""
        try:
            kind = AlertType(request.entities.get("type", "ice_raid")).value
        except ValueError:
            kind = AlertType.COMMUNITY_EMERGENCY.value
        try:
            urgency = UrgencyLevel(request.entities.get("urgency", "urgent")).value
        except ValueError:
            urgency = UrgencyLevel.URGENT.value
        return (f"Raid report: {kind.replace('_', ' ')}, {urgency}. Area as reported: "
                f"{general_area(request.entities.get('area'))}.")

    # Security notice included in relevant responses
    SECURITY_NOTICE = (
        "SECURITY REMINDER: Do not share specific addresses or identifying "
        "information in unsecured channels. Use encrypted communications when possible."
    )

    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Route request to appropriate handler based on intent.

        Args:
            request: The skill request with intent and entities
            context: Execution context including org, user, BDI state

        Returns:
            SkillResponse with rapid response information
        """
        handlers = {
            "raid_alert": self._handle_raid_alert,
            "bail_request": self._handle_bail_request,
            "legal_hotline": self._handle_legal_hotline,
            "safe_location": self._handle_safe_location,
            "response_debrief": self._handle_debrief,
        }

        handler = handlers.get(request.intent)
        if not handler:
            return SkillResponse(
                content=f"Unknown intent: {request.intent}. Supported intents: {list(handlers.keys())}",
                success=False,
            )

        return await handler(request, context)

    async def _handle_raid_alert(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Handle raid or activity alerts.

        Args:
            request: Request with alert details
            context: Execution context

        Returns:
            SkillResponse with alert status
        """
        alert_type = request.entities.get("type", "ice_raid")
        urgency = request.entities.get("urgency", "urgent")
        # NOTE: We only store general area, never specific addresses
        general_area = request.entities.get("area")
        description = request.entities.get("description", "Activity reported")
        verified = request.entities.get("verified", False)

        # Create alert - specific location never logged
        alert = await self.send_raid_alert(
            alert_type=alert_type,
            urgency=urgency,
            general_area=general_area,
            description=description,
            verified=verified,
        )

        content = "**Raid report: nobody has been alerted.**\n\n"
        content += (f"{not_connected('A rapid response network', 'this report has not reached any responders or legal observers')} "
                    f"{NOBODY_CONTACTED}\n\n")
        content += f"Type: {alert.alert_type.value.replace('_', ' ')}. Urgency: {alert.urgency.value}. Area: {alert.general_area}.\n\n"
        content += "**Do this now:**\n"
        content += f"- {self._line('rapid_response_hotline', 'your rapid response hotline')}\n"
        content += "- Share only general areas, never addresses or names, in unsecured channels.\n\n"
        content += self.RIGHTS
        content += f"\n{self.SECURITY_NOTICE}"

        return SkillResponse(
            content=content,
            success=True,
            data={
                "sent": alert.sent,
                "connected": False,
                "responders_notified": alert.responders_notified,
                "type": alert.alert_type.value,
                "urgency": alert.urgency.value,
            },
            requires_consensus=not consent_given(context),       # the approved run carries it out
            consensus_action=None if consent_given(context) else "activate_rapid_response",
            suggestions=[
                "Connect to legal hotline",
                "Find safe locations",
                "Get know-your-rights info",
            ],
        )

    async def send_raid_alert(
        self,
        alert_type: str,
        urgency: str,
        general_area: str | None,
        description: str,
        verified: bool = False,
    ) -> RapidAlert:
        """Send an alert to the rapid response network.

        NOTE: This method intentionally does NOT log specific locations.
        Only general neighborhood information is stored.

        Args:
            alert_type: Type of alert
            urgency: Urgency level
            general_area: General neighborhood (not specific address)
            description: Brief description
            verified: Whether alert has been verified

        Returns:
            Created alert object
        """
        # Nothing is connected: no alert network span is wired yet, so nothing is sent and nobody is counted. When one
        # is, it sends here and sets sent=True and the real count.

        try:
            alert_type_enum = AlertType(alert_type)
        except ValueError:
            alert_type_enum = AlertType.COMMUNITY_EMERGENCY

        try:
            urgency_enum = UrgencyLevel(urgency)
        except ValueError:
            urgency_enum = UrgencyLevel.URGENT

        return RapidAlert(
            alert_id="",
            alert_type=alert_type_enum,
            urgency=urgency_enum,
            description=description,
            general_area=general_area or "Area not specified",
            timestamp=datetime.now(timezone.utc),
            verified=verified,
            responders_notified=0,
            active=False,
            sent=False,
        )

    async def _handle_bail_request(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Handle bail fund requests.

        Args:
            request: Request with bail details
            context: Execution context

        Returns:
            SkillResponse with bail request status
        """
        urgency = request.entities.get("urgency", "urgent")
        amount = request.entities.get("amount")
        case_type = request.entities.get("case_type")

        result = await self.request_bail_support(
            urgency=urgency,
            amount=amount,
            case_type=case_type,
        )

        content = "**Bail request: it hasn't reached anyone.**\n\n"
        content += (f"{not_connected('A bail fund', 'no coordinator has been told and no money can move')} "
                    f"{NOBODY_CONTACTED}\n\n")
        content += "**Do this now:**\n"
        content += f"- {self._line('bail_fund', 'your local bail fund')}\n"
        content += "\n**Have ready:**\n"
        for item in result["have_ready"]:
            content += f"- {item}\n"
        content += f"\n{self.SECURITY_NOTICE}"

        return SkillResponse(
            content=content,
            success=True,
            data=result,
            requires_consensus=not consent_given(context),       # the approved run carries it out
            consensus_action=None if consent_given(context) else "release_bail_funds",
            suggestions=[
                "Get legal hotline number",
                "Get know-your-rights info",
            ],
        )

    async def request_bail_support(
        self,
        urgency: str,
        amount: float | None = None,
        case_type: str | None = None,
    ) -> dict[str, Any]:
        """Submit a bail fund support request.

        NOTE: Minimal information stored. Detailed case info
        collected through secure channels only.

        Args:
            urgency: Request urgency level
            amount: Bail amount if known
            case_type: Type of case if known

        Returns:
            Bail request result
        """
        # Nothing is connected: no bail fund span is wired yet, so nothing is submitted and no money moves.
        return {
            "sent": False,
            "connected": False,
            "urgency": urgency,
            "have_ready": [
                "The case or booking number",
                "The name of the detention facility",
                "An emergency contact",
            ],
            "bail_fund_line": self.contacts.get("bail_fund"),
        }

    async def _handle_legal_hotline(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Connect to emergency legal hotline.

        Args:
            request: Request with urgency and type
            context: Execution context

        Returns:
            SkillResponse with hotline connection info
        """
        urgency = request.entities.get("urgency", "standard")
        issue_type = request.entities.get("type", "general")
        language = request.entities.get("language", "en")

        hotline = await self.connect_legal_hotline(
            urgency=urgency,
            issue_type=issue_type,
            language=language,
        )

        content = "**Legal hotline**\n\n"
        if hotline["number"]:
            content += f"Your organization's legal hotline: **{hotline['number']}**\n\n"
        else:
            content += (f"{not_connected('A legal hotline', 'I have no number to give you')} "
                        f"Contact a legal aid or immigrant rights organization you trust. {self.NO_LINE}\n\n")
        content += "**Have ready when you call:**\n"
        for item in hotline["prepare"]:
            content += f"- {item}\n"
        content += "\n" + self.RIGHTS

        return SkillResponse(
            content=content,
            success=True,
            data=hotline,
            suggestions=[
                "Get know-your-rights info",
                "Find safe locations",
            ],
        )

    async def connect_legal_hotline(
        self,
        urgency: str,
        issue_type: str,
        language: str,
    ) -> dict[str, Any]:
        """Connect to the appropriate legal hotline.

        Args:
            urgency: Urgency level
            issue_type: Type of legal issue
            language: Preferred language

        Returns:
            Hotline connection information
        """
        # Only the deployment's own line: no legal_hotline span is wired yet, so nothing about hours, languages or wait
        # times is known, and none is claimed.
        return {
            "number": self.contacts.get("legal_hotline"),
            "connected": False,
            "prepare": [
                "Where the person needing help is (a general area is enough to start)",
                "Any case or booking numbers",
                "The name of the detention facility, if there is one",
                "A short description of what happened",
            ],
        }

    async def _handle_safe_location(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Find safe locations during emergencies.

        NOTE: Specific addresses are NEVER included in responses.
        Users are connected to coordinators who provide locations
        through secure channels.

        Args:
            request: Request with location needs
            context: Execution context

        Returns:
            SkillResponse with safe location process
        """
        location_type = request.entities.get("type", "general")
        services_needed = request.entities.get("services", [])
        language = request.entities.get("language", "en")

        locations = await self.find_safe_locations(
            location_type=location_type,
            services=services_needed,
            language=language,
        )

        content = "**Safe locations**\n\n"
        content += "*Specific addresses are never shared here: only through a secure channel, by people you trust.*\n\n"
        line = self.contacts.get("safe_location_line")
        if line:
            content += f"To find a safe place, call your organization's line: **{line}**.\n\n"
        else:
            content += (f"{not_connected('A safe-location directory', 'I can\'t list safe places')} "
                        f"Contact your rapid response network or a local organization you trust. {self.NO_LINE}\n\n")
        content += f"{self.SECURITY_NOTICE}"

        return SkillResponse(
            content=content,
            success=True,
            data={
                "locations_available": len(locations),
                "connected": False,
                "safe_location_line": line,
            },
            requires_consensus=True,
            consensus_action="share_location_alert",
            suggestions=[
                "Connect to legal hotline",
                "Get know-your-rights info",
            ],
        )

    async def find_safe_locations(
        self,
        location_type: str,
        services: list[str],
        language: str,
    ) -> list[SafeLocation]:
        """Find safe locations matching criteria.

        NOTE: Returns only general information. Specific addresses
        are NEVER returned through this method - only through
        verified secure channels.

        Args:
            location_type: Type of safe location needed
            services: Services required
            language: Language support needed

        Returns:
            List of safe location options (without specific addresses)
        """
        # No safe_location_db span is wired yet, so there are no places to list, and none is made up.
        return []

    async def _handle_debrief(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Conduct post-response debrief.

        Args:
            request: Request with debrief details
            context: Execution context

        Returns:
            SkillResponse with debrief structure
        """
        alert_id = request.entities.get("alert_id")
        response_type = request.entities.get("type", "general")

        debrief = await self.conduct_debrief(
            alert_id=alert_id,
            response_type=response_type,
        )

        content = "**RAPID RESPONSE DEBRIEF**\n\n"
        content += f"Response ID: {debrief['response_id']}\n"
        content += f"Date: {debrief['date']}\n\n"

        content += "**Debrief Questions:**\n"
        for i, question in enumerate(debrief["questions"], 1):
            content += f"{i}. {question}\n"

        content += "\n**Documentation Guidelines:**\n"
        for guideline in debrief["documentation_guidelines"]:
            content += f"- {guideline}\n"

        content += "\n**Support:**\n"
        content += "Rapid response work can be stressful. Support worth arranging, if your network doesn't have it yet:\n"
        for resource in debrief["support_resources"]:
            content += f"- {resource}\n"

        content += f"\n{self.SECURITY_NOTICE}"

        return SkillResponse(
            content=content,
            success=True,
            data=debrief,
            suggestions=[
                "Get know-your-rights info",
            ],
        )

    async def conduct_debrief(
        self,
        alert_id: str | None,
        response_type: str,
    ) -> dict[str, Any]:
        """Create a debrief structure for a rapid response.

        Args:
            alert_id: ID of the alert being debriefed
            response_type: Type of response

        Returns:
            Debrief structure and guidelines
        """
        return {
            "response_id": alert_id or f"DEBRIEF-{datetime.now().strftime('%Y%m%d')}",
            "date": datetime.now().strftime("%B %d, %Y"),
            "questions": [
                "What worked well in this response?",
                "What could be improved?",
                "Were there any safety concerns?",
                "Did we have adequate resources/responders?",
                "What follow-up is needed for affected community members?",
                "Are there any training gaps to address?",
                "Were communications effective and secure?",
            ],
            "documentation_guidelines": [
                "Do NOT include specific addresses or locations",
                "Do NOT include names or identifying information",
                "Focus on process improvements, not individuals",
                "Note resource needs for future responses",
                "Highlight successful tactics for training",
            ],
            "support_resources": [
                "A support line for responders",
                "Community care circles",
                "Mental health resources",
                "Peer support",
            ],
        }

    async def get_bdi_context(
        self,
        beliefs: list[dict[str, Any]],
        desires: list[dict[str, Any]],
        intentions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Filter BDI context for rapid response information.

        NOTE: This method filters carefully to avoid exposing
        sensitive location or timing information in BDI state.

        Args:
            beliefs: Current belief state
            desires: Current desires/goals
            intentions: Current intentions/plans

        Returns:
            Filtered BDI state (security-conscious)
        """
        # Security-conscious filtering - exclude location beliefs
        safe_belief_types = {
            "response_readiness",
            "network_status",
            "training_status",
            "resource_availability",
        }
        response_domains = {"rapid_response", "community_defense", "bail_fund"}

        return {
            "beliefs": [
                b for b in beliefs
                if b.get("type") in safe_belief_types
                and "location" not in str(b).lower()
                and "address" not in str(b).lower()
            ],
            "desires": [
                d for d in desires
                if d.get("type") in [
                    "community_safety",
                    "response_readiness",
                    "network_strength",
                ]
            ],
            "intentions": [
                i for i in intentions
                if i.get("domain") in response_domains
                and "location" not in str(i).lower()
            ],
        }
