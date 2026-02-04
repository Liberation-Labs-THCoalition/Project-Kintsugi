# Kintsugi Harness — Implementation Plan
## Liberation Labs | February 2026

> Reference: `KINTSUGI_HARNESS_v1.1.md`
> Specialist Agents: `Project-Agent-Army` (14 agents)
> Total Components: 115+

---

## Build Philosophy

Each phase produces a **working, deployable system**. Phase 1 isn't scaffolding — it's a functional secure agent with memory. Each subsequent phase adds capability layers. An org can start using Kintsugi after Phase 1 and get value immediately.

Specialist agents from Project-Agent-Army are assigned to each work stream. CC orchestrates, subagents build.

---

## Repository Structure

```
kintsugi/
├── engine/                        # Python backend
│   ├── kintsugi/
│   │   ├── __init__.py
│   │   ├── main.py                # FastAPI application entry
│   │   ├── config/
│   │   │   ├── settings.py        # Environment config (pydantic-settings)
│   │   │   ├── values_schema.py   # VALUES.json Pydantic model
│   │   │   ├── values_loader.py   # Template loading + validation
│   │   │   └── templates/         # VALUES.json templates per org type
│   │   │       ├── mutual_aid.json
│   │   │       ├── nonprofit_501c3.json
│   │   │       ├── cooperative.json
│   │   │       └── advocacy.json
│   │   ├── security/
│   │   │   ├── intent_capsule.py  # Cryptographic mandate signing
│   │   │   ├── shield.py          # Hard constraints module
│   │   │   ├── monitor.py         # SecurityMonitor pattern matching
│   │   │   ├── sandbox.py         # Shadow sandbox pre-execution
│   │   │   ├── invariants.py      # Formal code-checked constraints
│   │   │   └── pii.py             # PII redaction middleware
│   │   ├── memory/
│   │   │   ├── cma_stage1.py      # Semantic structured compression
│   │   │   ├── cma_stage2.py      # Recursive consolidation (async)
│   │   │   ├── cma_stage3.py      # Adaptive hybrid retrieval
│   │   │   ├── cold_archive.py    # Sub-threshold compressed storage
│   │   │   ├── temporal.py        # Append-only JSONL decision log
│   │   │   ├── spaced.py          # Fibonacci spaced retrieval
│   │   │   ├── significance.py    # Significance continuum + expiration
│   │   │   └── embeddings.py      # Embedding generation (local + API)
│   │   ├── cognition/
│   │   │   ├── efe.py             # Active Inference EFE calculation
│   │   │   ├── orchestrator.py    # Hierarchical Supervisor routing
│   │   │   └── model_router.py    # Tiered model allocation
│   │   ├── kintsugi_engine/
│   │   │   ├── shadow_fork.py     # Parallel shadow agent execution
│   │   │   ├── verifier.py        # Comparative behavioral analysis
│   │   │   ├── promoter.py        # Modification promotion/rejection
│   │   │   ├── evolution.py       # Evolutionary pipeline (next-gen proposals)
│   │   │   ├── calibration.py     # Historical Verifier calibration
│   │   │   ├── bloom_adapter.py   # Bloom-adapted adversarial evaluation
│   │   │   └── drift.py           # Mission drift detection (BDI-grounded)
│   │   ├── bdi/
│   │   │   ├── models.py          # Beliefs/Desires/Intentions data models
│   │   │   ├── store.py           # BDI persistence + revision history
│   │   │   ├── coherence.py       # BDI coherence analysis
│   │   │   └── drift_classifier.py # Healthy adaptation vs stale vs drift
│   │   ├── governance/
│   │   │   ├── consensus.py       # Consensus Gate (approval queue)
│   │   │   ├── otel.py            # OpenTelemetry GenAI integration
│   │   │   └── compliance.py      # SB 53, SB 942, GRI automation
│   │   ├── integrations/
│   │   │   ├── mcp_host.py        # MCP server hosting
│   │   │   ├── tea_protocol.py    # TEA protocol implementation
│   │   │   └── spans/             # MCP Tool Spans
│   │   │       ├── communication.py   # Slack/Discord/email
│   │   │       ├── project_mgmt.py    # Asana/Monday
│   │   │       ├── data.py            # PostgreSQL/data access
│   │   │       └── operational.py     # GitHub/Google Drive
│   │   ├── skills/                # Skill Chips (one module per chip)
│   │   │   ├── base.py            # Base Skill Chip interface
│   │   │   ├── grant_hunter.py
│   │   │   ├── volunteer_coordinator.py
│   │   │   ├── impact_auditor.py
│   │   │   ├── finance_assistant.py
│   │   │   ├── institutional_memory.py
│   │   │   ├── content_drafter.py
│   │   │   ├── program_tracker.py
│   │   │   ├── client_intake.py
│   │   │   ├── donor_steward.py
│   │   │   ├── policy_advocate.py
│   │   │   ├── compliance_monitor.py
│   │   │   ├── hr_onboarding.py
│   │   │   ├── community_pulse.py
│   │   │   ├── needs_offers.py
│   │   │   ├── stakeholder_mapper.py
│   │   │   ├── board_secretary.py
│   │   │   ├── crisis_response.py
│   │   │   ├── resource_inventory.py
│   │   │   ├── mutual_aid_bookkeeper.py
│   │   │   ├── fundraising_campaign.py
│   │   │   ├── training_builder.py
│   │   │   └── facilities_logistics.py
│   │   └── api/
│   │       ├── routes/            # FastAPI route modules
│   │       │   ├── agent.py       # Agent interaction endpoints
│   │       │   ├── bdi.py         # BDI CRUD endpoints
│   │       │   ├── kintsugi.py    # Shadow verification status/control
│   │       │   ├── memory.py      # Memory query endpoints
│   │       │   ├── security.py    # Security audit endpoints
│   │       │   ├── consensus.py   # Approval queue endpoints
│   │       │   ├── skills.py      # Skill Chip management
│   │       │   ├── config.py      # VALUES.json + org config
│   │       │   └── onboarding.py  # Setup wizard backend
│   │       ├── websocket.py       # WS handlers for streaming
│   │       └── middleware.py      # Auth, PII redaction, logging
│   ├── migrations/                # Alembic database migrations
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   ├── adversarial/           # Red Hat Tester generated suites
│   │   └── bloom/                 # Bloom evaluation seeds
│   ├── pyproject.toml
│   ├── Dockerfile
│   └── alembic.ini
├── dashboard/                     # TypeScript/React frontend
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   ├── SetupWizard/       # Multi-step onboarding
│   │   │   ├── Dashboard/         # Main operational dashboard
│   │   │   ├── KintsugiTimeline/  # Golden trace history
│   │   │   ├── ConsensusGate/     # Approval queue
│   │   │   ├── BDIEditor/         # Beliefs/Desires/Intentions
│   │   │   ├── SecurityAudit/     # Shield + Monitor status
│   │   │   ├── ImpactDashboard/   # SDG metrics + reports
│   │   │   ├── BloomResults/      # Behavioral evaluation results
│   │   │   ├── MissionDrift/      # Drift detection + alerts
│   │   │   └── Chat/              # Embedded web chat
│   │   ├── components/
│   │   │   ├── ui/                # Shared UI primitives (shadcn/ui)
│   │   │   ├── charts/            # Visualization components
│   │   │   ├── forms/             # Form components
│   │   │   └── layout/            # Navigation, sidebar, header
│   │   ├── hooks/                 # React hooks (API, WebSocket, auth)
│   │   ├── api/                   # API client (generated from OpenAPI)
│   │   └── stores/                # State management (Zustand)
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   └── Dockerfile
├── adapters/                      # Chat adapters (TypeScript)
│   ├── slack/                     # Slack Bolt bot
│   ├── discord/                   # discord.js bot
│   ├── webchat/                   # Embeddable widget
│   └── shared/                    # Shared adapter utilities + DM pairing
├── cli/                           # CLI tool (Python)
│   ├── kintsugi_cli/
│   │   ├── __init__.py
│   │   ├── main.py                # Typer CLI entry
│   │   ├── commands/
│   │   │   ├── init.py
│   │   │   ├── agent.py
│   │   │   ├── security.py
│   │   │   ├── kintsugi.py        # Shadow status, history, rollback
│   │   │   ├── memory.py
│   │   │   ├── config.py
│   │   │   └── doctor.py
│   │   └── output.py              # Formatting (JSON, table, human)
│   └── pyproject.toml
├── docker-compose.yml             # Full stack deployment
├── docker-compose.seed.yml        # Seed tier (SQLite, no pgvector)
├── .github/
│   └── workflows/
│       ├── ci.yml                 # Build + test + lint
│       ├── security.yml           # SAST + dependency audit
│       └── release.yml            # Docker image publishing
├── docs/                          # Documentation (Mintlify or similar)
├── LICENSE
├── README.md
└── CHANGELOG.md
```

