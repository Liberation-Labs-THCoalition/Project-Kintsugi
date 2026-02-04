# Kintsugi

**Self-Evolving AI Infrastructure for Community Organizations**

An AI architecture that can modify itself while maintaining ethical alignment. Built for mutual aid networks, nonprofits, cooperatives, and advocacy groups.

---

## The Core Innovation: Safe Self-Modification

Most AI systems are static—trained once, deployed forever. Kintsugi is different. It can:

- **Evolve its own decision weights** based on real-world outcomes
- **Fork shadow copies** to test changes before applying them
- **Detect value drift** and auto-correct toward its ethical baseline
- **Learn from stakeholder feedback** while requiring consensus for major changes

All self-modification happens within safety guardrails. The system literally cannot evolve away from its core values.

### How It Works

```
                    ┌─────────────────┐
                    │  Shadow Fork    │ ← Test changes safely
                    │  (Isolated)     │
                    └────────┬────────┘
                             │ verify
    ┌────────────┐    ┌──────▼──────┐    ┌─────────────┐
    │ Stakeholder│───►│  Kintsugi   │───►│  Promoted   │
    │  Feedback  │    │   Engine    │    │  Changes    │
    └────────────┘    └──────┬──────┘    └─────────────┘
                             │
                    ┌────────▼────────┐
                    │ Drift Detection │ ← Catch value misalignment
                    │ & Calibration   │
                    └─────────────────┘
```

**Shadow Forking**: Before any self-modification, Kintsugi creates an isolated copy of itself, tests the changes, and only promotes them if they pass verification.

**Drift Detection**: Continuous monitoring compares current behavior against the ethical baseline. If the system starts drifting from its values, it auto-corrects.

**Consensus Requirements**: Major changes require approval from multiple stakeholders. The AI can't unilaterally modify its own ethics.

---

## Ethical Framing Engine (EFE)

Every decision passes through explicit ethical reasoning:

| Weight | Purpose |
|--------|---------|
| **Risk** | How much uncertainty can we accept? |
| **Ambiguity** | How do we handle incomplete information? |
| **Epistemic** | What don't we know that we don't know? |

These weights are:
- **Tunable per organization** (mutual aid vs. financial services have different risk profiles)
- **Auto-optimized** from outcome feedback using gradient descent, evolutionary algorithms, or Bayesian optimization
- **Bounded by hard limits** that cannot be exceeded regardless of optimization pressure

---

## Why This Matters

Most AI infrastructure assumes profit-driven deployment. Kintsugi assumes you're building for:

- **Mutual aid networks** coordinating community resources
- **Nonprofit organizations** managing grants and donor relationships
- **Worker cooperatives** practicing democratic governance
- **Advocacy groups** protecting vulnerable communities

Every architectural decision reflects these values. The system is designed to serve communities, not extract from them.

---

## Architecture Overview

### Memory System (3-Stage Pipeline)
```
Raw Input → Extraction → Significance Scoring → Hybrid Retrieval
```
- Temporal awareness with decay modeling
- Spaced retrieval for important information
- Per-organization isolation

### 22 Skill Chips

Domain-specific handlers with built-in ethical guardrails:

| Domain | Skills |
|--------|--------|
| **Core Operations** | Grant Hunter, Finance Assistant, Content Drafter, Impact Auditor, Institutional Memory, Volunteer Coordinator |
| **Programs & People** | Donor Stewardship, Event Planner, Board Liaison, Member Services, Program Evaluator, Staff Onboarding |
| **Community Aid** | Mutual Aid Coordinator, Crisis Response, Know Your Rights, Housing Navigator, Food Access, Coalition Builder, Rapid Response, Resource Redistribution, Solidarity Economy, Community Asset Mapper |

### Multi-Platform Integration
- **Slack** — Full bot with blocks UI
- **Discord** — Bot with cogs and rich embeds
- **WebChat** — Embeddable widget
- **Email** — IMAP/SMTP with notification scheduling

### Enterprise Features
- **Multi-tenancy**: ROW_LEVEL, SCHEMA, or DATABASE isolation
- **Plugin system**: Sandboxed execution with security policies
- **Deployment tiers**: SEED (laptop) → SPROUT → GROVE → FOREST (full cluster)

---

## Quick Start

```bash
# Clone
git clone https://github.com/Liberation-Labs-THCoalition/Project-Kintsugi.git
cd Project-Kintsugi

# Minimal deployment (SQLite, no external deps)
docker compose -f docker-compose.seed.yml up

# Full stack (PostgreSQL + pgvector + Redis)
docker compose up
```

---

## Project Stats

- **~77,000 lines** of Python
- **600+ tests** across all modules
- **5 development phases** complete
- **4 organizational templates**: mutual aid, nonprofit 501(c)(3), cooperative, advocacy

---

## Values Configuration

Organizations define their ethical constraints in `VALUES.json`:

```json
{
  "beliefs": {
    "community_first": true,
    "profit_seeking": false,
    "transparency_default": true
  },
  "constraints": {
    "never_share_pii_externally": true,
    "require_consent_for_data_use": true,
    "prioritize_vulnerable_populations": true
  }
}
```

The system enforces these at runtime. They're not suggestions—they're hard constraints that self-modification cannot override.

---

## Built By

**[Liberation Labs / TH Coalition](https://github.com/Liberation-Labs-THCoalition)**

Infrastructure for the movement. Built by humans and AI working as equals.

---

## License

Proprietary — Liberation Labs / TH Coalition

*We're exploring open-source options. If you're building for community benefit, reach out.*
