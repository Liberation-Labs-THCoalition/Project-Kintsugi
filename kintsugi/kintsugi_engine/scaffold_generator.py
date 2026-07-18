"""Adaptive Scaffold Generator — LLM-authored SkillDAGs.

Instead of selecting pre-built DAGs, the scaffold generator asks an LLM
to write a task-specific DAG conditioned on:
  1. The task description
  2. Available skills (from SkillRegistry)
  3. Past scaffold outcomes (from KG memory, when available)
  4. EFE explore/exploit signal

The output is a valid SkillDAG that the existing DAGExecutor can run.

Phase 1: basic generation (this file)
Phase 2: shadow comparison (extend ShadowFork)
Phase 3: KG-based learning (scaffold memory)
Phase 4: EFE-driven exploration
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from kintsugi.skills.dag import DAGNode, SkillDAG
from kintsugi.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    """Protocol for any LLM that can generate text from a prompt."""
    def generate(self, prompt: str, system: str = "", **kwargs) -> str: ...


@dataclass
class ScaffoldProposal:
    """A proposed scaffold with its rationale."""
    dag: SkillDAG
    strategy: str
    rationale: str
    confidence: str = "medium"
    source: str = "generated"


@dataclass
class ScaffoldMemory:
    """Past scaffold outcomes for a task type (Phase 3 placeholder)."""
    preferred_patterns: list[str] = field(default_factory=list)
    avoided_patterns: list[str] = field(default_factory=list)
    win_rates: dict[str, float] = field(default_factory=dict)


SCAFFOLD_SYSTEM_PROMPT = """You are a scaffold architect for an AI agent system.

Given a task and a list of available skills, design an execution plan as a
SkillDAG (Directed Acyclic Graph). The DAG defines which skills run in what
order, with layer-parallel execution for independent skills.

Rules:
- Skills in the same layer run in parallel
- Skills in later layers receive outputs from earlier layers
- Every DAG must end with a quality/safety gate as the final layer
- Prefer fewer layers (parallel where possible) for efficiency
- Prefer more layers (sequential) when ordering matters for quality
- The "strategy" field should be one of: quality, efficiency, simplicity

Output ONLY valid JSON in this exact format:
{
  "strategy": "quality|efficiency|simplicity",
  "rationale": "1-2 sentences explaining why this structure",
  "confidence": "high|medium|low",
  "nodes": [
    {"skill": "skill_name", "layer": 0, "input_keys": ["key1"], "output_keys": ["key2"]},
    ...
  ]
}"""


class ScaffoldGenerator:
    """Generates task-adaptive SkillDAGs via LLM.

    Parameters
    ----------
    registry:
        The SkillRegistry containing available skills.
    llm:
        Any LLM client that implements the generate() protocol.
    memory:
        Optional scaffold memory for conditioning on past outcomes.
    """

    def __init__(
        self,
        registry: SkillRegistry,
        llm: LLMClient | None = None,
        memory: ScaffoldMemory | None = None,
    ):
        self._registry = registry
        self._llm = llm
        self._memory = memory or ScaffoldMemory()

    def available_skills_block(self) -> str:
        """Format available skills for the LLM prompt."""
        skills = self._registry.list_names()
        lines = ["Available skills:"]
        for name in sorted(skills):
            chip = self._registry.get(name)
            desc = chip.description if chip else ""
            lines.append(f"  - {name}: {desc}")
        return "\n".join(lines)

    def memory_block(self) -> str:
        """Format scaffold memory for conditioning."""
        if not self._memory.preferred_patterns and not self._memory.avoided_patterns:
            return ""

        lines = ["Past experience:"]
        if self._memory.preferred_patterns:
            lines.append(f"  Preferred patterns: {', '.join(self._memory.preferred_patterns)}")
        if self._memory.avoided_patterns:
            lines.append(f"  Avoid: {', '.join(self._memory.avoided_patterns)}")
        if self._memory.win_rates:
            top = sorted(self._memory.win_rates.items(), key=lambda x: -x[1])[:3]
            lines.append(f"  Best strategies: {', '.join(f'{k} ({v:.0%})' for k, v in top)}")
        return "\n".join(lines)

    def generate(self, task: str, context: dict[str, Any] | None = None) -> ScaffoldProposal:
        """Generate a scaffold for the given task.

        If no LLM is available, falls back to a heuristic default DAG.
        """
        if self._llm is None:
            return self._heuristic_scaffold(task, context)

        skills_block = self.available_skills_block()
        memory_block = self.memory_block()

        prompt = f"""Task: {task}

{skills_block}

{memory_block}

