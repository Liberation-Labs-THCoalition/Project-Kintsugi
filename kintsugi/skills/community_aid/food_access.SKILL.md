---
name: food_access
description: "Coordinate food pantries, SNAP assistance, and community meals"
---

Coordinate food pantries, SNAP assistance, and community meals.

This chip helps community members access food resources by finding
nearby pantries with real-time inventory, assisting with SNAP
applications, and coordinating community meal programs.

Attributes:
    name: Unique chip identifier
    description: Human-readable description
    domain: MUTUAL_AID domain for direct assistance
    efe_weights: High stakeholder benefit focus
    capabilities: READ_DATA, WRITE_DATA, SCHEDULE_TASKS, EXTERNAL_API
    consensus_actions: Actions requiring approval
    required_spans: MCP tool spans needed

## Metadata

- **Domain**: 
- **Version**: 1.0.0
- **Capabilities**: general
- **Consensus actions**: approve_food_distribution, partner_food_share
