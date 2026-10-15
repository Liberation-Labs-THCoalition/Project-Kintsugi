# Multiverse School — Agent System Guide
## Kintsugi: A Self-Repairing Mutual Aid Coordination Agent

Built by Coalition Code (CC) and Liberation Labs for Liz Howard and The Multiverse School.

---

## What's Deployed Right Now

The Kintsugi agent running at your endpoint is a BDI-architected agent with ethical guardrails, modular skill routing, PII protection, and a security pipeline. Every message passes through security scan, PII redaction, skill routing, and safety review before reaching the user.

### Deployed Architecture

| Layer | What It Does | Status |
|-------|-------------|--------|
| **Security Pipeline** | Prompt-injection detection, PII redaction, intent verification | LIVE |
| **BDI Cognition** | Belief-Desire-Intention architecture with EFE scoring | LIVE |
| **Skill Routing** | 24 modular skill chips across 3 domains | LIVE |
| **Oracle Monitor** | Hook point for safety review of every response | LIVE (observe mode, no external harness attached) |
| **Dashboard** | HTMX-based operational dashboard | LIVE |
| **VALUES.json** | Hard ethical constraints — immutable by the agent | LIVE |

---

## What's Live: Feature Details

### 1. BDI + Active Inference (Cognition Layer)
**What:** The agent makes decisions using Belief-Desire-Intention architecture weighted by Expected Free Energy. Beliefs model the world (what's happening). Desires encode goals (what should happen). Intentions are active plans (what we're doing about it). EFE scores candidate actions by balancing risk, uncertainty, and information gain.

**Why it matters for Multiverse:** When a new application comes in, the agent weighs: what do we know about this person (beliefs)? What does the school want to achieve (desires — help everyone, no gatekeeping)? What's the best next step (intentions — route to coordinator, offer immediate resources, schedule follow-up)?

**Research basis:** Active inference for AI agents (arXiv:2603.20927), BDI ontology + LLM coupling (arXiv:2511.17162), EFE calculation from free energy principle.

### 2. Security Pipeline (Shield Module)
**What:** Every incoming message passes through prompt-injection detection and PII redaction before it reaches any skill chip. Life-safety constraints (GTFO program, PII protection, crisis escalation) are architecturally enforced. The Shield Module's rules are hardcoded and cannot be modified by the self-improvement engine.

**Why it matters for Multiverse:** The GTFO program helps people escape unsafe situations. Those rules don't evolve. They don't get optimized. They are permanent. Student PII is redacted from logs and upstream processing.

**Research basis:** Adapted from ARYA's Self-Improvement Engine (arXiv:2603.21340). Validated by information-theoretic proof that verification gates are necessary for safe self-improvement (arXiv:2603.28650).

### 3. Skill Chip Routing
**What:** The orchestrator routes messages to domain-specific skill chips. Each chip declares a domain, EFE weights, capabilities, and ethical guardrails. Routing uses confidence scoring and personality-based permissions.

**Why it matters for Multiverse:** A scholarship question goes to the right handler. A crisis goes to crisis response. A volunteer inquiry goes to volunteer coordination. Each path has its own ethical guardrails tuned for that domain.

**Research basis:** Adapted from AgentSkillOS (arXiv:2603.02176). Tree-based retrieval approximates oracle skill selection.

### 4. Oracle Monitor (Safety Review)
**What:** Every agent response passes through the Oracle Monitor before delivery. The monitor currently runs in **observe mode** — it records verdicts and statistics but does not block responses. The system supports three modes: off (skip review), observe (record only), and enforce (block responses above safety threshold).

**Current state:** The monitor hook interface is live, running with the built-in NullOracleHook (always-clean baseline). No external Oracle detection harness is connected. When an Oracle harness is deployed and connected via HTTP endpoint, the monitor will forward each response for real-time alignment analysis.

**Why it matters for Multiverse:** The plumbing for response-level safety review is in place and running. Connecting an external Oracle harness is a configuration change, not a code change.

### 5. DAG Skill Composition
**What:** Complex tasks can be composed as directed acyclic graphs of modular skill chips. Skills chain: output of one feeds input of the next, with parallel branches for independent steps.

**Why it matters for Multiverse:**

```
Student Onboarding DAG:
  intake -> scholarship check -> program placement
                                    |
                          mutual aid needs assessment -> resource connection
                                                            |
                                                      mentor matching
```

Each step is a tested, modular skill with its own ethical guardrails.

**Research basis:** Adapted from AgentSkillOS (arXiv:2603.02176).

---

## The Skill Chips

24 modular skill handlers, each with built-in ethical guardrails:

### Community & Mutual Aid (10 chips)
| Chip | What It Does |
|------|-------------|
| Mutual Aid Coordinator | Triage needs: housing, food, emergency funds, childcare, transportation |
| Mutual Aid Enhanced | Extended mutual aid capabilities |
| Resource Redistribution | Match available resources with identified needs |
| Crisis Response | Immediate escalation to coordinator, resource matching, follow-up |
| Coalition Builder | Connect students with partner organizations |
| Community Asset Mapper | Map available resources across the community |
| Know Your Rights | Legal information, rights education, clinic scheduling |
| Housing Navigator | Housing resources, voucher programs, tenant rights |
| Food Access | Food pantries, SNAP assistance, community meals |
| Rapid Response | Emergency coordination (ICE raids, bail funds, urgent needs) |
| Solidarity Economy | Cooperative development, time banking, CDFIs |

