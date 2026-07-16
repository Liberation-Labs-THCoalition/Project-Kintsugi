---
name: content_drafter
description: "Draft communications, reports, and content with SB 942 AI labeling compliance"
---

Draft communications, reports, and content with SB 942 AI labeling compliance.

This chip assists nonprofit staff in creating communications across
multiple channels while ensuring compliance with California's SB 942
AI disclosure requirements.

Intents handled:
    - draft_email: Draft email communications
    - draft_social: Create social media content
    - draft_newsletter: Draft newsletter content
    - draft_report: Generate report documents
    - content_review: Review and improve existing content

Consensus actions:
    - publish_external: Requires approval for external publication
    - send_mass_email: Requires approval for mass email sends

Example:
    chip = ContentDrafterChip()
    request = SkillRequest(
        intent="draft_social",
        entities={"platform": "twitter", "topic": "volunteer_appreciation"}
    )
    response = await chip.handle(request, context)

## Metadata

- **Domain**: 
- **Version**: 1.0.0
- **Capabilities**: general
- **Consensus actions**: publish_external, send_mass_email