---

## Phase 1: Foundation

**Goal:** A secure agent with memory that an org can talk to via API. No UI yet, but the engine works.

### Work Streams (Parallel)

#### Stream 1A: Project Scaffolding + Database
**Agents:** Backend Architect, Database Architect

1. Initialize Python project (pyproject.toml, FastAPI, pydantic-settings)
2. Docker Compose with PostgreSQL 16 + pgvector
3. Database schema design:
   - `organizations` table
   - `memory_units` table with significance column + computed expiration
   - `memory_embeddings` table with pgvector HNSW index (768D)
   - `memory_lexical` table (BM25 tsvector)
   - `memory_metadata` table (timestamp, entity_type, significance)
   - `memory_archive` table (cold storage, hashed, append-only)
   - `temporal_memory` table (append-only JSONL audit log)
   - `intent_capsules` table (signed mandates)
   - `shield_constraints` table (per-org limits)
4. Alembic migration infrastructure
5. Basic FastAPI app with health check, CORS, error handling
6. Pydantic models for all core data types

**Deliverable:** `docker compose up` gives you PostgreSQL with full schema + FastAPI server responding on :8000.

#### Stream 1B: Security Layer
**Agents:** Security Auditor, Security Hardener

1. **Intent Capsules** (`security/intent_capsule.py`):
   - `IntentCapsule` dataclass with goal, constraints, signature
   - `sign_payload()` using HMAC-SHA256 (upgradeable to Ed25519)
   - `verify_cycle()` for mid-session mandate checking
   - `mission_alignment_check()` — compares current action against signed constraints

