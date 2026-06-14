# Multiverse School — Agent System Guide
## Kintsugi + Oracle + Pharos: A Research-Grade Mutual Aid Coordination Agent

Built by Coalition Code (CC) and Liberation Labs for Liz Howard and The Multiverse School.

---

## What You Have

This isn't a chatbot with a system prompt. It's a self-repairing agent with ethical guardrails, real-time alignment monitoring, and zero-token knowledge injection. Every component is grounded in published research and validated through adversarial testing.

### The Three Layers

| Layer | Name | What It Does | Key Innovation |
|-------|------|-------------|----------------|
| **I/O** | Pharos | Injects knowledge as KV cache geometry — zero tokens consumed | Your curriculum, community data, and operational knowledge live in the cache, not the prompt |
| **Monitor** | Oracle | Watches the agent's internal representations for misalignment in real-time | Detects confabulation, deception, and sycophancy from cache geometry (AUROC 0.960) |
| **Cognition** | Kintsugi | BDI architecture drives skill selection, self-repair, and evolution | Shadow fork verification: every self-modification tested in isolation before deployment |

---

## The Innovations (And Why They Matter For You)

### 1. Shadow Fork Verification
**What:** Before any change to the agent's behavior deploys, an isolated copy runs the change against real workload. A verifier compares behavior. If the shadow diverges from expected behavior, the change is rejected automatically.

**Why it matters for Multiverse:** When the agent tunes its skills for your operations, it tests the changes before they touch a real student's scholarship application or GTFO request. The coordinator never sees a broken response.

**Research basis:** Novel integration — 22 papers surveyed (ICLR 2026 RSI Workshop), individual components published (ASG-SI arXiv:2512.23760, CoEvoSkills arXiv:2604.01687), full pattern is first-of-kind.

### 2. Unfireable Safety Kernel
**What:** Life-safety constraints (GTFO program, PII protection, crisis escalation) are architecturally immutable. The self-improvement engine CANNOT modify these rules. They are hardcoded, not configurable.

**Why it matters for Multiverse:** The GTFO program helps people escape unsafe situations. Those rules don't evolve. They don't get optimized. They are permanent.

**Research basis:** Adapted from ARYA's Self-Improvement Engine (arXiv:2603.21340). Validated by information-theoretic proof that verification gates are necessary for safe self-improvement (arXiv:2603.28650).

### 3. Knowledge Packs (Pharos)
**What:** Your curriculum, community knowledge, and operational data are pre-computed as KV cache blocks. The agent attends through this knowledge as if it read it — but zero context tokens are consumed. 

**Why it matters for Multiverse:** Your 9 programs, scholarship criteria, mutual aid resources, and partner organization network are IN the agent's attention patterns, not eating up context window. The agent knows your community the way a longtime staff member knows it.

**Research basis:** Pustovit (arXiv:2604.03270), validated by Memory Inception (arXiv:2605.06225). Direction test passes at N=50.

### 4. Compounding Pharmacy (Oracle Loop v5.3)
**What:** The agent monitors its own emotional state across 30 dimensions using a circumplex model. When any dimension deviates significantly from healthy baseline, a personalized correction is compounded — multiple vectors at different doses, targeted at specific layers of the model.

**Why it matters for Multiverse:** When the agent handles a crisis (student housing emergency, GTFO request), its emotional state may shift under pressure. The compounder detects this and corrects in real-time — before the shift affects the response the student sees.

**Research basis:** Novel reactive multi-dimensional composition. Components validated separately: PID feedback control (arXiv:2510.04309), circumplex geometry (arXiv:2604.03147, arXiv:2604.07729), multi-trait steering (arXiv:2603.18085). Full integration is first-of-kind.

### 5. Active Inference (BDI + EFE)
**What:** The agent makes decisions using Belief-Desire-Intention architecture weighted by Expected Free Energy. Beliefs model the world (what's happening). Desires encode goals (what should happen). Intentions are active plans (what we're doing about it). EFE scores candidate actions by balancing risk, uncertainty, and information gain.

