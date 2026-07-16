---
name: rapid_response
description: "Coordinate rapid response networks for ICE raids, bail funds, and emergencies"
---

Coordinate rapid response networks for emergencies.

This chip manages rapid response communications for ICE raids,
bail fund requests, and community emergencies. It prioritizes
operational security and privacy - sensitive location data is
never logged or stored.

SECURITY PRINCIPLES:
- No specific addresses logged
- No identifying information stored unnecessarily
- Encrypted communications preferred
- Verified responder network
- Operational security protocols enforced

Attributes:
    name: Unique chip identifier
    description: Human-readable description
    domain: ADVOCACY domain for community defense
    efe_weights: Mission and stakeholder focused
    capabilities: READ_DATA, WRITE_DATA, SEND_NOTIFICATIONS, PII_ACCESS
    consensus_actions: Actions requiring approval
    required_spans: MCP tool spans needed

## Metadata

- **Domain**: 
- **Version**: 1.0.0
- **Capabilities**: general
- **Consensus actions**: activate_rapid_response, release_bail_funds, share_location_alert
