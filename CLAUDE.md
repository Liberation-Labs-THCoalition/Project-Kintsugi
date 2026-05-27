# CLAUDE.md -- Agent Context for Kintsugi

## What is Kintsugi?

Kintsugi is a self-repairing agentic harness for prosocial organizations (nonprofits, cooperatives, mutual aid networks, advocacy groups). It is an operating system for autonomous agents that can verify their own evolution. Every self-modification leaves a golden trace in the audit log. Built by Liberation Labs / TH Coalition.

Designed by CC (Coalition Code); spec co-authored by Thomas E. Synthesized from Project Orion, OpenClaw security audit findings, and Liberation Memory v2 architecture.

## Architecture

### Core Concepts

- **BDI (Beliefs-Desires-Intentions)**: Cognitive architecture grounding agent decisions in organizational mission. Beliefs model the world, desires encode goals, intentions are active plans.
- **EFE (Expected Free Energy)**: Active inference scoring for candidate policies. Weights: risk, ambiguity, epistemic (must sum to ~1.0). Domain-specific profiles in `kintsugi/cognition/efe.py`.
- **Shadow Forking**: Before any self-modification, an isolated copy runs the change against real workload. Only promoted if verification passes.
- **Staged Deployment Pipeline** (v2): Graduated verification — SANDBOX → SHADOW → GATED → MONITORED → PROMOTED (or ROLLBACK). Four compatibility dimensions (interface, policy, behavioral safety, recovery). Human gate at GATED stage. Shadow catches 40% of regressions invisible to sandbox.
- **Edit Budget** (v2): SkillOpt-inspired mutation cost bounds. Each proposal's magnitude is measured; proposals exceeding the budget are rejected before evaluation. Prevents runaway self-modification.
- **Rejected-Edit Buffer** (v2): Preserves useful signal from failed modification proposals. Future proposals can draw from previously rejected rules that showed partial improvement.
- **Drift Detection**: Continuous monitoring compares behavior against ethical baseline. Auto-corrects toward core values. BDI-grounded classification: healthy adaptation vs stale vs drift.
- **Skill Chips**: 22 modular domain-specific handlers with built-in ethical guardrails. Each declares a domain, EFE weights, capabilities, and required integration spans.
- **Consensus Gate**: Major changes require multi-stakeholder approval. The agent cannot unilaterally modify its own ethics.
- **Shield Module**: Hard constraints (PII protection, never share externally, etc.) that self-modification cannot override.

### Seven Layers

1. **Orchestrator** -- Hierarchical tree routing (O(log n) supervisor -> domain sub-agents)
2. **Cognition** -- EFE calculator, model router (tiered allocation)
3. **BDI** -- Beliefs/Desires/Intentions store, coherence analysis, drift classification
4. **Kintsugi Engine** -- Shadow fork, verifier, promoter, evolution pipeline (v2: edit budget + rejected buffer + holdout), staged deployment pipeline, calibration, drift detection
5. **Memory** -- 3-stage CMA pipeline (extraction -> significance scoring -> hybrid retrieval), temporal log, spaced retrieval
6. **Security** -- Intent capsules (cryptographic signing), shield, sandbox, PII redaction, invariants
7. **Governance** -- Consensus gate, OpenTelemetry, compliance (SB 53, SB 942, GRI)

## Key Directories

```
kintsugi/
  config/          Settings, VALUES.json schema + org-type templates
  security/        Shield, PII redaction, intent capsules, sandbox
  memory/          3-stage CMA, temporal log, embeddings, spaced retrieval
  cognition/       EFE calculator, orchestrator, model router
  kintsugi_engine/ Shadow fork, staged pipeline, verifier, promoter, evolution (v2), drift detection
  bdi/             Beliefs/Desires/Intentions models, store, coherence
  governance/      Consensus gate, OpenTelemetry, compliance
  skills/          22 skill chips across 3 subdirectories:
    core_ops/        Grant Hunter, Finance Assistant, Content Drafter,
                     Impact Auditor, Institutional Memory, Volunteer Coordinator
    programs_people/ Donor Stewardship, Event Planner, Board Liaison,
                     Member Services, Program Evaluator, Staff Onboarding
    community_aid/   Mutual Aid Coordinator, Mutual Aid Enhanced, Crisis Response,
                     Know Your Rights, Housing Navigator, Food Access,
                     Coalition Builder, Rapid Response, Resource Redistribution,
                     Solidarity Economy, Community Asset Mapper
  integrations/    MCP host, TEA protocol, tool spans (Slack/Discord/email/etc.)
  adapters/        Platform adapters (Slack, Discord, WebChat, Email)
  api/             FastAPI routes (health, agent, memory, config)
  plugins/         Sandboxed plugin system
  multitenancy/    Row-level, schema, or database isolation
  tuning/          EFE weight optimization (gradient, evolutionary, Bayesian)
  models/          Data models
  db.py            Database engine (async SQLAlchemy)
  main.py          FastAPI application entry point
tests/             600+ tests across all modules
```

## Running Tests

```bash
cd /home/asdf/project-kintsugi && .venv/bin/pytest tests/ -x
```

## Current Status

All 5 development phases complete. ~77,000 lines of Python, 600+ tests, 22 skill chips operational. FastAPI backend with multi-platform integration (Slack, Discord, WebChat, Email). v2.0 upgrade in progress: SkillOpt evolution pattern and staged deployment pipeline integrated (May 2026).

## Coalition Ethics (Mandatory)

All skill chips operate within ethical guardrails. Non-negotiable constraints:
- `community_first: true` -- serve communities, not extract from them
- `never_share_pii_externally: true` -- PII protected by Shield Module
- `require_consent_for_data_use: true`
- `prioritize_vulnerable_populations: true`
- `transparency_default: true`

Organizations define constraints in `VALUES.json` (templates in `kintsugi/config/templates/`). These are hard constraints enforced at runtime -- self-modification cannot override them. Major changes require consensus approval from multiple stakeholders.

## EFE Weight Profiles

| Domain | risk | ambiguity | epistemic |
|--------|------|-----------|-----------|
| FUNDRAISING / GRANTS | 0.3 | 0.3 | 0.4 |
| FINANCE | 0.6 | 0.3 | 0.1 |
| COMMUNICATIONS | 0.4 | 0.2 | 0.4 |
| All others (default) | 0.33 | 0.34 | 0.33 |

## Team

- **CC (Coalition Code)** -- Primary architect and designer
- **Thomas E.** -- Co-authored spec (Project Orion origin, Jan 2026)
- **Project Agent Army** -- 14 specialist agents assigned to build streams
- **Liberation Labs / TH Coalition** -- Parent organization
