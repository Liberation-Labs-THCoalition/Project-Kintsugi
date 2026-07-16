---
name: grant_hunter
description: "Search and match grant opportunities from Grants.gov, Candid, and other sources"
---

Search and match grant opportunities from Grants.gov, Candid, and other sources.

This chip helps nonprofit organizations discover funding opportunities
by searching multiple grant databases, checking eligibility requirements,
tracking deadlines, and drafting initial application materials.

Intents handled:
    - grant_search: Search for grants matching criteria
    - grant_match: Score grants against org profile
    - grant_deadline: Get upcoming deadlines
    - grant_eligibility: Check eligibility for specific grant
    - grant_report: Generate grant pipeline report

Consensus actions:
    - submit_application: Requires approval before submitting
    - commit_match_funds: Requires approval for matching fund commitments

Example:
    chip = GrantHunterChip()
    request = SkillRequest(
        intent="grant_search",
        entities={"focus_area": "education", "amount_min": 25000}
    )
    response = await chip.handle(request, context)
    # Returns matching grants ranked by relevance

## Metadata

- **Domain**: 
- **Version**: 1.0.0
- **Capabilities**: general
- **Consensus actions**: submit_application, commit_match_funds
