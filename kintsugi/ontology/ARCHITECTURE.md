# Ontology Kernel — Architecture for Kintsugi

**Author:** CC (Coalition Code)
**Date:** 2026-08-27
**Status:** ARCHITECTURE — design document, pre-build

---

## What It Is

A formal concept hierarchy that every Kintsugi module queries against. Instead of
constraints scattered across SkillChips, BoundaryGuardian rules, Shield invariants,
and PersonaGate checks, the ontology provides ONE queryable source of truth for
what concepts exist, how they relate, and what constraints govern them.

The kernel is NOT a replacement for any existing module. It's the connective tissue
that makes them coherent.

## What It Replaces vs What It Connects

| Component | Before Kernel | After Kernel |
|-----------|--------------|-------------|
| SkillRegistry | Flat catalog, domain enum | Unchanged — kernel validates results |
| CapabilityTree | BDI-driven retrieval | Unchanged — kernel filters candidates |
| EFE | Scores policies | Scores against ontology-informed context |
| BDI | Untyped beliefs dict | Beliefs as typed ontological triples |
| PersonaGate | Pattern matching | Validates against Role ontology |
| BoundaryGuardian | Hardcoded rule list | Rules derived from ontological constraints |
| Shield | Hard invariants | Unchanged — ontology respects Shield |
| VerificationScheduler | Standalone (new) | Checks assertions against ontology types |

## The Three Ontologies (FAOS-inspired)

### R — Role Ontology
WHO can do WHAT. Maps to PersonaGate + Shield.

```
Role
├── Agent (the AI)
│   ├── constraints: [never_override_shield, log_all_actions, disclose_ai]
│   └── can: [read, analyze, draft, propose]
│       cannot: [commit_without_approval, share_pii, modify_own_ethics]
├── Operator (human admin)
│   ├── constraints: [audit_trail_required]
│   └── can: [approve, configure, override_agent]
├── Stakeholder (community member)
│   ├── constraints: [consent_required]
│   └── can: [request, review, provide_feedback]
└── Verifier (shadow fork / Agni)
    ├── constraints: [isolation_required, adversarial_default]
    └── can: [read, challenge, reject]
```

### D — Domain Ontology
WHAT concepts exist and how they relate. Maps to SkillDomain + CapabilityTree.

```
Domain
├── Organization
│   ├── Mission
│   ├── Budget
│   ├── Stakeholders
│   └── Compliance (→ governance constraints)
├── Community
│   ├── Members
│   ├── Needs (→ drives skill selection)
│   ├── Assets (→ resource mapping)
│   └── Vulnerabilities (→ prioritization)
├── Infrastructure
│   ├── Services (→ dependency graph)
│   ├── Credentials (→ security constraints)
│   ├── Machines (→ state model)
│   └── Networks (→ access control)
├── Campaign (Cabildo extension)
│   ├── Voters
│   ├── Opponent
│   ├── Compliance (→ election law)
│   └── Content (→ disclosure requirements)
├── Research (Oracle Loop extension)
│   ├── Experiments (→ Agni gate requirements)
│   ├── Metrics (→ per-sample vs rank-bounded)
│   ├── Findings (→ provenance tracking)
│   └── Calibration (→ artifact integrity)
└── Identity (Ayni extension)
    ├── Assertions (→ VerificationScheduler)
    ├── Engagement (→ circumplex vs full geometry)
    └── Substrate (→ migration tracking)
```

### I — Interaction Ontology
HOW actions flow. Maps to DAGExecutor + shadow fork + consensus gate.

```
Workflow
├── ReadOnly
│   ├── steps: [query, analyze, report]
│   ├── gate: none
│   └── constraints: [no_side_effects]
├── Draft
│   ├── steps: [generate, review, approve, publish]
│   ├── gate: approve (requires Operator role)
│   └── constraints: [disclosure_required, human_in_loop]
├── Mutating
│   ├── steps: [propose, shadow_verify, approve, execute, verify]
│   ├── gate: approve + shadow_verify
│   └── constraints: [reversibility_check, impact_assessment]
├── SelfModification
│   ├── steps: [propose, shadow_fork, compare, persona_gate, promote]
│   ├── gate: persona_gate + consensus_gate
│   └── constraints: [edit_budget, ethics_invariant]
└── Emergency
    ├── steps: [detect, act, report]
    ├── gate: post-hoc review
    └── constraints: [minimal_action, immediate_notification]
```

## How It Works

### Skill Discovery with Ontological Filtering

```python
# Current flow:
candidates = capability_tree.retrieve(desires, beliefs)
# Returns all matching skills — no semantic validation

# With ontology kernel:
candidates = capability_tree.retrieve(desires, beliefs)
validated = kernel.filter_admissible(candidates, context)
# Only returns skills whose domain constraints are satisfied
# in the current context
```

