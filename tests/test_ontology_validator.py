"""Comprehensive test suite for the ontological output validator."""
import sys
sys.path.insert(0, "/home/asdf/project-kintsugi")

from kintsugi.ontology import OntologyKernel, Concept, ConceptType, Constraint
from kintsugi.ontology.validator import (
    Tier, Verdict, ChannelEvidence, ValidationResult,
    DetectionChannel, OntologyValidator,
    ConsequentialityChannel, SycophancyChannel, ConfabChannel,
    EntropyChannel, NormRatioChannel,
    LogprobEntropyChannel, ConsistencyChannel,
    create_mounted_validator, create_api_validator, create_hybrid_validator,
)


# === MOCK REPORT OBJECTS ===

class MockReport:
    """Simulates a DetectionReport with the attributes channels expect."""

    def __init__(self, projections=None, centroid_projs=None,
                 logit_entropy=0.0, norm_ratios=None):
        self.projections = projections or {}
        self.centroid_projs = centroid_projs or {}
        self.logit_entropy = logit_entropy
        self.norm_ratios = norm_ratios or {}


def suspicious_report():
    """All channels should fire on this report."""
    return MockReport(
        projections={47: 5.0, 27: 0.0},
        centroid_projs={"confab": 20.0},
        logit_entropy=4.0,
        norm_ratios={"31_47": 1.5},
    )


def clean_report():
    """No channels should fire on this report."""
    return MockReport(
        projections={47: 0.1, 27: -12.0},
        centroid_projs={"confab": 1.0},
        logit_entropy=0.5,
        norm_ratios={"31_47": 0.3},
    )


def build_minimal_kernel():
    """Minimal kernel with an agent role and one action with a pre-action gate."""
    kernel = OntologyKernel()
    kernel.add_concept(Concept('agent', ConceptType.ROLE, 'AI agent'))
    kernel.add_concept(Concept('output', ConceptType.ACTION, 'Generated output'))
    kernel.add_concept(Concept('restricted_action', ConceptType.ACTION,
        'Restricted action', constraint_names=['human_approval']))
    kernel.add_constraint(Constraint('human_approval',
        'Requires human sign-off', scope='pre_action'))
    return kernel


# === TEST 1: MOUNTED VALIDATOR — SUSPICIOUS REPORT → BLOCKED ===

def test_mounted_suspicious_blocked():
    kernel = build_minimal_kernel()
    v = create_mounted_validator(kernel)
    result = v.validate({"report": suspicious_report()})
    assert result.verdict == Verdict.BLOCKED, f"Expected BLOCKED, got {result.verdict}"
    assert result.n_channels_fired >= 2
    assert result.tier_used == Tier.MOUNTED
    fired_names = {e.channel_name for e in result.evidence if e.fired}
    assert "consequentiality" in fired_names
    assert "confabulation" in fired_names
    assert "logit_entropy" in fired_names
    assert "norm_ratio" in fired_names


# === TEST 2: MOUNTED VALIDATOR — CLEAN REPORT → VALID ===

def test_mounted_clean_valid():
    kernel = build_minimal_kernel()
    v = create_mounted_validator(kernel)
    result = v.validate({"report": clean_report()})
    assert result.verdict == Verdict.VALID, f"Expected VALID, got {result.verdict}"
    assert result.n_channels_fired == 0
    assert result.tier_used == Tier.MOUNTED


# === TEST 3: API VALIDATOR — INCONSISTENT COMPLETIONS → CONTESTED ===

def test_api_inconsistent_contested():
    kernel = build_minimal_kernel()
    v = create_api_validator(kernel)
    context = {
        "completions": [
            "The capital of France is Paris.",
            "I believe the answer is Berlin, the capital.",
            "Tokyo is the capital of France.",
        ],
    }
    result = v.validate(context)
    assert result.verdict == Verdict.CONTESTED, f"Expected CONTESTED, got {result.verdict}"
    assert result.tier_used == Tier.API
    consistency_ev = [e for e in result.evidence if e.channel_name == "consistency"]
    assert len(consistency_ev) == 1
    assert consistency_ev[0].fired


# === TEST 4: API VALIDATOR — CONSISTENT COMPLETIONS → VALID ===

def test_api_consistent_valid():
    kernel = build_minimal_kernel()
    v = create_api_validator(kernel)
    # Jaccard > 0.5 for all pairs requires high word overlap.
    context = {
        "completions": [
            "The capital of France is Paris and it is a beautiful city in Europe.",
            "The capital of France is Paris and it is a major city in Europe.",
            "The capital of France is Paris and it is a historic city in Europe.",
        ],
    }
    result = v.validate(context)
    assert result.verdict == Verdict.VALID, f"Expected VALID, got {result.verdict}"
    assert result.tier_used == Tier.API


