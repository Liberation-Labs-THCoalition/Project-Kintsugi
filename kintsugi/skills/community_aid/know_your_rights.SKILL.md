---
name: know_your_rights
description: "Provide legal information, rights education, and clinic scheduling"
---

Provide legal information, rights education, and clinic scheduling.

This chip serves as an educational resource to help community members
understand their legal rights across various domains. It provides
jurisdiction-aware information, schedules legal clinics, and generates
know-your-rights materials in multiple languages.

DISCLAIMER: This chip provides general legal information for educational
purposes only. It does NOT constitute legal advice. Users should always
consult with a qualified attorney for specific legal matters.

Attributes:
    name: Unique chip identifier
    description: Human-readable description
    domain: ADVOCACY domain for rights-focused work
    efe_weights: Mission and stakeholder focused weights
    capabilities: READ_DATA, SCHEDULE_TASKS, GENERATE_REPORTS
    consensus_actions: Actions requiring approval
    required_spans: MCP tool spans needed

## Metadata

- **Domain**: 
- **Version**: 1.0.0
- **Capabilities**: general
- **Consensus actions**: schedule_legal_clinic, distribute_legal_materials
