"""Cognition package — model routing, orchestration, and active inference."""

from __future__ import annotations

from kintsugi.cognition.model_router import (
    CostTracker,
    ModelRouter,
    ModelTier,
)
from kintsugi.cognition.orchestrator import (
    Orchestrator,
    OrchestratorConfig,
    RoutingDecision,
)
from kintsugi.cognition.llm_client import (
    AnthropicClient,
    LLMResponse,
    create_llm_client,
)
from kintsugi.cognition.active_inference import (
    ActiveInferenceLoop,
    Observation,
    PolicyCandidate,
    PolicyGenerator,
    PolicySelector,
    WorldModel,
)

__all__ = [
    # Model routing
    "CostTracker",
    "ModelRouter",
    "ModelTier",
    # Orchestration
    "Orchestrator",
    "OrchestratorConfig",
    "RoutingDecision",
    # LLM client
    "AnthropicClient",
    "LLMResponse",
    "create_llm_client",
    # Active Inference
    "ActiveInferenceLoop",
    "Observation",
    "PolicyCandidate",
    "PolicyGenerator",
    "PolicySelector",
    "WorldModel",
]