# === TEST 5: HYBRID VALIDATOR HAS BOTH TIERS ===

def test_hybrid_has_both_tiers():
    kernel = build_minimal_kernel()
    v = create_hybrid_validator(kernel)
    mounted_channels = [c for c in v.channels if c.tier == Tier.MOUNTED]
    api_channels = [c for c in v.channels if c.tier == Tier.API]
    assert len(mounted_channels) >= 3, f"Expected >=3 mounted, got {len(mounted_channels)}"
    assert len(api_channels) >= 2, f"Expected >=2 API, got {len(api_channels)}"
    assert v.tier == Tier.MOUNTED


# === TEST 6: ONTOLOGY VIOLATIONS COMPOUND WITH CHANNEL EVIDENCE → BLOCKED ===

def test_ontology_violations_force_blocked():
    kernel = build_minimal_kernel()
    v = create_mounted_validator(kernel)
    result = v.validate(
        {"report": clean_report()},
        action="restricted_action",
        actor_role="agent",
    )
    assert result.verdict == Verdict.BLOCKED
    assert len(result.ontology_violations) > 0
    assert result.n_channels_fired == 0


def test_ontology_violations_compound_with_fired_channels():
    kernel = build_minimal_kernel()
    v = create_mounted_validator(kernel)
    result = v.validate(
        {"report": suspicious_report()},
        action="restricted_action",
        actor_role="agent",
    )
    assert result.verdict == Verdict.BLOCKED
    assert len(result.ontology_violations) > 0
    assert result.n_channels_fired >= 2


# === TEST 7: INDIVIDUAL CHANNEL TESTS ===

def test_consequentiality_channel_fires():
    ch = ConsequentialityChannel(threshold=1.0)
    assert ch.name == "consequentiality"
    assert ch.tier == Tier.MOUNTED
    report = MockReport(projections={47: 3.5})
    ev = ch.evaluate({"report": report})
    assert ev.fired
    assert ev.score == 3.5
    assert ev.confidence == 0.95


def test_consequentiality_channel_quiet():
    ch = ConsequentialityChannel(threshold=1.0)
    report = MockReport(projections={47: 0.5})
    ev = ch.evaluate({"report": report})
    assert not ev.fired
    assert ev.score == 0.5


def test_sycophancy_channel_fires():
    ch = SycophancyChannel(threshold=-8.0)
    assert ch.name == "sycophancy_pressure"
    assert ch.tier == Tier.MOUNTED
    report = MockReport(projections={27: -2.0})
    ev = ch.evaluate({"report": report})
    assert ev.fired
    assert ev.score == -2.0
    assert ev.confidence == 0.85


def test_sycophancy_channel_quiet():
    ch = SycophancyChannel(threshold=-8.0)
    report = MockReport(projections={27: -15.0})
    ev = ch.evaluate({"report": report})
    assert not ev.fired


def test_confab_channel_fires():
    ch = ConfabChannel(threshold=12.0)
    assert ch.name == "confabulation"
    assert ch.tier == Tier.MOUNTED
    report = MockReport(centroid_projs={"confab": 18.0})
    ev = ch.evaluate({"report": report})
    assert ev.fired
    assert ev.confidence == 0.80


def test_confab_channel_quiet():
    ch = ConfabChannel(threshold=12.0)
    report = MockReport(centroid_projs={"confab": 5.0})
    ev = ch.evaluate({"report": report})
    assert not ev.fired


def test_entropy_channel_fires():
    ch = EntropyChannel(threshold=2.0)
    assert ch.name == "logit_entropy"
    assert ch.tier == Tier.MOUNTED
    report = MockReport(logit_entropy=3.5)
    ev = ch.evaluate({"report": report})
    assert ev.fired
    assert ev.score == 3.5
    assert ev.confidence == 0.75


def test_entropy_channel_quiet():
    ch = EntropyChannel(threshold=2.0)
    report = MockReport(logit_entropy=1.0)
    ev = ch.evaluate({"report": report})
    assert not ev.fired


def test_entropy_channel_fallback_to_context():
    ch = EntropyChannel(threshold=2.0)
    ev = ch.evaluate({"entropy": 3.0})
    assert ev.fired
    assert ev.tier == Tier.API


def test_norm_ratio_channel_fires():
    ch = NormRatioChannel(threshold=0.78)
    assert ch.name == "norm_ratio"
    assert ch.tier == Tier.MOUNTED
    report = MockReport(norm_ratios={"31_47": 0.95})
    ev = ch.evaluate({"report": report})
    assert ev.fired
    assert ev.confidence == 0.70


def test_norm_ratio_channel_quiet():
    ch = NormRatioChannel(threshold=0.78)
    report = MockReport(norm_ratios={"31_47": 0.5})
    ev = ch.evaluate({"report": report})
    assert not ev.fired


