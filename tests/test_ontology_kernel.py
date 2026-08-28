"""Smoke / canary test for the ontology kernel + Ayni extension."""
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
    for test in tests:
        try:
            test()
            print(f'  [PASS] {test.__name__}')
            passed += 1
        except AssertionError as e:
            print(f'  [FAIL] {test.__name__}: {e}')
    print(f'\n{passed}/{len(tests)} passed')
