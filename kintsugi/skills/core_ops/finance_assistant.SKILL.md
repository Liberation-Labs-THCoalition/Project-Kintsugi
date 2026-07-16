---
name: finance_assistant
description: "Financial management, budget tracking, and accounting integration"
---

Financial management, budget tracking, and accounting integration.

This chip provides comprehensive financial management capabilities
for nonprofit organizations, integrating with popular accounting
systems and providing real-time budget insights.

Intents handled:
    - budget_check: Check budget status for categories
    - expense_report: Generate expense reports
    - invoice_create: Create new invoices
    - financial_summary: Generate financial summaries
    - variance_analysis: Analyze budget vs actual variance

Consensus actions:
    - approve_expense: Requires approval for expenses over threshold
    - transfer_funds: Requires approval for fund transfers
    - create_invoice: Requires approval for new invoices
    - modify_budget: Requires approval for budget modifications

Example:
    chip = FinanceAssistantChip()
    request = SkillRequest(
        intent="budget_check",
        entities={"category": "programs"}
    )
    response = await chip.handle(request, context)

## Metadata

- **Domain**: 
- **Version**: 1.0.0
- **Capabilities**: general
- **Consensus actions**: approve_expense, transfer_funds, create_invoice, modify_budget
