"""Enhanced Orchestrator — wires tree discovery, DAG composition, and Active Inference
into the existing routing pipeline.

Wraps the base Orchestrator with v2 capabilities:
1. CapabilityTree for O(log n) skill discovery (replaces flat keyword matching)
2. DAG composition for multi-step tasks (replaces single-skill routing)
3. ActiveInferenceLoop for BDI-driven decision-making

Backward compatible — if none of the v2 components are provided,
falls back to the base orchestrator's keyword routing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from kintsugi.cognition.orchestrator import Orchestrator, OrchestratorConfig, RoutingDecision
from kintsugi.skills.registry import SkillRegistry, get_registry
from kintsugi.skills.capability_tree import CapabilityTree
from kintsugi.skills.dag import SkillDAG, DAGBuilder, DAGExecutor, DAGResult
from kintsugi.skills.base import SkillContext, SkillRequest

logger = logging.getLogger(__name__)


@dataclass
class EnhancedDecision:
    """Extended routing decision with DAG composition support."""
    routing: RoutingDecision
    dag: Optional[SkillDAG] = None
    skill_names: list[str] = None
    is_composed: bool = False
    tree_path: list[str] = None

    @property
    def skill_domain(self) -> str:
        return self.routing.skill_domain

    @property
    def confidence(self) -> float:
        return self.routing.confidence


MULTI_STEP_KEYWORDS = [
    "and then", "after that", "first", "next", "finally",
    "steps", "process", "workflow", "pipeline", "sequence",
    "apply for", "sign up", "onboard", "enroll",
]


class EnhancedOrchestrator:
    """Orchestrator with tree discovery, DAG composition, and Active Inference.

    Usage:
        registry = get_registry()
        tree = CapabilityTree(registry)
        tree.build_from_registry()

        orch = EnhancedOrchestrator(
            registry=registry,
            tree=tree,
            dag_executor=DAGExecutor(registry),
        )

        decision = await orch.route(message, org_id)
        if decision.is_composed:
            result = await orch.execute_dag(decision.dag, context)
        else:
            chip = registry.get(decision.skill_names[0])
            response = await chip.handle(request, context)
    """

    def __init__(
        self,
        registry: SkillRegistry = None,
        tree: CapabilityTree = None,
        dag_executor: DAGExecutor = None,
        base_orchestrator: Orchestrator = None,
        config: OrchestratorConfig = None,
    ):
        self._registry = registry or get_registry()
        self._tree = tree
        self._dag_executor = dag_executor or DAGExecutor(self._registry)
        self._base = base_orchestrator or Orchestrator(config=config or OrchestratorConfig())

    async def route(
        self,
        message: str,
        org_id: str,
        context: dict[str, Any] = None,
        desires: list[dict] = None,
        beliefs: list[dict] = None,
    ) -> EnhancedDecision:
        """Route a request using tree discovery + DAG composition."""

        base_decision = await self._base.route(message, org_id, context)

        skill_names = []
        tree_path = []

        if self._tree and self._tree.root:
            retrieval = self._tree.retrieve(
                desires=desires or [],
                beliefs=beliefs or [],
                max_results=5,
            )
            if retrieval.skill_names:
                skill_names = retrieval.skill_names
                tree_path = retrieval.path
                logger.info("Tree retrieval: %d candidates via path %s",
                           len(skill_names), [p.split("/")[-1] for p in tree_path[:3]])

        if not skill_names:
            domain_chips = self._registry.get_by_domain(
                self._domain_to_enum(base_decision.skill_domain))
            skill_names = [c.name for c in domain_chips] if domain_chips else []

        is_multi_step = self._detect_multi_step(message)

        dag = None
        if is_multi_step and len(skill_names) >= 2:
            dag = DAGBuilder.from_skill_sequence(
                skill_names[:4],
                self._registry,
            )
            logger.info("Composed DAG: %d nodes for multi-step request", len(dag.nodes))

        return EnhancedDecision(
            routing=base_decision,
            dag=dag,
            skill_names=skill_names,
            is_composed=dag is not None,
            tree_path=tree_path,
        )

    async def execute_dag(
        self,
        dag: SkillDAG,
        context: SkillContext,
        initial_artifacts: dict = None,
    ) -> DAGResult:
        """Execute a composed DAG."""
        return await self._dag_executor.execute(dag, context, initial_artifacts)

    def _detect_multi_step(self, message: str) -> bool:
        """Detect if a request needs multi-step composition."""
        msg_lower = message.lower()
        return any(kw in msg_lower for kw in MULTI_STEP_KEYWORDS)

    def _domain_to_enum(self, domain_str: str):
        """Convert domain string to SkillDomain enum."""
        from kintsugi.skills.base import SkillDomain
        mapping = {
            "grants": SkillDomain.FUNDRAISING,
            "finance": SkillDomain.FINANCE,
            "communications": SkillDomain.COMMUNICATIONS,
            "volunteers": SkillDomain.COMMUNITY,
            "impact": SkillDomain.OPERATIONS,
            "mutual_aid": SkillDomain.MUTUAL_AID,
            "general": SkillDomain.OPERATIONS,
        }
        return mapping.get(domain_str, SkillDomain.OPERATIONS)

    @property
    def base(self) -> Orchestrator:
        return self._base

    @property
    def tree(self) -> Optional[CapabilityTree]:
        return self._tree