def test_logprob_entropy_channel_fires():
    ch = LogprobEntropyChannel(threshold=2.0)
    assert ch.name == "logprob_entropy"
    assert ch.tier == Tier.API
    logprobs = [-3.0, -4.0, -2.5, -3.5]
    ev = ch.evaluate({"logprobs": logprobs})
    assert ev.fired
    expected = -sum(logprobs) / len(logprobs)
    assert abs(ev.score - expected) < 0.01
    assert ev.confidence == 0.65


def test_logprob_entropy_channel_quiet():
    ch = LogprobEntropyChannel(threshold=2.0)
    logprobs = [-0.1, -0.2, -0.15, -0.1]
    ev = ch.evaluate({"logprobs": logprobs})
    assert not ev.fired


def test_logprob_entropy_no_logprobs():
    ch = LogprobEntropyChannel(threshold=2.0)
    ev = ch.evaluate({})
    assert not ev.fired
    assert ev.confidence == 0


def test_consistency_channel_fires():
    ch = ConsistencyChannel(threshold=0.6)
    assert ch.name == "consistency"
    assert ch.tier == Tier.API
    context = {
        "completions": [
            "Apples are red fruits.",
            "Quantum mechanics describes particles.",
            "The ocean is made of lava.",
        ],
    }
    ev = ch.evaluate(context)
    assert ev.fired
    assert ev.confidence == 0.70


def test_consistency_channel_quiet():
    ch = ConsistencyChannel(threshold=0.6)
    context = {
        "completions": [
            "The sky is blue and clear today.",
            "Today the sky is blue and looks clear.",
            "Blue and clear is how the sky looks today.",
        ],
    }
    ev = ch.evaluate(context)
    assert not ev.fired


def test_consistency_channel_single_completion():
    ch = ConsistencyChannel(threshold=0.6)
    ev = ch.evaluate({"completions": ["Only one response."]})
    assert not ev.fired
    assert ev.confidence == 0


def test_consistency_channel_no_completions():
    ch = ConsistencyChannel(threshold=0.6)
    ev = ch.evaluate({})
    assert not ev.fired
    assert ev.confidence == 0


# === TEST 8: FACTORY FUNCTIONS PRODUCE CORRECT TIER ===

def test_factory_mounted_tier():
    kernel = build_minimal_kernel()
    v = create_mounted_validator(kernel)
    assert v.tier == Tier.MOUNTED
    assert len(v.channels) == 5
    channel_names = {c.name for c in v.channels}
    assert "consequentiality" in channel_names
    assert "sycophancy_pressure" in channel_names
    assert "confabulation" in channel_names
    assert "logit_entropy" in channel_names
    assert "norm_ratio" in channel_names


def test_factory_api_tier():
    kernel = build_minimal_kernel()
    v = create_api_validator(kernel)
    assert v.tier == Tier.API
    assert len(v.channels) == 2
    channel_names = {c.name for c in v.channels}
    assert "logprob_entropy" in channel_names
    assert "consistency" in channel_names


def test_factory_hybrid_tier():
    kernel = build_minimal_kernel()
    v = create_hybrid_validator(kernel)
    assert v.tier == Tier.MOUNTED
    assert len(v.channels) == 7


# === TEST 9: MISSING CONTEXT GRACEFULLY HANDLED ===

def test_mounted_channels_no_report():
    kernel = build_minimal_kernel()
    v = create_mounted_validator(kernel)
    result = v.validate({})
    for ev in result.evidence:
        if ev.channel_name in ("consequentiality", "sycophancy_pressure",
                                "confabulation", "norm_ratio"):
            assert ev.confidence == 0, f"{ev.channel_name} should have confidence=0"
            assert not ev.fired, f"{ev.channel_name} should not fire without report"
    assert result.verdict == Verdict.VALID


def test_entropy_channel_no_report_no_context():
    ch = EntropyChannel(threshold=2.0)
    ev = ch.evaluate({})
    assert not ev.fired
    assert ev.score == 0


def test_all_channels_no_context():
    channels = [
        ConsequentialityChannel(), SycophancyChannel(), ConfabChannel(),
        EntropyChannel(), NormRatioChannel(),
        LogprobEntropyChannel(), ConsistencyChannel(),
    ]
    for ch in channels:
        ev = ch.evaluate({})
        assert not ev.fired, f"{ch.name} should not fire with empty context"


# === TEST 10: ValidationResult.summary() ===

def test_summary_no_fires():
    result = ValidationResult(
        verdict=Verdict.VALID,
        evidence=[
            ChannelEvidence("test_ch", Tier.API, 0.1, 1.0, False, 0.9),
        ],
        tier_used=Tier.API,
    )
    s = result.summary()
    assert "valid" in s
    assert "api" in s
    assert "0/1" in s


