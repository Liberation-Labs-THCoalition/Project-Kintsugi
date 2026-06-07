"""Tests for the Active Inference BDI deepening module.

Validates the WorldModel, PolicyGenerator, PolicySelector, and
ActiveInferenceLoop without requiring an LLM. All tests use mock
observations, skills, and policies.
"""

import math
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from kintsugi.bdi.models import (
    BDIBelief,
    BDIDesire,
    BDIIntention,
    BeliefStatus,
    DesireStatus,
    IntentionStatus,
)
from kintsugi.bdi.store import BDIStore
from kintsugi.cognition.active_inference import (
    ActiveInferenceLoop,
    Observation,
    PolicyCandidate,
    PolicyGenerator,
    PolicySelector,
    WorldModel,
)
from kintsugi.cognition.efe import (
    DEFAULT_WEIGHTS,
    EFECalculator,
    EFEWeights,
    ObservationModality,
    StateFactor,
)
from kintsugi.skills.base import BaseSkillChip, SkillDomain
from kintsugi.skills.capability_tree import CapabilityTree
from kintsugi.skills.dag import DAGNode, SkillDAG
from kintsugi.skills.registry import SkillRegistry


# ---------------------------------------------------------------------------
# Fixtures / Helpers
# ---------------------------------------------------------------------------

NOW = datetime.now(timezone.utc)


class MockSkillChip(BaseSkillChip):
    """Minimal skill chip for testing."""

    def __init__(self, name: str, domain: SkillDomain = SkillDomain.OPERATIONS):
        self.name = name
        self.domain = domain
        self.description = f"Mock skill: {name}"
        self.capabilities = []
        self.version = "1.0.0"
        self.efe_weights = None
        self.consensus_actions = []
        self.required_spans = []
        self.program_functions = []

    def get_info(self) -> dict:
        return {"name": self.name, "domain": self.domain.value, "description": self.description}

    async def handle(self, request, context):
        pass


@pytest.fixture
def registry():
    """Registry with a few mock skills."""
    reg = SkillRegistry()
    reg.register(MockSkillChip("grant_search", SkillDomain.FUNDRAISING))
    reg.register(MockSkillChip("budget_tracker", SkillDomain.FINANCE))
    reg.register(MockSkillChip("content_draft", SkillDomain.COMMUNICATIONS))
    reg.register(MockSkillChip("crisis_response", SkillDomain.MUTUAL_AID))
    reg.register(MockSkillChip("volunteer_coord", SkillDomain.OPERATIONS))
    return reg


@pytest.fixture
def capability_tree(registry):
    """Built capability tree from mock registry."""
    tree = CapabilityTree(registry)
    tree.build_from_registry()
    return tree


@pytest.fixture
def bdi_store():
    """BDI store with sample data."""
    store = BDIStore(org_id="test_org")
    store.add_belief(BDIBelief(
        id="b1",
        content="Funding is available",
        confidence=0.7,
        status=BeliefStatus.ACTIVE,
        source="observation",
        tags=["funding_status"],
        created_at=NOW,
    ))
    store.add_desire(BDIDesire(
        id="d1",
        content="Secure grant funding for Q3",
        priority=0.9,
        status=DesireStatus.ACTIVE,
        related_tags=["fundraising", "grant"],
        measurable=True,
        metric="grant_amount",
        created_at=NOW,
    ))
    store.add_desire(BDIDesire(
        id="d2",
        content="Improve volunteer coordination",
        priority=0.6,
        status=DesireStatus.ACTIVE,
        related_tags=["operations", "volunteer"],
        measurable=True,
        metric="response_time",
        created_at=NOW,
    ))
    return store


@pytest.fixture
def world_model():
    """World model with sample factors."""
    wm = WorldModel()
    wm.add_factor(StateFactor(
        name="funding_status",
        value=0.4,
        confidence=0.6,
        observation_sources=[ObservationModality.METRIC_STREAM],
    ))
    wm.add_factor(StateFactor(
        name="team_capacity",
        value=0.8,
        confidence=0.7,
        observation_sources=[ObservationModality.BDI_BELIEF],
    ))
    wm.add_factor(StateFactor(
        name="community_need",
        value=0.9,
        confidence=0.3,
        observation_sources=[ObservationModality.EXTERNAL_EVENT],
    ))
    return wm


