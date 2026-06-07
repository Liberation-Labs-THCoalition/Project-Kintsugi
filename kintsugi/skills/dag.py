"""
DAG-based skill composition for Kintsugi.

Adapted from AgentSkillOS (arXiv:2603.02176). Provides declarative
skill composition via directed acyclic graphs with layer-parallel execution.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .base import SkillContext, SkillRequest, SkillResponse
from .registry import SkillRegistry


@dataclass
class DAGNode:
    """A single node in a skill composition DAG."""

    node_id: str
    skill_name: str
    sub_task: str
    layer: int
    input_keys: list[str] = field(default_factory=list)
    output_keys: list[str] = field(default_factory=list)


@dataclass
class DAGResult:
    """Result of executing a complete DAG."""

    dag_id: str
    artifacts: dict[str, Any] = field(default_factory=dict)
    node_results: dict[str, SkillResponse] = field(default_factory=dict)
    node_errors: dict[str, str] = field(default_factory=dict)
    success: bool = True
    execution_time_ms: float = 0.0
    layers_executed: int = 0


@dataclass
class SkillDAG:
    """Directed acyclic graph of skill compositions."""

    dag_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    nodes: dict[str, DAGNode] = field(default_factory=dict)
    edges: list[tuple[str, str]] = field(default_factory=list)
    strategy: str = "quality"  # quality | efficiency | simplicity
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_node(self, node: DAGNode) -> None:
        self.nodes[node.node_id] = node

    def add_edge(self, source: str, target: str) -> None:
        self.edges.append((source, target))

    def layers(self) -> list[list[str]]:
        """Return node IDs grouped by layer, ordered by layer index."""
        layer_map: dict[int, list[str]] = {}
        for node in self.nodes.values():
            layer_map.setdefault(node.layer, []).append(node.node_id)
        return [layer_map[k] for k in sorted(layer_map.keys())]

    def topological_sort(self) -> list[str]:
        """Kahn's algorithm. Returns full execution order respecting edges."""
        in_degree: dict[str, int] = {nid: 0 for nid in self.nodes}
        adjacency: dict[str, list[str]] = {nid: [] for nid in self.nodes}

        for src, tgt in self.edges:
            adjacency[src].append(tgt)
            in_degree[tgt] += 1

        queue = deque(
            sorted(
                [nid for nid, deg in in_degree.items() if deg == 0],
                key=lambda nid: self.nodes[nid].layer,
            )
        )
        order: list[str] = []

        while queue:
            nid = queue.popleft()
            order.append(nid)
            for neighbor in adjacency[nid]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return order

    def validate(self, registry: SkillRegistry) -> list[str]:
        """Validate the DAG. Returns list of error strings (empty = valid)."""
        errors: list[str] = []

        # Check all skill_names exist
        for node in self.nodes.values():
            if node.skill_name not in registry:
                errors.append(f"Node '{node.node_id}': skill '{node.skill_name}' not in registry")

        # Check edges reference valid nodes
        for src, tgt in self.edges:
            if src not in self.nodes:
                errors.append(f"Edge source '{src}' not in nodes")
            if tgt not in self.nodes:
                errors.append(f"Edge target '{tgt}' not in nodes")

        # Check edges respect layer ordering (source.layer < target.layer)
        for src, tgt in self.edges:
            if src in self.nodes and tgt in self.nodes:
                if self.nodes[src].layer >= self.nodes[tgt].layer:
                    errors.append(
                        f"Edge ({src} -> {tgt}): source layer {self.nodes[src].layer} "
                        f"must be < target layer {self.nodes[tgt].layer}"
                    )

        # Cycle detection via topological sort
        topo = self.topological_sort()
        if len(topo) != len(self.nodes):
            errors.append("DAG contains a cycle")

        return errors

    def content_hash(self) -> str:
        """Deterministic hash for provenance signing."""
        canonical = json.dumps(
            {
                "nodes": {
                    nid: {
                        "skill_name": n.skill_name,
                        "sub_task": n.sub_task,
                        "layer": n.layer,
                        "input_keys": n.input_keys,
                        "output_keys": n.output_keys,
                    }
                    for nid, n in sorted(self.nodes.items())
                },
                "edges": sorted(self.edges),
                "strategy": self.strategy,
            },
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


class DAGExecutor:
    """Executes a SkillDAG against a registry with layer-parallel scheduling."""

    def __init__(self, registry: SkillRegistry, max_parallel: int = 4) -> None:
        self.registry = registry
        self.max_parallel = max_parallel

    async def execute(
        self,
        dag: SkillDAG,
        initial_context: SkillContext,
        initial_artifacts: dict[str, Any] | None = None,
    ) -> DAGResult:
        artifacts: dict[str, Any] = dict(initial_artifacts or {})
        node_results: dict[str, SkillResponse] = {}
        node_errors: dict[str, str] = {}

        t0 = time.perf_counter()
        layers = dag.layers()
        layers_executed = 0

        for layer_nodes in layers:
            sem = asyncio.Semaphore(self.max_parallel)

            async def _run_node(node_id: str) -> None:
                async with sem:
                    node = dag.nodes[node_id]
                    chip = self.registry.get(node.skill_name)
                    if chip is None:
                        node_errors[node_id] = f"Skill '{node.skill_name}' not found"
                        return

                    # Build request from sub_task + upstream artifacts
                    input_data = {k: artifacts[k] for k in node.input_keys if k in artifacts}
                    request = SkillRequest(
                        intent=node.sub_task,
                        parameters=input_data,
                        raw_input=node.sub_task,
                    )

                    try:
                        response = await chip.handle(request, initial_context)
                        node_results[node_id] = response

                        # Map response data to output artifact keys
                        if response.success and response.data:
                            if len(node.output_keys) == 1:
                                artifacts[node.output_keys[0]] = response.data
                            else:
                                for key in node.output_keys:
                                    if key in response.data:
                                        artifacts[key] = response.data[key]
                    except Exception as exc:
                        node_errors[node_id] = str(exc)

            await asyncio.gather(*[_run_node(nid) for nid in layer_nodes])
            layers_executed += 1

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        success = len(node_errors) == 0

        return DAGResult(
            dag_id=dag.dag_id,
            artifacts=artifacts,
            node_results=node_results,
            node_errors=node_errors,
            success=success,
            execution_time_ms=elapsed_ms,
            layers_executed=layers_executed,
        )


class DAGBuilder:
    """Constructs SkillDAGs from BDI intentions or skill sequences."""

    @staticmethod
    def from_skill_sequence(
        skill_names: list[str],
        registry: SkillRegistry,
        sub_tasks: list[str] | None = None,
    ) -> SkillDAG:
        """Build a linear chain DAG from an ordered list of skill names."""
        dag = SkillDAG(strategy="simplicity")
        prev_output_key: str | None = None

        for i, name in enumerate(skill_names):
            task = sub_tasks[i] if sub_tasks and i < len(sub_tasks) else name
            output_key = f"step_{i}_out"
            input_keys = [prev_output_key] if prev_output_key else []

            node = DAGNode(
                node_id=f"node_{i}",
                skill_name=name,
                sub_task=task,
                layer=i,
                input_keys=input_keys,
                output_keys=[output_key],
            )
            dag.add_node(node)

            if i > 0:
                dag.add_edge(f"node_{i - 1}", f"node_{i}")

            prev_output_key = output_key

        return dag

    @staticmethod
    def from_intention(
        intention: dict[str, Any],
        registry: SkillRegistry,
        strategy: str = "quality",
    ) -> SkillDAG:
        """Build a DAG from a BDI intention structure.

        Expected intention format:
            {
                "goal": str,
                "steps": [
                    {
                        "skill": str,
                        "task": str,
                        "layer": int,
                        "inputs": list[str],
                        "outputs": list[str],
                        "depends_on": list[str],  # node IDs
                    },
                    ...
                ]
            }
        """
        dag = SkillDAG(
            strategy=strategy,
            metadata={"goal": intention.get("goal", "")},
        )

        steps = intention.get("steps", [])
        for i, step in enumerate(steps):
            node_id = step.get("id", f"node_{i}")
            node = DAGNode(
                node_id=node_id,
                skill_name=step["skill"],
                sub_task=step.get("task", step["skill"]),
                layer=step.get("layer", i),
                input_keys=step.get("inputs", []),
                output_keys=step.get("outputs", [f"{node_id}_out"]),
            )
            dag.add_node(node)

            for dep in step.get("depends_on", []):
                dag.add_edge(dep, node_id)

        return dag
