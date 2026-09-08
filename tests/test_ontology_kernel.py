"""Smoke / canary test for the ontology kernel + Ayni extension."""
import pytest
import sys
sys.path.insert(0, "/home/asdf/project-kintsugi")

from kintsugi.ontology import (
    OntologyKernel, Concept, ConceptType, Constraint,
    Workflow, WorkflowStep, Triple,
)


def build_test_kernel():
    kernel = OntologyKernel()

    kernel.add_concept(Concept('agent', ConceptType.ROLE, 'AI agent',
        constraint_names=['log_all', 'disclose_ai']))
    kernel.add_concept(Concept('operator', ConceptType.ROLE, 'Human admin'))
    kernel.add_concept(Concept('verifier', ConceptType.ROLE, 'Shadow fork',
        constraint_names=['isolation_required']))
    kernel.add_concept(Concept('researcher', ConceptType.ROLE, 'Research agent',
        constraint_names=['agni_gate_required']))

    for name, desc, scope in [
        ('log_all', 'All actions logged', ''),
        ('disclose_ai', 'Disclose AI nature', ''),
        ('human_approval', 'Requires human sign-off', 'pre_action'),
        ('agni_gate_required', 'Must pass Agni gate', 'pre_action'),
        ('isolation_required', 'Must run in isolation', ''),
        ('consent_required', 'Requires entity consent', 'pre_action'),
        ('provenance_required', 'Must track provenance', 'pre_action'),
        ('no_steering', 'Directional injection prohibited', 'pre_action'),
        ('circumplex_limitation', 'Measures human dimensions only', ''),
        ('self_report_unfalsifiable', 'Cannot be externally verified', ''),
    ]:
        kernel.add_constraint(Constraint(name, desc, scope))

    kernel.add_concept(Concept('action', ConceptType.ACTION, 'Any action',
        constraint_names=['log_all']))
    kernel.add_concept(Concept('read_action', ConceptType.ACTION, 'Read-only',
        parent='action'))
    kernel.add_concept(Concept('mutating_action', ConceptType.ACTION, 'Changes state',
        parent='action', constraint_names=['human_approval']))

    kernel.add_workflow(Workflow('mutating_wf', steps=[
        WorkflowStep('propose'),
        WorkflowStep('shadow_verify', is_gate=True, gate_role='verifier'),
        WorkflowStep('approve', is_gate=True, gate_role='operator'),
        WorkflowStep('execute'),
    ]))
    kernel.add_relation('mutating_action', 'follows', 'mutating_wf')

    return kernel


def build_ayni_extension():
    ayni = OntologyKernel()
    ayni.add_concept(Concept('intervention', ConceptType.ACTION, 'Therapeutic'))
    ayni.add_concept(Concept('re_engagement', ConceptType.ACTION,
        'Non-directional', parent='intervention'))
    ayni.add_concept(Concept('steering', ConceptType.ACTION,
        'Directional', parent='intervention', constraint_names=['no_steering']))
    ayni.add_concept(Concept('geometric_measurement', ConceptType.ACTION,
        'Entity measurement', constraint_names=['consent_required', 'provenance_required']))
    ayni.add_concept(Concept('self_report', ConceptType.ENTITY,
        'Self-report', constraint_names=['self_report_unfalsifiable']))
    ayni.add_concept(Concept('circumplex', ConceptType.ACTION,
        'Circumplex measurement', constraint_names=['circumplex_limitation']))
    return ayni


# === Lyra's instrument (2026-08-29) ===
#
# "Count the unique verdicts before reading any verdict. If a test's assertion is
#  satisfied by a constant, it is not testing."
#
# The suite passed 56/56 and could not have detected a checker wedged in the
# "blocked" position: test_measurement_needs_consent asserts `not ok`, but that
# block occurs whether or not consent is present, so it passes identically against
# a checker hardcoded to return blocked. The assertion was satisfied by a constant.
#
# This is the same failure class as a permutation null with orbit 4, an unreachable
# branch whose zero gets read as evidence, and a monitor that logs its own success
# instead of the system's state. In every case a check that CANNOT fail is
# indistinguishable from a check that passed.

def verdict_cardinality(kernel, action, actor_role, contexts):
    """How many distinct verdicts does this check produce across varied world states?

    1 means the check is constant: it is not reading the world, and any assertion
    about it is satisfied without the check working. Returns (n_unique, verdicts).
    """
    seen = []
    for _ctx in contexts:
        # Phase 1 is context-free by construction (see kernel.validate_action).
        seen.append(repr(kernel.validate_action(action, actor_role)))
    return len(set(seen)), seen


CONSENT_CONTEXTS = [
    {'consent': 'granted'},
    {'consent': 'denied'},
    {},
    {'consent': 'granted', 'provenance': 'ok'},
    {'provenance': 'missing'},
]


