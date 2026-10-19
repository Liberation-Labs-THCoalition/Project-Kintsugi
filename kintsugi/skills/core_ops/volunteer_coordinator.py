"""Skill Chip: Volunteer Coordinator

Domain: OPERATIONS
Spans: twilio_sms, calendar_api, geocoding
EFE Profile: risk=0.33, ambiguity=0.34, epistemic=0.33
Description: Coordinates volunteer scheduling, communications, and skill-to-need matching.

Volunteer Coordinator Skill Chip for Kintsugi CMA.

This chip coordinates volunteer scheduling, communications, and engagement
for nonprofit organizations. It helps staff manage volunteer availability,
match skills to needs, send reminders, and track hours.

Key capabilities:
- Find available volunteers for shifts or events
- Schedule and manage volunteer assignments
- Send reminders and notifications via SMS/email
- Log and track volunteer hours
- Match volunteer skills to organizational needs

Example:
    chip = VolunteerCoordinatorChip()
    request = SkillRequest(
        intent="volunteer_schedule",
        entities={"volunteer_id": "vol_123", "shift_date": "2024-01-15", "role": "food_prep"}
    )
    response = await chip.handle(request, context)
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Awaitable, Callable

from kintsugi.skills import (
    BaseSkillChip,
    EFEWeights,
    SkillCapability,
    SkillContext,
    SkillDomain,
    SkillRequest,
    SkillResponse,
    register_chip,
)
from kintsugi.skills.base import consent_given, current_org, org_scoped
from kintsugi.skills.honesty import not_connected


class VolunteerStatus(str, Enum):
    """Status of a volunteer in the system."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ON_LEAVE = "on_leave"
    PENDING = "pending"


class ShiftStatus(str, Enum):
    """Status of a volunteer shift."""
    SCHEDULED = "scheduled"
    CONFIRMED = "confirmed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


@dataclass
class Volunteer:
    """Represents a volunteer in the system.

    Attributes:
        id: Unique volunteer identifier
        name: Full name
        email: Email address
        phone: Phone number for SMS
        skills: List of skills/certifications
        availability: Weekly availability pattern
        status: Current volunteer status
        total_hours: Total hours volunteered
        preferred_roles: Preferred volunteer roles
    """
    id: str
    name: str
    email: str
    phone: str = ""
    skills: list[str] = field(default_factory=list)
    availability: dict[str, list[str]] = field(default_factory=dict)
    status: VolunteerStatus = VolunteerStatus.ACTIVE
    total_hours: float = 0.0
    preferred_roles: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "skills": self.skills,
            "availability": self.availability,
            "status": self.status.value,
            "total_hours": self.total_hours,
            "preferred_roles": self.preferred_roles,
        }


@dataclass
class Shift:
    """Represents a volunteer shift or assignment.

    Attributes:
        id: Unique shift identifier
        date: Date of the shift
        start_time: Start time
        end_time: End time
        role: Role or position for this shift
        location: Physical or virtual location
        volunteer_id: Assigned volunteer ID (if any)
        status: Current shift status
        notes: Additional notes
    """
    id: str
    date: datetime
    start_time: str
    end_time: str
    role: str
    location: str = ""
    volunteer_id: str | None = None
    status: ShiftStatus = ShiftStatus.SCHEDULED
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "date": self.date.isoformat(),
            "start_time": self.start_time,
            "end_time": self.end_time,
            "role": self.role,
            "location": self.location,
            "volunteer_id": self.volunteer_id,
            "status": self.status.value,
            "notes": self.notes,
        }