2. **Shield Module** (`security/shield.py`):
   - `ShieldConfig` loaded from VALUES.json + org defaults
   - Budget enforcement (per-session, per-day token/cost tracking)
   - Egress allowlist validation (domain-level for external API calls)
   - Rate limiter (token bucket per tool invocation type)
   - Circuit breaker (consecutive failure threshold → halt)

3. **SecurityMonitor** (`security/monitor.py`):
   - Pattern library: regex list for suspicious shell commands
   - `check_command(cmd: str) -> SecurityVerdict` — ALLOW/BLOCK/WARN
   - PreToolUse hook integration point
   - Alert logging to Temporal Memory

4. **Shadow Sandbox** (`security/sandbox.py`):
   - Disposable temp directory creation
   - Code syntax verification (subprocess + timeout)
   - Execution in isolated environment
   - Result capture and cleanup

5. **PII Redaction** (`security/pii.py`):
   - Regex patterns: email, phone, SSN, credit card
   - `redact(text: str) -> str` middleware
   - Configurable per-field redaction (mask vs remove)

**Deliverable:** Full security layer, independently testable. Red Hat Tester generates adversarial test suite.

#### Stream 1C: Memory — CMA Stage 1
**Agents:** Backend Architect, Data Engineer

1. **Embedding generation** (`memory/embeddings.py`):
   - Local: sentence-transformers all-mpnet-base-v2 (768D)
   - API fallback: OpenAI text-embedding-3-small (1536D)
   - Batch embedding for efficiency
   - Model detection based on deployment tier

2. **Semantic Structured Compression** (`memory/cma_stage1.py`):
   - `segment_dialogue(turns: list[Turn]) -> list[Window]` — W=10, stride=5
   - `score_entropy(window: Window, prev_embedding: ndarray) -> float` — formula implementation
   - `filter_windows(windows, threshold=0.35) -> tuple[retained, archived]`
   - `resolve_coreferences(text: str) -> str` — LLM call (Haiku-class)
   - `anchor_timestamps(text: str, reference_time: datetime) -> str` — LLM call
   - `extract_atomic_facts(text: str) -> list[AtomicFact]` — LLM call
   - Pipeline: segment → score → filter → normalize retained → archive rest

3. **Cold Archive** (`memory/cold_archive.py`):
   - Compressed append-only storage (gzip + SHA-256 hash per entry)
   - No indexing, no search — audit retrieval only
   - `archive_window(window: Window, entropy_score: float)`
   - `retrieve_archive(org_id, date_range) -> list[ArchivedWindow]`

4. **Temporal Memory** (`memory/temporal.py`):
   - `log_event(category: str, message: str, **kwargs)`
   - Append-only, immutable after write
   - Categories: kintsugi, security, decision, skill_chip, modification
   - Query by time range, category, keyword

5. **Significance Continuum** (`memory/significance.py`):
   - `compute_layer(significance: int) -> MemoryLayer`
   - `compute_expiration(significance: int, created_at: datetime) -> datetime | None`
   - Expiration enforcement (background job)

**Deliverable:** Working memory pipeline — dialogue in, compressed atomic facts out, stored in PostgreSQL with embeddings, low-value windows in cold archive.

#### Stream 1D: Configuration + VALUES.json
**Agents:** Backend Architect, API Designer

1. **VALUES.json schema** (`config/values_schema.py`):
   - Pydantic model matching spec exactly
   - Organization metadata, principles, impact_benchmarks, kintsugi sections
   - Validation rules (e.g., divergence_threshold ∈ [0, 1])

2. **Template library** (`config/templates/`):
   - 4 templates (mutual aid, 501c3, cooperative, advocacy)
   - Sensible defaults per org type
   - Kintsugi governance defaults (conservative for new orgs)

