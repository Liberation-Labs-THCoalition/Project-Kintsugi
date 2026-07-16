---
name: resource_redistribution
description: "Coordinate surplus allocation, food rescue, and resource sharing"
---

Coordinate surplus allocation and time-sensitive resource sharing.

This chip handles the full lifecycle of resource redistribution:
1. Partners report surplus resources with expiry information
2. System matches surplus with community requests
3. Volunteers are dispatched for pickup and delivery
4. Inventory is tracked across the network

Time-sensitivity is critical - perishable goods need rapid matching
and logistics coordination.

## Metadata

- **Domain**: 
- **Version**: 1.0.0
- **Capabilities**: general
- **Consensus actions**: approve_large_redistribution, partner_agreement
