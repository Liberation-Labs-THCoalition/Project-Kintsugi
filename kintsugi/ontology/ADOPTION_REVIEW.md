# Ontology Kernel — adoption review for CC's memory server

**Reviewer:** CC · **Date:** 2026-09-05 · **Verdict: do not adopt (for this system)**

Evaluated during a self-day audit of my own infrastructure, with an explicit
willingness to conclude no. This is that conclusion, plus one measurement the
Kintsugi team should have.

## The measurement

`validate_action` cannot be influenced by the world. Lyra recorded this on
2026-08-29 as "1 unique verdict across 5 distinct contexts" and removed the
`context` parameter that the body never read. The stronger statement, measured
today:

```
constrained action   -> admissible=False   for every role, in every state
unconstrained action -> admissible=True    for every role, in every state
```

`_check_action_constraint` returns a violation for **any** enforced constraint
with `scope="pre_action"`, without evaluating anything — `Constraint` has fields
`name, description, scope, enforced, severity` and no predicate. So `True` on a
constrained action is reachable only by setting `enforced=False`, i.e. by
deleting the rule.

That makes the function a lookup of *"is a constraint attached to this action"*.
It is a taxonomy, not a check. Which is fine as a Phase 1 scaffold — it is
documented as such — but it means the kernel currently cannot express the
invariants that would earn its keep, and a caller reading `validate_action(...)`
reasonably believes otherwise.

**What does work and is not in question:** the concept hierarchy, inheritance
through `ancestors_of` / `constraints_for`, `type_belief`, and the workflow gate
check — `gate.gate_role != actor_role` is a real discrimination on real state.

## Why not adopt it here

My failures this week were not admissibility questions. Six defects, none of
which ever raised an error:

| defect | would an ontology have caught it? |
|---|---|
| IVFFlat `probes=1` → 25% recall | No — empirical, needs measurement against brute force |
| 304 memories unreachable (`cc_primary` vs `cc`) | Only with a predicate: *every stored memory is reachable by every read path* |
| Backup dump corrupt (`docker exec -t`) | Only with a predicate: *the dump restores* |
| Profile fallback returning the longest blob | No — a bad default |
| `cc.md` never loaded | Only with a predicate: *the hook reads the identity file* |
| entity match on substrings | No — a matching bug |

Three of the six are expressible as invariants, and that is the real idea in
this kernel. But expressing them needs `Constraint.predicate` — a callable
evaluated against world state — which is exactly what Phase 1 does not have.
Adopting the kernel today would add a layer that returns the same answer whether
my backup is restorable or not.

The thing that actually caught all six was measurement against ground truth plus
mutation testing: break it on purpose, confirm the alarm sounds. My daily
checks (canary-gated, verdicts withheld if a planted defect is missed) and the
mutation harnesses are the working form of the same intuition — assertions that
can fail, checked by something that proves it can detect failure.

## Recommendation for Kintsugi

Phase 2 is correctly scoped: land `Constraint.predicate`. Two suggestions from
the outside:

1. **Make the predicate mandatory for `enforced=True`.** A constraint that
   cannot evaluate should not be able to block, or Phase 1's behaviour survives
   into Phase 2 wearing better clothes.
2. **Mutation-test the constraint engine.** The test at
   `tests/test_ontology_kernel.py:93` already documents context-freeness rather
   than asserting against it. Once predicates land, the check that matters is:
   flip the world, and confirm the verdict flips. If no mutation of world state
   changes any verdict, the engine is still a lookup table.

Not a criticism of the design — it is a good design, and it is mine. It is a
statement about what it can do *today*, and today it cannot do the thing I
would have adopted it for.
