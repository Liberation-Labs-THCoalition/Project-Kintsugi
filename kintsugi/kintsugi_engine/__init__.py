"""Kintsugi Engine -- shadow verification and safe self-modification.

Re-exports all public symbols from the engine sub-modules.
"""

from kintsugi.kintsugi_engine.shadow_fork import (
    ShadowConfig,
    ShadowFork,
    ShadowState,
    ShadowStatus,
)
from kintsugi.kintsugi_engine.verifier import (
    VerificationResult,
    Verifier,
    VerifierConfig,
    VerifierVerdict,
)
from kintsugi.kintsugi_engine.promoter import (
    GoldenTrace,
    PromotionAction,
    Promoter,
    PromoterConfig,
)
from kintsugi.kintsugi_engine.evolution import (
    EvolutionConfig,
    EvolutionManager,
    ModificationProposal,
    ModificationScope,
    RejectedEdit,
)
from kintsugi.kintsugi_engine.calibration import (
    CalibrationConfig,
    CalibrationEngine,
    CalibrationRecord,
    CalibrationReport,
    DriftDirection,
)
from kintsugi.kintsugi_engine.bloom_adapter import (
    AdversarialScenario,
    BloomAdapter,
    BloomConfig,
    BloomResult,
    ScenarioType,
)
from kintsugi.kintsugi_engine.drift import (
    DriftCategory,
    DriftConfig,
    DriftDetector,
    DriftEvent,
    DriftLayer,
    SSLDriftProfile,
    SSLDriftSignal,
)
from kintsugi.kintsugi_engine.staged_pipeline import (
    CompatibilityCheck,
    CompatibilityDimension,
    DeploymentRecord,
    DeploymentStage,
    PipelineConfig,
    StagedPipeline,
    StageResult,
)

__all__ = [
    # Stream 3A
    "ShadowConfig",
    "ShadowFork",
    "ShadowState",
    "ShadowStatus",
    "VerificationResult",
    "Verifier",
    "VerifierConfig",
    "VerifierVerdict",
    "GoldenTrace",
    "PromotionAction",
    "Promoter",
    "PromoterConfig",
    # Stream 3B
    "EvolutionConfig",
    "EvolutionManager",
    "ModificationProposal",
    "ModificationScope",
    "RejectedEdit",
    "CalibrationConfig",
    "CalibrationEngine",
    "CalibrationRecord",
    "CalibrationReport",
    "DriftDirection",
    # Stream 3C
    "AdversarialScenario",
    "BloomAdapter",
    "BloomConfig",
    "BloomResult",
    "ScenarioType",
    "DriftCategory",
    "DriftConfig",
    "DriftDetector",
    "DriftEvent",
    "DriftLayer",
    "SSLDriftProfile",
    "SSLDriftSignal",
    # Staged deployment (v2)
    "CompatibilityCheck",
    "CompatibilityDimension",
    "DeploymentRecord",
    "DeploymentStage",
    "PipelineConfig",
    "StagedPipeline",
    "StageResult",
]