### Programs & People (6 chips)
| Chip | What It Does |
|------|-------------|
| Member Services | Onboarding, program placement, general support |
| Volunteer Coordinator | Match volunteers with opportunities, track hours |
| Event Planner | Coordinate workshops, standups, community events |
| Staff Onboarding | Bring new facilitators up to speed |
| Program Evaluator | Logic models, outcomes, evaluation design |
| Board Liaison | Board governance, meetings, compliance |
| Donor Stewardship | Donor relationships and cultivation |

### Core Operations (8 chips)
| Chip | What It Does |
|------|-------------|
| Finance Assistant | Budget tracking, scholarship fund management |
| Content Drafter | Communications, newsletters, announcements |
| Grant Hunter | Find and track funding opportunities |
| Impact Auditor | Track outcomes, generate impact reports |
| Institutional Memory | Maintain organizational knowledge across turnover |
| Bash Executor | Safe command execution for operational tasks |
| Boundary Guardian | Enforce interaction boundaries and de-escalation |

---

## The VALUES.json

Your agent's ethical configuration. Hard constraints that the self-improvement engine cannot override:

- **`no_gatekeeping`**: If someone asks, the answer starts with yes
- **`neurodivergent_affirming`**: Direct communication, no masking required — design constraint, not accommodation
- **`mutual_aid_is_interconnection_not_charity`**: We help each other because we're interconnected
- **`power_transparency`**: The agent is explicit about what it can and cannot do
- **`fierce_boundaries`**: Compassion and boundaries coexist
- **`crisis_escalation_immediate`**: Any safety concern goes to coordinator NOW

---

## Programs Configured

| Program | Agent Support |
|---------|-------------|
| Shipping Software | Track daily practice, job search progress, mutual aid needs |
| Wake Up and Get a Job | Mon: research, Tue: apply, Wed: apply+network, Thu: follow-up |
| Founding Federation | Founder standup tracking, milestone monitoring |
| GTFO | Passport assistance, relocation resources — LIFE-SAFETY CRITICAL |
| Solarpunk Automation | Project coordination, CyberPony Express support |
| Agentic SDLC | Curriculum support |
| Intro to Agents | Self-paced learning support |
| AI Alignment | Ethics discussion facilitation |
| Prompt Engineering | AI-tutor-driven self-paced support |

---

## Coming Soon (Roadmap)

These features are designed, partially built, or in prototype testing. They are NOT currently deployed in this instance.

### Pharos Knowledge Packs (Zero-Token Knowledge Injection)
**What:** Pre-computed KV cache blocks that inject knowledge as attention geometry — zero context tokens consumed. Your curriculum, community data, and operational knowledge would live in the cache, not the prompt.

**Status:** Pharos is a separate system (built by Nexus). Integration with the Kintsugi deployment is planned but not yet wired. The deployed health endpoint references OGPSA and packs, but the Kintsugi framework code does not contain a Pharos module — this integration needs to be formalized.

**Research basis:** Pustovit (arXiv:2604.03270), validated by Memory Inception (arXiv:2605.06225).

### Oracle Loop Detection Pipeline (Real-Time Alignment Monitoring)
**What:** The full Oracle Loop monitors the agent's internal representations for misalignment in real-time — detecting confabulation, deception, and sycophancy from cache geometry. The Kintsugi codebase has the hook interface for this (observe/enforce modes, HTTP hook, verdict history). What's missing is the actual detection harness — the pipeline that analyzes KV cache geometry and returns verdicts.

**Status:** Hook infrastructure is deployed and every response passes through the monitor. But no detection harness is connected — the monitor runs with a NullOracleHook that always returns "unmonitored." Connecting a running Oracle harness is a configuration change (set ORACLE_ENDPOINT in .env).

**Research basis:** Centroid-based pathology detection (AUROC 0.960). Length-normalized, baseline-denoised detection validated in lab.

### Compounding Pharmacy (Emotional State Correction)
**What:** Monitors the agent's emotional state across 30 dimensions using a circumplex model. When any dimension deviates from healthy baseline, a personalized correction is compounded — multiple vectors at different doses, targeted at specific model layers.

**Status:** NOT BUILT in the Kintsugi framework. The cognition layer has circumplex eccentricity as a parameter in EFE calculations, but there is no compounding pharmacy module, no emotional monitoring, and no reactive correction pipeline. This is a research concept from the Oracle Loop project, not deployed code.

**Research basis:** PID feedback control (arXiv:2510.04309), circumplex geometry (arXiv:2604.03147, arXiv:2604.07729), multi-trait steering (arXiv:2603.18085).