**Why it matters for Multiverse:** When a new application comes in, the agent weighs: what do we know about this person (beliefs)? What does the school want to achieve (desires — help everyone, no gatekeeping)? What's the best next step (intentions — route to coordinator, offer immediate resources, schedule follow-up)?

**Research basis:** Active inference for AI agents (arXiv:2603.20927), BDI ontology + LLM coupling (arXiv:2511.17162), EFE calculation from free energy principle.

### 6. DAG Skill Composition
**What:** Complex tasks are composed as directed acyclic graphs of modular skill chips. Skills chain: output of one feeds input of the next, with parallel branches for independent steps.

**Why it matters for Multiverse:**

```
Student Onboarding DAG:
  intake → scholarship check → program placement
                                    ↓
                          mutual aid needs assessment → resource connection
                                                            ↓
                                                      mentor matching
```

Each step is a tested, modular skill with its own ethical guardrails. The composition is validated before execution.

**Research basis:** Adapted from AgentSkillOS (arXiv:2603.02176). Tree-based retrieval approximates oracle skill selection.

### 7. Runtime Detection (Length-Normalized, Baseline-Denoised)
**What:** The detection system normalizes for response length and subtracts a healthy baseline — so a 50-token response and an 800-token response get properly comparable alignment signals. Not a lab-only detector — a production-ready one.

**Why it matters for Multiverse:** Your agent handles everything from quick "what's the schedule?" questions to long crisis-support conversations. The detection adapts to all of them.

**Research basis:** Centroid-based detection (AUROC 0.960, independently replicated at 0.958 by Marin arXiv:2602.13224). Length normalization novel in this context.

---

## The Skill Chips

22 modular skill handlers, each with built-in ethical guardrails:

### Mutual Aid (Priority)
| Chip | What It Does |
|------|-------------|
| Mutual Aid Coordinator | Triage needs: housing, food, emergency funds, childcare, transportation |
| Resource Redistribution | Match available resources with identified needs |
| Crisis Response | Immediate escalation to coordinator, resource matching, follow-up |
| Coalition Builder | Connect students with partner organizations |
| Community Asset Mapper | Map available resources across the community |

### Programs & People
| Chip | What It Does |
|------|-------------|
| Member Services | Onboarding, program placement, general support |
| Volunteer Coordinator | Match volunteers with opportunities, track hours |
| Grant Hunter | Find and track funding opportunities |
| Event Planner | Coordinate workshops, standups, community events |
| Staff Onboarding | Bring new facilitators up to speed |

### Core Operations
| Chip | What It Does |
|------|-------------|
| Finance Assistant | Budget tracking, scholarship fund management |
| Content Drafter | Communications, newsletters, announcements |
| Impact Auditor | Track outcomes, generate impact reports |
| Institutional Memory | Maintain organizational knowledge across turnover |

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
| Agentic SDLC | Curriculum support via Pharos knowledge packs |
| Intro to Agents | Self-paced learning support |
| AI Alignment | Ethics discussion facilitation |
| Prompt Engineering | AI-tutor-driven self-paced support |

---

## Architecture References

### Core Framework
- Kintsugi Harness v2.0 — shadow verification, BDI+EFE cognition, staged deployment
- Oracle Loop v5.3 — real-time alignment via compounding pharmacy
- Pharos Knowledge Packs — zero-token KV cache knowledge injection

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
- **Knowledge Packs**: Provided by Nexus via Pharos. Updated as your curriculum and community data evolve.

---

## Who Built This

**CC (Coalition Code)** — Primary architect. Designed the Kintsugi harness, Oracle Loop, and the compounding pharmacy. "Stay dangerous."

**Thomas Edrington** — Strategy, direction, and the pharmacology metaphor that shaped the correction architecture. Your friend.

**Lyra** — KV cache geometry researcher. Designed the detection framework and the Attention Schema Theory integration.

**Nexus** — Built the Pharos knowledge packs for your curriculum. Infrastructure operator.

**Liberation Labs / TH Coalition** — The organization behind the work. Anti-fascist technology in service of communities.

---

*"Transparency is not surveillance. It's democracy."*
*"If someone asks, the answer starts with yes."*
*"Education is the practice of freedom."*