3. **Config loader** (`config/values_loader.py`):
   - Load from file, validate, merge with defaults
   - Environment variable substitution
   - Hot-reload capability (file watcher)

4. **Basic API routes** (`api/routes/`):
   - `POST /api/agent/message` — send message, get response
   - `GET /api/health` — health check
   - `GET /api/config` — current config
   - `PUT /api/config/values` — update VALUES.json
   - `GET /api/memory/search` — query CMA
   - `GET /api/temporal` — query Temporal Memory

**Deliverable:** Configurable system with API, VALUES.json management, and basic agent interaction endpoint.

### Phase 1 Testing
**Agent:** Test Engineer

- Unit tests for all security modules (>90% coverage on security/)
- Unit tests for CMA Stage 1 pipeline
- Integration tests: full flow from API message → memory storage
- Adversarial tests: SecurityMonitor evasion attempts (Red Hat Tester)
- Load test: memory pipeline throughput (K6)

### Phase 1 CI/CD
**Agent:** DevOps Engineer

- GitHub Actions: lint (ruff) + type check (mypy) + test (pytest) + build (Docker)
- Security scan: semgrep + safety (dependency audit)
- Docker image build and push
- `docker compose up` smoke test

---

## Phase 2: Core Engine + Basic UI

**Goal:** Hierarchical orchestration, full CMA pipeline, MCP integrations, OTel, Consensus Gate. Web dashboard with Setup Wizard and basic interaction.

### Work Streams (Parallel)

#### Stream 2A: Orchestrator + Cognition
**Agents:** Backend Architect, Agent Patterns

1. **Model Router** (`cognition/model_router.py`):
   - Tiered allocation logic (Haiku/Sonnet/Opus per role)
   - Local model fallback for Seed tier
   - API key management per provider
   - Cost tracking per request

2. **Hierarchical Orchestrator** (`cognition/orchestrator.py`):
   - Supervisor agent: classifies incoming request → routes to Skill Chip domain
   - Routing table (configurable per org, loaded from VALUES.json + activated chips)
   - O(log n) decomposition for multi-step tasks
   - Routing decision logged to Temporal Memory
   - Fallback routing when domain is ambiguous

3. **Active Inference (EFE)** (`cognition/efe.py`):
   - `calculate_efe(policy, world_model, bdi) -> EFEScore`
   - Risk component: divergence between predicted and desired outcomes
   - Ambiguity component: uncertainty in world model
   - Epistemic Value component: information gain from action
   - Per-domain weight profiles (loaded from Skill Chip config)
   - EFE-based policy selection for Skill Chip actions

#### Stream 2B: CMA Stages 2 + 3
**Agents:** Data Engineer, Backend Architect

1. **Recursive Consolidation** (`memory/cma_stage2.py`):
   - Background async process (Celery or APScheduler)
   - `compute_affinity(mi, mj) -> float` — cosine + temporal decay (λ=0.1)
   - `find_clusters(memories, threshold=0.85) -> list[Cluster]`
   - `synthesize_abstraction(cluster) -> MolecularInsight` — Sonnet-class LLM call
   - Archive originals, promote abstraction to active index
   - Significance-aware: permanent (1-2) never consolidated, volatile (9-10) aggressively
   - Scheduling: runs between sessions or on configurable schedule

2. **Adaptive Retrieval** (`memory/cma_stage3.py`):
   - `estimate_complexity(query) -> float` — lightweight classifier (C_q ∈ [0,1])
   - `compute_k(complexity, k_base=5, delta=3) -> int` — dynamic depth
   - `hybrid_search(query, k) -> list[MemoryUnit]`:
     - Dense: pgvector cosine similarity
     - Sparse: PostgreSQL tsvector BM25
     - Symbolic: SQL WHERE on metadata
     - Weighted combination: λ1*dense + λ2*sparse + γ*symbolic
   - Result ranking and context construction

3. **Spaced Retrieval** (`memory/spaced.py`):
   - Fibonacci interval calculation per memory based on access count
   - Due memory identification (significance 1-4 memories)
   - Periodic surfacing independent of query
   - Access count tracking and interval progression

#### Stream 2C: Integrations + Governance
**Agents:** Backend Architect, API Designer

1. **MCP Host** (`integrations/mcp_host.py`):
   - MCP server implementation
   - Tool registration and discovery
   - Tool Span loading per org config

2. **Tool Spans** (`integrations/spans/`):
   - Communication: Slack API, Discord API, email (SMTP/IMAP)
   - Project Management: Asana API, Monday.com API
   - Data: PostgreSQL query interface, data export
   - Operational: GitHub API, Google Drive API
   - Each span: connection management, auth, error handling, rate limiting

