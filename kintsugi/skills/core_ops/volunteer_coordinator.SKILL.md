---
name: volunteer_coordinator
description: "Coordinate volunteer scheduling, communications, and engagement"
---

Coordinate volunteer scheduling, communications, and engagement.

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

## Metadata

- **Domain**: 
- **Version**: 1.0.0
- **Capabilities**: general
- **Consensus actions**: mass_notification, schedule_change_all
