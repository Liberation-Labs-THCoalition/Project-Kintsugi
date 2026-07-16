---
name: staff_onboarding
description: "Guide new staff through onboarding, training, and policy orientation"
---

Guide new staff through onboarding, training, and policy orientation.

This chip supports HR and managers in efficiently onboarding new
employees through structured workflows, training assignments,
policy reviews, and progress tracking.

Intents:
    onboard_start: Initialize onboarding for new employee
    training_assign: Assign training modules
    policy_review: Present policies for review
    checklist_status: Check onboarding progress
    onboard_complete: Finalize onboarding

Example:
    >>> chip = StaffOnboardingChip()
    >>> request = SkillRequest(intent="onboard_start", entities={"employee_id": "emp_001"})
    >>> response = await chip.handle(request, context)
    >>> print(response.data["onboarding_plan"]["checklist_items"])

## Metadata

- **Domain**: 
- **Version**: 1.0.0
- **Capabilities**: general
- **Consensus actions**: complete_onboarding, grant_system_access, update_employee_record
