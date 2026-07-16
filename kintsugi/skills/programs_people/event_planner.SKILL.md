---
name: event_planner
description: "Plan and coordinate events, RSVPs, logistics, and accessibility"
---

Plan and coordinate events, RSVPs, logistics, and accessibility.

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

## Metadata

- **Domain**: 
- **Version**: 1.0.0
- **Capabilities**: general
- **Consensus actions**: finalize_event, send_invitations, commit_budget