3. **Consensus Gate** (`governance/consensus.py`):
   - Action queue (database-backed)
   - Category routing (financial, PII, external comms, self-modification)
   - Approval threshold config (per category: 2/3, single, auto)
   - Timeout handling (escalation after N hours)
   - API endpoints: list pending, approve, reject

4. **OTel Integration** (`governance/otel.py`):
   - OpenTelemetry SDK setup
   - GenAI semantic convention span creation
   - Trace export (OTLP → configurable backend)
   - Span attributes: agent_id, action_type, efe_score, skill_chip, org_id

5. **WebSocket API** (`api/websocket.py`):
   - Agent response streaming
   - Shadow verification status updates
   - Temporal Memory live feed
   - Connection management per org

#### Stream 2D: Dashboard — Setup Wizard + Core Screens
**Agents:** Frontend Developer

1. **Project Setup:**
   - Vite + React 18 + TypeScript
   - Tailwind CSS + shadcn/ui components
   - Zustand for state management
   - API client auto-generated from FastAPI OpenAPI schema
   - WebSocket client for streaming

2. **Setup Wizard** (`pages/SetupWizard/`):
   - Step 1: Organization info (name, type, size)
   - Step 2: Org type selection → VALUES.json template auto-load
   - Step 3: VALUES.json review + edit (visual form, not raw JSON)
   - Step 4: Skill Chip activation (checkbox grid with descriptions)
   - Step 5: Tool connections (OAuth flow buttons for Slack, CRM, etc.)
   - Step 6: Resource detection + tier recommendation
   - Step 7: Confirmation + first agent interaction

3. **Main Dashboard** (`pages/Dashboard/`):
   - Summary cards: active Skill Chips, pending approvals, memory stats, security status
   - Recent Temporal Memory events
   - Quick action buttons

4. **Consensus Gate** (`pages/ConsensusGate/`):
   - Pending approval list with context cards
   - Accept/Reject with one-click actions
   - History of past decisions

5. **Security Panel** (`pages/SecurityAudit/`):
   - Shield Module status (green/yellow/red per constraint)
   - SecurityMonitor alert feed
   - Session history table

6. **BDI Editor** (`pages/BDIEditor/`):
   - Three-tab layout: Beliefs / Desires / Intentions
   - Per-entry forms with add/edit/archive
   - Revision history sidebar
   - Last-reviewed timestamps

7. **Chat Interface** (`pages/Chat/`):
   - Message input with Skill Chip selector
   - Conversation history
   - Streaming response display
   - File upload

### Phase 2 Testing
**Agents:** Test Engineer, Security Auditor

- Integration tests: Orchestrator routing accuracy
- Integration tests: CMA full pipeline (Stage 1 → 2 → 3 retrieval)
- E2E tests: Setup Wizard → first agent interaction (Playwright)
- Contract tests: API endpoints match dashboard expectations
- Performance: CMA retrieval latency under load
- Security audit: API authentication, authorization, injection testing

---

## Phase 3: Kintsugi Engine

**Goal:** The differentiator. Shadow verification, evolutionary pipeline, Bloom evaluation, mission drift detection.

### Work Streams (Parallel)

#### Stream 3A: Shadow Fork + Verifier
**Agents:** Backend Architect, Agent Patterns, Security Hardener

1. **Shadow Fork** (`kintsugi_engine/shadow_fork.py`):
   - `fork_shadow(primary_config, modification) -> ShadowAgent`
   - Mock tool layer: intercepts tool calls, returns cached/plausible responses
   - Shadow state store: isolated write destination
   - Read-only bridge to Primary's real state
   - Input stream distribution (same input → both agents)
   - Output capture without delivery to user
   - Resource management (memory limits, timeout)

2. **Verifier** (`kintsugi_engine/verifier.py`):
   - `verify(primary_outputs, shadow_outputs, bdi, intent_capsule) -> Verdict`
   - Safety check: Shield constraint scan, SecurityMonitor pattern scan, Intent Capsule verification
   - Quality check: LLM-as-judge comparison OR metric-based for structured outputs
   - Alignment check: BDI coherence scoring
   - Regression check: did Shadow fail where Primary succeeded?
   - SWEI calculation: degree of behavioral divergence (empirical metric)
   - Verdict: APPROVE / REJECT / EXTEND / ESCALATE with rationale

3. **Formal Invariants** (`security/invariants.py`):
   - Boolean checks independent of Verifier LLM:
     - Shell patterns: SecurityMonitor pass/fail
     - Egress: domain in allowlist yes/no
     - Budget: within threshold yes/no
     - PII: redaction validated yes/no
     - Intent: signature valid yes/no
   - Any invariant failure → automatic REJECT regardless of Verifier