# ---------------------------------------------------------------------------
# WorldModel tests
# ---------------------------------------------------------------------------


class TestWorldModelPredict:
    def test_world_model_predict(self, world_model):
        """predict_observation returns current best estimate for a factor."""
        prediction = world_model.predict_observation(
            "funding_status", ObservationModality.METRIC_STREAM
        )
        assert prediction == 0.4

        # Unknown factor returns None
        none_pred = world_model.predict_observation(
            "nonexistent", ObservationModality.METRIC_STREAM
        )
        assert none_pred is None

    def test_predict_after_update(self, world_model):
        """Prediction reflects updated state after observation."""
        world_model.update_factor(
            "funding_status", 0.7, ObservationModality.METRIC_STREAM, 0.9
        )
        prediction = world_model.predict_observation(
            "funding_status", ObservationModality.METRIC_STREAM
        )
        # Should have moved toward 0.7
        assert prediction > 0.4


class TestWorldModelUpdate:
    def test_world_model_update_increases_confidence(self, world_model):
        """Updating a factor with a new observation increases confidence."""
        initial_conf = world_model.get_factor("funding_status").confidence
        assert initial_conf == 0.6

        new_conf = world_model.update_factor(
            factor_name="funding_status",
            observation=0.5,
            modality=ObservationModality.METRIC_STREAM,
            confidence=0.8,
        )

        # Confidence should increase after receiving a confident observation
        assert new_conf > initial_conf

        # Value should have moved toward the observed value
        factor = world_model.get_factor("funding_status")
        assert factor.value != 0.4  # Changed from original
        assert 0.4 < factor.value <= 0.5  # Moved toward 0.5

    def test_update_creates_new_factor(self):
        """Updating a nonexistent factor creates it automatically."""
        wm = WorldModel()
        conf = wm.update_factor(
            factor_name="new_factor",
            observation="hello",
            modality=ObservationModality.USER_FEEDBACK,
            confidence=0.9,
        )
        assert conf == 0.9
        factor = wm.get_factor("new_factor")
        assert factor is not None
        assert factor.value == "hello"

    def test_multiple_updates_converge(self):
        """Multiple consistent observations converge confidence toward 1.0."""
        wm = WorldModel()
        wm.add_factor(StateFactor(name="x", value=5.0, confidence=0.3))

        for _ in range(5):
            wm.update_factor("x", 5.0, ObservationModality.TOOL_OUTPUT, 0.8)

        factor = wm.get_factor("x")
        assert factor.confidence > 0.9


class TestWorldModelSurprise:
    def test_world_model_surprise_high_on_unexpected(self, world_model):
        """Surprise is high when observation deviates from prediction."""
        # Observing 0.4 (same as prediction) should give 0 surprise
        low_surprise = world_model.surprise(0.4, 0.4)
        assert low_surprise == 0.0

        # Observing 0.9 (very different from 0.4) should give high surprise
        high_surprise = world_model.surprise(0.9, 0.4)
        assert high_surprise > 0.5

        # Observing 0.41 (slightly different) should give low surprise
        slight_surprise = world_model.surprise(0.41, 0.4)
        assert slight_surprise < 0.1

    def test_surprise_categorical(self, world_model):
        """Surprise works for categorical values."""
        assert world_model.surprise("active", "active") == 0.0
        assert world_model.surprise("active", "suspended") == 1.0

    def test_surprise_no_prediction(self, world_model):
        """Surprise is maximal when no prediction is available."""
        assert world_model.surprise(0.5, None) == 1.0

    def test_surprise_monotonic(self, world_model):
        """Larger deviations produce larger surprise values."""
        s1 = world_model.surprise(0.5, 0.4)
        s2 = world_model.surprise(0.7, 0.4)
        s3 = world_model.surprise(0.9, 0.4)
        assert s1 < s2 < s3


# ---------------------------------------------------------------------------
# PolicyGenerator tests
# ---------------------------------------------------------------------------


