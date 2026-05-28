"""Expected Free Energy (EFE) calculation for active inference.

Implements a lightweight EFE scorer used by the decision engine to rank
candidate policies.  Lower total EFE indicates the preferred policy
(least expected surprise / best alignment with desired outcomes).

v2 (May 2026): Added state factor decomposition and observation model
for proper Active Inference grounding. Reference: arXiv:2412.10425.

The Free Energy Principle: agents act to minimize surprise (free energy).
This naturally balances exploitation (pursuing goals = reducing expected
divergence from desired states) and exploration (reducing uncertainty =
maximizing information gain). EFE is the look-ahead version: expected
free energy of a *future* policy, not current observations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Weight profiles
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EFEWeights:
    """Component weights for the EFE calculation.

    Must approximately sum to 1.0 (tolerance 0.05).
    """

    risk: float
    ambiguity: float
    epistemic: float

    def __post_init__(self) -> None:
        total = self.risk + self.ambiguity + self.epistemic
        if not math.isclose(total, 1.0, abs_tol=0.05):
            raise ValueError(
                f"EFEWeights must sum to ~1.0; got {total:.4f} "
                f"(risk={self.risk}, ambiguity={self.ambiguity}, "
                f"epistemic={self.epistemic})"
            )


class ObservationModality(str, Enum):
    """Channels through which the agent observes the environment."""
    TOOL_OUTPUT = "tool_output"
    USER_FEEDBACK = "user_feedback"
    METRIC_STREAM = "metric_stream"
    BDI_BELIEF = "bdi_belief"
    DRIFT_SIGNAL = "drift_signal"
    EXTERNAL_EVENT = "external_event"


@dataclass
class StateFactor:
    """A single factored dimension of the environment state.

    Active Inference decomposes the world model into independent state
    factors, each observed through one or more modalities. This enables
    targeted belief updating: when an observation arrives on one modality,
    only the relevant state factors need revision.

    Attributes:
        name: Identifier for this factor (e.g., "funding_status", "team_capacity")
        value: Current estimated value
        confidence: Bayesian confidence in the estimate (0 = unknown, 1 = certain)
        observation_sources: Which modalities inform this factor
        last_updated: When this factor was last revised
        prior: Default/prior value before any observations
    """
    name: str
    value: Any = None
    confidence: float = 0.5
    observation_sources: List[ObservationModality] = field(default_factory=list)
    last_updated: Optional[str] = None
    prior: Any = None

    def update_from_observation(
        self, observed_value: Any, observation_confidence: float = 0.8
    ) -> None:
        """Bayesian-like belief update from a new observation.

        Uses a simplified confidence-weighted blend: the new confidence is
        a weighted combination of prior confidence and observation confidence.
        The value updates proportionally.
        """
        if self.value is None:
            self.value = observed_value
            self.confidence = observation_confidence
        else:
            blend = observation_confidence / (self.confidence + observation_confidence)
            try:
                old_val = float(self.value)
                new_val = float(observed_value)
                self.value = old_val * (1 - blend) + new_val * blend
            except (TypeError, ValueError):
                if observation_confidence > self.confidence:
                    self.value = observed_value
            self.confidence = min(self.confidence + observation_confidence * 0.5, 1.0)
        from datetime import datetime, timezone
        self.last_updated = datetime.now(timezone.utc).isoformat()


@dataclass
class WorldModel:
    """Factored environment model for Active Inference.

    The world model decomposes the agent's understanding of its environment
    into independent state factors, each with its own observation sources
    and confidence. This enables:
    - Targeted belief updates (only revise relevant factors)
    - Uncertainty decomposition (know WHERE the agent is uncertain)
    - Information gain estimation (which observations reduce most uncertainty)
    """
    factors: Dict[str, StateFactor] = field(default_factory=dict)

    def add_factor(self, factor: StateFactor) -> None:
        self.factors[factor.name] = factor

    def get_factor(self, name: str) -> Optional[StateFactor]:
        return self.factors.get(name)

    def observe(
        self,
        factor_name: str,
        value: Any,
        confidence: float = 0.8,
    ) -> bool:
        factor = self.factors.get(factor_name)
        if factor is None:
            return False
        factor.update_from_observation(value, confidence)
        return True

    def get_uncertainty(self) -> float:
        """Average uncertainty across all factors. Lower = more certain."""
        if not self.factors:
            return 1.0
        return 1.0 - sum(f.confidence for f in self.factors.values()) / len(self.factors)

    def get_uncertain_factors(self, threshold: float = 0.5) -> List[StateFactor]:
        """Return factors with confidence below threshold."""
        return [f for f in self.factors.values() if f.confidence < threshold]

    def to_predicted_outcome(self) -> Dict[str, Any]:
        """Export current factor values as a predicted outcome dict.

        Bridges WorldModel into the existing EFE calculate_efe() interface.
        """
        return {f.name: f.value for f in self.factors.values() if f.value is not None}

    def information_gain_estimate(self, factor_name: str) -> float:
        """Estimate information gain from observing a specific factor.

        Higher gain for factors with low confidence and high prior uncertainty.
        """
        factor = self.factors.get(factor_name)
        if factor is None:
            return 0.0
        return 1.0 - factor.confidence


# Domain-specific weight profiles
GRANTS_WEIGHTS = EFEWeights(risk=0.3, ambiguity=0.3, epistemic=0.4)
FINANCE_WEIGHTS = EFEWeights(risk=0.6, ambiguity=0.3, epistemic=0.1)
COMMUNICATIONS_WEIGHTS = EFEWeights(risk=0.4, ambiguity=0.2, epistemic=0.4)
DEFAULT_WEIGHTS = EFEWeights(risk=0.33, ambiguity=0.34, epistemic=0.33)


# ---------------------------------------------------------------------------
# Score container
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EFEScore:
    """Result of an EFE evaluation for a single policy."""

    total: float
    risk_component: float
    ambiguity_component: float
    epistemic_component: float
    policy_id: str


# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------


class EFECalculator:
    """Compute Expected Free Energy for candidate policies.

    Parameters
    ----------
    default_weights:
        Fallback weights when none are provided per call.
    """

    def __init__(self, default_weights: EFEWeights | None = None) -> None:
        self._default_weights = default_weights or DEFAULT_WEIGHTS

    # -- public API ---------------------------------------------------------

    def calculate_efe(
        self,
        policy_id: str,
        predicted_outcome: dict,
        desired_outcome: dict,
        uncertainty: float,
        information_gain: float,
        weights: EFEWeights | None = None,
    ) -> EFEScore:
        """Score a single policy.

        Parameters
        ----------
        policy_id:
            Unique identifier for the candidate policy.
        predicted_outcome:
            Dict of predicted state variables after executing the policy.
        desired_outcome:
            Dict of target / goal state variables.
        uncertainty:
            Scalar representing outcome uncertainty (0 = certain).
        information_gain:
            Expected information gain from executing this policy.
        weights:
            Per-call weight override; uses *default_weights* when *None*.

        Returns
        -------
        EFEScore
            Decomposed score with total and per-component values.
        """
        w = weights or self._default_weights
        divergence = self.compute_divergence(predicted_outcome, desired_outcome)

        risk_component = w.risk * divergence
        ambiguity_component = w.ambiguity * uncertainty
        epistemic_component = w.epistemic * (-information_gain)
        total = risk_component + ambiguity_component + epistemic_component

        return EFEScore(
            total=total,
            risk_component=risk_component,
            ambiguity_component=ambiguity_component,
            epistemic_component=epistemic_component,
            policy_id=policy_id,
        )

    def calculate_efe_from_world_model(
        self,
        policy_id: str,
        world_model: WorldModel,
        desired_outcome: dict,
        weights: EFEWeights | None = None,
    ) -> EFEScore:
        """Score a policy using the factored world model.

        Extracts predicted outcome, uncertainty, and information gain
        directly from the WorldModel's state factors. This is the
        Active Inference-native interface — it uses the world model's
        own uncertainty decomposition rather than externally supplied scalars.
        """
        predicted = world_model.to_predicted_outcome()
        uncertainty = world_model.get_uncertainty()
        uncertain_factors = world_model.get_uncertain_factors()
        info_gain = (
            sum(world_model.information_gain_estimate(f.name) for f in uncertain_factors)
            / max(len(world_model.factors), 1)
        )
        return self.calculate_efe(
            policy_id=policy_id,
            predicted_outcome=predicted,
            desired_outcome=desired_outcome,
            uncertainty=uncertainty,
            information_gain=info_gain,
            weights=weights,
        )

    def select_policy(self, scores: list[EFEScore]) -> EFEScore:
        """Return the policy with the lowest total EFE.

        Raises ``ValueError`` if *scores* is empty.
        """
        if not scores:
            raise ValueError("Cannot select from an empty score list")
        return min(scores, key=lambda s: s.total)

    @staticmethod
    def compute_divergence(predicted: dict, desired: dict) -> float:
        """Normalised symmetric difference between two outcome dicts.

        For overlapping keys with numeric values the divergence is the mean
        absolute difference normalised by the max absolute value (per key).
        Keys present in only one dict contribute 1.0 each.  The final value
        is averaged over the union of keys so the result lies in ``[0, 1]``.
        """
        all_keys = set(predicted) | set(desired)
        if not all_keys:
            return 0.0

        total = 0.0
        for key in all_keys:
            if key not in predicted or key not in desired:
                total += 1.0
                continue
            pv, dv = predicted[key], desired[key]
            try:
                pf, df = float(pv), float(dv)
            except (TypeError, ValueError):
                # Non-numeric: exact equality check
                total += 0.0 if pv == dv else 1.0
                continue
            max_abs = max(abs(pf), abs(df), 1e-9)
            total += abs(pf - df) / max_abs

        return total / len(all_keys)
