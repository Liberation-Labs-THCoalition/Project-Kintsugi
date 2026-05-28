"""Tests for Active Inference extensions to EFE (state factors, world model)."""

import pytest

from kintsugi.cognition.efe import (
    DEFAULT_WEIGHTS,
    EFECalculator,
    EFEWeights,
    ObservationModality,
    StateFactor,
    WorldModel,
)


class TestStateFactor:
    def test_basic_creation(self):
        f = StateFactor(name="budget", value=50000, confidence=0.8)
        assert f.name == "budget"
        assert f.value == 50000
        assert f.confidence == 0.8

    def test_update_from_observation_numeric(self):
        f = StateFactor(name="budget", value=50000.0, confidence=0.5)
        f.update_from_observation(60000.0, observation_confidence=0.8)
        assert f.value != 50000.0
        assert f.value != 60000.0
        assert 50000.0 < f.value < 60000.0
        assert f.confidence > 0.5
        assert f.last_updated is not None

    def test_update_from_observation_first_value(self):
        f = StateFactor(name="status")
        assert f.value is None
        f.update_from_observation("active", 0.9)
        assert f.value == "active"
        assert f.confidence == 0.9

    def test_update_non_numeric_higher_confidence_wins(self):
        f = StateFactor(name="status", value="pending", confidence=0.3)
        f.update_from_observation("active", observation_confidence=0.8)
        assert f.value == "active"

    def test_update_non_numeric_lower_confidence_keeps(self):
        f = StateFactor(name="status", value="pending", confidence=0.9)
        f.update_from_observation("active", observation_confidence=0.2)
        assert f.value == "pending"

    def test_confidence_capped_at_one(self):
        f = StateFactor(name="x", value=1.0, confidence=0.95)
        f.update_from_observation(1.0, 0.9)
        assert f.confidence <= 1.0

    def test_observation_sources(self):
        f = StateFactor(
            name="team_mood",
            observation_sources=[ObservationModality.USER_FEEDBACK, ObservationModality.METRIC_STREAM],
        )
        assert len(f.observation_sources) == 2


class TestWorldModel:
    def test_add_and_get_factor(self):
        wm = WorldModel()
        wm.add_factor(StateFactor(name="budget", value=1000, confidence=0.7))
        assert wm.get_factor("budget") is not None
        assert wm.get_factor("nonexistent") is None

    def test_observe_updates_factor(self):
        wm = WorldModel()
        wm.add_factor(StateFactor(name="budget", value=1000.0, confidence=0.5))
        assert wm.observe("budget", 1200.0, 0.8)
        f = wm.get_factor("budget")
        assert f.value != 1000.0

    def test_observe_unknown_factor_returns_false(self):
        wm = WorldModel()
        assert not wm.observe("nonexistent", 42)

    def test_get_uncertainty_all_certain(self):
        wm = WorldModel()
        wm.add_factor(StateFactor(name="a", value=1, confidence=1.0))
        wm.add_factor(StateFactor(name="b", value=2, confidence=1.0))
        assert wm.get_uncertainty() == 0.0

    def test_get_uncertainty_all_unknown(self):
        wm = WorldModel()
        wm.add_factor(StateFactor(name="a", value=1, confidence=0.0))
        assert wm.get_uncertainty() == 1.0

    def test_get_uncertainty_empty(self):
        wm = WorldModel()
        assert wm.get_uncertainty() == 1.0

    def test_get_uncertain_factors(self):
        wm = WorldModel()
        wm.add_factor(StateFactor(name="known", value=1, confidence=0.9))
        wm.add_factor(StateFactor(name="unknown", value=2, confidence=0.2))
        uncertain = wm.get_uncertain_factors(threshold=0.5)
        assert len(uncertain) == 1
        assert uncertain[0].name == "unknown"

    def test_to_predicted_outcome(self):
        wm = WorldModel()
        wm.add_factor(StateFactor(name="a", value=10))
        wm.add_factor(StateFactor(name="b", value=20))
        wm.add_factor(StateFactor(name="c"))  # None value, excluded
        pred = wm.to_predicted_outcome()
        assert pred == {"a": 10, "b": 20}

    def test_information_gain_estimate(self):
        wm = WorldModel()
        wm.add_factor(StateFactor(name="certain", confidence=0.95))
        wm.add_factor(StateFactor(name="uncertain", confidence=0.1))
        assert wm.information_gain_estimate("certain") < 0.1
        assert wm.information_gain_estimate("uncertain") > 0.8
        assert wm.information_gain_estimate("nonexistent") == 0.0


class TestEFEWithWorldModel:
    def test_calculate_from_world_model(self):
        calc = EFECalculator()
        wm = WorldModel()
        wm.add_factor(StateFactor(name="funding", value=0.7, confidence=0.8))
        wm.add_factor(StateFactor(name="capacity", value=0.5, confidence=0.3))

        desired = {"funding": 1.0, "capacity": 1.0}
        score = calc.calculate_efe_from_world_model("policy-1", wm, desired)
        assert score.policy_id == "policy-1"
        assert score.total != 0.0
        assert score.risk_component >= 0
        assert score.epistemic_component <= 0  # info gain is negative

    def test_world_model_vs_manual_consistency(self):
        calc = EFECalculator()
        wm = WorldModel()
        wm.add_factor(StateFactor(name="x", value=0.5, confidence=0.3))
        desired = {"x": 1.0}

        wm_score = calc.calculate_efe_from_world_model("p1", wm, desired)
        uncertain = wm.get_uncertain_factors()
        info_gain = (
            sum(wm.information_gain_estimate(f.name) for f in uncertain)
            / max(len(wm.factors), 1)
        )
        manual_score = calc.calculate_efe(
            "p1",
            predicted_outcome={"x": 0.5},
            desired_outcome={"x": 1.0},
            uncertainty=wm.get_uncertainty(),
            information_gain=info_gain,
        )
        assert abs(wm_score.total - manual_score.total) < 0.01

    def test_uncertain_model_favors_exploration(self):
        calc = EFECalculator(default_weights=EFEWeights(risk=0.2, ambiguity=0.2, epistemic=0.6))

        certain_wm = WorldModel()
        certain_wm.add_factor(StateFactor(name="x", value=0.5, confidence=0.95))

        uncertain_wm = WorldModel()
        uncertain_wm.add_factor(StateFactor(name="x", value=0.5, confidence=0.1))

        desired = {"x": 1.0}
        certain_score = calc.calculate_efe_from_world_model("p1", certain_wm, desired)
        uncertain_score = calc.calculate_efe_from_world_model("p2", uncertain_wm, desired)

        # Uncertain model should have lower (better) EFE because epistemic
        # component is more negative (higher info gain)
        assert uncertain_score.epistemic_component < certain_score.epistemic_component

    def test_select_policy_prefers_lower_efe(self):
        calc = EFECalculator()
        wm_good = WorldModel()
        wm_good.add_factor(StateFactor(name="x", value=0.9, confidence=0.9))
        wm_bad = WorldModel()
        wm_bad.add_factor(StateFactor(name="x", value=0.1, confidence=0.2))

        desired = {"x": 1.0}
        score_good = calc.calculate_efe_from_world_model("good", wm_good, desired)
        score_bad = calc.calculate_efe_from_world_model("bad", wm_bad, desired)
        best = calc.select_policy([score_good, score_bad])
        assert best.policy_id == "good"


class TestObservationModality:
    def test_all_modalities_exist(self):
        assert len(ObservationModality) == 6
        assert ObservationModality.TOOL_OUTPUT.value == "tool_output"
        assert ObservationModality.DRIFT_SIGNAL.value == "drift_signal"