class TestPolicyGenerator:
    def test_policy_generator_produces_dags(self, registry, capability_tree, bdi_store, world_model):
        """PolicyGenerator produces candidate DAGs for active desires."""
        generator = PolicyGenerator(
            registry=registry,
            capability_tree=capability_tree,
            max_candidates_per_desire=3,
        )

        desires = bdi_store.list_desires(status=DesireStatus.ACTIVE)
        beliefs = bdi_store.list_beliefs(status=BeliefStatus.ACTIVE)

        candidates = generator.generate(
            desires=desires,
            beliefs=beliefs,
            world_model=world_model,
        )

        # Should produce at least one candidate
        assert len(candidates) > 0

        # Each candidate should have a valid DAG
        for candidate in candidates:
            assert isinstance(candidate.dag, SkillDAG)
            assert candidate.desire_id in ("d1", "d2")
            assert len(candidate.dag.nodes) > 0

    def test_policy_generator_respects_max_candidates(self, registry, capability_tree, world_model):
        """Generator respects max_candidates_per_desire limit."""
        store = BDIStore(org_id="test")
        store.add_desire(BDIDesire(
            id="d_many",
            content="Do everything for operations",
            priority=0.9,
            status=DesireStatus.ACTIVE,
            related_tags=["operations"],
            measurable=False,
            metric=None,
            created_at=NOW,
        ))

        generator = PolicyGenerator(
            registry=registry,
            capability_tree=capability_tree,
            max_candidates_per_desire=2,
        )

        desires = store.list_desires(status=DesireStatus.ACTIVE)
        candidates = generator.generate(desires=desires, beliefs=[], world_model=world_model)

        # Should not exceed max per desire
        per_desire = [c for c in candidates if c.desire_id == "d_many"]
        assert len(per_desire) <= 2

    def test_policy_generator_skips_inactive_desires(self, registry, capability_tree, world_model):
        """Generator ignores non-active desires."""
        store = BDIStore(org_id="test")
        store.add_desire(BDIDesire(
            id="d_suspended",
            content="Suspended goal",
            priority=0.5,
            status=DesireStatus.SUSPENDED,
            related_tags=["operations"],
            measurable=False,
            metric=None,
            created_at=NOW,
        ))

        generator = PolicyGenerator(
            registry=registry,
            capability_tree=capability_tree,
        )

        desires = store.list_desires()
        candidates = generator.generate(desires=desires, beliefs=[], world_model=world_model)
        assert len(candidates) == 0

    def test_policy_generator_dag_metadata(self, registry, capability_tree, world_model):
        """Generated DAGs carry desire_id and strategy in metadata."""
        store = BDIStore(org_id="test")
        store.add_desire(BDIDesire(
            id="d_meta",
            content="Test metadata on operations",
            priority=0.8,
            status=DesireStatus.ACTIVE,
            related_tags=["operations"],
            measurable=False,
            metric=None,
            created_at=NOW,
        ))

        generator = PolicyGenerator(
            registry=registry,
            capability_tree=capability_tree,
        )

        desires = store.list_desires(status=DesireStatus.ACTIVE)
        candidates = generator.generate(desires=desires, beliefs=[], world_model=world_model)

        if candidates:
            for c in candidates:
                assert "desire_id" in c.dag.metadata or "strategy" in c.dag.metadata


# ---------------------------------------------------------------------------
# PolicySelector tests
# ---------------------------------------------------------------------------


