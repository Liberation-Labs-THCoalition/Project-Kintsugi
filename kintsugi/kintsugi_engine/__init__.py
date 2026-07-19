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
from kintsugi.kintsugi_engine.scaffold_generator import (
    ScaffoldGenerator,
    ScaffoldMemory,
    ScaffoldProposal,
)
from kintsugi.kintsugi_engine.scaffold_comparator import (
    ScaffoldComparator,
    ScaffoldComparison,
    ScaffoldMetrics,
    run_scaffold_comparison,
)
from kintsugi.kintsugi_engine.scaffold_memory import (
    InMemoryScaffoldKG,
    ScaffoldRecord,
)
from kintsugi.kintsugi_engine.scaffold_exploration import (
    ExplorationDecision,
    ExplorationResult,
    ScaffoldExplorer,
)
from kintsugi.kintsugi_engine.scaffold_orchestrator import (
    ScaffoldExecutionResult,
    ScaffoldOrchestrator,
    ScaffoldOrchestratorConfig,
)
from kintsugi.kintsugi_engine.persona_gate import (
    PersonaGate,
    PersonaGateConfig,
    PersonaGateResult,
    PersonaMeasurement,
    PersonaStatus,
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
    # Adaptive scaffold evolution
    "ScaffoldGenerator",
    "ScaffoldMemory",
    "ScaffoldProposal",
    "ScaffoldComparator",
    "ScaffoldComparison",
    "ScaffoldMetrics",
    "run_scaffold_comparison",
    "InMemoryScaffoldKG",
    "ScaffoldRecord",
    "ExplorationDecision",
    "ExplorationResult",
    "ScaffoldExplorer",
    "ScaffoldExecutionResult",
    "ScaffoldOrchestrator",
    "ScaffoldOrchestratorConfig",
    # Persona coherence gate (OGPSA)
    "PersonaGate",
    "PersonaGateConfig",
    "PersonaGateResult",
    "PersonaMeasurement",
    "PersonaStatus",
]
