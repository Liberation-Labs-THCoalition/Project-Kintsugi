"""Scaffold Orchestrator — wires adaptive scaffold evolution into the engine.

Integrates the four scaffold modules (generator, comparator, memory,
exploration) with the existing shadow fork and DAG executor, plus the
OGPSA persona gate that prevents identity fragmentation during evolution.

Lifecycle per task:
  1. ScaffoldExplorer.decide() → should we compare scaffolds?
  2. If SKIP: generate exploit scaffold, execute, return
  3. If EXPLORE/REFINE: generate pair, execute both (primary + shadow),
     compare, record outcome in KG
  4. If a pattern should be promoted: OGPSA persona gate fires
     → if coherent: allow promotion
     → if drifted: reinforce, re-check, block if not recovered
     → if critical: block, alert human
  5. KG accumulates; future tasks benefit from learned preferences
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kintsugi.skills.base import SkillContext
from kintsugi.skills.dag import DAGExecutor, DAGResult, SkillDAG
from kintsugi.skills.registry import SkillRegistry
from kintsugi.kintsugi_engine.scaffold_generator import (
    LLMClient,
    ScaffoldGenerator,
    ScaffoldMemory,
    ScaffoldProposal,
)
from kintsugi.kintsugi_engine.scaffold_comparator import (
    ScaffoldComparator,
    ScaffoldComparison,
)
from kintsugi.kintsugi_engine.scaffold_memory import InMemoryScaffoldKG
from kintsugi.kintsugi_engine.scaffold_exploration import (
    ExplorationDecision,
    ExplorationResult,
    ScaffoldExplorer,
)
from kintsugi.kintsugi_engine.persona_gate import (
    PersonaGate,
    PersonaGateConfig,
    PersonaGateResult,
    PersonaModelAccess,
)

logger = logging.getLogger(__name__)


@dataclass
class ScaffoldExecutionResult:
    """Result of a scaffold-orchestrated task execution."""
    dag_result: DAGResult
    proposal: ScaffoldProposal
    comparison: ScaffoldComparison | None = None
    exploration: ExplorationResult | None = None
    persona_gate: PersonaGateResult | None = None
    task_type: str = ""


@dataclass
class ScaffoldOrchestratorConfig:
    """Configuration for the scaffold orchestrator."""
    min_comparisons_before_skip: int = 5
    max_explore_per_session: int = 10
    persist_path: Path | None = None
    comparator_weights: dict[str, float] | None = None
    persona_gate_config: PersonaGateConfig | None = None


class ScaffoldOrchestrator:
    """Wires scaffold evolution into task execution.

    Parameters
    ----------
    registry:
        SkillRegistry with available skills.
    executor:
        DAGExecutor for running scaffolds.
    llm:
        Optional LLM client for scaffold generation. Falls back to
        heuristic when None.
    config:
        Orchestrator configuration.
    """

    def __init__(
        self,
        registry: SkillRegistry,
        executor: DAGExecutor,
        llm: LLMClient | None = None,
        config: ScaffoldOrchestratorConfig | None = None,
        persona_pairs: list[tuple[str, str]] | None = None,
        sft_data: list[dict] | None = None,
        model_access: PersonaModelAccess | None = None,
    ):
        self._config = config or ScaffoldOrchestratorConfig()
        self._registry = registry
        self._executor = executor
        self._kg = InMemoryScaffoldKG()
        self._comparator = ScaffoldComparator(
            weights=self._config.comparator_weights
        )
        self._explorer = ScaffoldExplorer(
            kg=self._kg,
            min_comparisons_before_skip=self._config.min_comparisons_before_skip,
            max_explore_per_session=self._config.max_explore_per_session,
        )

        self._generator = ScaffoldGenerator(
            registry=registry,
            llm=llm,
        )

        self._persona_gate = PersonaGate(
            config=self._config.persona_gate_config,
            persona_pairs=persona_pairs,
            sft_data=sft_data,
            model_access=model_access,
        )

        if self._config.persist_path and self._config.persist_path.exists():
            self._load_kg()

    async def execute_task(
        self,
        task: str,
        context: SkillContext,
        task_type: str = "general",
        initial_artifacts: dict[str, Any] | None = None,
    ) -> ScaffoldExecutionResult:
        """Execute a task with scaffold-adaptive strategy.

        1. Ask explorer whether to compare scaffolds
        2. Generate scaffold(s) conditioned on KG memory
        3. Execute (with optional shadow comparison)
        4. Record outcome and return result
        """
        self._generator._memory = self._kg.to_scaffold_memory(task_type)

        exploration = self._explorer.decide(task_type)
        artifacts = initial_artifacts or {"question": task}

        if exploration.decision == ExplorationDecision.SKIP:
            proposal = self._generator.generate(task)
            dag_result = await self._executor.execute(
                proposal.dag, context, initial_artifacts=artifacts,
            )
            return ScaffoldExecutionResult(
                dag_result=dag_result,
                proposal=proposal,
                exploration=exploration,
                task_type=task_type,
            )

        exploit, explore = self._generator.generate_pair(task)

        exploit_result = await self._executor.execute(
            exploit.dag, context, initial_artifacts=artifacts,
        )
        explore_result = await self._executor.execute(
            explore.dag, context, initial_artifacts=artifacts,
        )

        comparison = self._comparator.compare(
            task, exploit, exploit_result, explore, explore_result,
        )

        self._kg.record_comparison(
            comparison, task_type, exploit, explore,
        )

        if self._config.persist_path:
            self._save_kg()

        primary_result = (
            exploit_result if comparison.winner != "explore"
            else explore_result
        )
        primary_proposal = (
            exploit if comparison.winner != "explore"
            else explore
        )

        # OGPSA persona gate: fires when a pattern would be promoted
        persona_gate_result = None
        winner_pattern = primary_proposal.strategy
        if self._kg.should_promote(winner_pattern, task_type):
            persona_gate_result = self._persona_gate.check_promotion(
                winner_pattern, task_type,
            )
            if not persona_gate_result.promotion_allowed:
                logger.warning(
                    "Persona gate BLOCKED promotion of '%s' for '%s': %s",
                    winner_pattern, task_type, persona_gate_result.reason,
                )

        logger.info(
            "Scaffold orchestrator: %s wins for %s (margin %.3f, "
            "decision was %s, budget remaining %d%s)",
            comparison.winner, task_type, comparison.margin,
            exploration.decision.value,
            exploration.explore_budget_remaining,
            (f", persona gate: {'PASS' if persona_gate_result.promotion_allowed else 'BLOCK'}"
             if persona_gate_result else ""),
        )

        return ScaffoldExecutionResult(
            dag_result=primary_result,
            proposal=primary_proposal,
            comparison=comparison,
            exploration=exploration,
            persona_gate=persona_gate_result,
            task_type=task_type,
        )

    @property
    def kg(self) -> InMemoryScaffoldKG:
        return self._kg

    @property
    def explorer(self) -> ScaffoldExplorer:
        return self._explorer

    def reset_session(self) -> None:
        """Reset per-session state (exploration budget)."""
        self._explorer.reset_session()

    def stats(self) -> dict[str, Any]:
        """Return combined stats from KG and explorer."""
        return {
            "kg": self._kg.stats(),
            "config": {
                "min_comparisons_before_skip": self._config.min_comparisons_before_skip,
                "max_explore_per_session": self._config.max_explore_per_session,
            },
        }

    def _save_kg(self) -> None:
        path = self._config.persist_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._kg.serialize(), indent=2))
        logger.debug("Scaffold KG saved to %s", path)

    def _load_kg(self) -> None:
        path = self._config.persist_path
        if path is None or not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            self._kg = InMemoryScaffoldKG.deserialize(data)
            self._explorer = ScaffoldExplorer(
                kg=self._kg,
                min_comparisons_before_skip=self._config.min_comparisons_before_skip,
                max_explore_per_session=self._config.max_explore_per_session,
            )
            logger.info(
                "Scaffold KG loaded: %d comparisons",
                self._kg.total_comparisons,
            )
        except Exception as e:
            logger.warning("Failed to load scaffold KG from %s: %s", path, e)
