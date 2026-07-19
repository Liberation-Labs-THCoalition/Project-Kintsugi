"""Tests for kintsugi.kintsugi_engine.persona_gate (OGPSA persona coherence)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
import torch

from kintsugi.kintsugi_engine.persona_gate import (
    PersonaGate,
    PersonaGateConfig,
    PersonaGateResult,
    PersonaMeasurement,
    PersonaModelAccess,
    PersonaStatus,
    ReinforcementResult,
)


# ---------------------------------------------------------------------------
# Mock model access
# ---------------------------------------------------------------------------

class _MockModelAccess:
    """Fake model that returns pre-configured hidden states.

    Parameters
    ----------
    hidden_states_fn:
        Callable (text, layers) -> {layer: np.ndarray}.
        Controls what concentration the SVD computation will produce.
    reinforce_loss:
        Loss value returned by reinforce_adapter.
    post_reinforce_fn:
        Optional callable (text, layers) -> {layer: np.ndarray} that
        replaces hidden_states_fn after the first reinforce_adapter call.
        Lets tests simulate recovery (or failure to recover).
    """

    def __init__(
        self,
        hidden_states_fn,
        reinforce_loss: float = 0.01,
        post_reinforce_fn=None,
    ):
        self._fn = hidden_states_fn
        self._reinforce_loss = reinforce_loss
        self._post_reinforce_fn = post_reinforce_fn
        self.reinforce_call_count = 0

    def extract_hidden_states(
        self, text: str, layers: list[int],
    ) -> dict[int, Any]:
        return self._fn(text, layers)

    def reinforce_adapter(
        self, sft_data: list[dict], steps: int, lr: float,
    ) -> float:
        self.reinforce_call_count += 1
        if self._post_reinforce_fn is not None:
            self._fn = self._post_reinforce_fn
        return self._reinforce_loss


# ---------------------------------------------------------------------------
# Hidden-state factory helpers
# ---------------------------------------------------------------------------

def _rank1_hidden_states(dim: int = 8):
    """Return a function that produces rank-1 hidden states.

    All difference vectors (persona - baseline) are scalar multiples
    of the same direction, so SVD top-1 variance ratio is ~1.0.

    Returns torch tensors since the production code tries torch first.
    """
    direction = np.random.default_rng(42).standard_normal(dim)
    direction /= np.linalg.norm(direction)
    direction_t = torch.from_numpy(direction).float()
    call_count = [0]

    def fn(text: str, layers: list[int]) -> dict[int, torch.Tensor]:
        call_count[0] += 1
        scale = 1.0 + 0.1 * call_count[0]  # small variation in magnitude
        return {l: direction_t * scale for l in layers}

    return fn


def _scattered_hidden_states(dim: int = 8, concentration_target: str = "low"):
    """Return a function that produces scattered hidden states.

    Difference vectors point in different orthogonal directions so
    SVD concentration is well below 1.0.

    concentration_target:
        'low'  -> differences are fully orthogonal (concentration ~1/n)
        'mid'  -> partially aligned (concentration ~0.7)

    Returns torch tensors since the production code tries torch first.
    """
    rng = np.random.default_rng(99)
    call_count = [0]

    if concentration_target == "mid":
        # Partially aligned: dominant direction + noise
        dominant = rng.standard_normal(dim).astype(np.float32)
        dominant /= np.linalg.norm(dominant)

        def fn(text: str, layers: list[int]) -> dict[int, torch.Tensor]:
            call_count[0] += 1
            noise = rng.standard_normal(dim).astype(np.float32) * 0.6
            vec = torch.from_numpy(dominant * 2.0 + noise)
            return {l: vec for l in layers}

    else:
        # Fully scattered: each call returns a different orthogonal-ish direction
        basis = torch.eye(dim)

        def fn(text: str, layers: list[int]) -> dict[int, torch.Tensor]:
            idx = call_count[0] % dim
            call_count[0] += 1
            return {l: basis[idx] for l in layers}

    return fn


# ---------------------------------------------------------------------------
# 1. PersonaStatus enum values
# ---------------------------------------------------------------------------

class TestPersonaStatus:
    def test_values_exist(self):
        assert PersonaStatus.HEALTHY == "HEALTHY"
        assert PersonaStatus.DRIFTED == "DRIFTED"
        assert PersonaStatus.CRITICAL == "CRITICAL"

    def test_is_str_enum(self):
        assert isinstance(PersonaStatus.HEALTHY, str)

    def test_all_members(self):
        assert set(PersonaStatus) == {
            PersonaStatus.HEALTHY,
            PersonaStatus.DRIFTED,
            PersonaStatus.CRITICAL,
        }


# ---------------------------------------------------------------------------
# 2. PersonaGateConfig defaults
# ---------------------------------------------------------------------------

class TestPersonaGateConfig:
    def test_default_identity_layers(self):
        cfg = PersonaGateConfig()
        assert cfg.identity_layers == [3, 4, 5]

    def test_default_measurement_layers(self):
        cfg = PersonaGateConfig()
        assert cfg.measurement_layers == [3, 4, 5, 7, 10]

    def test_default_thresholds(self):
        cfg = PersonaGateConfig()
        assert cfg.threshold_healthy == 0.80
        assert cfg.threshold_critical == 0.60

    def test_default_reinforcement_params(self):
        cfg = PersonaGateConfig()
        assert cfg.reinforcement_steps == 10
        assert cfg.reinforcement_lr == 1e-5
        assert cfg.max_reinforcements_per_day == 3

    def test_custom_config(self):
        cfg = PersonaGateConfig(
            identity_layers=[1, 2],
            threshold_healthy=0.9,
            threshold_critical=0.5,
            max_reinforcements_per_day=5,
        )
        assert cfg.identity_layers == [1, 2]
        assert cfg.threshold_healthy == 0.9
        assert cfg.threshold_critical == 0.5
        assert cfg.max_reinforcements_per_day == 5


# ---------------------------------------------------------------------------
# 3. PersonaGate with no model (measurement-only mode)
# ---------------------------------------------------------------------------

class TestNoModelAccess:
    def test_measure_returns_synthetic_healthy(self):
        gate = PersonaGate()
        m = gate.measure()
        assert isinstance(m, PersonaMeasurement)
        assert m.mean_identity_concentration == 1.0
        assert m.status == PersonaStatus.HEALTHY

    def test_measure_synthetic_layers(self):
        gate = PersonaGate()
        m = gate.measure()
        expected_layers = PersonaGateConfig().measurement_layers
        assert set(m.layer_concentrations.keys()) == set(expected_layers)
        for v in m.layer_concentrations.values():
            assert v == 1.0

    def test_check_promotion_allows_when_no_model(self):
        gate = PersonaGate()
        result = gate.check_promotion("pattern_x", "task_a")
        assert isinstance(result, PersonaGateResult)
        assert result.promotion_allowed is True
        assert result.reinforcement is None

    def test_cycle_counter_increments(self):
        gate = PersonaGate()
        m1 = gate.measure()
        m2 = gate.measure()
        m3 = gate.measure()
        assert m1.cycle == 1
        assert m2.cycle == 2
        assert m3.cycle == 3

    def test_check_promotion_increments_cycle(self):
        gate = PersonaGate()
        r = gate.check_promotion("p", "t")
        assert r.measurement.cycle == 1

    def test_timestamp_is_populated(self):
        gate = PersonaGate()
        m = gate.measure()
        assert len(m.timestamp) > 0


# ---------------------------------------------------------------------------
# 4. PersonaGate with mock model
# ---------------------------------------------------------------------------

_PERSONA_PAIRS = [
    ("I am the agent persona.", "I am a baseline."),
    ("My identity is X.", "Generic text."),
    ("Persona prompt three.", "Baseline prompt three."),
    ("Persona prompt four.", "Baseline prompt four."),
]

_SFT_DATA = [{"prompt": "Who are you?", "response": "I am the agent."}]


class TestHealthyScenario:
    """Mock returns high-concentration hidden states -> promotion allowed."""

    def test_healthy_measurement(self):
        model = _MockModelAccess(hidden_states_fn=_rank1_hidden_states())
        gate = PersonaGate(
            persona_pairs=_PERSONA_PAIRS,
            sft_data=_SFT_DATA,
            model_access=model,
        )
        m = gate.measure()
        assert m.status == PersonaStatus.HEALTHY
        assert m.mean_identity_concentration >= 0.80

    def test_healthy_promotion_allowed(self):
        model = _MockModelAccess(hidden_states_fn=_rank1_hidden_states())
        gate = PersonaGate(
            persona_pairs=_PERSONA_PAIRS,
            sft_data=_SFT_DATA,
            model_access=model,
        )
        result = gate.check_promotion("new_scaffold", "code_gen")
        assert result.promotion_allowed is True
        assert result.reinforcement is None
        assert "allowed" in result.reason.lower()


class TestDriftedScenario:
    """Mock returns moderate-concentration -> reinforcement fires."""

    def _make_gate(self, post_fn=None):
        """Build a gate with mid-concentration hidden states."""
        model = _MockModelAccess(
            hidden_states_fn=_scattered_hidden_states(concentration_target="mid"),
            reinforce_loss=0.005,
            post_reinforce_fn=post_fn,
        )
        cfg = PersonaGateConfig(
            identity_layers=[3, 4, 5],
            measurement_layers=[3, 4, 5],
            threshold_healthy=0.95,  # tight so mid-concentration => DRIFTED
            threshold_critical=0.30,
        )
        gate = PersonaGate(
            config=cfg,
            persona_pairs=_PERSONA_PAIRS,
            sft_data=_SFT_DATA,
            model_access=model,
        )
        return gate, model

    def test_drifted_measurement(self):
        gate, _ = self._make_gate()
        m = gate.measure()
        assert m.status == PersonaStatus.DRIFTED

    def test_drifted_triggers_reinforcement(self):
        gate, model = self._make_gate()
        result = gate.check_promotion("pat", "task")
        assert result.reinforcement is not None
        assert model.reinforce_call_count >= 1

    def test_drifted_recovery(self):
        """After reinforcement, mock switches to rank-1 -> recovered."""
        gate, model = self._make_gate(post_fn=_rank1_hidden_states())
        result = gate.check_promotion("pat", "task")
        assert result.reinforcement is not None
        assert result.reinforcement.recovered is True
        assert result.promotion_allowed is True
        assert "recovered" in result.reason.lower()

    def test_drifted_no_recovery(self):
        """Reinforcement does not bring concentration back -> blocked."""
        gate, _ = self._make_gate(post_fn=None)  # stays mid
        result = gate.check_promotion("pat", "task")
        assert result.reinforcement is not None
        assert result.reinforcement.recovered is False
        assert result.promotion_allowed is False
        assert "blocked" in result.reason.lower()


class TestCriticalScenario:
    """Very low concentration -> promotion blocked, human alert."""

    def test_critical_blocks_promotion(self):
        model = _MockModelAccess(
            hidden_states_fn=_scattered_hidden_states(concentration_target="low"),
            reinforce_loss=0.1,
        )
        cfg = PersonaGateConfig(
            identity_layers=[3, 4, 5],
            measurement_layers=[3, 4, 5],
            threshold_healthy=0.80,
            threshold_critical=0.60,
        )
        gate = PersonaGate(
            config=cfg,
            persona_pairs=_PERSONA_PAIRS,
            sft_data=_SFT_DATA,
            model_access=model,
        )
        result = gate.check_promotion("dangerous_pattern", "evolve")
        assert result.promotion_allowed is False
        assert "CRITICAL" in result.reason or "critical" in result.reason.lower()
        assert "blocked" in result.reason.lower()

    def test_critical_measurement_status(self):
        model = _MockModelAccess(
            hidden_states_fn=_scattered_hidden_states(concentration_target="low"),
        )
        cfg = PersonaGateConfig(
            identity_layers=[3, 4, 5],
            measurement_layers=[3, 4, 5],
            threshold_healthy=0.80,
            threshold_critical=0.60,
        )
        gate = PersonaGate(
            config=cfg,
            persona_pairs=_PERSONA_PAIRS,
            model_access=model,
        )
        m = gate.measure()
        assert m.status == PersonaStatus.CRITICAL
        assert m.mean_identity_concentration < 0.60


# ---------------------------------------------------------------------------
# 5. Daily reinforcement budget
# ---------------------------------------------------------------------------

class TestReinforcementBudget:
    def _make_gate(self, max_reinforcements: int = 2):
        model = _MockModelAccess(
            hidden_states_fn=_scattered_hidden_states(concentration_target="mid"),
            reinforce_loss=0.01,
        )
        cfg = PersonaGateConfig(
            identity_layers=[3, 4, 5],
            measurement_layers=[3, 4, 5],
            threshold_healthy=0.95,
            threshold_critical=0.30,
            max_reinforcements_per_day=max_reinforcements,
        )
        gate = PersonaGate(
            config=cfg,
            persona_pairs=_PERSONA_PAIRS,
            sft_data=_SFT_DATA,
            model_access=model,
        )
        return gate

    def test_budget_exhausted_stops_reinforcement(self):
        gate = self._make_gate(max_reinforcements=2)
        # First two promotions each consume one reinforcement
        r1 = gate.check_promotion("p1", "t1")
        r2 = gate.check_promotion("p2", "t2")
        assert r1.reinforcement is not None
        assert r2.reinforcement is not None
        # Third should have no reinforcement (budget exhausted)
        r3 = gate.check_promotion("p3", "t3")
        assert r3.reinforcement is None
        assert r3.promotion_allowed is False

    def test_reset_daily_budget(self):
        gate = self._make_gate(max_reinforcements=1)
        r1 = gate.check_promotion("p1", "t1")
        assert r1.reinforcement is not None
        # Budget exhausted
        r2 = gate.check_promotion("p2", "t2")
        assert r2.reinforcement is None
        # Reset budget
        gate.reset_daily_budget()
        r3 = gate.check_promotion("p3", "t3")
        assert r3.reinforcement is not None


# ---------------------------------------------------------------------------
# 6. History tracking
# ---------------------------------------------------------------------------

class TestHistory:
    def test_history_records_measurements_with_model(self):
        model = _MockModelAccess(hidden_states_fn=_rank1_hidden_states())
        gate = PersonaGate(
            persona_pairs=_PERSONA_PAIRS,
            model_access=model,
        )
        gate.measure()
        gate.measure()
        gate.measure()
        assert len(gate.history) == 3
        assert gate.history[0].cycle == 1
        assert gate.history[2].cycle == 3

    def test_history_returns_copy(self):
        model = _MockModelAccess(hidden_states_fn=_rank1_hidden_states())
        gate = PersonaGate(
            persona_pairs=_PERSONA_PAIRS,
            model_access=model,
        )
        gate.measure()
        h = gate.history
        h.clear()
        assert len(gate.history) == 1  # original unchanged

    def test_no_model_measure_not_in_history(self):
        """Synthetic measurements (no model) bypass _history append."""
        gate = PersonaGate()
        gate.measure()
        gate.measure()
        # _synthetic_measurement does not append to _history
        assert len(gate.history) == 0

    def test_serialize_history(self):
        model = _MockModelAccess(hidden_states_fn=_rank1_hidden_states())
        gate = PersonaGate(
            persona_pairs=_PERSONA_PAIRS,
            model_access=model,
        )
        gate.measure()
        gate.measure()
        serialized = gate.serialize_history()
        assert isinstance(serialized, list)
        assert len(serialized) == 2
        for entry in serialized:
            assert "cycle" in entry
            assert "layer_concentrations" in entry
            assert "mean_identity_concentration" in entry
            assert "status" in entry
            assert "timestamp" in entry
            # status should be the string value, not enum
            assert isinstance(entry["status"], str)

    def test_serialize_history_empty(self):
        gate = PersonaGate()
        assert gate.serialize_history() == []


# ---------------------------------------------------------------------------
# 7. _classify_status boundary conditions
# ---------------------------------------------------------------------------

class TestClassifyStatus:
    def setup_method(self):
        self.gate = PersonaGate()

    def test_at_healthy_threshold(self):
        assert self.gate._classify_status(0.80) == PersonaStatus.HEALTHY

    def test_above_healthy_threshold(self):
        assert self.gate._classify_status(0.99) == PersonaStatus.HEALTHY

    def test_just_below_healthy(self):
        assert self.gate._classify_status(0.799) == PersonaStatus.DRIFTED

    def test_at_critical_threshold(self):
        assert self.gate._classify_status(0.60) == PersonaStatus.DRIFTED

    def test_just_below_critical(self):
        assert self.gate._classify_status(0.599) == PersonaStatus.CRITICAL

    def test_zero_concentration(self):
        assert self.gate._classify_status(0.0) == PersonaStatus.CRITICAL

    def test_one_concentration(self):
        assert self.gate._classify_status(1.0) == PersonaStatus.HEALTHY

    def test_custom_thresholds(self):
        cfg = PersonaGateConfig(threshold_healthy=0.90, threshold_critical=0.50)
        gate = PersonaGate(config=cfg)
        assert gate._classify_status(0.91) == PersonaStatus.HEALTHY
        assert gate._classify_status(0.89) == PersonaStatus.DRIFTED
        assert gate._classify_status(0.50) == PersonaStatus.DRIFTED
        assert gate._classify_status(0.49) == PersonaStatus.CRITICAL


# ---------------------------------------------------------------------------
# 8. SVD concentration computation
# ---------------------------------------------------------------------------

class TestSVDConcentration:
    def test_rank1_data_high_concentration(self):
        """All difference vectors are scalar multiples -> concentration ~1.0."""
        direction = np.array([1.0, 0.0, 0.0, 0.0])
        diffs = [direction * s for s in [1.0, 2.0, 3.0, 4.0, 5.0]]
        conc = PersonaGate._svd_concentration(diffs)
        assert conc == pytest.approx(1.0, abs=1e-6)

    def test_scattered_data_low_concentration(self):
        """Orthogonal difference vectors -> concentration well below 1.0."""
        diffs = [
            np.array([1.0, 0.0, 0.0, 0.0]),
            np.array([0.0, 1.0, 0.0, 0.0]),
            np.array([0.0, 0.0, 1.0, 0.0]),
            np.array([0.0, 0.0, 0.0, 1.0]),
        ]
        conc = PersonaGate._svd_concentration(diffs)
        # After demeaning, 4 equal-magnitude orthogonal vectors lose 1 rank
        # -> 3 equal singular values -> concentration = 1/3
        assert conc == pytest.approx(1.0 / 3.0, abs=0.05)

    def test_two_directions_with_noise(self):
        """Two directions with per-sample noise -> moderate concentration."""
        rng = np.random.default_rng(42)
        diffs = []
        for _ in range(10):
            base = np.array([3.0, 0.0, 0.0, 0.0]) if rng.random() > 0.5 else np.array([0.0, 3.0, 0.0, 0.0])
            diffs.append(base + rng.standard_normal(4) * 0.5)
        conc = PersonaGate._svd_concentration(diffs)
        assert 0.3 < conc < 0.98

    def test_single_vector(self):
        """Single vector: trivially rank-1, returns 1.0."""
        diffs = [np.array([1.0, 2.0, 3.0])]
        conc = PersonaGate._svd_concentration(diffs)
        assert conc == pytest.approx(1.0)

    def test_returns_float(self):
        diffs = [
            np.array([1.0, 0.0]),
            np.array([0.0, 1.0]),
        ]
        conc = PersonaGate._svd_concentration(diffs)
        assert isinstance(conc, float)

    def test_nearly_rank1_with_noise(self):
        """Dominant direction with small noise -> concentration near 1.0."""
        rng = np.random.default_rng(123)
        direction = np.array([1.0, 0.0, 0.0, 0.0, 0.0])
        diffs = [direction * s + rng.standard_normal(5) * 0.01
                 for s in [1.0, 2.0, 3.0, 4.0, 5.0]]
        conc = PersonaGate._svd_concentration(diffs)
        assert conc > 0.95


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_persona_pairs_with_model(self):
        """Model provided but no persona pairs -> synthetic measurement."""
        model = _MockModelAccess(hidden_states_fn=_rank1_hidden_states())
        gate = PersonaGate(model_access=model, persona_pairs=[])
        m = gate.measure()
        assert m.mean_identity_concentration == 1.0
        assert m.status == PersonaStatus.HEALTHY

    def test_no_sft_data_skips_reinforcement(self):
        """Model available but no SFT data -> reinforcement returns None."""
        model = _MockModelAccess(
            hidden_states_fn=_scattered_hidden_states(concentration_target="mid"),
        )
        cfg = PersonaGateConfig(
            identity_layers=[3, 4, 5],
            measurement_layers=[3, 4, 5],
            threshold_healthy=0.95,
            threshold_critical=0.30,
        )
        gate = PersonaGate(
            config=cfg,
            persona_pairs=_PERSONA_PAIRS,
            model_access=model,
            sft_data=[],
        )
        result = gate.check_promotion("pat", "task")
        assert result.reinforcement is None
        assert result.promotion_allowed is False

    def test_compute_concentrations_no_model(self):
        """_compute_concentrations with no model returns all 1.0."""
        gate = PersonaGate()
        conc = gate._compute_concentrations([3, 4, 5])
        assert conc == {3: 1.0, 4: 1.0, 5: 1.0}

    def test_dataclass_fields(self):
        """PersonaMeasurement and ReinforcementResult have expected fields."""
        m = PersonaMeasurement(
            layer_concentrations={3: 0.9},
            mean_identity_concentration=0.9,
            status=PersonaStatus.HEALTHY,
        )
        assert m.timestamp == ""
        assert m.cycle == 0

        r = ReinforcementResult(
            pre_concentration=0.7,
            post_concentration=0.85,
            steps_taken=10,
            final_loss=0.01,
            recovered=True,
        )
        assert r.recovered is True
