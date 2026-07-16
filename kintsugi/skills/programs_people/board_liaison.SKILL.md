---
name: board_liaison
description: "Support board governance, meeting preparation, and resolution tracking"
---

Support board governance, meeting preparation, and resolution tracking.

This chip assists staff and board members with governance activities
including preparing meeting packets, drafting minutes, tracking
resolutions, monitoring compliance, and generating board reports.

Intents:
    meeting_prep: Prepare meeting agenda and materials
    minutes_draft: Draft meeting minutes
    resolution_track: Track resolution status and implementation
    compliance_check: Check compliance requirements
    board_report: Generate board reports

Example:
    >>> chip = BoardLiaisonChip()
    >>> request = SkillRequest(intent="meeting_prep", entities={"meeting_type": "regular"})
    >>> response = await chip.handle(request, context)
    >>> print(response.data["meeting_packet"]["agenda_items"])

## Metadata

- **Domain**: 
- **Version**: 1.0.0
- **Capabilities**: general
- **Consensus actions**: distribute_materials, record_resolution, update_bylaws
