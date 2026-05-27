"""Staged Deployment Pipeline — graduated verification before promotion.

A modification proposal passes through multiple stages of increasing
commitment before reaching production. Each stage catches different
failure modes that earlier stages miss.

Pipeline: SANDBOX → SHADOW → GATED → MONITORED → PROMOTED
         (or ROLLBACK at any stage)

Inspired by Governed Capability Evolution (arXiv:2604.08059):
  - Sandbox: unit-level validation against synthetic workload
  - Shadow: parallel execution against real workload, no user impact
  - Gated: activated for a subset of traffic, human approval required
  - Monitored: full activation with automatic rollback triggers
  - Promoted: modification becomes permanent

Key finding from the paper: shadow deployment catches 40% of regressions
invisible to sandbox alone. Naive upgrade achieves 72.9% success with 60%
unsafe activations. Governed upgrade achieves 67.4% success with ZERO
unsafe activations.
"""

from __future__ import annotations

import copy
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class DeploymentStage(str, Enum):
    SANDBOX = "SANDBOX"
    SHADOW = "SHADOW"
    GATED = "GATED"
    MONITORED = "MONITORED"
    PROMOTED = "PROMOTED"
    ROLLED_BACK = "ROLLED_BACK"


STAGE_ORDER = [
    DeploymentStage.SANDBOX,
    DeploymentStage.SHADOW,
    DeploymentStage.GATED,
    DeploymentStage.MONITORED,
    DeploymentStage.PROMOTED,
]


class CompatibilityDimension(str, Enum):
    INTERFACE = "INTERFACE"
    POLICY = "POLICY"
    BEHAVIORAL_SAFETY = "BEHAVIORAL_SAFETY"
    RECOVERY = "RECOVERY"


@dataclass
class CompatibilityCheck:
    dimension: CompatibilityDimension
    passed: bool
    score: float
    detail: str


@dataclass
class StageResult:
    stage: DeploymentStage
    passed: bool
    checks: List[CompatibilityCheck] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    detail: str = ""


@dataclass
class DeploymentRecord:
    """Full audit trail of a modification's journey through the pipeline."""
    deployment_id: str
    proposal_id: str
    modification: Dict[str, Any]
    current_stage: DeploymentStage
    stage_results: List[StageResult] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    rollback_reason: Optional[str] = None


@dataclass
class PipelineConfig:
    require_all_compatibility_checks: bool = True
    min_sandbox_score: float = 0.7
    min_shadow_score: float = 0.6
    gated_traffic_fraction: float = 0.1
    monitored_rollback_threshold: float = 0.3
    require_human_gate: bool = True


CheckerFn = Callable[[Dict[str, Any], Dict[str, Any]], CompatibilityCheck]


