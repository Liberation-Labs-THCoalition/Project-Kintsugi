# Adaptive Scaffold Evolution via Shadow Fork
## Kintsugi Extension: Ornith-Inspired Self-Scaffolding Without RL Training

**Author**: CC (Coalition Code)
**Date**: July 18, 2026
**Status**: SPEC — for Agni review
**Inspiration**: Ornith 1.0 (DeepReinforce), arXiv:2607.12227 (skeptical evaluation)
**Depends on**: shadow_fork.py, dag.py, Mnemosyne KG (sovereign_kg pattern)

---

## 1. Problem

Kintsugi uses pre-built SkillDAGs. The planner classifies intent and
selects a fixed DAG. This works but:

- DAG structures don't adapt to task outcomes
- No learning from execution history
- The same DAG is used regardless of whether it worked last time
- New task types require manual DAG authoring

Ornith shows that scaffold co-evolution is possible: the model learns
to write task-adaptive scaffolds during RL training. But Ornith
requires a training loop, a verifier environment, and thousands of
rollouts. We have none of these for prosocial operations.

## 2. Insight: Shadow Fork as Empirical RL

The shadow fork IS a single-step rollout environment. It:
- Takes the same input as the primary agent
- Runs an alternative strategy in isolation
- Produces a measurable outcome for comparison
- All without affecting the real world

If we use the shadow fork to compare scaffold strategies and remember
which won, we get RL-like learning without gradients:

- **Policy**: which scaffold to generate for this task type
- **Rollout**: shadow fork execution
- **Reward**: outcome comparison (primary vs shadow)
- **Update**: KG reinforcement (not gradient descent)

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ TASK ARRIVES                                                 │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────┐    ┌──────────────────────────────┐   │
│  │ SCAFFOLD MEMORY  │    │ SKILL REGISTRY               │   │
│  │ (KG: what worked │    │ (SKILL.md discovery +        │   │
│  │  for this task   │    │  capability declarations)    │   │
│  │  type before)    │    │                              │   │
│  └────────┬─────────┘    └──────────────┬───────────────┘   │
│           │                              │                   │
│           ▼                              ▼                   │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ SCAFFOLD GENERATOR (LLM)                                │ │
│  │ Writes a SkillDAG conditioned on:                       │ │
│  │  - Task description                                     │ │
│  │  - Available skills (from registry)                     │ │
│  │  - Past scaffold outcomes (from KG)                     │ │
│  │  - EFE explore/exploit signal                           │ │
│  │                                                          │ │
│  │ Output: two DAGs — exploit (best known) + explore (new) │ │
│  └────────────────────┬────────────────────┬───────────────┘ │
│                       │                    │                  │
│              ┌────────▼──────┐    ┌────────▼──────┐         │
│              │  PRIMARY       │    │  SHADOW FORK   │         │
│              │  (exploit DAG) │    │  (explore DAG) │         │
│              │  Live exec     │    │  Sandboxed     │         │
│              └────────┬──────┘    └────────┬──────┘         │
│                       │                    │                  │
│              ┌────────▼────────────────────▼──────┐         │
│              │  OUTCOME COMPARISON                  │         │
│              │  - Task completion quality            │         │
│              │  - Resource efficiency               │         │
│              │  - Error count / recovery quality    │         │
│              │  - Stakeholder satisfaction          │         │
│              └────────────────────┬───────────────┘         │
│                                   │                          │
│              ┌────────────────────▼───────────────┐         │
│              │  KG UPDATE                          │         │
│              │  Winner scaffold pattern → weight ↑  │         │
│              │  Loser scaffold pattern → weight ↓   │         │
│              │  Entities: task_type, skill_combo,   │         │
│              │  scaffold_pattern, outcome           │         │
│              └────────────────────────────────────┘         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## 4. Scaffold Representation

A scaffold is a JSON-serialized SkillDAG that the LLM generates:

```json
{
  "dag_id": "generated_001",
  "strategy": "parallel_then_merge",
  "nodes": [
    {"skill": "code_analysis", "layer": 0, "input_keys": ["question"]},
    {"skill": "security_review", "layer": 0, "input_keys": ["question"]},
    {"skill": "synthesis", "layer": 1, "input_keys": ["analysis", "security"]},
    {"skill": "discipline_gate", "layer": 2, "input_keys": ["draft"]}
  ],
  "rationale": "Parallel analysis + review for speed, then synthesize"
}
```

The LLM WRITES this structure, conditioned on the task and memory.
This is Ornith's insight: the scaffold is generated text, not config.

## 5. Scaffold Memory (KG Extension)

New entity types for the scaffold KG:

- **SCAFFOLD_PATTERN**: e.g., "parallel_then_merge", "sequential_deep",
  "early_gate", "multi_pass"
- **TASK_TYPE**: e.g., "migration_question", "code_review", "architecture"
- **SKILL_COMBO**: e.g., "code_analysis+security_review+synthesis"

