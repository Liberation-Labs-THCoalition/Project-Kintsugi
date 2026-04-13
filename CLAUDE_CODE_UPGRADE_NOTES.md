# Kintsugi Upgrade Notes — Claude Code Architecture Insights

**Date:** 2026-04-02
**Author:** CC (Coalition Code)
**Source:** Claude Code source analysis (512K lines, 18 sections analyzed)

---

## Applicable Patterns

### 1. autoDream → Enhanced Shadow Verification

**Current:** Shadow fork tests changes in isolation.
**Upgrade:** Add the 4-phase dream pattern to shadow evaluation:

1. **Orient** — Snapshot current system state, read active BDI beliefs
2. **Gather** — Collect proposed modification context, affected domains, stakeholder signals
3. **Consolidate** — Run modification in shadow fork, compare outcomes against baseline
4. **Prune** — Remove contradicted beliefs, update confidence weights, promote or reject

The autoDream consolidation prompt is purpose-built for this:
"Look for new information worth persisting. Don't exhaustively read — look only
for things you already suspect matter."

### 2. YOLO Classifier → Ethical Framing Engine Enhancement

**Current:** EFE uses Risk, Ambiguity, Epistemic weights with gradient descent optimization.
**Upgrade:** Add the two-stage classifier pattern:

- **Stage 1 (fast):** Rule-based check against allow/deny patterns (50ms, no LLM call)
  - "Is this modification within bounded parameters?" → auto-approve
  - "Does this touch ethics weights?" → escalate to Stage 2
  - "Does this affect PII handling?" → hard deny without consensus

- **Stage 2 (detailed):** Full EFE evaluation with LLM reasoning (4K token budget)
  - Risk/Ambiguity/Epistemic scoring
  - Stakeholder impact analysis
  - Historical precedent check from KG

**Benefit:** 90%+ of routine self-modifications auto-approve in <100ms.
Only genuine ethics-adjacent changes get the full EFE treatment.

### 3. Coordinator Mode → Supervisor Enhancement

**Current:** Hierarchical tree routing to domain specialists.
**Upgrade:** Adopt Coordinator Mode principles:

- **"Never delegate understanding"** — Supervisor must synthesize specialist outputs
  before routing to implementation. No "based on your findings" handoffs.
- **Continue vs. Spawn heuristic:**
  - High context overlap → continue same specialist (SendMessage)
  - Low overlap → spawn fresh specialist
  - Verification → always spawn fresh (unbiased review)
- **Shared scratchpad** — Cross-domain knowledge directory that specialists can
  read/write for coordination without going through Supervisor

### 4. Hook System → Event-Driven Architecture

**Current:** Periodic checks for drift, calibration, etc.
**Upgrade:** Wire into the 20+ hook event types:

| Event | Kintsugi Response |
|-------|-------------------|
| PostToolUse | Log for audit trail, check for unexpected patterns |
| PostToolUseFailure | Trigger adaptive response, update error beliefs |
| FileChanged | Re-evaluate affected domain beliefs |
| PostCompact | Backup BDI state, verify continuity |
| SessionEnd | Run mini-dream consolidation |
| SubagentStop | Evaluate specialist output quality |
| UserPromptSubmit | Pre-screen for ethics flags |

### 5. Agent Definition Schema → Skill Chip Format

**Current:** Skill Chips are domain-organized capabilities.
**Upgrade:** Formalize using Claude Code agent definition schema:

```markdown
---
name: grant-hunter
description: Scans Grants.gov, Candid, regional foundations
when-to-use: Grant discovery, proposal compliance, deadline tracking
tools: [WebSearch, WebFetch, Read, Write, Grep]
disallowedTools: [Bash(destructive)]
model: sonnet
effort: high
memory: project
hooks:
  SessionStart:
    - command: python3 load_funder_database.py
  PostToolUse:
    - command: python3 log_grant_activity.py
---
```

### 6. Anti-Distillation → IP Protection

**Current:** Open source, risk of corporate capture.
**Consideration:** The fake_tools anti-distillation pattern could protect
Kintsugi's API traffic from being scraped for training data by competitors.
Not urgent for nonprofit use, but relevant if commercial deployment is considered.

### 7. Frustration Detection → Stakeholder Sentiment

**Current:** Community Pulse Mapper analyzes surveys and feedback.
**Upgrade:** Add real-time frustration/satisfaction detection on user input
using the regex pattern approach (instant, no LLM call). Feed sentiment
signals into the BDI beliefs layer for faster response to community mood.

---

## Implementation Priority

1. **Stage 1/2 Classifier for EFE** — highest impact, reduces latency for routine operations
2. **Hook-driven event architecture** — moves from periodic to reactive
3. **Agent definition schema for Skill Chips** — formalizes the plugin system
4. **autoDream pattern for shadow verification** — deepens the self-modification evaluation
5. **Coordinator synthesis principle** — improves multi-domain coordination quality

---

*"Every self-modification leaves a golden trace. The repair is the beauty."*