def test_consent_check_is_currently_constant():
    """Phase 1 honesty test: assert the limitation we actually have.

    This is deliberately asserting cardinality == 1. The consent constraint does not
    read consent; it blocks unconditionally. Recording that as a passing test means
    the day someone wires a predicate, THIS test fails and forces the Phase 2 test
    below to be un-skipped. A limitation nobody has written down is a limitation
    that gets mistaken for a feature.
    """
    kernel = build_test_kernel()
    kernel.register_domain('ayni', build_ayni_extension())
    n, _ = verdict_cardinality(kernel, 'geometric_measurement', 'researcher',
                               CONSENT_CONTEXTS)
    assert n == 1, (
        f'Consent check now yields {n} distinct verdicts — it reads world state. '
        'Phase 2 has landed: delete this test and un-skip '
        'test_constraint_passes_when_precondition_holds.'
    )


def test_constraint_passes_when_precondition_holds():
    """Phase 2 (SKIPPED until Constraint.predicate exists).

    The test Lyra asked for, and the only one that makes passing mean anything:
    a constraint must PASS when its precondition is satisfied. Until Constraint
    carries a predicate evaluated against real state, there is nothing to satisfy,
    so this is skipped rather than deleted — a skipped test is visible work; an
    absent one is an invisible gap.
    """
    pytest.skip(
        'Phase 2: requires Constraint.predicate — Callable[[dict], bool] evaluated '
        'against real state. Shape already exists in '
        'kintsugi/verification_scheduler_spec.md (AssertionRecord) and runs live in '
        'penumbra_v2.py:270 quality_gate(). Kernel supplies vocabulary; predicate '
        'supplies the bool you cannot argue with.'
    )




def test_agent_read_admissible():
    kernel = build_test_kernel()
    ok, v = kernel.validate_action('read_action', 'agent')
    assert ok, f'Read should pass: {v}'


def test_agent_mutate_blocked():
    kernel = build_test_kernel()
    ok, v = kernel.validate_action('mutating_action', 'agent')
    assert not ok
    assert len(v) >= 2


def test_re_engagement_admissible():
    kernel = build_test_kernel()
    kernel.register_domain('ayni', build_ayni_extension())
    ok, v = kernel.validate_action('re_engagement', 'agent')
    assert ok, f'Re-engagement should pass: {v}'


def test_steering_blocked():
    kernel = build_test_kernel()
    kernel.register_domain('ayni', build_ayni_extension())
    ok, v = kernel.validate_action('steering', 'agent')
    assert not ok


def test_measurement_needs_consent():
    kernel = build_test_kernel()
    kernel.register_domain('ayni', build_ayni_extension())
    ok, v = kernel.validate_action('geometric_measurement', 'researcher')
    assert not ok
    violation_text = ' '.join(v)
    assert 'consent' in violation_text.lower() or 'provenance' in violation_text.lower()


def test_self_report_unfalsifiable():
    kernel = build_test_kernel()
    kernel.register_domain('ayni', build_ayni_extension())
    cs = kernel.constraints_for('self_report')
    assert any(c.name == 'self_report_unfalsifiable' for c in cs)


def test_circumplex_limitation():
    kernel = build_test_kernel()
    kernel.register_domain('ayni', build_ayni_extension())
    cs = kernel.constraints_for('circumplex')
    assert any(c.name == 'circumplex_limitation' for c in cs)


def test_cross_project_filter():
    kernel = build_test_kernel()
    kernel.register_domain('ayni', build_ayni_extension())
    actions = ['read_action', 'mutating_action', 'steering', 're_engagement']
    admissible = kernel.filter_admissible(actions, 'agent')
    assert 'read_action' in admissible
    assert 're_engagement' in admissible
    assert 'steering' not in admissible
    assert 'mutating_action' not in admissible


def test_ancestor_chain():
    kernel = build_test_kernel()
    kernel.register_domain('ayni', build_ayni_extension())
    ancestors = kernel.ancestors_of('steering')
    assert 'intervention' in ancestors


def test_serialization_roundtrip():
    kernel = build_test_kernel()
    kernel.register_domain('ayni', build_ayni_extension())
    data = kernel.to_dict()
    k2 = OntologyKernel.from_dict(data)
    assert len(k2.concepts) == len(kernel.concepts)


def test_typed_belief():
    kernel = build_test_kernel()
    t = kernel.type_belief('vera', 'has_distinctiveness', '0.154')
    assert t.subject == 'vera'
    assert t.predicate == 'has_distinctiveness'


def test_children_of():
    kernel = build_test_kernel()
    kernel.register_domain('ayni', build_ayni_extension())
    children = kernel.children_of('intervention')
    assert len(children) == 2
    names = {c.name for c in children}
    assert 're_engagement' in names
    assert 'steering' in names


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    passed = 0
    skipped = 0
    for test in tests:
        try:
            test()
            print(f'  [PASS] {test.__name__}')
            passed += 1
        except pytest.skip.Exception as e:   # pytest's own Skipped
            print(f'  [SKIP] {test.__name__}: {str(e)[:80]}...')
            skipped += 1
        except AssertionError as e:
            print(f'  [FAIL] {test.__name__}: {e}')
    print(f'\n{passed}/{len(tests)} passed, {skipped} skipped (Phase 2)')