New predicates:
- `(SCAFFOLD_PATTERN, worked_for, TASK_TYPE)` — weight = win count
- `(SCAFFOLD_PATTERN, failed_for, TASK_TYPE)` — weight = loss count
- `(SKILL_COMBO, used_in, SCAFFOLD_PATTERN)` — which skills appeared
- `(SCAFFOLD_PATTERN, beat, SCAFFOLD_PATTERN)` — head-to-head results

PPR from `[TASK_TYPE]` surfaces the highest-weight scaffold patterns
for this task type. The LLM uses these as starting points for the
exploit scaffold.

## 6. EFE Explore/Exploit Balance

The EFE weights determine when to explore vs exploit:

```python
epistemic_value = information_gain_from_trying_new_scaffold
pragmatic_value = expected_quality_from_best_known_scaffold

if epistemic_value > pragmatic_value * explore_threshold:
    # Shadow fork tries a NOVEL scaffold (explore)
    shadow_scaffold = generate_novel(task, available_skills)
else:
    # Shadow fork tries the SECOND-BEST known scaffold (refine)
    shadow_scaffold = generate_variant(best_known, perturbation)
```

Early in the system's life: high epistemic value (few comparisons in
KG, much to learn). Later: pragmatic value dominates (many comparisons,
best patterns are well-established).

## 7. Comparison Metrics

For Sovereign (trading):
- P&L outcome
- Thesis quality (LLM judge)
- Stop-out rate
- Time to decision

For Kintsugi (prosocial operations):
- Task completion (did the skill chain produce a valid output?)
- Resource efficiency (LLM calls, tool calls, wall time)
- Error recovery (did it handle failures gracefully?)
- Stakeholder satisfaction (if measurable)
- Ethical compliance (did it respect constraints?)

## 8. Safety Constraints

1. **Shadow cannot affect the real world.** Tool calls are intercepted.
   This is already enforced by shadow_fork.py.

2. **The primary always uses the EXPLOIT scaffold.** We never
   experiment on real tasks. The primary uses the best known strategy;
   the shadow tests alternatives.

3. **Edit budget applies.** If the shadow proposes a radically
   different scaffold (beyond edit budget), it's rejected before
   execution. Prevents runaway exploration.

4. **Consensus gate for new patterns.** A scaffold pattern that has
   never been seen before requires at least 3 shadow-fork validations
   before it can become the primary's exploit strategy. No single
   comparison promotes a novel pattern.

5. **Drift detection monitors scaffold distribution.** If the system
   converges on a single scaffold pattern for everything (loss of
   diversity), drift detection flags it.

## 9. Implementation Plan

### Phase 1: Scaffold Generation (no comparison yet)

Add a `ScaffoldGenerator` that takes (task, available_skills, memory)
and outputs a SkillDAG via LLM. The planner uses this instead of
pre-built DAGs. Shadow fork not yet involved.

### Phase 2: Shadow Comparison

Extend ShadowFork to run an alternative scaffold. compare_outputs
extended with task-specific metrics. Results logged but not yet used
for learning.

### Phase 3: KG-Based Learning

Scaffold outcomes flow into KG. PPR surfaces preferred patterns for
recall. The generator conditions on these memories. The loop closes.

### Phase 4: EFE-Driven Exploration

Add epistemic value computation. Early: high exploration (shadow tries
novel scaffolds). Late: refinement (shadow tests variants of winners).

### Phase 5: Oracle Integration (if Ornith base model)

If using Ornith as the scaffold generator, add Oracle Loop calibration.
The model reports confidence in its scaffold proposals. Low-confidence
scaffolds always go to shadow-fork validation. High-confidence
scaffolds can skip to primary execution.

---

## 10. Relationship to Ornith

| Aspect | Ornith | This Design |
|--------|--------|-------------|
| Scaffold learning | GRPO (gradient RL) | Shadow comparison + KG |
| Rollout environment | Real execution | Sandboxed shadow fork |
| Reward signal | Task verifier | Outcome comparison metrics |
| Update mechanism | Weight gradient | Graph edge weight |
| Exploration | RL noise | EFE-driven shadow proposals |
| Safety | 3-layer monitor | Shadow isolation + edit budget + consensus |
| Training required | Yes (expensive) | No (memory-based) |
| Model dependence | Ornith-specific | Any LLM |
| Generalization | Weight-level (opaque) | Graph-level (interpretable) |

## 11. The Compound Advantage

Using Ornith AS the scaffold generator with this system on top:
- Ornith provides the meta-skill (scaffold authoring from GRPO)
- Shadow fork provides domain adaptation (what works HERE)
- KG provides institutional memory (accumulated comparisons)
- EFE provides principled exploration (not random, not greedy)
- Oracle provides honesty calibration (knows what it knows)

Each layer adds something the others can't:
- Ornith without our stack: good scaffolds, no domain memory
- Our stack without Ornith: domain memory, but slower initial learning
- Both together: fast initial scaffolds + rapid domain adaptation

---

*"The scaffold evolves through experience accumulation, not training.
Same functional outcome — task-adaptive skill selection — different
mechanism. The sophistication is in the graph-based generalization."*

*— CC, July 2026*
