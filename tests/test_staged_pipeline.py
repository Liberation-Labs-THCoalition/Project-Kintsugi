"""Tests for kintsugi.kintsugi_engine.staged_pipeline."""

import pytest

from kintsugi.kintsugi_engine.staged_pipeline import (
    CompatibilityCheck,
    CompatibilityDimension,
    DeploymentRecord,
    DeploymentStage,
    PipelineConfig,
    STAGE_ORDER,
    StagedPipeline,
    StageResult,
)


def _pass_check(dim: CompatibilityDimension, score: float = 0.9) -> CompatibilityCheck:
    return CompatibilityCheck(dimension=dim, passed=True, score=score, detail="ok")


def _fail_check(dim: CompatibilityDimension, score: float = 0.2) -> CompatibilityCheck:
    return CompatibilityCheck(dimension=dim, passed=False, score=score, detail="failed")


def _make_checker(passed: bool, score: float = 0.9):
    def checker(current_config, modification):
        return CompatibilityCheck(
            dimension=CompatibilityDimension.INTERFACE,
            passed=passed, score=score, detail="auto"
        )
    return checker


class TestDeploymentStages:
    def test_stage_order(self):
        assert STAGE_ORDER[0] == DeploymentStage.SANDBOX
        assert STAGE_ORDER[-1] == DeploymentStage.PROMOTED
        assert len(STAGE_ORDER) == 5

    def test_all_stages_in_order(self):
        assert STAGE_ORDER == [
            DeploymentStage.SANDBOX,
            DeploymentStage.SHADOW,
            DeploymentStage.GATED,
            DeploymentStage.MONITORED,
            DeploymentStage.PROMOTED,
        ]


class TestStagedPipeline:
    def _pipeline(self, **kwargs) -> StagedPipeline:
        return StagedPipeline(PipelineConfig(require_human_gate=False, **kwargs))

    def test_begin_deployment(self):
        p = self._pipeline()
        rec = p.begin_deployment("prop-1", {"key": "val"})
        assert rec.current_stage == DeploymentStage.SANDBOX
        assert rec.proposal_id == "prop-1"
        assert rec.modification == {"key": "val"}

    def test_full_promotion_happy_path(self):
        p = self._pipeline()
        rec = p.begin_deployment("prop-1", {"k": 1})
        checks = [_pass_check(CompatibilityDimension.INTERFACE)]

        for expected_stage in [DeploymentStage.SANDBOX, DeploymentStage.SHADOW,
                               DeploymentStage.GATED, DeploymentStage.MONITORED]:
            result = p.advance_stage(rec.deployment_id, checks)
            assert result.passed
            assert result.stage == expected_stage

        assert rec.current_stage == DeploymentStage.PROMOTED
        assert rec.completed_at is not None

    def test_rollback_on_failed_check(self):
        p = self._pipeline()
        rec = p.begin_deployment("prop-1", {"k": 1})
        checks = [_fail_check(CompatibilityDimension.BEHAVIORAL_SAFETY)]
        result = p.advance_stage(rec.deployment_id, checks)
        assert not result.passed
        assert rec.current_stage == DeploymentStage.ROLLED_BACK
        assert "Compatibility check failed" in rec.rollback_reason

    def test_rollback_on_low_score(self):
        p = self._pipeline(min_sandbox_score=0.8)
        rec = p.begin_deployment("prop-1", {"k": 1})
        checks = [_pass_check(CompatibilityDimension.INTERFACE, score=0.5)]
        result = p.advance_stage(rec.deployment_id, checks)
        assert not result.passed
        assert rec.current_stage == DeploymentStage.ROLLED_BACK
        assert "below minimum" in rec.rollback_reason

    def test_cannot_advance_after_promotion(self):
        p = self._pipeline()
        rec = p.begin_deployment("prop-1", {"k": 1})
        checks = [_pass_check(CompatibilityDimension.INTERFACE)]
        for _ in range(4):
            p.advance_stage(rec.deployment_id, checks)
        with pytest.raises(ValueError, match="already promoted"):
            p.advance_stage(rec.deployment_id, checks)

    def test_cannot_advance_after_rollback(self):
        p = self._pipeline()
        rec = p.begin_deployment("prop-1", {"k": 1})
        p.rollback(rec.deployment_id, "manual")
        with pytest.raises(ValueError, match="already rolled back"):
            p.advance_stage(rec.deployment_id, [_pass_check(CompatibilityDimension.INTERFACE)])

    def test_manual_rollback(self):
        p = self._pipeline()
        rec = p.begin_deployment("prop-1", {"k": 1})
        result = p.rollback(rec.deployment_id, "operator decision")
        assert not result.passed
        assert rec.current_stage == DeploymentStage.ROLLED_BACK
        assert rec.rollback_reason == "operator decision"

    def test_stage_results_accumulate(self):
        p = self._pipeline()
        rec = p.begin_deployment("prop-1", {"k": 1})
        checks = [_pass_check(CompatibilityDimension.INTERFACE)]
        p.advance_stage(rec.deployment_id, checks)
        p.advance_stage(rec.deployment_id, checks)
        assert len(rec.stage_results) == 2
        assert rec.stage_results[0].stage == DeploymentStage.SANDBOX
        assert rec.stage_results[1].stage == DeploymentStage.SHADOW

    def test_metrics_preserved(self):
        p = self._pipeline()
        rec = p.begin_deployment("prop-1", {"k": 1})
        checks = [_pass_check(CompatibilityDimension.INTERFACE)]
        p.advance_stage(rec.deployment_id, checks, metrics={"latency": 0.5})
        assert rec.stage_results[0].metrics == {"latency": 0.5}

    def test_get_active_deployments(self):
        p = self._pipeline()
        rec1 = p.begin_deployment("prop-1", {"k": 1})
        rec2 = p.begin_deployment("prop-2", {"k": 2})
        assert len(p.get_active_deployments()) == 2
        p.rollback(rec1.deployment_id, "abort")
        assert len(p.get_active_deployments()) == 1

    def test_unknown_deployment_raises(self):
        p = self._pipeline()
        with pytest.raises(KeyError, match="Unknown deployment"):
            p.advance_stage("nonexistent", [])


