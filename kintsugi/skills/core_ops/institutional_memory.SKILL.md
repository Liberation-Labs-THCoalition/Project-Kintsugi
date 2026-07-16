---
name: institutional_memory
description: "Query and maintain organizational knowledge using CMA and temporal memory"
---

Query and maintain organizational knowledge using CMA and temporal memory.

This chip serves as the organization's collective memory, enabling
staff to search for historical decisions, policies, procedures,
and organizational knowledge. It uses semantic search and maintains
temporal context for all records.

Intents handled:
    - knowledge_search: Search memory using natural language
    - history_query: Query historical decisions or events
    - policy_lookup: Find specific policies or procedures
    - decision_context: Get context for past decisions
    - gap_identify: Identify knowledge gaps

Consensus actions:
    - archive_record: Requires approval to archive important records
    - delete_memory: Requires approval to delete any record

Example:
    chip = InstitutionalMemoryChip()
    request = SkillRequest(
        intent="policy_lookup",
        entities={"policy_name": "expense reimbursement"}
    )
    response = await chip.handle(request, context)

## Metadata

- **Domain**: 
- **Version**: 1.0.0
- **Capabilities**: general
- **Consensus actions**: archive_record, delete_memory