class VolunteerCoordinatorChip(BaseSkillChip):
    """Coordinate volunteer scheduling, communications, and engagement.

    This chip helps nonprofit organizations manage their volunteer workforce
    by providing scheduling, communication, and tracking capabilities.

    Intents handled:
        - volunteer_schedule: Schedule a volunteer for a shift
        - volunteer_search: Find volunteers matching criteria
        - volunteer_notify: Send notifications to volunteers
        - volunteer_hours: Log or report volunteer hours
        - volunteer_match: Match volunteer skills to needs

    Consensus actions:
        - mass_notification: Requires approval for bulk messages
        - schedule_change_all: Requires approval for widespread schedule changes

    Example:
        chip = VolunteerCoordinatorChip()
        request = SkillRequest(
            intent="volunteer_search",
            entities={"skill": "food_safety", "date": "2024-01-15"}
        )
        response = await chip.handle(request, context)
    """

    name = "volunteer_coordinator"
    description = "Coordinate volunteer scheduling, communications, and engagement"
    version = "1.0.0"
    domain = SkillDomain.OPERATIONS

    efe_weights = EFEWeights(
        mission_alignment=0.20,
        stakeholder_benefit=0.35,
        resource_efficiency=0.20,
        transparency=0.10,
        equity=0.15,
    )

    capabilities = [
        SkillCapability.READ_DATA,
        SkillCapability.WRITE_DATA,
        SkillCapability.SEND_NOTIFICATIONS,
        SkillCapability.SCHEDULE_TASKS,
    ]

    consensus_actions = ["mass_notification", "schedule_change_all"]
    # Consensus: which intents ask for which action, held before handle() runs (kintsugi/governance/consumer.py).
    consensus_intents = {"volunteer_notify": "mass_notification"}
    # Who approves (Vera, 10-18): money and private info take two people (FINANCIAL, PII); the rest one.
    consensus_categories = {"mass_notification": "EXTERNAL_COMMS"}
    # A method, not a lambda: "mass" counts what this requester has already sent in the last day, so ten batches of
    # ten aren't ten small notices (Vera, 10-18 follow-ons).
    consensus_when = {"volunteer_notify": "_asks_mass"}
    MASS_LIMIT = 10
    MASS_WINDOW_HOURS = 24
    # sender (person_of) -> [(when, how many), ...], this org's alone. In memory: a crash or deploy resets the window.
    # Persist it when the consent file next changes shape, not before (Vera, 10-19).
    _notified = org_scoped(dict)
    consensus_unreachable = {
        "schedule_change_all": "no intent performs this yet: declared for a future one, so it can't happen ungated",
    }
    required_spans = ["twilio_sms", "calendar_api", "geocoding"]
    # Honest without its spans (kintsugi/skills/honesty.py): the roster and the sender are the deployment's
    # (VolunteerCoordinatorChip(roster=..., sender=...)). Without a roster no volunteer is listed; without a sender
    # nothing is sent and it says so; a shift or logged hours aren't saved anywhere, and it says so. The mass limit
    # counts only real sends.
    simulated = False

    def __init__(self, roster: Callable[[str], list["Volunteer"]] | None = None,
                 sender: Callable[["Volunteer", str, str], Awaitable[bool]] | None = None) -> None:
        super().__init__()
        # roster(org_id) -> that org's volunteers; sender(volunteer, channel, message) -> True once delivered.
        self.roster = roster
        self.sender = sender

    def while_held(self, action: str) -> str:
        if action == "mass_notification" and self.sender is None:
            return not_connected("A messaging service", "approving this will not send anything")
        return ""

    SUPPORTED_INTENTS = {
        "volunteer_schedule": "_handle_schedule",
        "volunteer_search": "_handle_search",
        "volunteer_notify": "_handle_notify",
        "volunteer_hours": "_handle_hours",
        "volunteer_match": "_handle_match",
    }

    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Route request to appropriate handler based on intent.

        Args:
            request: The skill request with intent and entities
            context: Execution context with org, user, BDI state

        Returns:
            SkillResponse with volunteer information or confirmation
        """
        handler_name = self.SUPPORTED_INTENTS.get(request.intent)

        if handler_name is None:
            return SkillResponse(
                content=f"Unknown intent '{request.intent}' for volunteer_coordinator chip.",
                success=False,
                data={"supported_intents": list(self.SUPPORTED_INTENTS.keys())},
            )

        handler = getattr(self, handler_name)
        return await handler(request, context)

    async def get_bdi_context(
        self,
        beliefs: list[dict[str, Any]],
        desires: list[dict[str, Any]],
        intentions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Extract operations-relevant BDI context.

        Filters BDI state to return beliefs about volunteer capacity,
        program needs, and scheduling state.
        """
        ops_types = {"volunteer_capacity", "staffing_needs", "event_schedule", "program_demand"}

        filtered_beliefs = [
            b for b in beliefs
            if b.get("type") in ops_types or b.get("domain") == "operations"
        ]

        filtered_desires = [
            d for d in desires
            if d.get("type") in {"coverage_goal", "engagement_target", "retention_goal"}
        ]

        return {
            "beliefs": filtered_beliefs,
            "desires": filtered_desires,
            "intentions": intentions,
        }

    async def _handle_schedule(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Schedule a volunteer for a shift or event.

        Supported entities:
            - volunteer_id: ID of volunteer to schedule
            - shift_id: ID of existing shift to fill
            - date: Date for new shift
            - start_time: Shift start time
            - end_time: Shift end time
            - role: Role or position
            - location: Location of shift
        """
        entities = request.entities
        volunteer_id = entities.get("volunteer_id")
        shift_id = entities.get("shift_id")

        if not volunteer_id:
            return SkillResponse(
                content="Please specify a volunteer to schedule.",
                success=False,
            )

        # Get volunteer details
        volunteer = await self._get_volunteer(volunteer_id)
        if not volunteer:
            return SkillResponse(
                content=f"Volunteer '{volunteer_id}' not found.",
                success=False,
            )

        # Schedule the shift
        result = await self.schedule_shift(
            volunteer_id=volunteer_id,
            shift_id=shift_id,
            date=entities.get("date"),
            start_time=entities.get("start_time"),
            end_time=entities.get("end_time"),
            role=entities.get("role", "general"),
            location=entities.get("location", ""),
        )

        if not result["success"]:
            return SkillResponse(
                content=f"Could not schedule: {result['reason']}",
                success=False,
                data=result,
            )

        shift = result["shift"]
        content = (
            f"Draft shift for **{volunteer.name}**: {shift.role}\n"
            f"Date: {shift.date.strftime('%A, %B %d, %Y')}\n"
            f"Time: {shift.start_time} - {shift.end_time}\n"
            f"Location: {shift.location or 'TBD'}\n\n"
            f"{not_connected('A shift calendar', 'this shift has not been saved anywhere and nobody has been told')}"
        )

        return SkillResponse(
            content=content,
            success=True,
            data={"shift": shift.to_dict(), "volunteer": volunteer.to_dict(), "saved": False},
            suggestions=[],
        )

    async def _handle_search(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Search for available volunteers.

        Supported entities:
            - date: Date to check availability
            - time_slot: Time slot to check
            - skill: Required skill or certification
            - role: Role to fill
            - location: Preferred location (for distance matching)
        """
        entities = request.entities

        volunteers = await self.find_available(
            date=entities.get("date"),
            time_slot=entities.get("time_slot"),
            skill=entities.get("skill"),
            role=entities.get("role"),
            location=entities.get("location"),
            org_id=context.org_id,
        )

        if not volunteers:
            content = ("No available volunteers found matching your criteria." if self.roster else
                       not_connected("A volunteer roster", "I can't list or search your volunteers"))
            return SkillResponse(
                content=content,
                success=True,
                data={"volunteers": [], "connected": self.roster is not None},
                suggestions=["Try broadening your search criteria"] if self.roster else [],
            )

        content_lines = [f"Found {len(volunteers)} available volunteers:\n"]
        for v in volunteers[:10]:
            skills_str = ", ".join(v.skills[:3]) if v.skills else "General"
            content_lines.append(
                f"- **{v.name}** - Skills: {skills_str} | Hours: {v.total_hours:.0f}"
            )

        return SkillResponse(
            content="\n".join(content_lines),
            success=True,
            data={"volunteers": [v.to_dict() for v in volunteers]},
            suggestions=["Schedule one of these volunteers?"],
        )

    async def _handle_notify(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Send notifications to volunteers.

        Supported entities:
            - volunteer_ids: List of volunteer IDs (or "all" for mass)
            - message: Message content
            - channel: Notification channel (sms, email, both)
            - notification_type: Type (reminder, update, urgent)
        """
        entities = request.entities
        volunteer_ids = entities.get("volunteer_ids", [])
        message = entities.get("message", "")
        channel = entities.get("channel", "both")
        notification_type = entities.get("notification_type", "update")

        if not message:
            return SkillResponse(
                content="Please provide a message to send.",
                success=False,
            )

        # Check if this is a mass notification requiring consensus
        is_mass = self._asks_mass(request, context)
        if is_mass and not consent_given(context):
            return SkillResponse(
                content="Mass notification requires approval. Please confirm to proceed.",
                success=True,
                requires_consensus=True,
                consensus_action="mass_notification",
                data={
                    "volunteer_count": len(volunteer_ids) if isinstance(volunteer_ids, list) else "all",
                    "message_preview": message[:100],
                    "channel": channel,
                },
            )

        if volunteer_ids == "all":
            # "all" means every volunteer in this org; it used to be iterated as the letters "a", "l", "l"
            volunteer_ids = [v.id for v in await self._get_all_volunteers(context.org_id)]

        # Send notifications
        result = await self.send_reminder(
            volunteer_ids=volunteer_ids,
            message=message,
            channel=channel,
            notification_type=notification_type,
        )

        if result["sent"]:
            self._notified.setdefault(self._sender(context), []).append(
                (datetime.now(timezone.utc).isoformat(), result["sent"]))

        if self.roster is None:
            content = not_connected("A volunteer roster", "I can't reach any volunteer, and nothing was sent")
        elif self.sender is None:
            content = (f"{not_connected('A messaging service', 'nothing was sent')} "
                       f"Contact the {result['reachable']} volunteer(s) directly.")
        else:
            content = f"Delivered to {result['sent']} volunteer(s); {result['failed']} not delivered."
        return SkillResponse(
            content=content,
            success=result["sent"] > 0,
            data=result,
        )

    @staticmethod
    def _sender(context: SkillContext) -> str:
        """Who is sending, as a person when their key names one: one person's two keys share one limit."""
        from kintsugi.security.api_keys import person_of
        return person_of(context.user_id)

    def _sent_recently(self, requester: str) -> int:
        """How many volunteers this requester notified in the last MASS_WINDOW_HOURS, in this org."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.MASS_WINDOW_HOURS)
        recent = [(t, n) for t, n in self._notified.get(requester, []) if datetime.fromisoformat(t) >= cutoff]
        self._notified[requester] = recent
        return sum(n for _, n in recent)

    def _asks_mass(self, request: SkillRequest, context: SkillContext) -> bool:
        """A notice is mass when it goes to "all", to more than MASS_LIMIT people, or would take this requester past
        MASS_LIMIT within the window: batches of ten add up."""
        ids = request.entities.get("volunteer_ids", [])
        if ids == "all":
            return True
        return len(ids) > self.MASS_LIMIT or self._sent_recently(self._sender(context)) + len(ids) > self.MASS_LIMIT

    async def _handle_hours(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Log or report volunteer hours.

        Supported entities:
            - volunteer_id: Volunteer to log/report hours for
            - action: "log" or "report"
            - hours: Hours to log (for log action)
            - date: Date of volunteer work
            - shift_id: Associated shift ID
            - date_range: For reports (e.g., "this_month", "ytd")
        """
        entities = request.entities
        action = entities.get("action", "report")
        volunteer_id = entities.get("volunteer_id")

        if action == "log":
            if not volunteer_id or not entities.get("hours"):
                return SkillResponse(
                    content="Please specify volunteer_id and hours to log.",
                    success=False,
                )

            result = await self.log_hours(
                volunteer_id=volunteer_id,
                hours=entities["hours"],
                date=entities.get("date"),
                shift_id=entities.get("shift_id"),
                notes=entities.get("notes", ""),
            )

            if not result.get("success"):
                return SkillResponse(content=f"Could not log hours: {result['reason']}", success=False, data=result)
            return SkillResponse(
                content=(f"{entities['hours']} hours for {volunteer_id}: "
                         f"{not_connected('A volunteer database', 'they have not been recorded anywhere')} "
                         "Record them in your volunteer records."),
                success=True,
                data=result,
            )

        else:  # report
            date_range = entities.get("date_range", "this_month")
            report = await self._generate_hours_report(
                volunteer_id=volunteer_id,
                org_id=context.org_id,
                date_range=date_range,
            )

            return SkillResponse(
                content=report["summary"],
                success=True,
                data=report,
                suggestions=[],
            )

    async def _handle_match(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        """Match volunteer skills to organizational needs.

        Supported entities:
            - need_type: Type of need to match
            - required_skills: Skills needed
            - date: Date of need
            - urgency: How urgent (low, medium, high)
        """
        entities = request.entities
        required_skills = entities.get("required_skills", [])
        need_type = entities.get("need_type", "general")

        matches = await self.match_skills_to_needs(
            required_skills=required_skills,
            need_type=need_type,
            date=entities.get("date"),
            org_id=context.org_id,
        )

        if not matches:
            content = ("No volunteers found with matching skills." if self.roster else
                       not_connected("A volunteer roster", "I can't match anyone's skills"))
            suggestions = []
        else:
            content_lines = [f"Found {len(matches)} volunteers matching '{need_type}':\n"]
            for m in matches[:5]:
                match_pct = m["match_score"] * 100
                content_lines.append(
                    f"- **{m['volunteer']['name']}** - {match_pct:.0f}% match\n"
                    f"  Skills: {', '.join(m['matching_skills'])}"
                )
            content = "\n".join(content_lines)
            suggestions = ["Draft a shift for the top match"]

        return SkillResponse(
            content=content,
            success=True,
            data={"matches": matches},
            suggestions=suggestions,
        )

    # Core implementation methods

    async def find_available(
        self,
        date: str | None = None,
        time_slot: str | None = None,
        skill: str | None = None,
        role: str | None = None,
        location: str | None = None,
        org_id: str = "",
    ) -> list[Volunteer]:
        """Find volunteers available for a given date/time with optional skill filter.

        Args:
            date: Date to check availability (YYYY-MM-DD)
            time_slot: Time slot (morning, afternoon, evening)
            skill: Required skill or certification
            role: Preferred role
            location: Location for distance matching
            org_id: Organization identifier

        Returns:
            List of available volunteers sorted by relevance
        """
        all_volunteers = await self._get_all_volunteers(org_id)

        available = []
        for v in all_volunteers:
            if v.status != VolunteerStatus.ACTIVE:
                continue

            # Check skill match
            if skill and skill.lower() not in [s.lower() for s in v.skills]:
                continue

            # Check role preference
            if role and v.preferred_roles and role.lower() not in [r.lower() for r in v.preferred_roles]:
                # Don't exclude, but could lower ranking
                pass

            # Check availability for date/time
            if date and time_slot:
                day_of_week = datetime.fromisoformat(date).strftime("%A").lower()
                day_availability = v.availability.get(day_of_week, [])
                if time_slot.lower() not in [t.lower() for t in day_availability]:
                    continue

            available.append(v)

        # Sort by total hours (reward experienced volunteers)
        available.sort(key=lambda x: x.total_hours, reverse=True)

        return available

    async def schedule_shift(
        self,
        volunteer_id: str,
        shift_id: str | None = None,
        date: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        role: str = "general",
        location: str = "",
    ) -> dict[str, Any]:
        """Schedule a volunteer for a shift.

        Args:
            volunteer_id: Volunteer to schedule
            shift_id: Existing shift ID to fill
            date: Date for new shift
            start_time: Start time
            end_time: End time
            role: Role or position
            location: Location of shift

        Returns:
            Dictionary with success status and shift details
        """
        # Validate volunteer exists and is available
        volunteer = await self._get_volunteer(volunteer_id)
        if not volunteer:
            return {"success": False, "reason": "Volunteer not found"}

        if volunteer.status != VolunteerStatus.ACTIVE:
            return {"success": False, "reason": f"Volunteer is {volunteer.status.value}"}

        # Create or update shift
        if shift_id:
            shift = await self._get_shift(shift_id)
            if not shift:
                return {"success": False, "reason": "Shift not found"}
            shift.volunteer_id = volunteer_id
            shift.status = ShiftStatus.SCHEDULED
        else:
            if not date or not start_time or not end_time:
                return {"success": False, "reason": "Date and times required for new shift"}

            shift = Shift(
                id=f"shift_{datetime.now().timestamp()}",
                date=datetime.fromisoformat(date),
                start_time=start_time,
                end_time=end_time,
                role=role,
                location=location,
                volunteer_id=volunteer_id,
                status=ShiftStatus.SCHEDULED,
            )

        # Not saved: no calendar_api span is wired yet. The response says so.
        return {"success": True, "shift": shift, "saved": False}

    async def send_reminder(
        self,
        volunteer_ids: list[str],
        message: str,
        channel: str = "both",
        notification_type: str = "reminder",
    ) -> dict[str, Any]:
        """Send reminders or notifications to volunteers.

        Args:
            volunteer_ids: List of volunteer IDs to notify
            message: Message content
            channel: Channel to use (sms, email, both)
            notification_type: Type of notification

        Returns:
            Dictionary with send statistics
        """
        sent = 0
        failed = 0
        reachable = 0
        results = []

        for vol_id in volunteer_ids:
            volunteer = await self._get_volunteer(vol_id)
            if not volunteer:
                failed += 1
                results.append({"volunteer_id": vol_id, "status": "not_found"})
                continue

            channels = [c for c, ok in (("sms", channel in ("sms", "both") and volunteer.phone),
                                        ("email", channel in ("email", "both") and volunteer.email)) if ok]
            if not channels:
                failed += 1
                results.append({"volunteer_id": vol_id, "status": "no_contact_info"})
                continue
            reachable += 1
            if self.sender is None:
                # Nothing is connected to send through: nothing is sent, and nothing is counted as sent.
                results.append({"volunteer_id": vol_id, "status": "not_sent", "channels": channels})
                continue
            delivered = {c: bool(await self.sender(volunteer, c, message)) for c in channels}
            if any(delivered.values()):
                sent += 1
                results.append({"volunteer_id": vol_id, "name": volunteer.name, "status": "sent",
                                "channels": {c: ("sent" if ok else "failed") for c, ok in delivered.items()}})
            else:
                failed += 1
                results.append({"volunteer_id": vol_id, "status": "failed"})

        return {
            "sent": sent,
            "failed": failed,
            "reachable": reachable,
            "connected": self.sender is not None,
            "total": len(volunteer_ids),
            "results": results,
        }

    async def log_hours(
        self,
        volunteer_id: str,
        hours: float,
        date: str | None = None,
        shift_id: str | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        """Log volunteer hours.

        Args:
            volunteer_id: Volunteer who worked
            hours: Hours to log
            date: Date of work
            shift_id: Associated shift if any
            notes: Additional notes

        Returns:
            Dictionary with logging confirmation and new totals
        """
        volunteer = await self._get_volunteer(volunteer_id)
        if not volunteer:
            return {"success": False, "reason": "Volunteer not found"}

        # Not recorded: no volunteer database is wired to write to. The roster's total is left as it is.
        return {
            "success": True,
            "recorded": False,
            "volunteer_id": volunteer_id,
            "hours": hours,
            "date": date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "shift_id": shift_id,
        }

    async def match_skills_to_needs(
        self,
        required_skills: list[str],
        need_type: str,
        date: str | None = None,
        org_id: str = "",
    ) -> list[dict[str, Any]]:
        """Match volunteer skills to organizational needs.

        Args:
            required_skills: Skills needed for the role
            need_type: Type of need (event, program, administrative)
            date: Date of need for availability checking
            org_id: Organization identifier

        Returns:
            List of matches with score and volunteer details
        """
        volunteers = await self.find_available(date=date, org_id=org_id)

        matches = []
        for v in volunteers:
            vol_skills_lower = [s.lower() for s in v.skills]
            matching = [s for s in required_skills if s.lower() in vol_skills_lower]

            if matching:
                match_score = len(matching) / len(required_skills) if required_skills else 0.5
                matches.append({
                    "volunteer": v.to_dict(),
                    "matching_skills": matching,
                    "missing_skills": [s for s in required_skills if s.lower() not in vol_skills_lower],
                    "match_score": match_score,
                })

        # Sort by match score
        matches.sort(key=lambda x: x["match_score"], reverse=True)

        return matches

    # Private helper methods

    async def _get_volunteer(self, volunteer_id: str, org_id: str = "") -> Volunteer | None:
        """Fetch a volunteer by ID from the deployment's roster."""
        for v in await self._get_all_volunteers(org_id):
            if v.id == volunteer_id:
                return v
        return None

    async def _get_all_volunteers(self, org_id: str) -> list[Volunteer]:
        """The deployment's volunteers for this org, or none when no roster is connected (no one is invented)."""
        if self.roster is None:
            return []
        # Every request runs in its own org's scope (the base wrapper), so a caller that passes no org gets that one.
        return list(self.roster(org_id or current_org() or ""))

    async def _get_shift(self, shift_id: str) -> Shift | None:
        """Fetch a shift by ID."""
        # In production, would query database
        return None

    async def _generate_hours_report(
        self,
        volunteer_id: str | None,
        org_id: str,
        date_range: str,
    ) -> dict[str, Any]:
        """Volunteer hours from the deployment's roster, labelled as lifetime totals (no dated records exist)."""
        if self.roster is None:
            return {"summary": not_connected("A volunteer roster", "I have no hours to report"),
                    "connected": False, "date_range": date_range}
        if volunteer_id:
            volunteer = await self._get_volunteer(volunteer_id)
            summary = f"Volunteer Hours Report: {volunteer.name if volunteer else 'Unknown'}\n"
            summary += f"Lifetime total on the roster: {volunteer.total_hours if volunteer else 0:.1f} hours (not by period)"
            return {
                "summary": summary,
                "volunteer_id": volunteer_id,
                "total_hours": volunteer.total_hours if volunteer else 0,
                "date_range": date_range,
            }
        else:
            # Org-wide report
            volunteers = await self._get_all_volunteers(org_id)
            total_hours = sum(v.total_hours for v in volunteers)
            summary = f"Organization Volunteer Hours (lifetime totals on the roster, not by period)\n"
            summary += f"Volunteers: {len(volunteers)}\n"
            summary += f"Total Hours: {total_hours:.1f}\n"
            summary += f"Average Hours/Volunteer: {total_hours / len(volunteers):.1f}" if volunteers else ""
            return {
                "summary": summary,
                "total_volunteers": len(volunteers),
                "total_hours": total_hours,
                "date_range": date_range,
            }