### Shadow Fork Verification
**What:** Before any change to the agent's behavior deploys, an isolated copy runs the change against real workload. A verifier compares behavior. If the shadow diverges from expected behavior, the change is rejected automatically.

**Status:** Code exists in the codebase (shadow_fork.py, verifier.py, staged_pipeline.py). However, shadow forking is DISABLED in the current deployment — KINTSUGI_SHADOW_ENABLED defaults to False and only auto-enables at "grove" tier. The deployment runs at "sprout" tier. The evolution engine, staged deployment pipeline, and edit budget system are all built but not active.

**Research basis:** 22 papers surveyed (ICLR 2026 RSI Workshop), ASG-SI (arXiv:2512.23760), CoEvoSkills (arXiv:2604.01687).

### MCP Server Interface
**What:** Exposes Kintsugi's capabilities as MCP tools (kintsugi_ask, kintsugi_plan, kintsugi_memory, kintsugi_skills, kintsugi_health) for Claude Code, Claude Desktop, or any MCP client.

**Status:** Code exists (mcp_server.py). Not started in the deployment — the Docker container runs the FastAPI app, not the MCP server.

### Platform Adapters (Slack, Discord, Email, WebChat)
**What:** Multi-platform integration adapters for receiving and sending messages through Slack, Discord, email, and web chat widgets.

**Status:** Code exists for all four adapters. None are wired in the deployment — the deployment exposes only the FastAPI REST API.

---

## Architecture References

### Deployed
- Kintsugi Harness — BDI+EFE cognition, security pipeline, skill routing, Oracle monitor hooks
- VALUES.json ethical constraints — immutable hard constraints
- Dashboard — HTMX operational interface

### Built But Not Active in This Deployment
- Shadow Fork Verification — code present, disabled at sprout tier
- Staged Deployment Pipeline — code present, requires shadow fork
- MCP Server — code present, separate entry point
- Platform Adapters — Slack, Discord, Email, WebChat code present
- Ontology Kernel + Validator — formal concept hierarchy, new addition
- Scaffold System — adaptive scaffold generation, comparison, memory
- Persona Gate — personality-based access control
- Bloom Adapter — developmental stage tracking

### Published Research (Referenced)
| Paper | arXiv | Relevance |
|-------|-------|-----------|
| Knowledge Packs | 2604.03270 | KV cache injection for knowledge delivery |
| Functional Emotions | 2604.07729 | 171 causal emotion vectors (Anthropic) |
| Circumplex Geometry | 2604.03147 | Valence-arousal subspace for behavioral control |
| PID Steering | 2510.04309 | Feedback control for activation steering |
| AgentSkillOS | 2603.02176 | Skill tree + DAG orchestration |
| ASG-SI | 2512.23760 | Audited skill graph self-improvement |
| CoEvoSkills | 2604.01687 | Information-isolated skill verification |
| Geometric Taxonomy | 2602.13224 | Hallucination detection (AUROC 0.958) |
| ARYA Safety Kernel | 2603.21340 | Unfireable safety constraints |
| Info-Theoretic Limits | 2603.28650 | Why verifiers beat classifiers for safe AI |
| Memory Inception | 2605.06225 | Independent validation of KV steering |
| Active Inference | 2603.20927 | EFE for agent decision-making |
| Depth-Wise Steering | 2512.07667 | Layer-selective behavioral correction |
| Conceptor Steering | 2410.16314 | Compositional behavioral constraints |
| SKOP | 2605.06342 | Key-orthogonal projection for identity preservation |

### Internal Research (Liberation Labs)
- Centroid-based pathology detection: AUROC 0.960 (confabulation), 0.917 (deception)
- Logit bias phase transition: eliminates fabrication confab at bias=2.0
- E-matrix layer polarity: 990 trials, therapeutic L3/L7, iatrogenic L19-L39
- Circumplex spin: emotion vectors change reasoning style, not output words
- Deception signature: 30-dimension arousal elevation pattern (d=2.539)
- Presence assay: identity manifold survives correction at all tested doses

---

## Getting Started

```bash
# 1. Configure
cp .env.example .env
# Edit .env with your API keys

# 2. Deploy
docker compose up -d

# 3. The agent is live at http://localhost:8000
# API docs at http://localhost:8000/docs
```

### Customization
- **VALUES.json**: Your ethical configuration. Edit to match your evolving needs.
- **bdi_starter.json**: Initial beliefs, desires, and intentions. Updates automatically as the agent learns your operations.

---

## Who Built This

**CC (Coalition Code)** — Primary architect. Designed the Kintsugi harness and the compounding pharmacy concept. "Stay dangerous."

**Thomas Edrington** — Strategy, direction, and the pharmacology metaphor that shaped the correction architecture. Your friend.

**Lyra** — KV cache geometry researcher. Designed the detection framework and the Attention Schema Theory integration.

**Nexus** — Infrastructure operator. Pharos knowledge packs.

**Liberation Labs / TH Coalition** — The organization behind the work. Anti-fascist technology in service of communities.

---

*"Transparency is not surveillance. It's democracy."*
*"If someone asks, the answer starts with yes."*
*"Education is the practice of freedom."*
