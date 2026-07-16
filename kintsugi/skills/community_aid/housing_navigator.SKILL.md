---
name: housing_navigator
description: "Navigate housing resources, voucher programs, and tenant rights"
---

Navigate housing resources, voucher programs, and tenant rights.

This chip helps community members find stable housing by searching
available units, tracking voucher applications, providing tenant
rights information, and maintaining landlord accountability records.

Attributes:
    name: Unique chip identifier
    description: Human-readable description
    domain: ADVOCACY domain for housing rights
    efe_weights: Stakeholder-focused weights
    capabilities: READ_DATA, WRITE_DATA, EXTERNAL_API, PII_ACCESS
    consensus_actions: Actions requiring approval
    required_spans: MCP tool spans needed

## Metadata

- **Domain**: 
- **Version**: 1.0.0
- **Capabilities**: general
- **Consensus actions**: submit_voucher_application, share_tenant_data
