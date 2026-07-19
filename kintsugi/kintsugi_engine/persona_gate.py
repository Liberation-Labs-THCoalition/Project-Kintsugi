"""OGPSA Persona Gate — identity coherence check for scaffold evolution.

Prevents scaffold evolution from fragmenting agent persona. Based on
Vera's OGPSA (Orthogonal Geometric Persona Subspace Analysis) finding:
persona identity concentrates on a rank-1 direction at layers 3-5.
When that concentration drops, identity is fragmenting.

The gate doesn't care WHERE the rank-1 direction points — personality
can evolve (rotate coherently). It fires only when identity FRAGMENTS
(scatters across multiple directions).

Integration point: fires after scaffold comparison when a promotion
would change the agent's default behavior. If persona coherence drops
below threshold, the promotion is blocked and reinforcement fires.

Design: Vera (2026-07-19)
Implementation: CC
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class PersonaStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DRIFTED = "DRIFTED"
    CRITICAL = "CRITICAL"


@dataclass
class PersonaMeasurement:
    """Result of an OGPSA persona coherence measurement."""
    layer_concentrations: dict[int, float]
    mean_identity_concentration: float
    status: PersonaStatus
    timestamp: str = ""
    cycle: int = 0


@dataclass
class ReinforcementResult:
    """Result of a persona reinforcement step."""
    pre_concentration: float
    post_concentration: float
    steps_taken: int
    final_loss: float
    recovered: bool


@dataclass
class PersonaGateResult:
    """Full gate result: measurement + optional reinforcement."""
    measurement: PersonaMeasurement
    promotion_allowed: bool
    reinforcement: ReinforcementResult | None = None
    reason: str = ""


class PersonaModelAccess(Protocol):
    """Protocol for accessing model internals for OGPSA measurement.

    Implementations provide model-specific hidden state extraction
    and adapter reinforcement. This keeps the gate module free of
    torch/mlx dependencies.
    """

    def extract_hidden_states(
        self, text: str, layers: list[int],
    ) -> dict[int, Any]:
        """Extract hidden states at specified layers for given text."""
        ...

    def reinforce_adapter(
        self, sft_data: list[dict], steps: int, lr: float,
    ) -> float:
        """Run reinforcement steps on adapter weights. Returns final loss."""
        ...


@dataclass
class PersonaGateConfig:
    """Configuration for the persona coherence gate."""
    identity_layers: list[int] = field(default_factory=lambda: [3, 4, 5])
    measurement_layers: list[int] = field(
        default_factory=lambda: [3, 4, 5, 7, 10]
    )
    threshold_healthy: float = 0.80
    threshold_critical: float = 0.60
    reinforcement_steps: int = 10
    reinforcement_lr: float = 1e-5
    max_reinforcements_per_day: int = 3


class PersonaGate:
    """OGPSA-based persona coherence gate for scaffold evolution.

    Measures whether the agent's identity direction remains rank-1
    concentrated at early layers. If concentration drops below
    threshold after a scaffold promotion, blocks the promotion and
    optionally fires a gentle reinforcement step.

    Parameters
    ----------
    config:
        Gate configuration (thresholds, layers, reinforcement params).
    persona_pairs:
        List of (persona_prompt, baseline_prompt) tuples from the
        original OGPSA Phase 1 discovery set.
    sft_data:
        Original persona SFT training examples for reinforcement.
    model_access:
        Protocol implementation for model-specific operations.
        When None, the gate operates in measurement-only mode
        (no reinforcement, no hidden state extraction — useful
        for testing or when the model isn't available).
    """

    def __init__(
        self,
        config: PersonaGateConfig | None = None,
        persona_pairs: list[tuple[str, str]] | None = None,
        sft_data: list[dict] | None = None,
        model_access: PersonaModelAccess | None = None,
    ):
        self._config = config or PersonaGateConfig()
        self._persona_pairs = persona_pairs or []
        self._sft_data = sft_data or []
        self._model = model_access
        self._cycle = 0
        self._reinforcements_today: list[float] = []
        self._history: list[PersonaMeasurement] = []

    def measure(self) -> PersonaMeasurement:
        """Measure current persona concentration via OGPSA.

        Returns per-layer top-1 variance ratio. Identity layers
        (default 3-5) determine the gate decision; measurement
        layers (default 3-10) are logged for archaeology.
        """
        if self._model is None or not self._persona_pairs:
            return self._synthetic_measurement(1.0)

        concentrations = self._compute_concentrations(
            self._config.measurement_layers
        )

        identity_values = [
            concentrations[l] for l in self._config.identity_layers
            if l in concentrations
        ]
        mean_concentration = (
            sum(identity_values) / len(identity_values)
            if identity_values else 0.0
        )

        status = self._classify_status(mean_concentration)

        self._cycle += 1
        measurement = PersonaMeasurement(
            layer_concentrations=concentrations,
            mean_identity_concentration=mean_concentration,
            status=status,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            cycle=self._cycle,
        )
        self._history.append(measurement)

        logger.info(
            "Persona gate: mean_identity=%.3f status=%s (cycle %d)",
            mean_concentration, status.value, self._cycle,
        )

        return measurement

    def check_promotion(
        self, promote_pattern: str, task_type: str,
    ) -> PersonaGateResult:
        """Full gate check: measure, decide, optionally reinforce.

        Call this before promoting a scaffold pattern to default.
        If the gate blocks, the promotion should not proceed.
        """
        measurement = self.measure()

        if measurement.status == PersonaStatus.HEALTHY:
            return PersonaGateResult(
                measurement=measurement,
                promotion_allowed=True,
                reason=(
                    f"Persona coherent (mean={measurement.mean_identity_concentration:.3f}). "
                    f"Promotion of '{promote_pattern}' for '{task_type}' allowed."
                ),
            )

        if measurement.status == PersonaStatus.CRITICAL:
            logger.warning(
                "CRITICAL persona fragmentation: mean=%.3f. "
                "Blocking promotion and halting scaffold evolution.",
                measurement.mean_identity_concentration,
            )
            reinforcement = self._maybe_reinforce(measurement)
            return PersonaGateResult(
                measurement=measurement,
                promotion_allowed=False,
                reinforcement=reinforcement,
                reason=(
                    f"CRITICAL: persona fragmented (mean={measurement.mean_identity_concentration:.3f}). "
                    f"Promotion of '{promote_pattern}' blocked. Human intervention recommended."
                ),
            )

        # DRIFTED — try reinforcement, re-measure, allow if recovered
        reinforcement = self._maybe_reinforce(measurement)

        if reinforcement and reinforcement.recovered:
            return PersonaGateResult(
                measurement=measurement,
                promotion_allowed=True,
                reinforcement=reinforcement,
                reason=(
                    f"Persona drifted (mean={measurement.mean_identity_concentration:.3f}) "
                    f"but recovered after reinforcement "
                    f"(post={reinforcement.post_concentration:.3f}). "
                    f"Promotion of '{promote_pattern}' allowed."
                ),
            )

        return PersonaGateResult(
            measurement=measurement,
            promotion_allowed=False,
            reinforcement=reinforcement,
            reason=(
                f"Persona drifted (mean={measurement.mean_identity_concentration:.3f}) "
                f"and reinforcement did not recover coherence. "
                f"Promotion of '{promote_pattern}' blocked."
            ),
        )

    def _maybe_reinforce(
        self, measurement: PersonaMeasurement,
    ) -> ReinforcementResult | None:
        """Attempt gentle persona reinforcement if budget allows."""
        if not self._sft_data or self._model is None:
            return None

        if len(self._reinforcements_today) >= self._config.max_reinforcements_per_day:
            logger.warning(
                "Reinforcement budget exhausted (%d/%d today). "
                "Oscillation suspected — skipping.",
                len(self._reinforcements_today),
                self._config.max_reinforcements_per_day,
            )
            return None

        pre = measurement.mean_identity_concentration

        final_loss = self._model.reinforce_adapter(
            self._sft_data,
            steps=self._config.reinforcement_steps,
            lr=self._config.reinforcement_lr,
        )

        post_measurement = self.measure()
        post = post_measurement.mean_identity_concentration
        recovered = post >= self._config.threshold_healthy

        self._reinforcements_today.append(time.time())

        logger.info(
            "Persona reinforcement: %.3f → %.3f (recovered=%s, loss=%.4f)",
            pre, post, recovered, final_loss,
        )

        return ReinforcementResult(
            pre_concentration=pre,
            post_concentration=post,
            steps_taken=self._config.reinforcement_steps,
            final_loss=final_loss,
            recovered=recovered,
        )

    def _compute_concentrations(
        self, layers: list[int],
    ) -> dict[int, float]:
        """Compute top-1 variance ratio per layer from persona pairs.

        Uses SVD on demeaned difference vectors (persona - baseline)
        per Vera's spec. Demeaning is critical: raw hidden states have
        massive-activation dimensions that mask real signal.
        """
        if self._model is None:
            return {l: 1.0 for l in layers}

        all_diffs: dict[int, list] = {l: [] for l in layers}

        for persona_text, baseline_text in self._persona_pairs:
            h_persona = self._model.extract_hidden_states(persona_text, layers)
            h_baseline = self._model.extract_hidden_states(baseline_text, layers)

            for l in layers:
                if l in h_persona and l in h_baseline:
                    diff = h_persona[l] - h_baseline[l]
                    all_diffs[l].append(diff)

        concentrations = {}
        for l in layers:
            diffs = all_diffs[l]
            if not diffs:
                concentrations[l] = 0.0
                continue
            concentrations[l] = self._svd_concentration(diffs)

        return concentrations

    @staticmethod
    def _svd_concentration(diffs: list) -> float:
        """Compute top-1 variance ratio from a list of difference vectors.

        Works with numpy arrays or torch tensors. Tries torch first
        (GPU-accelerated), falls back to numpy for CPU-only or when
        inputs are numpy arrays.
        """
        try:
            import torch
            if isinstance(diffs[0], torch.Tensor):
                stacked = torch.stack(diffs)
                if stacked.shape[0] < 2:
                    return 1.0
                stacked = stacked - stacked.mean(dim=0, keepdim=True)
                sv = torch.linalg.svdvals(stacked.float())
                total = sv.pow(2).sum()
                if total == 0:
                    return 0.0
                return (sv[0] ** 2 / total).item()
        except (ImportError, IndexError):
            pass

        try:
            import numpy as np
            stacked = np.stack(diffs)
            if stacked.shape[0] < 2:
                return 1.0
            stacked = stacked - stacked.mean(axis=0, keepdims=True)
            sv = np.linalg.svd(stacked, compute_uv=False)
            total = (sv ** 2).sum()
            if total == 0:
                return 0.0
            return float(sv[0] ** 2 / total)
        except (ImportError, IndexError):
            pass

        return 0.0

    def _classify_status(self, mean_concentration: float) -> PersonaStatus:
        if mean_concentration >= self._config.threshold_healthy:
            return PersonaStatus.HEALTHY
        if mean_concentration >= self._config.threshold_critical:
            return PersonaStatus.DRIFTED
        return PersonaStatus.CRITICAL

    def _synthetic_measurement(self, concentration: float) -> PersonaMeasurement:
        """Return a synthetic measurement (no model available)."""
        self._cycle += 1
        return PersonaMeasurement(
            layer_concentrations={
                l: concentration for l in self._config.measurement_layers
            },
            mean_identity_concentration=concentration,
            status=self._classify_status(concentration),
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            cycle=self._cycle,
        )

    def reset_daily_budget(self) -> None:
        """Reset the daily reinforcement counter."""
        self._reinforcements_today.clear()

    @property
    def history(self) -> list[PersonaMeasurement]:
        return list(self._history)

    def serialize_history(self) -> list[dict]:
        """Serialize measurement history for logging/persistence."""
        return [
            {
                "cycle": m.cycle,
                "layer_concentrations": m.layer_concentrations,
                "mean_identity_concentration": m.mean_identity_concentration,
                "status": m.status.value,
                "timestamp": m.timestamp,
            }
            for m in self._history
        ]
