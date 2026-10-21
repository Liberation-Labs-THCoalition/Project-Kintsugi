---
name: crisis_response
description: "Rapid mobilization for emergencies, disasters, and urgent community needs"
---

Rapid mobilization for emergencies with tiered escalation.

This chip coordinates crisis response through:
1. Alert broadcasting based on crisis severity
2. Volunteer mobilization matching skills to needs
3. Resource deployment tracking
4. Status updates and coordination
5. Post-incident debriefing

Escalation tiers:
- CRITICAL: Immediate all-hands alert, emergency protocol activation
- HIGH: Rapid response team deployment, leadership notification
- MEDIUM: Coordinated response, standard protocols
- LOW: Monitored response, limited mobilization

## Metadata

- **Domain**: 
- **Version**: 1.0.0
- **Capabilities**: general
- **Consensus actions**: activate_emergency_protocol, release_emergency_funds

## Inputs for crisis_alert

- crisis_type, severity
- **location**: a neighbourhood or cross streets, not a home address. With on-call people named, it is sent to them at once (unless the deployment turns
  ONCALL_SEND_AREA off), so it must never be an address.
- description: kept with the request for the approvers; never sent to on-call.