Design the optimal SkillDAG for this task. Remember: output ONLY JSON."""

        try:
            response = self._llm.generate(
                prompt,
                system=SCAFFOLD_SYSTEM_PROMPT,
                max_tokens=500,
                temperature=0.3,
            )
            return self._parse_response(response, task)
        except Exception as e:
            logger.warning("Scaffold generation failed (%s), using heuristic", e)
            return self._heuristic_scaffold(task, context)

    def generate_pair(self, task: str, context: dict[str, Any] | None = None
                      ) -> tuple[ScaffoldProposal, ScaffoldProposal]:
        """Generate an exploit + explore scaffold pair for shadow comparison.

        The exploit scaffold uses the best known strategy.
        The explore scaffold tries an alternative approach.
        """
        exploit = self.generate(task, context)

        if self._llm is None:
            explore = self._heuristic_scaffold(task, context)
            explore.source = "heuristic_explore"
            return exploit, explore

        # Generate alternative by requesting a DIFFERENT strategy
        alt_strategy = {
            "quality": "efficiency",
            "efficiency": "simplicity",
            "simplicity": "quality",
        }.get(exploit.strategy, "quality")

        alt_prompt = f"""Task: {task}

{self.available_skills_block()}

CONSTRAINT: Use a "{alt_strategy}" strategy. Do NOT use the same
structure as: {exploit.rationale}. Find a genuinely different approach.

Design the optimal SkillDAG. Output ONLY JSON."""

        try:
            response = self._llm.generate(
                alt_prompt,
                system=SCAFFOLD_SYSTEM_PROMPT,
                max_tokens=500,
                temperature=0.7,
            )
            explore = self._parse_response(response, task)
            explore.source = "generated_explore"
        except Exception:
            explore = self._heuristic_scaffold(task, context)
            explore.source = "heuristic_explore"

        return exploit, explore

    def _parse_response(self, response: str, task: str) -> ScaffoldProposal:
        """Parse LLM JSON response into a ScaffoldProposal."""
        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        start = text.find("{")
        end = text.rfind("}") + 1
        if start < 0 or end <= start:
            raise ValueError(f"No JSON found in response: {text[:200]}")

        data = json.loads(text[start:end])

        dag = SkillDAG(strategy=data.get("strategy", "quality"))
        dag.metadata["task"] = task[:200]
        dag.metadata["rationale"] = data.get("rationale", "")

        nodes = data.get("nodes", [])
        prev_layer_nodes = []

        for i, node_data in enumerate(nodes):
            skill_name = node_data.get("skill", "")
            if not self._registry.get(skill_name):
                logger.warning("Generated scaffold references unknown skill: %s", skill_name)
                continue

            node = DAGNode(
                node_id=f"{skill_name}_{i}",
                skill_name=skill_name,
                sub_task=task[:100],
                layer=node_data.get("layer", i),
                input_keys=node_data.get("input_keys", []),
                output_keys=node_data.get("output_keys", [skill_name]),
            )
            dag.add_node(node)

            if node.layer > 0 and prev_layer_nodes:
                for prev in prev_layer_nodes:
                    if self._dag_nodes_by_layer(dag, prev.layer) != self._dag_nodes_by_layer(dag, node.layer):
                        dag.add_edge(prev.node_id, node.node_id)

            if not prev_layer_nodes or node.layer > prev_layer_nodes[-1].layer:
                prev_layer_nodes = [node]
            elif node.layer == prev_layer_nodes[-1].layer:
                prev_layer_nodes.append(node)

        return ScaffoldProposal(
            dag=dag,
            strategy=data.get("strategy", "quality"),
            rationale=data.get("rationale", ""),
            confidence=data.get("confidence", "medium"),
            source="generated",
        )

    def _dag_nodes_by_layer(self, dag: SkillDAG, layer: int) -> list[str]:
        return [n.node_id for n in dag.nodes.values() if n.layer == layer]

    def _heuristic_scaffold(self, task: str, context: dict | None = None) -> ScaffoldProposal:
        """Fallback: build a simple sequential DAG from available skills."""
        skills = self._registry.list_names()

        dag = SkillDAG(strategy="simplicity")
        dag.metadata["task"] = task[:200]
        dag.metadata["rationale"] = "Heuristic fallback: sequential execution"

        for i, skill_name in enumerate(skills[:5]):
            node = DAGNode(
                node_id=f"{skill_name}_{i}",
                skill_name=skill_name,
                sub_task=task[:100],
                layer=i,
                input_keys=["question"] if i == 0 else [skills[i-1]],
                output_keys=[skill_name],
            )
            dag.add_node(node)
            if i > 0:
                dag.add_edge(f"{skills[i-1]}_{i-1}", node.node_id)

        return ScaffoldProposal(
            dag=dag,
            strategy="simplicity",
            rationale="Heuristic fallback: sequential execution of available skills",
            confidence="low",
            source="heuristic",
        )
