"""Skill Chip: Event Planner

Domain: OPERATIONS
Spans: calendar_api, rsvp_system, venue_booking, accessibility_checker
EFE Profile: risk=0.33, ambiguity=0.34, epistemic=0.33
Description: Plans and coordinates events including RSVPs, logistics, and accessibility compliance.

Event Planner Skill Chip for Kintsugi CMA.

Plans and coordinates events including RSVPs, logistics, accessibility,
and follow-up communications. Balances stakeholder benefit with resource
efficiency while ensuring equitable access through accessibility features.

Example:
    chip = EventPlannerChip()
    request = SkillRequest(
        intent="event_create",
        entities={"event_name": "Annual Gala", "event_date": "2024-05-15"},
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
class Event:
    """Represents an event."""
    event_id: str
    name: str
    event_type: str  # gala, workshop, meeting, conference, webinar
    date: datetime
    end_date: datetime | None = None
    location: str = ""
    virtual_link: str | None = None
    capacity: int = 100
    status: str = "draft"  # draft, published, cancelled, completed
    description: str = ""
    budget: float = 0.0
    registration_required: bool = True


@dataclass
class RSVP:
    """Represents an event RSVP."""
    rsvp_id: str
    event_id: str
    attendee_name: str
    attendee_email: str
    status: str  # confirmed, declined, tentative, waitlist
    guests: int = 0
    dietary_requirements: str | None = None
    accessibility_needs: list[str] = field(default_factory=list)
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AccessibilityFeature:
    """Represents an accessibility accommodation."""
    feature_id: str
    category: str  # mobility, visual, hearing, cognitive, dietary
    description: str
    available: bool = True
    notes: str = ""


class EventPlannerChip(BaseSkillChip):
    """Plan and coordinate events, RSVPs, logistics, and accessibility.

    This chip supports event planning through creation, RSVP management,
    logistics coordination, accessibility verification, and post-event
    follow-up. Prioritizes stakeholder experience while managing resources.

    Intents:
        event_create: Create new event
        event_rsvp: Manage RSVPs
        event_logistics: Coordinate logistics
        event_accessibility: Check accessibility features
        event_followup: Send follow-up communications

    Example:
        >>> chip = EventPlannerChip()
        >>> request = SkillRequest(intent="event_create", entities={"event_name": "Gala"})
        >>> response = await chip.handle(request, context)
        >>> print(response.data["event"]["event_id"])
    """

    name = "event_planner"
    description = "Plan and coordinate events, RSVPs, logistics, and accessibility"
    version = "1.0.0"
    domain = SkillDomain.OPERATIONS

    efe_weights = EFEWeights(
        mission_alignment=0.20,
        stakeholder_benefit=0.30,
        resource_efficiency=0.25,
        transparency=0.10,
        equity=0.15,
    )

    capabilities = [
        SkillCapability.READ_DATA,
        SkillCapability.WRITE_DATA,
        SkillCapability.SEND_NOTIFICATIONS,
        SkillCapability.SCHEDULE_TASKS,
    ]

    consensus_actions = ["finalize_event", "send_invitations", "commit_budget"]
    # Consensus: which intents ask for which action, held before handle() runs (kintsugi/governance/consumer.py).
    consensus_intents = {}
    consensus_unreachable = {
        "finalize_event": "no intent performs this yet: declared for a future one, so it can't happen ungated",
        # event_followup only drafts and event_logistics only lists what to arrange: nothing sends or spends (10-19)
        "send_invitations": "no intent performs this yet: declared for a future one, so it can't happen ungated",
        "commit_budget": "no intent performs this yet: declared for a future one, so it can't happen ungated",
    }

    required_spans = ["calendar_api", "rsvp_system", "venue_booking", "accessibility_checker"]
    # Honest without its spans (kintsugi/skills/honesty.py): events are drafts, logistics and accessibility are
    # checklists of what to arrange and ask, follow-ups are drafts with [gaps]; no venue, vendor, RSVP, contact, link or
    # result is invented, and nothing is booked, sent or scheduled.
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
            "event_create": self._create_event,
            "event_rsvp": self._manage_rsvps,
            "event_logistics": self._coordinate_logistics,
            "event_accessibility": self._check_accessibility,
            "event_followup": self._send_followup,
        }

        handler = handlers.get(intent)
        if not handler:
            return SkillResponse(
                content=f"Unknown intent '{intent}' for event planner.",
                success=False,
                suggestions=[
                    "Try 'event_create' to create a new event",
                    "Try 'event_rsvp' to manage RSVPs",
                    "Try 'event_logistics' to coordinate logistics",
                ],
            )

        return await handler(request, context, bdi)

    async def get_bdi_context(
        self,
        beliefs: list[dict[str, Any]],
        desires: list[dict[str, Any]],
        intentions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Filter BDI state for event planning context.

        Extracts beliefs about events, venues, and stakeholder
        engagement priorities.
        """
        event_beliefs = [
            b for b in beliefs
            if b.get("domain") in ("events", "operations", "community")
            or b.get("type") in ("venue_status", "budget_available", "stakeholder_interest")
        ]

        event_desires = [
            d for d in desires
            if d.get("type") in ("successful_event", "community_engagement", "donor_cultivation")
            or d.get("domain") == "events"
        ]

        return {
            "beliefs": event_beliefs,
            "desires": event_desires,
            "intentions": intentions,
        }

    async def _create_event(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """Draft an event: date, place, capacity and budget as given, a checklist and milestones. Nothing is saved."""
        event_name = request.entities.get("event_name", "Untitled Event")
        event_type = request.entities.get("event_type", "meeting")
        event_date = request.entities.get("event_date", (datetime.now(timezone.utc) + timedelta(days=30)).isoformat())
        duration_hours = request.entities.get("duration_hours", 2)
        location = request.entities.get("location", "")
        virtual = request.entities.get("virtual", False)
        capacity = request.entities.get("capacity", 50)
        budget = request.entities.get("budget", 0.0)
        description = request.entities.get("description", "")
        virtual_link = request.entities.get("virtual_link") or None
        date_given = "event_date" in request.entities

        event_dt = datetime.fromisoformat(event_date) if isinstance(event_date, str) else event_date
        end_dt = event_dt + timedelta(hours=duration_hours)

        event = Event(
            event_id=f"evt_{uuid4().hex[:8]}",
            name=event_name,
            event_type=event_type,
            date=event_dt,
            end_date=end_dt,
            location=location or ("Virtual" if virtual else "TBD"),
            virtual_link=virtual_link,
            capacity=capacity,
            status="draft",
            description=description,
            budget=budget,
            registration_required=True,
        )

        # Generate event checklist based on type
        checklist = self._generate_event_checklist(event, date_given)

        # Calculate timeline milestones. "Now" in the date's own zone: a date typed without one stays as typed (a naive
        # date used to crash here: naive minus aware).
        now = datetime.now(event_dt.tzinfo)
        days_until_event = (event_dt - now).days

        milestones = []
        if days_until_event >= 60:
            milestones.append({"milestone": "Finalize venue", "target": (event_dt - timedelta(days=60)).isoformat()})
        if days_until_event >= 45:
            milestones.append({"milestone": "Send save-the-dates", "target": (event_dt - timedelta(days=45)).isoformat()})
        if days_until_event >= 30:
            milestones.append({"milestone": "Open registration", "target": (event_dt - timedelta(days=30)).isoformat()})
        if days_until_event >= 14:
            milestones.append({"milestone": "Confirm vendors", "target": (event_dt - timedelta(days=14)).isoformat()})
        if days_until_event >= 7:
            milestones.append({"milestone": "Send reminders", "target": (event_dt - timedelta(days=7)).isoformat()})
        milestones.append({"milestone": "Event day", "target": event_dt.isoformat()})
        milestones.append({"milestone": "Send follow-up", "target": (event_dt + timedelta(days=2)).isoformat()})

        event_data = {
            "event_id": event.event_id,
            "name": event.name,
            "type": event.event_type,
            "date": event.date.isoformat(),
            "end_date": event.end_date.isoformat() if event.end_date else None,
            "duration_hours": duration_hours,
            "location": event.location,
            "virtual_link": event.virtual_link,
            "capacity": event.capacity,
            "status": event.status,
            "description": event.description,
            "budget": event.budget,
            "registration_required": event.registration_required,
            "checklist": checklist,
            "milestones": milestones,
            "days_until_event": days_until_event,
            "saved": False,
        }
        gaps = []
        if not date_given:
            gaps.append("no date was given, so it's a placeholder 30 days out")
        if virtual and not virtual_link:
            gaps.append("there's no video link yet: add your own")

        return SkillResponse(
            content=(f"Draft {event_type} event '{event_name}' for {event_dt.strftime('%B %d, %Y at %I:%M %p')}, "
                     f"capacity {capacity}, with a {len(checklist)}-item checklist. "
                     + (f"Note: {'; '.join(gaps)}. " if gaps else "")
                     + not_connected("A calendar", "it has not been saved, published or booked")),
            success=True,
            data={"event": event_data},
            suggestions=["Draft a logistics checklist", "Draft an accessibility checklist"],
        )

    def _generate_event_checklist(self, event: Event, date_given: bool = True) -> list[dict[str, Any]]:
        """Generate event checklist based on event type: only what the request itself settles is marked done."""
        base_checklist = [
            {"item": "Confirm date and time", "category": "planning", "completed": date_given},
            {"item": "Determine budget", "category": "planning", "completed": event.budget > 0},
            {"item": "Create event description", "category": "planning", "completed": bool(event.description)},
            {"item": "Set up registration", "category": "registration", "completed": False},
            {"item": "Review accessibility needs", "category": "accessibility", "completed": False},
        ]

        if event.event_type in ("gala", "conference"):
            base_checklist.extend([
                {"item": "Book venue", "category": "logistics", "completed": False},
                {"item": "Arrange catering", "category": "logistics", "completed": False},
                {"item": "Plan program/agenda", "category": "content", "completed": False},
                {"item": "Arrange A/V equipment", "category": "logistics", "completed": False},
                {"item": "Coordinate volunteers", "category": "staffing", "completed": False},
                {"item": "Prepare materials/signage", "category": "materials", "completed": False},
            ])

        if event.event_type == "webinar":
            base_checklist.extend([
                {"item": "Set up virtual platform", "category": "technology", "completed": False},
                {"item": "Test technology", "category": "technology", "completed": False},
                {"item": "Prepare presentation", "category": "content", "completed": False},
                {"item": "Plan engagement activities", "category": "content", "completed": False},
            ])

        if event.event_type == "workshop":
            base_checklist.extend([
                {"item": "Develop curriculum", "category": "content", "completed": False},
                {"item": "Prepare handouts", "category": "materials", "completed": False},
                {"item": "Arrange supplies", "category": "logistics", "completed": False},
            ])

        base_checklist.append({"item": "Send post-event follow-up", "category": "follow-up", "completed": False})

        return base_checklist

    async def _manage_rsvps(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """RSVPs: none are listed or recorded without an RSVP system, and none is invented."""
        event_id = request.entities.get("event_id", "")
        action = request.entities.get("action", "list")  # list, add, update, cancel
        attendee_data = request.entities.get("attendee", {})

        rsvp_data = {"event_id": event_id, "rsvps": [], "summary": None, "special_needs": None,
                     "connected": False, "recorded": False}
        if action in ("add", "update", "cancel") and attendee_data:
            name = attendee_data.get("name") or "this attendee"
            content = not_connected("An RSVP system", f"the RSVP for {name} has not been recorded")
        else:
            content = not_connected("An RSVP system", "I can't list RSVPs or count attendance")
        return SkillResponse(content=content, success=True, data={"rsvp_data": rsvp_data}, suggestions=[])

    async def _coordinate_logistics(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """A logistics checklist to fill in: venue, catering, A/V, staffing, materials, timeline. Nothing is booked."""
        event_id = request.entities.get("event_id", "")
        event_type = request.entities.get("event_type", "meeting")
        expected_attendance = request.entities.get("expected_attendance", 50)
        budget = request.entities.get("budget")

        logistics = {
            "event_id": event_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "booked": False,
            "venue": {"to_decide": ["Venue and address", f"Capacity for about {expected_attendance}",
                                    "Rental cost and deposit", "Setup and teardown times", "Venue contact"],
                      "confirmed": False},
            "catering": {"to_decide": ["Caterer", "Menu and serving style", "Cost per person",
                                       "Dietary needs (ask at registration)"],
                         "confirmed": False},
            "av_equipment": {"to_decide": ["Microphones", "Projector and screen", "Speakers",
                                           "Who provides each: venue or organization"]},
            "staffing": {"to_decide": ["Event lead", "Registration table", "Room monitors", "Tech support",
                                       "Volunteers needed"]},
            "materials": [{"item": i, "status": "not started"} for i in
                          ("Name badges", "Programs/agendas", "Sign-in sheets", "Signage")],
            "timeline": {
                "day_before": ["Confirm all vendors", "Prepare materials and supplies"],
                "event_day": ["Venue access and setup", "A/V check", "Catering arrives", "Registration opens",
                              "Event start", "Event end and teardown", "Venue cleared"],
            },
            "budget_tracking": {"allocated": budget, "committed": None, "spent": None, "tracked": False},
            "emergency_contacts": [{"role": r, "name": None, "phone": None}
                                   for r in ("Event Lead", "Venue Contact", "Catering Contact")],
        }

        return SkillResponse(
            content=(f"Logistics checklist for a {event_type} of about {expected_attendance}: venue, catering, A/V, "
                     f"staffing, materials and a day-of timeline, to fill in. "
                     + not_connected("A venue booking system", "nothing is booked or confirmed and no money is committed")),
            success=True,
            data={"logistics": logistics},
            suggestions=["Draft an accessibility checklist"],
        )

    async def _check_accessibility(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """An accessibility checklist to confirm with the venue; nothing is checked, and no venue fact is invented."""
        event_id = request.entities.get("event_id", "")
        venue = request.entities.get("venue") or "the venue"

        to_confirm = [
            ("mobility", "Step-free, wheelchair-accessible entrance"),
            ("mobility", "Accessible parking near the entrance"),
            ("mobility", "Accessible restrooms"),
            ("mobility", "Elevator access to every floor used"),
            ("hearing", "Hearing loop or assistive listening"),
            ("hearing", "Sign language interpretation (often needs about 2 weeks' notice)"),
            ("visual", "Large print materials"),
            ("visual", "Screen-reader-compatible digital materials"),
            ("cognitive", "A quiet room"),
            ("dietary", "Dietary accommodations, asked at registration"),
        ]
        by_category: dict[str, list[dict[str, Any]]] = {}
        for category, description in to_confirm:
            by_category.setdefault(category, []).append(
                {"description": description, "available": None, "notes": "not checked"})

        accessibility_data = {
            "event_id": event_id,
            "venue": venue,
            "overall_assessment": None,
            "checked": False,
            "features": by_category,
            "recommendations": [
                {"recommendation": "Add an accessibility question to the registration form", "priority": "high"},
                {"recommendation": "Arrange sign language interpretation if requested", "priority": "medium",
                 "lead_time": "about 2 weeks"},
                {"recommendation": "Prepare large print agendas and materials", "priority": "medium"},
                {"recommendation": "Include accessibility information in event communications", "priority": "high"},
            ],
            "registration_requests": None,
            "accessibility_statement": (
                "We are committed to making this event accessible to all attendees. "
                "Please contact us at [contact email or phone] to request accommodations or discuss your "
                "accessibility needs."
            ),
        }

        return SkillResponse(
            content=(f"Accessibility checklist for {venue}: {len(to_confirm)} things to confirm, none checked yet, "
                     f"and a draft accessibility statement with your contact to fill in. "
                     + not_connected("An accessibility checker", "I can't say what the venue offers")),
            success=True,
            data={"accessibility": accessibility_data},
            suggestions=["Draft a follow-up message"],
        )

    async def _send_followup(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """Draft a post-event follow-up with [gaps] for what only the organization knows. Nothing is sent or scheduled."""
        event_id = request.entities.get("event_id", "")
        followup_type = request.entities.get("followup_type", "thank_you")
        include_survey = request.entities.get("include_survey", True)
        include_photos = request.entities.get("include_photos", True)

        now = datetime.now(timezone.utc)

        followup_templates = {
            "thank_you": {
                "subject": "Thank You for Attending [Event Name]!",
                "opening": "Thank you for joining us at [Event Name]. We truly appreciate your participation and support.",
                "highlights": ["[A highlight from the event]", "[What it made possible]"],
                "call_to_action": "Stay connected with us for future events and updates.",
            },
            "survey": {
                "subject": "We'd Love Your Feedback on [Event Name]",
                "opening": "Thank you for attending [Event Name]. Your feedback helps us improve future events.",
                "survey_link": "[your survey link]",
            },
            "impact": {
                "subject": "The Impact of [Event Name] - Thank You!",
                "opening": "Thanks to your participation in [Event Name], we're excited to share the impact we've made together.",
                "impact_metrics": [{"metric": "[What you measured]", "value": "[value]"}],
            },
        }

        template = followup_templates.get(followup_type, followup_templates["thank_you"])

        followup_data = {
            "event_id": event_id,
            "followup_type": followup_type,
            "created_at": now.isoformat(),
            "scheduled_send": None,
            "sent": False,
            "recipients": {"count": None, "segments": ["attendees"]},
            "content": template,
            "attachments": [],
        }

        if include_photos:
            followup_data["attachments"].append({"type": "photo_gallery", "description": "[Your event photos]"})

        if include_survey:
            followup_data["survey"] = {
                "link": "[your survey link]",
                "questions": [
                    "Overall satisfaction (1-5)",
                    "Would you recommend this event?",
                    "What did you enjoy most?",
                    "How can we improve?",
                ],
            }

        extras = [x for x, on in (("a feedback survey", include_survey), ("a place for photos", include_photos)) if on]
        return SkillResponse(
            content=(f"Drafted a {followup_type.replace('_', ' ')} follow-up"
                     + (f" with {' and '.join(extras)}" if extras else "")
                     + ". Fill in the [bracketed] parts. "
                     + not_connected("A messaging service", "nothing has been sent or scheduled")),
            success=True,
            data={"followup": followup_data},
            suggestions=["Would you like to customize the message?"],
        )
