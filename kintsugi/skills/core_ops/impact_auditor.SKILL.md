---
name: impact_auditor
description: "Track, measure, and report organizational impact using SDG and GRI frameworks"
---

Track, measure, and report organizational impact using SDG and GRI frameworks.

This chip helps nonprofits measure and communicate their impact
using internationally recognized frameworks, supporting both
internal evaluation and external reporting.

Intents handled:
    - impact_measure: Record or retrieve measurements for indicators
    - impact_report: Generate impact reports
    - sdg_align: Map activities/outcomes to SDG targets
    - outcome_track: Track outcome progress over time
    - indicator_define: Define new indicators

Consensus actions:
    - publish_report: Requires approval before publishing
    - submit_to_funder: Requires approval before submitting reports

Example:
    chip = ImpactAuditorChip()
    request = SkillRequest(
        intent="sdg_align",
        entities={"program_name": "Youth Tutoring Program"}
    )
    response = await chip.handle(request, context)

## Metadata

- **Domain**: 
- **Version**: 1.0.0
- **Capabilities**: general
- **Consensus actions**: publish_report, submit_to_funder
