---
name: member_services
description: "Manage membership tracking, renewals, benefits, and communications"
---

Manage membership tracking, renewals, benefits, and communications.

This chip supports member services staff in managing the full
membership lifecycle including lookups, renewals, benefits
information, communications, and reporting.

Intents:
    member_lookup: Look up member information
    membership_renew: Process membership renewal
    benefits_info: Provide membership benefits information
    member_communicate: Send member communications
    membership_report: Generate membership reports

Example:
    >>> chip = MemberServicesChip()
    >>> request = SkillRequest(intent="member_lookup", entities={"member_id": "mem_001"})
    >>> response = await chip.handle(request, context)
    >>> print(response.data["member"]["membership_tier"])

## Metadata

- **Domain**: 
- **Version**: 1.0.0
- **Capabilities**: general
- **Consensus actions**: change_membership_tier, process_refund, bulk_communication