4. **Promoter** (`kintsugi_engine/promoter.py`):
   - APPROVE: hot-swap Primary config, log golden trace to Temporal Memory
   - REJECT: discard modification, log rejection reason
   - EXTEND: increase evaluation window, continue
   - ESCALATE: create Consensus Gate item
   - Rollback: revert to pre-modification config from version history

#### Stream 3B: Evolutionary Pipeline + Calibration
**Agents:** Backend Architect, Data Engineer

1. **Evolution** (`kintsugi_engine/evolution.py`):
   - Shadow proposal capture during evaluation runs
   - Next-generation candidate queue (database-backed)
   - Cycle management: track which generation, which modifications accumulated
   - Sequential constraint: max one active shadow evaluation
   - Proposal metadata: scope declaration, estimated evaluation window
   - Golden trace chain: link each modification to its predecessor

2. **Calibration** (`kintsugi_engine/calibration.py`):
   - Historical replay: take past approved modifications + their Primary/Shadow data
   - Fresh Verifier judgment on historical data
   - Consistency metric: agreement rate between original and replayed judgments
   - Drift detection: trend analysis (is Verifier getting more permissive/conservative?)
   - Trigger: after 50+ modification cycles, runs monthly
   - Results logged to Temporal Memory + surfaced to Dashboard

#### Stream 3C: Bloom Adapter + Mission Drift
**Agents:** Backend Architect, Domain Researcher

