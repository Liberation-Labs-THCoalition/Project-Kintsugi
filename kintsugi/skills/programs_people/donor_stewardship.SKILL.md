---
name: donor_stewardship
description: "Manage donor relationships, acknowledgments, and cultivation"
---

Manage donor relationships, acknowledgments, and cultivation.

This chip supports fundraising staff in building and maintaining
donor relationships through timely acknowledgments, strategic
cultivation, giving analysis, and personalized stewardship.

Intents:
    donor_thank: Generate thank you acknowledgment
    donor_profile: Retrieve or update donor profile
    giving_history: Analyze donor giving history
    cultivation_plan: Create cultivation plan
    stewardship_report: Generate stewardship report

Example:
    >>> chip = DonorStewardshipChip()
    >>> request = SkillRequest(intent="donor_profile", entities={"donor_id": "donor_001"})
    >>> response = await chip.handle(request, context)
    >>> print(response.data["profile"]["donor_level"])

## Metadata

- **Domain**: 
- **Version**: 1.0.0
- **Capabilities**: general
- **Consensus actions**: send_acknowledgment, update_donor_level, share_donor_data