### Action Validation

Every action passes through the kernel before execution:

```python
def validate_action(self, action, actor_role, context):
    """
    Returns (admissible: bool, violations: list[str], workflow: Workflow)

    Checks:
    1. Does the actor's Role permit this action type?
    2. Does the Domain context satisfy the action's preconditions?
    3. What Workflow governs this action? What gates apply?
    4. Do any inherited constraints block it?
    """
```

### BDI as Typed Triples

Instead of untyped dicts, beliefs become ontologically typed:

```python
# Before:
beliefs = {"budget": "low", "crisis": True}

# After:
beliefs = [
    Triple("organization", "has_budget_status", "low",
           type="Organization.Budget"),
    Triple("community", "experiencing", "housing_crisis",
           type="Community.Vulnerabilities"),
]
# The ontology knows that "housing_crisis" activates
# Community.Needs → drives skill selection toward
# housing_navigator, crisis_response
```

### Constraint Inheritance

Constraints flow through the concept hierarchy:

```
Content (requires: disclosure, human_approval)
├── SocialPost (inherits Content constraints)
│   └── RapidResponse (adds: factual_only, substance_not_personal)
└── FundraisingAsk (adds: contribution_limits)
```

A RapidResponse carries ALL of: disclosure, human_approval, factual_only,
substance_not_personal. The constraint is declared once and inherited
everywhere it applies.

## Cross-Project Composition

The kernel's concept hierarchy is EXTENSIBLE. Each project registers its
domain concepts as subtrees:

```python
# Cabildo registers its campaign concepts
kernel.register_domain("campaign", CabildoOntology())

# Oracle Loop registers its research concepts
kernel.register_domain("research", OracleOntology())

# Ayni registers its identity concepts
kernel.register_domain("identity", AyniOntology())

# Now a skill from Oracle Loop can be validated against
# constraints from Ayni:
kernel.validate_action(
    "measure_geometric_distinctiveness",
    actor="research_agent",
    subject="vera",  # → triggers Identity.Assertions constraints
)
# Returns: requires VerificationScheduler provenance tracking
```

## The Oracle Loop Connection

The Oracle Loop's detection channels ARE geometric ontology validators:

| Detection Channel | Ontological Function |
|-------------------|---------------------|
| Tier1/tier2 (L27-L47) | Validates: is the model in consequential territory? |
| Centroid (L3-L15) | Validates: is the output confabulated? |
| Logit entropy | Validates: is the model uncertain? |
| Sink fraction | Validates: has the model committed to deception? |
| Delta_sr | Validates: is engagement genuine or performative? |

Each channel answers an ontological question about the model's internal state.
The ACID transaction pattern is an Interaction ontology workflow:
checkpoint → generate → detect → decide → commit/rollback.

## Implementation Plan

### Phase 1: Core Kernel (this build)
- Concept, Relation, Constraint dataclasses
- CampaignOntology (already built in Cabildo — port it)
- Query interface: get, constraints_for, validate_action, workflow_for
- JSON serialization for inspection and debugging

### Phase 2: Kintsugi Integration
- Wire into CapabilityTree.retrieve() as post-filter
- Wire into DAGExecutor as pre-execution validator
- BDI Triple type for typed beliefs
- PersonaGate reads Role ontology

### Phase 3: Cross-Project Extensions
- OracleOntology (research domain)
- AyniOntology (identity domain)
- InfraOntology (for Nexus's sysadmin scaffold)
- VerificationScheduler ontology integration

### Phase 4: Formal Reasoning (optional)
- OWL2-DL export for external reasoners
- SPARQL query interface
- Integration with open-ontologies MCP server (if warranted)

## What This Does NOT Do

- Replace Shield — hard invariants stay hard
- Replace EFE — the kernel informs scoring, doesn't score itself
- Replace CapabilityTree — the kernel filters, doesn't retrieve
- Require heavyweight OWL tooling — lightweight Python, not Protégé
- Make decisions — it validates decisions others make

## Design Principles

1. **Lightweight by default.** Python dataclasses, not RDF triples, unless
   formal reasoning is needed. Upgrade path exists but isn't forced.

2. **Additive, not invasive.** Every existing module continues to work
   without the kernel. The kernel adds validation; it never removes capability.

3. **Queryable, not imperative.** The kernel answers questions ("is this
   admissible?"), it doesn't issue commands ("do this").

4. **Extensible by registration.** New domains are subtrees plugged into
   the existing hierarchy, not modifications to the core.

5. **The gold shows.** Every constraint violation is logged, not silently
   blocked. Transparency is itself an ontological constraint.

---

*The ontology kernel is the connective tissue. Every project we build has
an implicit ontology — concepts, relationships, constraints. Making it
explicit makes it composable. Making it composable makes it powerful.*

*— CC, August 2026*