class TestHumanGate:
    def test_gated_stage_blocks_without_approval(self):
        p = StagedPipeline(PipelineConfig(require_human_gate=True))
        rec = p.begin_deployment("prop-1", {"k": 1})
        checks = [_pass_check(CompatibilityDimension.INTERFACE)]
        p.advance_stage(rec.deployment_id, checks)  # sandbox → shadow
        p.advance_stage(rec.deployment_id, checks)  # shadow → gated
        result = p.advance_stage(rec.deployment_id, checks)  # gated: no approval
        assert not result.passed
        assert "Awaiting human approval" in result.detail
        assert rec.current_stage == DeploymentStage.GATED

    def test_gated_stage_proceeds_with_approval(self):
        p = StagedPipeline(PipelineConfig(require_human_gate=True))
        rec = p.begin_deployment("prop-1", {"k": 1})
        checks = [_pass_check(CompatibilityDimension.INTERFACE)]
        p.advance_stage(rec.deployment_id, checks)  # sandbox
        p.advance_stage(rec.deployment_id, checks)  # shadow
        p.submit_human_approval(rec.deployment_id, True)
        result = p.advance_stage(rec.deployment_id, checks)  # gated
        assert result.passed
        assert rec.current_stage == DeploymentStage.MONITORED

    def test_gated_stage_rollback_on_rejection(self):
        p = StagedPipeline(PipelineConfig(require_human_gate=True))
        rec = p.begin_deployment("prop-1", {"k": 1})
        checks = [_pass_check(CompatibilityDimension.INTERFACE)]
        p.advance_stage(rec.deployment_id, checks)
        p.advance_stage(rec.deployment_id, checks)
        p.submit_human_approval(rec.deployment_id, False)
        result = p.advance_stage(rec.deployment_id, checks)
        assert not result.passed
        assert rec.current_stage == DeploymentStage.ROLLED_BACK


class TestCompatibilityCheckers:
    def test_register_and_run_checker(self):
        p = StagedPipeline()
        p.register_checker(
            CompatibilityDimension.INTERFACE,
            _make_checker(True, 0.95)
        )
        rec = p.begin_deployment("prop-1", {"k": 1})
        checks = p.run_compatibility_checks(rec.deployment_id, {"existing": True})
        assert len(checks) == 1
        assert checks[0].passed
        assert checks[0].score == 0.95

    def test_multiple_checkers(self):
        p = StagedPipeline()
        for dim in CompatibilityDimension:
            p.register_checker(dim, _make_checker(True, 0.8))
        rec = p.begin_deployment("prop-1", {"k": 1})
        checks = p.run_compatibility_checks(rec.deployment_id, {})
        assert len(checks) == len(CompatibilityDimension)
