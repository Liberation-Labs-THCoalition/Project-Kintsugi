# Kintsugi CMA

**Prosocial Agent Memory Architecture for Ethical AI**

Kintsugi is a complete infrastructure for building AI agents that serve communities, not corporations. Named after the Japanese art of repairing broken pottery with gold, Kintsugi transforms the fractures in traditional AI systems into strengths through ethical guardrails, transparent decision-making, and community-centered values.

## Why Kintsugi?

Most AI infrastructure assumes profit-driven deployment. Kintsugi assumes you're building for:
- **Mutual aid networks** coordinating community resources
- **Nonprofit organizations** managing grants and programs
- **Cooperatives** practicing democratic governance
- **Advocacy groups** protecting vulnerable communities

Every architectural decision reflects these values.

## Core Architecture

### Memory System (3-Stage Pipeline)
```
Raw Input → Stage 1 (Extraction) → Stage 2 (Significance) → Stage 3 (Retrieval)
```
- **Stage 1**: Atomic fact extraction with temporal awareness
- **Stage 2**: Significance scoring, spaced retrieval scheduling
- **Stage 3**: Hybrid search (vector + lexical + symbolic) with adaptive fusion

### Ethical Framing Engine (EFE)
Decision-making through explicit ethical weights:
- **Risk assessment** with configurable tolerance
- **Ambiguity handling** for uncertain situations
- **Epistemic humility** - knowing what you don't know

### 22 Skill Chips
Domain-specific handlers organized by function:

| Domain | Skills |
|--------|--------|
| **Core Operations** | Grant Hunter, Finance Assistant, Content Drafter, Impact Auditor, Institutional Memory, Volunteer Coordinator |
| **Programs & People** | Donor Stewardship, Event Planner, Board Liaison, Member Services, Program Evaluator, Staff Onboarding |
| **Community Aid** | Mutual Aid Coordinator, Crisis Response, Know Your Rights, Housing Navigator, Food Access, Coalition Builder, Rapid Response, Resource Redistribution, Solidarity Economy, Community Asset Mapper |

### Multi-Platform Adapters
- **Slack** - Full bot integration with blocks UI
- **Discord** - Bot with cogs and embeds
- **WebChat** - Embeddable widget for websites
- **Email** - IMAP/SMTP with notification scheduling

## Security & Governance

### Privacy Protection
- PII detection and redaction (SSN, credit cards, emails, phones)
- Content monitoring with ALLOW/WARN/BLOCK policies
- Per-organization memory isolation

### Values-Driven Constraints
- BDI (Belief-Desire-Intention) framework
- Hot-reloadable VALUES.json configuration
- 4 organizational templates: mutual aid, nonprofit, cooperative, advocacy

### Consensus Mechanisms
- Multi-stakeholder approval workflows
- Audit trails for all decisions
- Rollback capability

## Enterprise Features

### Multi-Tenancy
- **Isolation strategies**: ROW_LEVEL, SCHEMA, DATABASE
- **Tier system**: SEED → SPROUT → GROVE → FOREST
- **Quota management** with soft/hard limits

### Plugin System
- Sandboxed execution environment
- 4 plugin types: SkillChip, Adapter, Storage, Middleware
- Hot-reload capability
- Security policies per plugin

### Auto-Tuning
- EFE weight optimization from outcome feedback
- Multiple strategies: GRADIENT, EVOLUTIONARY, BAYESIAN
- Stakeholder feedback collection
- Consensus requirements for weight changes

## Quick Start

```bash
# Clone
git clone https://github.com/Liberation-Labs-THCoalition/Project-Kintsugi.git
cd Project-Kintsugi

# Seed tier (SQLite, minimal resources)
docker compose -f docker-compose.seed.yml up

# Full stack (PostgreSQL + pgvector + Redis)
docker compose up
```

## Project Structure

```
kintsugi/
├── memory/        # 3-stage CMA pipeline, embeddings, spaced retrieval
├── cognition/     # EFE, model routing, orchestration
├── skills/        # 22 skill chips across 3 domains
├── adapters/      # Slack, Discord, WebChat, Email
├── security/      # PII, monitoring, sandboxing, shields
├── governance/    # Consensus mechanisms, audit logging
├── multitenancy/  # Tenant isolation, quotas, tiers
├── plugins/       # SDK, loader, sandbox, registry
├── tuning/        # EFE auto-tuning, feedback collection
├── cli/           # Security audit, diagnostics, config
└── api/           # FastAPI routes, WebSocket support
```

## Requirements

- Python 3.11+
- PostgreSQL 15+ with pgvector (grove+ tiers)
- Redis (grove+ tiers)

## Stats

- **~77,000 lines** of Python
- **600+ tests** across all modules
- **5 development phases** complete

## Built By

[Liberation Labs / TH Coalition](https://github.com/Liberation-Labs-THCoalition)

*Infrastructure for the movement.*

## License

Proprietary - Liberation Labs / TH Coalition
