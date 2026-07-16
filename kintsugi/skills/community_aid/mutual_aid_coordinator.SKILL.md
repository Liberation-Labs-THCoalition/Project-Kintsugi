---
name: mutual_aid_coordinator
description: "Match community needs with offers, coordinate mutual aid requests"
---

Coordinate mutual aid requests and offers with privacy preservation.

This chip handles the full lifecycle of mutual aid coordination:
1. Community members post needs or offers anonymously
2. The system matches needs with appropriate offers
3. Both parties opt-in before contact information is shared
4. Aid fulfillment is tracked and reported

Privacy is a core principle - requester details are never exposed
until both parties confirm the match.

## Metadata

- **Domain**: 
- **Version**: 1.0.0
- **Capabilities**: general
- **Consensus actions**: approve_high_value_request, share_requester_info