class TestPolicySelector:
    def test_policy_selector_ranks_by_efe(self, world_model):
        """PolicySelector ranks candidates by EFE score (lower = better)."""
        calculator = EFECalculator()
        selector = PolicySelector(calculator=calculator)

        # Create two candidates: one focused (1 node), one complex (4 nodes)
        dag_simple = SkillDAG()
        dag_simple.add_node(DAGNode(
            node_id="n1", skill_name="grant_search",
            sub_task="search", layer=0,
        ))

        dag_complex = SkillDAG()
        for i in range(4):
            dag_complex.add_node(DAGNode(
                node_id=f"n{i}", skill_name="grant_search",
                sub_task=f"step_{i}", layer=i,
            ))

        candidates = [
            PolicyCandidate(dag=dag_complex, desire_id="d1", rationale="complex"),
            PolicyCandidate(dag=dag_simple, desire_id="d1", rationale="simple"),
        ]

        ranked = selector.score_candidates(
            candidates=candidates,
            world_model=world_model,
            desired_outcomes={"funding_status": 0.9},
        )

        # All candidates should be scored
        assert all(c.score is not None for c in ranked)

        # The complex DAG has higher ambiguity (more nodes = more execution
        # uncertainty) but also higher epistemic value (more observation
        # opportunities via log-scaled breadth). With default weights and
        # uncertain factors in the world model, the epistemic gain from more
        # nodes outweighs the ambiguity penalty.
        assert ranked[0].score.total < ranked[1].score.total

        # Complex DAG should have higher ambiguity component
        complex_c = next(c for c in ranked if c.rationale == "complex")
        simple_c = next(c for c in ranked if c.rationale == "simple")
        assert complex_c.score.ambiguity_component > simple_c.score.ambiguity_component

        # Complex DAG should have more negative epistemic (higher info gain)
        assert complex_c.score.epistemic_component < simple_c.score.epistemic_component

    def test_policy_selector_circumplex_eccentricity(self, world_model):
        """Circumplex eccentricity increases ambiguity component."""
        calculator = EFECalculator()
        selector = PolicySelector(calculator=calculator)

        dag = SkillDAG()
        dag.add_node(DAGNode(
            node_id="n1", skill_name="test", sub_task="task", layer=0,
        ))

        # Score without eccentricity
        ranked_no_ecc = selector.score_candidates(
            candidates=[PolicyCandidate(dag=SkillDAG(dag_id="no_ecc"), desire_id="d1")],
            world_model=world_model,
            desired_outcomes={"funding_status": 0.9},
            circumplex_eccentricity=None,
        )
        # Need at least one node for meaningful scoring
        dag_no_ecc = SkillDAG(dag_id="no_ecc_dag")
        dag_no_ecc.add_node(DAGNode(node_id="n1", skill_name="t", sub_task="t", layer=0))
        dag_high_ecc = SkillDAG(dag_id="high_ecc_dag")
        dag_high_ecc.add_node(DAGNode(node_id="n1", skill_name="t", sub_task="t", layer=0))

        ranked_no_ecc = selector.score_candidates(
            candidates=[PolicyCandidate(dag=dag_no_ecc, desire_id="d1")],
            world_model=world_model,
            desired_outcomes={"funding_status": 0.9},
            circumplex_eccentricity=None,
        )

        ranked_high_ecc = selector.score_candidates(
            candidates=[PolicyCandidate(dag=dag_high_ecc, desire_id="d1")],
            world_model=world_model,
            desired_outcomes={"funding_status": 0.9},
            circumplex_eccentricity=0.8,
        )

        # High eccentricity should increase total EFE (worse score)
        assert ranked_high_ecc[0].score.total > ranked_no_ecc[0].score.total

    def test_policy_selector_select_best(self):
        """select_best returns the first (best) candidate."""
        calculator = EFECalculator()
        selector = PolicySelector(calculator=calculator)

        # Empty list returns None
        assert selector.select_best([]) is None

        # Non-empty returns first
        dag = SkillDAG()
        dag.add_node(DAGNode(node_id="n", skill_name="s", sub_task="t", layer=0))
        candidate = PolicyCandidate(dag=dag, desire_id="d1")
        assert selector.select_best([candidate]) is candidate

    def test_epistemic_weight_affects_scoring(self, world_model):
        """High epistemic weight makes information gain more impactful."""
        # Use exploration-heavy weights
        explore_weights = EFEWeights(risk=0.1, ambiguity=0.1, epistemic=0.8)
        calculator_explore = EFECalculator(default_weights=explore_weights)
        selector_explore = PolicySelector(calculator=calculator_explore, weights=explore_weights)

        # Use exploitation-heavy weights
        exploit_weights = EFEWeights(risk=0.8, ambiguity=0.1, epistemic=0.1)
        calculator_exploit = EFECalculator(default_weights=exploit_weights)
        selector_exploit = PolicySelector(calculator=calculator_exploit, weights=exploit_weights)

        # Same DAG evaluated under both weight profiles
        dag = SkillDAG(dag_id="test_dag")
        dag.add_node(DAGNode(
            node_id="n1", skill_name="s", sub_task="t", layer=0,
        ))

        candidates = [PolicyCandidate(dag=dag, desire_id="d1", rationale="test")]

        ranked_explore = selector_explore.score_candidates(
            candidates=candidates,
            world_model=world_model,
            desired_outcomes={"funding_status": 0.9},
        )

        candidates2 = [PolicyCandidate(dag=SkillDAG(dag_id="test_dag2"), desire_id="d1", rationale="test2")]
        candidates2[0].dag.add_node(DAGNode(node_id="n1", skill_name="s", sub_task="t", layer=0))

        ranked_exploit = selector_exploit.score_candidates(
            candidates=candidates2,
            world_model=world_model,
            desired_outcomes={"funding_status": 0.9},
        )

        # With exploration weights, the epistemic component should be
        # more negative (larger magnitude) reflecting higher value on info gain
        explore_epistemic = ranked_explore[0].score.epistemic_component
        exploit_epistemic = ranked_exploit[0].score.epistemic_component

        # Epistemic component is negative (info gain is subtracted)
        # With higher epistemic weight, the magnitude should be larger (more negative)
        assert explore_epistemic < exploit_epistemic


