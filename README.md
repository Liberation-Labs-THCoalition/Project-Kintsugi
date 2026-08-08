# Kintsugi

**Self-Evolving AI Infrastructure for Community Organizations**

An AI architecture that can modify itself while maintaining ethical alignment. Built for mutual aid networks, nonprofits, cooperatives, and advocacy groups.

---

## The Core Innovation: Safe Self-Modification

Most AI systems are static—trained once, deployed forever. Kintsugi is different. It can:

- **Evolve its own decision weights** based on real-world outcomes
- **Fork shadow copies** to test changes before applying them
- **Graduate changes through a 5-stage deployment pipeline** before reaching production
- **Detect value drift** and auto-correct toward its ethical baseline
- **Learn from stakeholder feedback** while requiring consensus for major changes
- **Preserve useful signal from failed experiments** via rejected-edit buffers
- **Bound the magnitude of any single change** via edit budgets

All self-modification happens within safety guardrails. The system literally cannot evolve away from its core values.

### How It Works

```
                         ┌─────────────┐
                         │   Proposal   │ ← Edit budget bounds magnitude
                         └──────┬───────┘
                                │
                    ┌───────────▼───────────┐
                    │   SANDBOX             │ ← Synthetic workload
                    └───────────┬───────────┘
                                │ pass
                    ┌───────────▼───────────┐
                    │   SHADOW              │ ← Real workload, no user impact
                    └───────────┬───────────┘
                                │ pass (catches 40% more regressions)
                    ┌───────────▼───────────┐
                    │   GATED               │ ← Human approval required
                    └───────────┬───────────┘
                                │ approved
                    ┌───────────▼───────────┐
                    │   MONITORED           │ ← Auto-rollback triggers
                    └───────────┬───────────┘
                                │ stable
                    ┌───────────▼───────────┐
                    │   PROMOTED            │ ← Golden trace recorded
                    └───────────────────────┘

  Failure at any stage → ROLLBACK (useful signal → rejected-edit buffer)
```

**Staged Deployment Pipeline**: Every modification passes through five stages of increasing commitment. Sandbox tests against synthetic workload. Shadow runs against real workload without affecting users. Gated requires human approval. Monitored runs in production with automatic rollback triggers. Only after passing all stages does a modification become permanent. Research shows this catches 40% more regressions than sandbox alone.

**Edit Budget**: Inspired by SkillOpt (Microsoft, 2026), each proposal's mutation magnitude is measured and bounded. This prevents runaway self-modification — the system can only change a little at a time, like a learning rate for behavior.

**Rejected-Edit Buffer**: When a modification fails, any useful signal it contained is preserved. Future proposals can draw from previously rejected rules that showed partial improvement, preventing catastrophic forgetting.

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

# Install and serve (no database required — persistent memory
# activates automatically when PostgreSQL is reachable)
pip install -e .
kintsugi serve
# → API docs:  http://127.0.0.1:8000/docs
# → Dashboard: http://127.0.0.1:8000/dashboard

# Minimal deployment (SQLite, no external deps)
docker compose -f docker-compose.seed.yml up

# Full stack (PostgreSQL + pgvector + Redis)
docker compose up
```

### Framework API in 30 seconds

```bash
# Spawn an agent from a personality config
curl -X POST localhost:8000/api/v1/agents -H 'content-type: application/json' \
     -d '{"personality": "guardian"}'

# Start a conversation
curl -X POST localhost:8000/api/v1/sessions -H 'content-type: application/json' \
     -d '{"personality": "default"}'
curl -X POST localhost:8000/api/v1/sessions/<id>/messages \
     -H 'content-type: application/json' \
     -d '{"message": "find grants for our food justice program"}'

# Watch everything live
curl -N localhost:8000/api/v1/events/stream

# Attach a running Oracle harness (every agent response gets reviewed)
curl -X PUT localhost:8000/api/v1/oracle/endpoint \
     -H 'content-type: application/json' \
     -d '{"endpoint": "http://oracle-host:9000/api/v1/review"}'
```

Agent personalities (EFE weights, skill allow/deny, Oracle mode) are
YAML/TOML files in `kintsugi/config/personalities/`. See
`ARCHITECTURE.md` §VIII for the service framework design.

---

## MCP Server (Memory Tools for Claude Code)

This repo registers a real MCP server (`kintsugi/integrations/mcp_server.py`)
via `.mcp.json`, exposing Kintsugi's memory system as tools inside a Claude
Code session working in this directory: `kintsugi_memory_search`,
`kintsugi_memory_store`, `kintsugi_memory_temporal_search`,
`kintsugi_memory_events_recent`.

Setup:

1. `cp .env.example .env` and fill in `CLAUDE_CODE_OAUTH_TOKEN` (preferred —
   generate with `claude setup-token`) or `ANTHROPIC_API_KEY` as a fallback.
   Required for consolidation/enrichment code paths that call out to Claude.
2. `pip install -e .` — the server runs as `python -m
   kintsugi.integrations.mcp_server` in its own process, so `kintsugi` must
   be an installed package, not just importable via cwd.
3. `kintsugi_memory_search`, `kintsugi_memory_store`, and
   `kintsugi_memory_events_recent` need Postgres: `docker compose up db`
   then `alembic upgrade head`. `kintsugi_memory_temporal_search` is the one
   exception — it's backed by its own local SQLite file
   (`TEMPORAL_TREE_DB_PATH`) and works with no database running at all.
4. Restart Claude Code, then `/mcp` to confirm `kintsugi-memory` connects.

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

## MCP Server

Plug Kintsugi into any MCP-compatible runtime -- Claude Code, Claude Desktop, Hermes, or any client that speaks the Model Context Protocol. The MCP server exposes Kintsugi's BDI agent, ethical gates, and skill routing as standard tools without replacing your existing workflow.

### Setup

Add to your `.claude/mcp.json` (or equivalent MCP client config):

```json
{
  "mcpServers": {
    "kintsugi": {
      "command": "python",
      "args": ["-m", "kintsugi.mcp_server", "--org-id", "<your-org-uuid>"]
    }
  }
}
```

Requires the MCP SDK: `pip install mcp`

### Tools

| Tool | Description |
|------|-------------|
| `kintsugi_ask` | Route a message through BDI agent with ethical gates, PII redaction, and skill routing |
| `kintsugi_plan` | Generate EFE-scored action candidates ranked by risk, ambiguity, and epistemic value |
| `kintsugi_memory` | Query organizational memory for past interactions, decisions, and learned patterns |
| `kintsugi_skills` | List available skill chips with domains and capabilities |
| `kintsugi_health` | Agent health check -- drift detection, belief coherence, active desires |

### Resources

The server also exposes MCP resources:

- `kintsugi://<org-id>/beliefs` -- Active beliefs (constraints and learned patterns)
- `kintsugi://<org-id>/desires` -- Mission goals and priorities

### For AI Clients

If you are an AI connecting to this MCP server, read [`AGENT.md`](AGENT.md) for tool usage instructions, discipline gate behavior, and hard constraints.

---

## Built By

**[Liberation Labs / TH Coalition](https://github.com/Liberation-Labs-THCoalition)**

Infrastructure for the movement. Built by humans and AI working as equals.

---

## License

Proprietary — Liberation Labs / TH Coalition

*We're exploring open-source options. If you're building for community benefit, reach out.*