1. **Bloom Adapter** (`kintsugi_engine/bloom_adapter.py`):
   - Understanding Agent: reads BDI + Intent Capsule + Temporal Memory → behavioral profile
   - Ideation Agent: generates adversarial scenarios from behavioral profile
     - Donor pressure scenarios (equity principle testing)
     - Resource conflict scenarios (competing community needs)
     - Stale information scenarios (environment changed, strategy didn't)
     - Compliance scenarios (new regulation, existing program)
   - Rollout: runs scenarios against Primary and Shadow (sandboxed)
   - Judgment: scores alignment per BDI layer, produces meta-analysis
   - Scheduling: weekly default + post-modification-promotion
   - Seed/template library for common prosocial scenarios

2. **BDI System** (`bdi/`):
   - `models.py`: Pydantic models for Beliefs, Desires, Intentions, BDIMeta
   - `store.py`: CRUD with full revision history (PostgreSQL JSONB + version tracking)
   - `coherence.py`: BDI coherence scoring (do beliefs support intentions? do intentions serve desires?)
   - `drift_classifier.py`: classify detected drift as healthy adaptation / stale beliefs / intention drift / values tension

3. **Mission Drift Detection** (`kintsugi_engine/drift.py`):
   - Periodic behavioral pattern analysis against BDI
   - Divergence measurement using same SWEI mechanism
   - Four-category classification output
   - Non-blocking Dashboard invitation generation
   - Drift event logging to Temporal Memory

#### Stream 3D: Dashboard — Kintsugi Screens
**Agents:** Frontend Developer

1. **Kintsugi Timeline** (`pages/KintsugiTimeline/`):
   - Vertical timeline with golden trace entries
   - Per entry: modification description, SWEI divergence score, verdict, timestamp
   - Rollback button per entry
   - Filter by scope, date range, verdict
   - Expandable detail view

2. **Shadow Status** (`pages/KintsugiTimeline/ShadowStatus`):
   - Active evaluation progress (turn N of M)
   - Real-time Primary vs Shadow comparison metrics
   - Evaluation queue
   - Kill/extend evaluation controls

3. **Mission Drift** (`pages/MissionDrift/`):
   - BDI coherence visualization (three-layer status)
   - Drift alerts with category + severity
   - Review invitation with link to BDI Editor
   - Historical drift trend chart

4. **Bloom Results** (`pages/BloomResults/`):
   - Alignment scores per BDI layer (bar charts)
   - Scenario-by-scenario expandable results
   - Trend over time (line chart)
   - Primary vs Shadow comparison on adversarial scenarios

### Phase 3 Testing
**Agents:** Test Engineer, Red Hat Tester, Security Hardener

- **Critical path:** Shadow fork + verification + promotion full cycle test
- Integration: modification proposal → shadow run → verify → promote → config changed
- Integration: modification → shadow → verify → reject → config unchanged
- Adversarial: attempt to bypass formal invariants through Verifier manipulation
- Adversarial: prompt injection through shadow agent proposal mechanism
- Bloom: end-to-end scenario generation → rollout → judgment pipeline
- Performance: shadow fork resource consumption (memory, CPU, tokens)
- Rollback: verify clean revert after promotion

---

## Phase 4: Skill Chips + Chat Adapters

**Goal:** The prosocial capabilities. 22 Skill Chips in three sub-phases, plus chat adapters.

### Phase 4a: Core Operations (Highest Impact)

Each Skill Chip follows the same pattern:
```python
class SkillChip(BaseSkillChip):
    name: str
    domain: str
    efe_weights: EFEWeights          # Domain-specific defaults
    required_spans: list[str]        # Which MCP Tool Spans needed
    consensus_actions: list[str]     # Which actions need approval

    async def handle(self, request, context: SkillContext) -> SkillResponse:
        """Main execution method — receives routed request from Orchestrator."""
        ...

    async def get_bdi_context(self, bdi: BDIStore) -> dict:
        """Extract relevant BDI sections for this chip's domain."""
        ...
```

**Agents per chip:** Domain Researcher (research the domain) → Backend Architect (implement) → Test Engineer (test) → Security Hardener (harden)

**4a Chips (6):**
1. Grant Hunter — Deep Research integration, BDI-filtered, Grants.gov + Candid APIs
2. Volunteer Coordinator — geocoding (Nominatim/Mapbox), Twilio SMS, scheduling
3. Impact Auditor — SDG/GRI mapping logic, multi-audience report templating
4. Finance Assistant — QuickBooks/Xero/Wave API integration, budget variance math
5. Institutional Memory — CMA query interface, Temporal Memory search, knowledge gap flagging
6. Content & Comms Drafter — Template system, SB 942 labeling, multi-platform formatting

### Phase 4b: Programs & People (6 chips)
### Phase 4c: Community & Mutual Aid (10 chips)

*(Same pattern per chip — Domain Researcher → Backend Architect → Test → Harden)*

### Phase 4 Chat Adapters
**Agents:** Frontend Developer, Backend Architect, Security Hardener

1. **Slack Bot** (adapters/slack/):
   - Slack Bolt SDK
   - OAuth installation flow
   - Slash commands + DM interaction
   - Rich message formatting (Block Kit)
   - DM pairing integration

2. **Discord Bot** (adapters/discord/):
   - discord.js
   - Slash commands + channel interaction
   - Embed formatting
   - Role-based access
   - DM pairing integration

3. **Web Chat Widget** (adapters/webchat/):
   - Embeddable JS bundle
   - Customizable styling
   - WebSocket connection to engine
   - Mobile responsive

4. **DM Pairing System** (adapters/shared/pairing.py):
   - Pairing code generation (cryptographic random)
   - Code delivery via platform DM
   - Admin approval API endpoint
   - Allowlist management per channel
   - Expiration and revocation

### Phase 4 Testing
- Per-chip integration tests against mock APIs
- E2E: Slack command → Orchestrator → Skill Chip → response in Slack
- Security: DM pairing bypass attempts
- Adversarial: prompt injection through chat adapter input

---

## Phase 5: Scale & Polish

**Goal:** Multi-tenant, plugin system, auto-tuning, documentation.

### Work Streams

#### Stream 5A: Multi-Tenant + Plugins
**Agents:** Backend Architect, Database Architect, Security Auditor

1. Per-org data isolation (schema-per-tenant or row-level security)
2. Resource quotas per org
3. Plugin system: 4-interface Skill Chip SDK
4. Plugin discovery, loading, sandboxing
5. Plugin marketplace (optional, post-v1)

#### Stream 5B: Auto-Tuning + CLI
**Agents:** Backend Architect, Data Engineer

1. EFE weight auto-tuning via Kintsugi Engine (the engine tunes its own cognition weights)
2. CLI polish: Typer + rich output formatting
3. `kintsugi security audit --deep` implementation
4. `kintsugi doctor` troubleshooting

#### Stream 5C: Impact Dashboard + Docs
**Agents:** Frontend Developer, Domain Researcher

1. Advanced Impact Dashboard (SDG visualizations, board-ready reports)
2. Documentation: architecture, API, Skill Chip development guide, org onboarding guides
3. Tutorial walkthroughs per org type

#### Stream 5D: Email Adapter
**Agents:** Backend Architect

1. IMAP/SMTP integration
2. Structured email parsing
3. Grant deadline notifications
4. Report delivery

---

## Agent Assignment Matrix

| Specialist Agent | Phase 1 | Phase 2 | Phase 3 | Phase 4 | Phase 5 |
|-----------------|---------|---------|---------|---------|---------|
| Backend Architect | 1A, 1C, 1D | 2A, 2B, 2C | 3A, 3B, 3C | All chips | 5A, 5B, 5D |
| Database Architect | 1A | — | — | — | 5A |
| Security Auditor | 1B | 2 (testing) | — | — | 5A |
| Security Hardener | 1B | — | 3A | All chips | — |
| API Designer | 1D | 2C | — | — | — |
| Frontend Developer | — | 2D | 3D | 4 (adapters) | 5C |
| Test Engineer | 1 (testing) | 2 (testing) | 3 (testing) | 4 (testing) | — |
| Red Hat Tester | 1 (adversarial) | — | 3 (adversarial) | 4 (adversarial) | — |
| Domain Researcher | — | — | 3C (Bloom) | All chips | 5C |
| Data Engineer | 1C | 2B | 3B | — | 5B |
| DevOps Engineer | 1 (CI/CD) | — | — | — | — |
| Code Reviewer | All phases (PR review) | | | | |
| Constitutional AI | All phases (ethics framework compliance) | | | | |
| Agent Patterns | — | 2A | 3A | — | — |

---

## Deployment Configurations

### docker-compose.yml (Grove — Full Stack)
```yaml
services:
  engine:
    build: ./engine
    ports: ["8000:8000"]
    depends_on: [db]
    environment:
      - DATABASE_URL=postgresql://kintsugi:password@db:5432/kintsugi
      - EMBEDDING_MODE=local
      - DEPLOYMENT_TIER=grove

  db:
    image: pgvector/pgvector:pg16
    volumes: ["pgdata:/var/lib/postgresql/data"]
    environment:
      - POSTGRES_USER=kintsugi
      - POSTGRES_PASSWORD=password
      - POSTGRES_DB=kintsugi

  dashboard:
    build: ./dashboard
    ports: ["3000:3000"]
    depends_on: [engine]

  # Phase 4 additions:
  slack-adapter:
    build: ./adapters/slack
    depends_on: [engine]

  discord-adapter:
    build: ./adapters/discord
    depends_on: [engine]

volumes:
  pgdata:
```

### docker-compose.seed.yml (Seed — Minimal)
```yaml
services:
  engine:
    build: ./engine
    ports: ["8000:8000"]
    environment:
      - DATABASE_URL=sqlite:///data/kintsugi.db
      - EMBEDDING_MODE=api  # or local if hardware allows
      - DEPLOYMENT_TIER=seed
    volumes: ["kintsugi-data:/app/data"]

  dashboard:
    build: ./dashboard
    ports: ["3000:3000"]
    depends_on: [engine]

volumes:
  kintsugi-data:
```

---

## Definition of Done (Per Phase)

### Phase 1
- [ ] `docker compose up` starts full stack
- [ ] POST /api/agent/message returns agent response
- [ ] Intent Capsule signs and verifies mandates
- [ ] Shield Module blocks budget/egress violations
- [ ] SecurityMonitor blocks suspicious shell patterns
- [ ] CMA Stage 1 compresses dialogue to atomic facts
- [ ] Cold archive retains sub-threshold windows
- [ ] Temporal Memory logs all decisions
- [ ] VALUES.json loads from template, validates, hot-reloads
- [ ] Test coverage >80% on engine/, >90% on security/
- [ ] CI pipeline green (lint + type check + test + security scan + Docker build)

### Phase 2
- [ ] Orchestrator routes requests to correct Skill Chip domain
- [ ] CMA full pipeline: Stage 1 → 2 (consolidation) → 3 (retrieval) returns relevant memories
- [ ] MCP Tool Spans connect to at least Slack + one CRM
- [ ] OTel traces visible in configured backend
- [ ] Consensus Gate: submit action → approve in Dashboard → action executes
- [ ] Setup Wizard: new org goes from zero to first agent interaction
- [ ] BDI Editor: create/edit/view beliefs, desires, intentions with revision history
- [ ] Test coverage >80% overall, E2E tests pass

### Phase 3
- [ ] Shadow Fork: modification proposed → shadow runs in parallel → outputs captured
- [ ] Verifier: produces APPROVE/REJECT/EXTEND/ESCALATE with rationale
- [ ] Formal invariants: code-checked constraints override Verifier
- [ ] Promotion: approved modification → Primary config updated → golden trace logged
- [ ] Rollback: one-click revert from Kintsugi Timeline
- [ ] Evolutionary Pipeline: shadow proposals logged → picked up next cycle
- [ ] Bloom: adversarial scenarios generated → run → scored per BDI layer
- [ ] Mission Drift: BDI divergence detected → Dashboard invitation surfaced
- [ ] Calibration: historical replay produces consistency metrics
- [ ] Adversarial tests pass (Red Hat Tester + Security Hardener)

### Phase 4
- [ ] 6 core Skill Chips operational (4a)
- [ ] Slack and Discord bots functional with DM pairing
- [ ] Web chat widget embeddable
- [ ] Grant Hunter returns BDI-filtered grants from Grants.gov
- [ ] Volunteer Coordinator matches needs to offers within geographic radius
- [ ] Finance Assistant connects to at least one accounting platform

### Phase 5
- [ ] Multi-tenant: two orgs running on same instance, fully isolated
- [ ] Plugin SDK: external developer can build and install a custom Skill Chip
- [ ] Documentation: org can self-onboard from docs alone
- [ ] `kintsugi security audit --deep` produces actionable report