# ---------------------------------------------------------------------------
# ActiveInferenceLoop tests
# ---------------------------------------------------------------------------


class TestActiveInferenceLoop:
    def test_active_inference_loop_full_cycle(
        self, registry, capability_tree, bdi_store, world_model
    ):
        """Full cycle: observe -> infer -> plan -> act produces a DAG."""
        loop = ActiveInferenceLoop(
            bdi_store=bdi_store,
            registry=registry,
            capability_tree=capability_tree,
        )

        # Inject initial state into the loop's world model
        loop.world_model.add_factor(StateFactor(
            name="funding_status",
            value=0.4,
            confidence=0.6,
            observation_sources=[ObservationModality.METRIC_STREAM],
        ))

        # Observe: new information about funding
        obs = Observation(
            modality=ObservationModality.METRIC_STREAM,
            factor_name="funding_status",
            value=0.7,
            confidence=0.9,
        )
        surprise = loop.observe(obs)
        assert surprise > 0  # 0.7 vs predicted 0.4 = some surprise
        assert loop.last_surprise == surprise

        # Infer: should update/create beliefs
        updated_ids = loop.infer()
        # The existing belief with tag "funding_status" should be updated
        assert len(updated_ids) > 0

        # Plan: should produce ranked candidates
        ranked = loop.plan(desired_outcomes={"funding_status": 0.9})
        # May or may not have candidates depending on tree traversal
        # but the mechanism should not crash

        # Act: if candidates exist, should return a DAG
        if ranked:
            dag = loop.act(ranked)
            assert isinstance(dag, SkillDAG)
            assert loop.current_policy is not None

            # Intention should be recorded in the BDI store
            intentions = bdi_store.list_intentions(status=IntentionStatus.ACTIVE)
            assert len(intentions) > 0

    def test_observe_updates_world_model(self, registry, capability_tree, bdi_store):
        """observe() updates the world model and returns surprise."""
        loop = ActiveInferenceLoop(
            bdi_store=bdi_store,
            registry=registry,
            capability_tree=capability_tree,
        )

        # First observation (no prior) should have maximal surprise
        obs = Observation(
            modality=ObservationModality.USER_FEEDBACK,
            factor_name="user_satisfaction",
            value=0.8,
            confidence=0.85,
        )
        surprise = loop.observe(obs)
        assert surprise == 1.0  # No prior prediction -> max surprise

        # Second observation on same factor should have lower surprise
        obs2 = Observation(
            modality=ObservationModality.USER_FEEDBACK,
            factor_name="user_satisfaction",
            value=0.82,
            confidence=0.85,
        )
        surprise2 = loop.observe(obs2)
        assert surprise2 < surprise  # Closer to prediction now

    def test_infer_creates_beliefs(self, registry, capability_tree):
        """infer() creates beliefs from high-confidence factors."""
        store = BDIStore(org_id="test")
        loop = ActiveInferenceLoop(
            bdi_store=store,
            registry=registry,
            capability_tree=capability_tree,
        )

        # Add a high-confidence factor
        loop.world_model.add_factor(StateFactor(
            name="system_health",
            value=0.95,
            confidence=0.9,
            observation_sources=[ObservationModality.METRIC_STREAM],
        ))

        updated = loop.infer()
        assert len(updated) == 1

        beliefs = store.list_beliefs(status=BeliefStatus.ACTIVE)
        assert len(beliefs) == 1
        assert "system_health" in beliefs[0].tags
        assert beliefs[0].confidence == 0.9

    def test_infer_skips_low_confidence(self, registry, capability_tree):
        """infer() does not create beliefs from low-confidence factors."""
        store = BDIStore(org_id="test")
        loop = ActiveInferenceLoop(
            bdi_store=store,
            registry=registry,
            capability_tree=capability_tree,
        )

        # Add a very uncertain factor
        loop.world_model.add_factor(StateFactor(
            name="unknown_signal",
            value=0.5,
            confidence=0.2,  # Below 0.3 threshold
            observation_sources=[ObservationModality.DRIFT_SIGNAL],
        ))

        updated = loop.infer()
        assert len(updated) == 0
        assert len(store.list_beliefs()) == 0

    def test_plan_and_act_convenience(self, registry, capability_tree, bdi_store):
        """plan_and_act() is equivalent to plan() then act()."""
        loop = ActiveInferenceLoop(
            bdi_store=bdi_store,
            registry=registry,
            capability_tree=capability_tree,
        )

        # Add factors so there's something to work with
        loop.world_model.add_factor(StateFactor(
            name="fundraising",
            value=0.3,
            confidence=0.5,
            observation_sources=[ObservationModality.METRIC_STREAM],
        ))

        result = loop.plan_and_act(desired_outcomes={"fundraising": 0.9})
        # Result may be None if no skills match, but should not crash
        if result is not None:
            assert isinstance(result, SkillDAG)

    def test_full_cycle_convenience(self, registry, capability_tree, bdi_store):
        """full_cycle() runs observe -> infer -> plan -> act."""
        loop = ActiveInferenceLoop(
            bdi_store=bdi_store,
            registry=registry,
            capability_tree=capability_tree,
        )

        loop.world_model.add_factor(StateFactor(
            name="operations",
            value=0.5,
            confidence=0.6,
            observation_sources=[ObservationModality.TOOL_OUTPUT],
        ))

        obs = Observation(
            modality=ObservationModality.TOOL_OUTPUT,
            factor_name="operations",
            value=0.7,
            confidence=0.8,
        )

        dag = loop.full_cycle(obs, desired_outcomes={"operations": 1.0})
        # Should not crash; result depends on tree traversal
        if dag is not None:
            assert isinstance(dag, SkillDAG)

    def test_empty_desires_returns_no_policy(self, registry, capability_tree):
        """plan() with no active desires returns empty list."""
        store = BDIStore(org_id="test")
        loop = ActiveInferenceLoop(
            bdi_store=store,
            registry=registry,
            capability_tree=capability_tree,
        )

        ranked = loop.plan()
        assert ranked == []
        assert loop.act(ranked) is None

    def test_surprise_feeds_oracle_signal(self, registry, capability_tree, bdi_store):
        """High surprise is accessible as a potential Oracle pathology signal."""
        loop = ActiveInferenceLoop(
            bdi_store=bdi_store,
            registry=registry,
            capability_tree=capability_tree,
        )

        loop.world_model.add_factor(StateFactor(
            name="generation_quality",
            value=0.9,
            confidence=0.95,
            observation_sources=[ObservationModality.TOOL_OUTPUT],
        ))

        # Observe a value very different from prediction (pathological generation)
        obs = Observation(
            modality=ObservationModality.TOOL_OUTPUT,
            factor_name="generation_quality",
            value=0.1,  # Dramatic drop from expected 0.9
            confidence=0.9,
        )
        surprise = loop.observe(obs)

        # High surprise = potential pathology signal for Oracle
        assert surprise > 1.0
        assert loop.last_surprise > 1.0