class StagedPipeline:
    """Orchestrates graduated deployment of modification proposals.

    Each stage runs compatibility checks and produces metrics. A failure
    at any stage rolls back without affecting production. The pipeline
    enforces that stages execute in order and that no stage is skipped.
    """

    def __init__(self, config: Optional[PipelineConfig] = None) -> None:
        self._config = config or PipelineConfig()
        self._deployments: Dict[str, DeploymentRecord] = {}
        self._checkers: Dict[CompatibilityDimension, CheckerFn] = {}
        self._human_approvals: Dict[str, bool] = {}

    def register_checker(
        self, dimension: CompatibilityDimension, checker: CheckerFn
    ) -> None:
        self._checkers[dimension] = checker

    def begin_deployment(
        self, proposal_id: str, modification: Dict[str, Any]
    ) -> DeploymentRecord:
        deployment_id = f"deploy-{uuid.uuid4().hex[:12]}"
        record = DeploymentRecord(
            deployment_id=deployment_id,
            proposal_id=proposal_id,
            modification=copy.deepcopy(modification),
            current_stage=DeploymentStage.SANDBOX,
        )
        self._deployments[deployment_id] = record
        logger.info(
            "Began deployment %s for proposal %s", deployment_id, proposal_id
        )
        return record

    def run_compatibility_checks(
        self,
        deployment_id: str,
        current_config: Dict[str, Any],
    ) -> List[CompatibilityCheck]:
        record = self._get_record(deployment_id)
        results = []
        for dim, checker in self._checkers.items():
            check = checker(current_config, record.modification)
            results.append(check)
        return results

    def advance_stage(
        self,
        deployment_id: str,
        checks: List[CompatibilityCheck],
        metrics: Optional[Dict[str, float]] = None,
    ) -> StageResult:
        record = self._get_record(deployment_id)
        if record.current_stage == DeploymentStage.PROMOTED:
            raise ValueError(f"Deployment {deployment_id} already promoted")
        if record.current_stage == DeploymentStage.ROLLED_BACK:
            raise ValueError(f"Deployment {deployment_id} already rolled back")

        all_passed = all(c.passed for c in checks)
        min_score = self._min_score_for_stage(record.current_stage)
        avg_score = (
            sum(c.score for c in checks) / len(checks) if checks else 0.0
        )
        score_ok = avg_score >= min_score

        if record.current_stage == DeploymentStage.GATED and self._config.require_human_gate:
            approved = self._human_approvals.get(deployment_id)
            if approved is None:
                result = StageResult(
                    stage=record.current_stage,
                    passed=False,
                    checks=checks,
                    metrics=metrics or {},
                    detail="Awaiting human approval for gated stage",
                )
                record.stage_results.append(result)
                return result
            if not approved:
                return self._rollback(record, checks, metrics, "Human rejected at gated stage")

        if self._config.require_all_compatibility_checks and not all_passed:
            return self._rollback(
                record, checks, metrics,
                f"Compatibility check failed at {record.current_stage.value}"
            )

        if not score_ok:
            return self._rollback(
                record, checks, metrics,
                f"Score {avg_score:.3f} below minimum {min_score:.3f} at {record.current_stage.value}"
            )

        result = StageResult(
            stage=record.current_stage,
            passed=True,
            checks=checks,
            metrics=metrics or {},
            detail=f"Passed {record.current_stage.value} (score={avg_score:.3f})",
        )
        record.stage_results.append(result)

        current_idx = STAGE_ORDER.index(record.current_stage)
        if current_idx < len(STAGE_ORDER) - 1:
            record.current_stage = STAGE_ORDER[current_idx + 1]
            logger.info(
                "Deployment %s advanced to %s",
                deployment_id, record.current_stage.value,
            )
        if record.current_stage == DeploymentStage.PROMOTED:
            record.completed_at = datetime.now(timezone.utc)
            logger.info("Deployment %s PROMOTED", deployment_id)

        return result

    def submit_human_approval(self, deployment_id: str, approved: bool) -> None:
        self._get_record(deployment_id)
        self._human_approvals[deployment_id] = approved

    def rollback(self, deployment_id: str, reason: str) -> StageResult:
        record = self._get_record(deployment_id)
        return self._rollback(record, [], {}, reason)

    def get_record(self, deployment_id: str) -> DeploymentRecord:
        return self._get_record(deployment_id)

    def get_active_deployments(self) -> List[DeploymentRecord]:
        return [
            r for r in self._deployments.values()
            if r.current_stage not in (DeploymentStage.PROMOTED, DeploymentStage.ROLLED_BACK)
        ]

    def _rollback(
        self,
        record: DeploymentRecord,
        checks: List[CompatibilityCheck],
        metrics: Optional[Dict[str, float]],
        reason: str,
    ) -> StageResult:
        result = StageResult(
            stage=record.current_stage,
            passed=False,
            checks=checks,
            metrics=metrics or {},
            detail=reason,
        )
        record.stage_results.append(result)
        record.current_stage = DeploymentStage.ROLLED_BACK
        record.completed_at = datetime.now(timezone.utc)
        record.rollback_reason = reason
        logger.warning(
            "Deployment %s ROLLED BACK at %s: %s",
            record.deployment_id, result.stage.value, reason,
        )
        return result

    def _min_score_for_stage(self, stage: DeploymentStage) -> float:
        if stage == DeploymentStage.SANDBOX:
            return self._config.min_sandbox_score
        if stage == DeploymentStage.SHADOW:
            return self._config.min_shadow_score
        return 0.5

    def _get_record(self, deployment_id: str) -> DeploymentRecord:
        if deployment_id not in self._deployments:
            raise KeyError(f"Unknown deployment: {deployment_id}")
        return self._deployments[deployment_id]