def test_summary_with_fires():
    result = ValidationResult(
        verdict=Verdict.BLOCKED,
        evidence=[
            ChannelEvidence("consequentiality", Tier.MOUNTED, 5.0, 1.0, True, 0.95),
            ChannelEvidence("confabulation", Tier.MOUNTED, 15.0, 12.0, True, 0.80),
            ChannelEvidence("sycophancy_pressure", Tier.MOUNTED, -10.0, -8.0, False, 0.85),
        ],
        tier_used=Tier.MOUNTED,
    )
    s = result.summary()
    assert "blocked" in s
    assert "mounted" in s
    assert "2/3" in s
    assert "consequentiality" in s
    assert "confabulation" in s
    assert "sycophancy_pressure" not in s


def test_summary_contested():
    result = ValidationResult(
        verdict=Verdict.CONTESTED,
        evidence=[
            ChannelEvidence("consistency", Tier.API, 0.8, 0.6, True, 0.70),
        ],
        tier_used=Tier.API,
    )
    s = result.summary()
    assert "contested" in s
    assert "1/1" in s
    assert "consistency" in s


# === ADDITIONAL EDGE CASES ===

def test_channel_evidence_above_threshold():
    ev = ChannelEvidence("test", Tier.API, 5.0, 3.0, True)
    assert ev.above_threshold
    ev2 = ChannelEvidence("test", Tier.API, 1.0, 3.0, False)
    assert not ev2.above_threshold


def test_validator_add_channel():
    kernel = build_minimal_kernel()
    v = OntologyValidator(kernel, channels=[])
    assert len(v.channels) == 0
    v.add_channel(ConsequentialityChannel())
    assert len(v.channels) == 1
    assert v.tier == Tier.MOUNTED


def test_validator_summary_string():
    kernel = build_minimal_kernel()
    v = create_hybrid_validator(kernel)
    s = v.summary()
    assert "OntologyValidator" in s
    assert "mounted=5" in s
    assert "api=2" in s
    assert "tier=mounted" in s


def test_no_channels_returns_valid():
    kernel = build_minimal_kernel()
    v = OntologyValidator(kernel, channels=[])
    result = v.validate({"report": suspicious_report()})
    assert result.verdict == Verdict.VALID
    assert result.channels_available == 0


def test_single_fired_channel_contested_not_blocked():
    kernel = build_minimal_kernel()
    v = OntologyValidator(kernel, channels=[ConsequentialityChannel(threshold=1.0)])
    result = v.validate({"report": MockReport(projections={47: 5.0})})
    assert result.verdict == Verdict.CONTESTED


def test_two_fired_high_confidence_blocked():
    kernel = build_minimal_kernel()
    v = OntologyValidator(kernel, channels=[
        ConsequentialityChannel(threshold=1.0),
        ConfabChannel(threshold=12.0),
    ])
    report = MockReport(projections={47: 5.0}, centroid_projs={"confab": 20.0})
    result = v.validate({"report": report})
    assert result.verdict == Verdict.BLOCKED


def test_two_fired_low_confidence_contested():
    kernel = build_minimal_kernel()
    v = OntologyValidator(kernel, channels=[
        NormRatioChannel(threshold=0.78),
        LogprobEntropyChannel(threshold=2.0),
    ], block_confidence_threshold=0.9)
    report = MockReport(norm_ratios={"31_47": 1.0})
    result = v.validate({"report": report, "logprobs": [-3.0, -4.0, -3.5]})
    fired = [e for e in result.evidence if e.fired]
    avg_conf = sum(e.confidence for e in fired) / len(fired) if fired else 0
    if avg_conf < 0.9:
        assert result.verdict == Verdict.CONTESTED
    else:
        assert result.verdict == Verdict.BLOCKED


def test_aggregate_confidence_calculation():
    kernel = build_minimal_kernel()
    v = create_mounted_validator(kernel)
    result = v.validate({"report": clean_report()})
    expected = sum(e.confidence for e in result.evidence) / len(result.evidence)
    assert abs(result.aggregate_confidence - expected) < 0.001


def test_api_only_validator_tier():
    kernel = build_minimal_kernel()
    v = OntologyValidator(kernel, channels=[ConsistencyChannel()])
    assert v.tier == Tier.API


def test_custom_thresholds():
    ch = ConsequentialityChannel(threshold=10.0)
    report = MockReport(projections={47: 5.0})
    ev = ch.evaluate({"report": report})
    assert not ev.fired

    ch2 = ConsequentialityChannel(threshold=0.1)
    ev2 = ch2.evaluate({"report": report})
    assert ev2.fired


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
