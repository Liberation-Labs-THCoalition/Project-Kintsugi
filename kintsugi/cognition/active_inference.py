"""Active Inference BDI deepening module for Kintsugi.

Connects the BDI cognitive architecture to the DAG skill composition
framework via proper Active Inference. This is the theoretical deepening
that makes Kintsugi's BDI a proper Active Inference agent rather than
just a data structure.

The BDI cycle expressed as Active Inference:
    - Beliefs <- observation + inference (perception)
    - Desires <- goals remain stable (prior preferences)
    - Intentions <- selected policy/DAG (action selection)

Architecture connections:
    - In local mode: beliefs with high confidence become Knowledge Pack
      candidates for cross-context transfer.
    - The world model's surprise signal feeds into Oracle's detection
      pipeline (high surprise = potential pathology in generation).
    - Policy selection produces DAGs that can be encoded as cache topology
      via Pharos for KV-native execution.

Reference: arXiv:2412.10425 (Active Inference for agentic systems).
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from kintsugi.bdi.models import (
    BDIBelief,
    BDIDesire,
    BDIIntention,
    BeliefStatus,
    DesireStatus,
    IntentionStatus,
)
from kintsugi.bdi.store import BDIStore
from kintsugi.cognition.efe import (
    DEFAULT_WEIGHTS,
    EFECalculator,
    EFEScore,
    EFEWeights,
    ObservationModality,
    StateFactor,
    WorldModel as EFEWorldModel,
)
from kintsugi.skills.capability_tree import CapabilityTree, RetrievalResult
from kintsugi.skills.dag import DAGBuilder, DAGNode, SkillDAG
from kintsugi.skills.registry import SkillRegistry


# ---------------------------------------------------------------------------
# Observation container
# ---------------------------------------------------------------------------


@dataclass
class Observation:
    """A single observation from the environment.

    Observations arrive through modalities and update specific state factors
    in the world model. The confidence indicates how reliable the observation
    source is (e.g., direct tool output vs. inferred from user feedback).
    """

    modality: ObservationModality
    factor_name: str
    value: Any
    confidence: float = 0.8
    timestamp: Optional[str] = None

    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# World Model (Active Inference native)
# ---------------------------------------------------------------------------


class WorldModel:
    """Factored environment model for Active Inference policy evaluation.

    Holds state factors representing the agent's understanding of its
    environment. Each factor is independently updatable and contributes
    to uncertainty estimation. This is the generative model that the
    agent uses to predict observations and evaluate candidate policies.

    The model is lightweight — no neural networks. Uses confidence intervals
    and simple probabilistic reasoning. Compatible with the existing
    StateFactor/WorldModel in efe.py but adds prediction and surprise
    computation needed for the full inference loop.
    """

    def __init__(self) -> None:
        self._model = EFEWorldModel()
        self._observation_log: List[Observation] = []

    @property
    def factors(self) -> Dict[str, StateFactor]:
        return self._model.factors

    @property
    def uncertainty(self) -> float:
        """Overall uncertainty across all factors."""
        return self._model.get_uncertainty()

    def add_factor(self, factor: StateFactor) -> None:
        """Register a new state factor in the world model."""
        self._model.add_factor(factor)

    def get_factor(self, name: str) -> Optional[StateFactor]:
        """Retrieve a specific state factor by name."""
        return self._model.get_factor(name)

    def predict_observation(
        self, factor_name: str, modality: ObservationModality
    ) -> Optional[Any]:
        """Predict what observation to expect for a given factor.

        Returns the current best estimate for the factor's value. In a
        full generative model this would involve the observation likelihood
        mapping; here we use the factor value directly as the prediction,
        which is valid for the lightweight probabilistic case.
        """
        factor = self._model.get_factor(factor_name)
        if factor is None:
            return None
        # Prediction is the current best estimate (MAP of the generative model)
        return factor.value

    def update_factor(
        self,
        factor_name: str,
        observation: Any,
        modality: ObservationModality,
        confidence: float = 0.8,
    ) -> float:
        """Update a state factor from an observation. Returns new confidence.

        Performs Bayesian-style update: blends prior estimate with new
        observation weighted by relative confidence. Returns the updated
        confidence value after incorporation.
        """
        factor = self._model.get_factor(factor_name)
        if factor is None:
            # Auto-create factor if it does not exist
            new_factor = StateFactor(
                name=factor_name,
                value=observation,
                confidence=confidence,
                observation_sources=[modality],
            )
            self._model.add_factor(new_factor)
            return confidence

        old_confidence = factor.confidence
        factor.update_from_observation(observation, confidence)

        # Record observation
        obs = Observation(
            modality=modality,
            factor_name=factor_name,
            value=observation,
            confidence=confidence,
        )
        self._observation_log.append(obs)

        return factor.confidence

    def surprise(self, observation: Any, prediction: Any) -> float:
        """Compute surprise: how unexpected was this observation.

        Uses negative log-likelihood approximation. For numeric values,
        surprise is proportional to absolute difference normalized by
        expected magnitude. For categorical values, surprise is binary
        (0.0 if match, 1.0 if mismatch).

        Returns a value in [0, inf) where 0 = fully expected.
        High surprise feeds into Oracle's pathology detection pipeline.
        """
        if prediction is None:
            # No prediction available — maximum uncertainty
            return 1.0

        # Numeric case: normalized absolute difference
        try:
            obs_f = float(observation)
            pred_f = float(prediction)
            scale = max(abs(pred_f), 1e-9)
            raw_diff = abs(obs_f - pred_f) / scale
            # Map through log for proper surprise scaling
            # surprise = -log(1 - clipped_divergence)
            clipped = min(raw_diff, 0.999)
            return -math.log(1.0 - clipped)
        except (TypeError, ValueError):
            pass

        # Categorical case: exact match check
        if observation == prediction:
            return 0.0
        return 1.0

    def to_predicted_outcome(self) -> Dict[str, Any]:
        """Export current factor values as predicted outcome dict.

        Bridges into the EFECalculator interface.
        """
        return self._model.to_predicted_outcome()

    def get_uncertain_factors(self, threshold: float = 0.5) -> List[StateFactor]:
        """Return factors with confidence below threshold."""
        return self._model.get_uncertain_factors(threshold)

    def information_gain_estimate(self, factor_name: str) -> float:
        """Estimate information gain from observing a specific factor."""
        return self._model.information_gain_estimate(factor_name)


# ---------------------------------------------------------------------------
# Policy candidate container
# ---------------------------------------------------------------------------


@dataclass
class PolicyCandidate:
    """A candidate policy (SkillDAG) with its EFE score and metadata."""

    dag: SkillDAG
    desire_id: str
    score: Optional[EFEScore] = None
    rationale: str = ""

    @property
    def policy_id(self) -> str:
        return self.dag.dag_id


# ---------------------------------------------------------------------------
# Policy Generator
# ---------------------------------------------------------------------------


class PolicyGenerator:
    """Generates candidate policies as SkillDAGs from active desires.

    Takes active desires, current beliefs, and the capability tree to
    produce candidate execution plans. Each candidate addresses one or
    more active desires by composing available skills into DAGs.

    The generator uses the capability tree for skill retrieval:
    desires -> tree traversal -> candidate skills -> DAG composition.
    Produces 2-5 candidate DAGs per desire for the selector to rank.
    """

    def __init__(
        self,
        registry: SkillRegistry,
        capability_tree: CapabilityTree,
        max_candidates_per_desire: int = 3,
    ) -> None:
        self._registry = registry
        self._tree = capability_tree
        self._max_candidates = max_candidates_per_desire

    def generate(
        self,
        desires: List[BDIDesire],
        beliefs: List[BDIBelief],
        world_model: WorldModel,
    ) -> List[PolicyCandidate]:
        """Generate candidate policies for all active desires.

        For each active desire:
        1. Extract keywords from the desire content
        2. Traverse capability tree to find relevant skills
        3. Compose skills into candidate DAGs using different strategies
        4. Tag each candidate with the desire it addresses

        Returns a flat list of all candidates across all desires.
        """
        candidates: List[PolicyCandidate] = []

        for desire in desires:
            if desire.status != DesireStatus.ACTIVE:
                continue

            desire_candidates = self._generate_for_desire(
                desire, beliefs, world_model
            )
            candidates.extend(desire_candidates)

        return candidates

    def _generate_for_desire(
        self,
        desire: BDIDesire,
        beliefs: List[BDIBelief],
        world_model: WorldModel,
    ) -> List[PolicyCandidate]:
        """Generate candidate DAGs for a single desire."""
        # Retrieve relevant skills via capability tree
        desire_dict = {
            "content": desire.content,
            "type": desire.related_tags[0] if desire.related_tags else "general",
        }
        belief_dicts = [
            {"content": b.content, "confidence": b.confidence}
            for b in beliefs
            if b.status == BeliefStatus.ACTIVE
        ]

        retrieval = self._tree.retrieve(
            desires=[desire_dict],
            beliefs=belief_dicts,
            max_results=8,
        )

        skill_names = retrieval.skill_names
        if not skill_names:
            return []

        candidates: List[PolicyCandidate] = []

        # Strategy 1: Linear chain (simplest execution path)
        if len(skill_names) >= 1:
            linear_skills = skill_names[: min(3, len(skill_names))]
            dag = DAGBuilder.from_skill_sequence(
                skill_names=linear_skills,
                registry=self._registry,
                sub_tasks=[
                    f"{desire.content} via {s}" for s in linear_skills
                ],
            )
            dag.metadata["desire_id"] = desire.id
            dag.metadata["strategy"] = "linear"
            candidates.append(
                PolicyCandidate(
                    dag=dag,
                    desire_id=desire.id,
                    rationale=f"Linear chain: {' -> '.join(linear_skills)}",
                )
            )

        # Strategy 2: Parallel fan-out (if multiple independent skills)
        if len(skill_names) >= 2:
            parallel_skills = skill_names[: min(4, len(skill_names))]
            dag = self._build_parallel_dag(parallel_skills, desire)
            candidates.append(
                PolicyCandidate(
                    dag=dag,
                    desire_id=desire.id,
                    rationale=f"Parallel fan-out: {parallel_skills}",
                )
            )

        # Strategy 3: Focused single-skill (minimal uncertainty)
        if skill_names:
            best_skill = skill_names[0]
            dag = DAGBuilder.from_skill_sequence(
                skill_names=[best_skill],
                registry=self._registry,
                sub_tasks=[f"{desire.content} (focused)"],
            )
            dag.metadata["desire_id"] = desire.id
            dag.metadata["strategy"] = "focused"
            candidates.append(
                PolicyCandidate(
                    dag=dag,
                    desire_id=desire.id,
                    rationale=f"Focused execution: {best_skill}",
                )
            )

        return candidates[: self._max_candidates]

    def _build_parallel_dag(
        self, skill_names: List[str], desire: BDIDesire
    ) -> SkillDAG:
        """Build a parallel fan-out DAG where skills execute in the same layer."""
        dag = SkillDAG(
            strategy="efficiency",
            metadata={"desire_id": desire.id, "strategy": "parallel"},
        )

        for i, name in enumerate(skill_names):
            node = DAGNode(
                node_id=f"par_{i}",
                skill_name=name,
                sub_task=f"{desire.content} via {name}",
                layer=0,  # All in same layer = parallel
                input_keys=[],
                output_keys=[f"par_{i}_out"],
            )
            dag.add_node(node)

        return dag


# ---------------------------------------------------------------------------
# Policy Selector
# ---------------------------------------------------------------------------


class PolicySelector:
    """Scores and ranks candidate policies by Expected Free Energy.

    Evaluates each candidate DAG against the world model using the EFE
    decomposition:
        - Risk: expected divergence from desired outcomes (how likely to fail?)
        - Ambiguity: uncertainty about outcomes given this policy (how unpredictable?)
        - Epistemic: information gain from executing this policy (what will we learn?)

    Lower total EFE = preferred policy (least expected surprise, best alignment
    with desired outcomes while appropriately valuing exploration).

    Integrates with circumplex eccentricity compensation when vectors are
    involved: if a policy involves skills that operate in circumplex space,
    eccentricity is factored into the ambiguity component.
    """

    def __init__(
        self,
        calculator: EFECalculator,
        weights: Optional[EFEWeights] = None,
    ) -> None:
        self._calculator = calculator
        self._weights = weights or DEFAULT_WEIGHTS

    def score_candidates(
        self,
        candidates: List[PolicyCandidate],
        world_model: WorldModel,
        desired_outcomes: Dict[str, Any],
        circumplex_eccentricity: Optional[float] = None,
    ) -> List[PolicyCandidate]:
        """Score all candidates and return ranked list (best first).

        For each candidate:
        1. Estimate predicted outcome from DAG structure + world model
        2. Compute uncertainty specific to this policy's skill requirements
        3. Estimate information gain from executing this policy
        4. Calculate EFE = weighted(risk + ambiguity - epistemic)

        If circumplex_eccentricity is provided, it modifies the ambiguity
        component: high eccentricity (polarized vectors) increases ambiguity
        because the policy's outcome depends more on the exact vector
        orientation, making predictions less reliable.
        """
        scored: List[PolicyCandidate] = []

        for candidate in candidates:
            score = self._score_single(
                candidate, world_model, desired_outcomes, circumplex_eccentricity
            )
            candidate.score = score
            scored.append(candidate)

        # Sort by total EFE (lower = better)
        scored.sort(key=lambda c: c.score.total if c.score else float("inf"))
        return scored

    def _score_single(
        self,
        candidate: PolicyCandidate,
        world_model: WorldModel,
        desired_outcomes: Dict[str, Any],
        circumplex_eccentricity: Optional[float],
    ) -> EFEScore:
        """Score a single policy candidate."""
        dag = candidate.dag

        # Estimate predicted outcome: blend world model prediction with
        # DAG structure hints (more nodes = more potential for state change)
        predicted = world_model.to_predicted_outcome()

        # Policy-specific uncertainty: more nodes = more execution ambiguity
        node_count = len(dag.nodes)
        base_uncertainty = world_model.uncertainty
        policy_uncertainty = base_uncertainty + (0.05 * node_count)
        policy_uncertainty = min(policy_uncertainty, 1.0)

        # Apply circumplex eccentricity compensation
        if circumplex_eccentricity is not None and circumplex_eccentricity > 0:
            # High eccentricity = more ambiguity (vectors are polarized,
            # outcomes depend on exact orientation)
            eccentricity_penalty = circumplex_eccentricity * 0.1
            policy_uncertainty = min(policy_uncertainty + eccentricity_penalty, 1.0)

        # Information gain: policies touching uncertain factors are more
        # epistemically valuable
        info_gain = self._estimate_information_gain(dag, world_model)

        return self._calculator.calculate_efe(
            policy_id=candidate.policy_id,
            predicted_outcome=predicted,
            desired_outcome=desired_outcomes,
            uncertainty=policy_uncertainty,
            information_gain=info_gain,
            weights=self._weights,
        )

    def _estimate_information_gain(
        self, dag: SkillDAG, world_model: WorldModel
    ) -> float:
        """Estimate epistemic value of executing a DAG.

        Policies that touch uncertain state factors have higher information
        gain — executing them resolves uncertainty about the world.
        """
        uncertain_factors = world_model.get_uncertain_factors(threshold=0.6)
        if not uncertain_factors:
            return 0.0

        # Each node potentially resolves uncertainty proportional to the
        # number of uncertain factors it might observe
        node_count = len(dag.nodes)
        factor_count = len(uncertain_factors)

        # Average information gain per uncertain factor, scaled by policy breadth
        avg_uncertainty = sum(
            1.0 - f.confidence for f in uncertain_factors
        ) / max(factor_count, 1)

        # More nodes = more observation opportunities (log-scaled, gentle)
        breadth_factor = math.log1p(node_count) / math.log1p(100)

        return avg_uncertainty * breadth_factor

    def select_best(
        self, ranked_candidates: List[PolicyCandidate]
    ) -> Optional[PolicyCandidate]:
        """Return the best candidate (lowest EFE) or None if empty."""
        if not ranked_candidates:
            return None
        return ranked_candidates[0]


# ---------------------------------------------------------------------------
# Active Inference Loop
# ---------------------------------------------------------------------------


class ActiveInferenceLoop:
    """The main Active Inference loop tying BDI to DAG execution.

    This is the perception-action cycle expressed as Active Inference:
        observe() -> receive new observation, update world model
        infer()   -> update beliefs based on new state
        plan()    -> generate candidate policies, score via EFE
        act()     -> select best policy, return SkillDAG to execute

    The loop bridges the BDI architecture to concrete skill execution:
        - BDIStore provides beliefs and desires (the agent's epistemic state)
        - WorldModel tracks environment state factors
        - PolicyGenerator produces candidate DAGs
        - PolicySelector ranks them by Expected Free Energy
        - The selected DAG becomes the new BDI Intention

    Usage:
        loop = ActiveInferenceLoop(store, registry, tree)
        loop.observe(observation)
        loop.infer()
        dag = loop.plan_and_act()
        # Execute dag via DAGExecutor
    """

    def __init__(
        self,
        bdi_store: BDIStore,
        registry: SkillRegistry,
        capability_tree: CapabilityTree,
        weights: Optional[EFEWeights] = None,
        max_candidates_per_desire: int = 3,
    ) -> None:
        self._store = bdi_store
        self._registry = registry
        self._world_model = WorldModel()
        self._calculator = EFECalculator(default_weights=weights)
        self._generator = PolicyGenerator(
            registry=registry,
            capability_tree=capability_tree,
            max_candidates_per_desire=max_candidates_per_desire,
        )
        self._selector = PolicySelector(
            calculator=self._calculator,
            weights=weights,
        )
        self._last_surprise: float = 0.0
        self._observation_count: int = 0
        self._current_policy: Optional[PolicyCandidate] = None

    @property
    def world_model(self) -> WorldModel:
        """Access the internal world model for inspection."""
        return self._world_model

    @property
    def last_surprise(self) -> float:
        """Surprise value from the most recent observation.

        High surprise signals potential pathology — feeds into Oracle's
        detection pipeline in local mode.
        """
        return self._last_surprise

    @property
    def current_policy(self) -> Optional[PolicyCandidate]:
        """The currently selected policy, if any."""
        return self._current_policy

    # ------------------------------------------------------------------
    # Observe: receive new observation, update world model
    # ------------------------------------------------------------------

    def observe(self, observation: Observation) -> float:
        """Process a new observation from the environment.

        Updates the world model and computes surprise. High surprise
        values (> 1.0) indicate the world diverged from expectations,
        which may indicate:
        - Unexpected environment change (legitimate)
        - Stale beliefs that need revision
        - Potential pathology in upstream generation (Oracle signal)

        Returns the surprise value.
        """
        # Get prediction before update
        prediction = self._world_model.predict_observation(
            observation.factor_name, observation.modality
        )

        # Compute surprise
        self._last_surprise = self._world_model.surprise(
            observation.value, prediction
        )

        # Update the factor
        self._world_model.update_factor(
            factor_name=observation.factor_name,
            observation=observation.value,
            modality=observation.modality,
            confidence=observation.confidence,
        )

        self._observation_count += 1
        return self._last_surprise

    # ------------------------------------------------------------------
    # Infer: update BDI beliefs based on world model state
    # ------------------------------------------------------------------

    def infer(self) -> List[str]:
        """Update BDI beliefs based on current world model state.

        For each state factor with sufficient confidence, either:
        - Update an existing belief's confidence
        - Create a new belief from a newly observed factor

        Returns list of belief IDs that were created or updated.
        """
        updated_ids: List[str] = []

        for factor_name, factor in self._world_model.factors.items():
            if factor.confidence < 0.3:
                # Too uncertain to form a belief
                continue

            # Check if a belief already exists for this factor
            existing = self._find_belief_for_factor(factor_name)

            if existing is not None:
                # Update existing belief confidence
                new_confidence = min(factor.confidence, 1.0)
                if abs(existing.confidence - new_confidence) > 0.05:
                    self._store.update_belief(
                        existing.id, confidence=new_confidence
                    )
                    updated_ids.append(existing.id)
            else:
                # Create new belief from factor
                # In local mode, high-confidence beliefs become Knowledge Pack
                # candidates for cross-context transfer
                belief = BDIBelief(
                    id=f"belief_{factor_name}_{uuid.uuid4().hex[:8]}",
                    content=f"State factor '{factor_name}' = {factor.value}",
                    confidence=factor.confidence,
                    status=BeliefStatus.ACTIVE,
                    source="active_inference",
                    tags=[factor_name, "inferred"],
                    created_at=datetime.now(timezone.utc),
                )
                self._store.add_belief(belief)
                updated_ids.append(belief.id)

        return updated_ids

    def _find_belief_for_factor(self, factor_name: str) -> Optional[BDIBelief]:
        """Find an existing belief that corresponds to a state factor."""
        active_beliefs = self._store.list_beliefs(status=BeliefStatus.ACTIVE)
        for belief in active_beliefs:
            if factor_name in belief.tags:
                return belief
        return None

    # ------------------------------------------------------------------
    # Plan: generate and score candidate policies
    # ------------------------------------------------------------------

    def plan(
        self,
        desired_outcomes: Optional[Dict[str, Any]] = None,
        circumplex_eccentricity: Optional[float] = None,
    ) -> List[PolicyCandidate]:
        """Generate and score candidate policies.

        Uses active desires from the BDI store to generate candidate DAGs,
        then scores each by Expected Free Energy. Returns ranked list
        with best (lowest EFE) first.

        If desired_outcomes is not provided, constructs it from active
        desires in the BDI store.
        """
        # Gather active desires and beliefs
        active_desires = self._store.list_desires(status=DesireStatus.ACTIVE)
        active_beliefs = self._store.list_beliefs(status=BeliefStatus.ACTIVE)

        if not active_desires:
            return []

        # Generate candidates
        candidates = self._generator.generate(
            desires=active_desires,
            beliefs=active_beliefs,
            world_model=self._world_model,
        )

        if not candidates:
            return []

        # Construct desired outcomes from desires if not provided
        if desired_outcomes is None:
            desired_outcomes = self._desires_to_outcomes(active_desires)

        # Score and rank
        ranked = self._selector.score_candidates(
            candidates=candidates,
            world_model=self._world_model,
            desired_outcomes=desired_outcomes,
            circumplex_eccentricity=circumplex_eccentricity,
        )

        return ranked

    def _desires_to_outcomes(
        self, desires: List[BDIDesire]
    ) -> Dict[str, Any]:
        """Convert active desires to a desired outcome dict for EFE scoring."""
        outcomes: Dict[str, Any] = {}
        for desire in desires:
            # Use first tag as outcome key, priority as target value
            key = desire.related_tags[0] if desire.related_tags else desire.id
            outcomes[key] = desire.priority
        return outcomes

    # ------------------------------------------------------------------
    # Act: select best policy and commit as intention
    # ------------------------------------------------------------------

    def act(
        self, ranked_candidates: Optional[List[PolicyCandidate]] = None
    ) -> Optional[SkillDAG]:
        """Select the best policy and return its DAG for execution.

        If ranked_candidates is not provided, calls plan() first.
        The selected policy becomes a BDI Intention in the store.

        Returns the SkillDAG to execute, or None if no viable policy.
        """
        if ranked_candidates is None:
            ranked_candidates = self.plan()

        best = self._selector.select_best(ranked_candidates)
        if best is None:
            return None

        self._current_policy = best

        # Register the selected policy as a BDI Intention
        intention = BDIIntention(
            id=f"intention_{best.policy_id[:8]}",
            goal=best.rationale,
            status=IntentionStatus.ACTIVE,
            belief_ids=[],
            desire_ids=[best.desire_id],
            created_at=datetime.now(timezone.utc),
        )
        self._store.add_intention(intention)

        return best.dag

    # ------------------------------------------------------------------
    # Full cycle convenience
    # ------------------------------------------------------------------

    def plan_and_act(
        self,
        desired_outcomes: Optional[Dict[str, Any]] = None,
        circumplex_eccentricity: Optional[float] = None,
    ) -> Optional[SkillDAG]:
        """Run plan + act in one call. Returns the DAG to execute."""
        ranked = self.plan(
            desired_outcomes=desired_outcomes,
            circumplex_eccentricity=circumplex_eccentricity,
        )
        return self.act(ranked)

    def full_cycle(
        self,
        observation: Observation,
        desired_outcomes: Optional[Dict[str, Any]] = None,
    ) -> Optional[SkillDAG]:
        """Run the complete Active Inference cycle.

        observe -> infer -> plan -> act

        This is the canonical perception-action loop. In production,
        these steps may be called separately for finer control.
        """
        self.observe(observation)
        self.infer()
        return self.plan_and_act(desired_outcomes=desired_outcomes)
