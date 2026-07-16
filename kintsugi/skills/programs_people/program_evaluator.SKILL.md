---
name: program_evaluator
description: "Design and track program logic models, outcomes, and evaluations"
---

Design and track program logic models, outcomes, and evaluations.

This chip supports program staff and evaluators in developing theory
of change, tracking outcomes, designing evaluations, collecting data,
and generating findings reports. It emphasizes mission alignment and
stakeholder benefit in all evaluation activities.

Intents:
    logic_model: Build or retrieve program logic model
    outcome_track: Track and update outcome metrics
    evaluation_design: Design evaluation study
    data_collect: Set up data collection instruments
    findings_report: Generate evaluation findings report

Example:
    >>> chip = ProgramEvaluatorChip()
    >>> request = SkillRequest(intent="logic_model", entities={"program_id": "prog_001"})
    >>> response = await chip.handle(request, context)
    >>> print(response.data["logic_model"]["components"])

## Metadata

- **Domain**: 
- **Version**: 1.0.0
- **Capabilities**: general
- **Consensus actions**: finalize_evaluation, publish_findings
