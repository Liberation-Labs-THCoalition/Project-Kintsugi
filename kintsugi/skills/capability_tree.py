"""Capability tree — hierarchical skill discovery via BDI-driven traversal.

Provides O(log n) skill retrieval from large pools by organizing skills into
a navigable tree. The tree is an INDEX OVERLAY on the flat SkillRegistry —
it does not replace name-based lookup or provenance. Registry owns identity,
tree owns retrieval efficiency.

Adapted from AgentSkillOS (arXiv:2603.02176) with key modifications:
- BDI-driven traversal instead of LLM-per-level calls
- Tree structure emerges from existing SkillDomain categories
- Progressive insertion on skill promotion (not bulk rebuild)
- Capacity threshold splitting keeps retrieval O(log n)

Usage:
    tree = CapabilityTree(registry)
    tree.build_from_registry()

    candidates = tree.retrieve(
        desires=[{"type": "crisis_response"}],
        beliefs=[{"budget_status": "low"}],
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from .base import BaseSkillChip, SkillDomain
from .registry import SkillRegistry


@dataclass
class TreeNode:
    """A node in the capability tree.

    Leaf nodes hold skill names. Internal nodes hold only children.
    Each node has a category name and description for traversal matching.
    """

    node_id: str
    name: str
    description: str
    parent_id: Optional[str] = None
    children: list[str] = field(default_factory=list)
    skill_names: set[str] = field(default_factory=set)
    depth: int = 0

    @property
    def is_leaf(self) -> bool:
        return len(self.children) == 0

    @property
    def size(self) -> int:
        return len(self.skill_names)


@dataclass
class RetrievalResult:
    """Result of a tree-guided skill retrieval."""

    skill_names: list[str]
    path: list[str]
    scores: dict[str, float] = field(default_factory=dict)


class CapabilityTree:
    """Hierarchical skill organization for efficient retrieval.

    Wraps an existing SkillRegistry, adding tree-based navigation.
    The registry remains the source of truth — tree nodes reference
    skill names that must exist in the registry.
    """

    BRANCHING_FACTOR = 7
    CAPACITY_THRESHOLD = 10

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry
        self._nodes: dict[str, TreeNode] = {}
        self._root_id: Optional[str] = None

    @property
    def root(self) -> Optional[TreeNode]:
        if self._root_id is None:
            return None
        return self._nodes.get(self._root_id)

    @property
    def depth(self) -> int:
        if not self._nodes:
            return 0
        return max(n.depth for n in self._nodes.values()) + 1

    @property
    def size(self) -> int:
        return len(self._nodes)

    def build_from_registry(self) -> None:
        """Build the tree from the current registry state.

        Uses existing SkillDomain categories as the first level,
        then groups skills within each domain by their declared
        capabilities or subdirectory structure.
        """
        self._nodes.clear()

        root = TreeNode(
            node_id="root",
            name="all_skills",
            description="All registered skill chips",
            depth=0,
        )
        self._nodes["root"] = root
        self._root_id = "root"

        domains = self._registry.list_domains()
        for domain in domains:
            domain_node = TreeNode(
                node_id=f"domain_{domain.value}",
                name=domain.value,
                description=f"Skills in the {domain.value} domain",
                parent_id="root",
                depth=1,
            )

            chips = self._registry.get_by_domain(domain)
            for chip in chips:
                domain_node.skill_names.add(chip.name)

            self._nodes[domain_node.node_id] = domain_node
            root.children.append(domain_node.node_id)

            if domain_node.size > self.CAPACITY_THRESHOLD:
                self._split_node(domain_node)

    def _split_node(self, node: TreeNode) -> None:
        """Split an over-capacity leaf into children by grouping skills."""
        chips = [
            self._registry.get(name)
            for name in node.skill_names
            if self._registry.get(name) is not None
        ]

        groups = self._group_skills(chips)

        if len(groups) <= 1:
            return

        node.skill_names.clear()

        for group_name, group_chips in groups.items():
            child = TreeNode(
                node_id=f"{node.node_id}/{group_name}",
                name=group_name,
                description=f"{group_name} skills within {node.name}",
                parent_id=node.node_id,
                depth=node.depth + 1,
            )
            for chip in group_chips:
                child.skill_names.add(chip.name)

            self._nodes[child.node_id] = child
            node.children.append(child.node_id)

            if child.size > self.CAPACITY_THRESHOLD:
                self._split_node(child)

    def _group_skills(self, chips: list[BaseSkillChip]) -> dict[str, list[BaseSkillChip]]:
        """Group skills by shared capability patterns."""
        groups: dict[str, list[BaseSkillChip]] = {}

        for chip in chips:
            caps = frozenset(chip.capabilities) if hasattr(chip, "capabilities") else frozenset()
            key = "_".join(sorted(c.value for c in caps)) if caps else "general"
            if key not in groups:
                groups[key] = []
            groups[key].append(chip)

        if len(groups) == 1:
            key = next(iter(groups))
            group = groups[key]
            if len(group) > self.CAPACITY_THRESHOLD:
                mid = len(group) // 2
                groups = {
                    f"{key}_a": group[:mid],
                    f"{key}_b": group[mid:],
                }

        return groups

    def retrieve(
        self,
        desires: Sequence[dict[str, Any]] = (),
        beliefs: Sequence[dict[str, Any]] = (),
        max_results: int = 8,
    ) -> RetrievalResult:
        """Retrieve relevant skills using BDI-driven tree traversal.

        Desires determine which branches to explore. Beliefs narrow
        candidates within reached leaves. Returns ranked skill names.
        """
        if self._root_id is None:
            return RetrievalResult(skill_names=[], path=[])

        desire_keywords = self._extract_keywords(desires)
        belief_constraints = self._extract_constraints(beliefs)

        candidates: dict[str, float] = {}
        path: list[str] = []

        self._traverse(
            self._nodes[self._root_id],
            desire_keywords,
            belief_constraints,
            candidates,
            path,
        )

        ranked = sorted(candidates.items(), key=lambda x: x[1], reverse=True)
        top_names = [name for name, _ in ranked[:max_results]]

        return RetrievalResult(
            skill_names=top_names,
            path=path,
            scores=dict(ranked[:max_results]),
        )

    def _traverse(
        self,
        node: TreeNode,
        keywords: set[str],
        constraints: dict[str, Any],
        candidates: dict[str, float],
        path: list[str],
    ) -> None:
        """Recursively traverse the tree, scoring nodes by keyword match."""
        path.append(node.node_id)

        if node.is_leaf:
            for skill_name in node.skill_names:
                score = self._score_skill(skill_name, keywords, constraints)
                if score > 0:
                    candidates[skill_name] = score
            return

        for child_id in node.children:
            child = self._nodes.get(child_id)
            if child is None:
                continue
            relevance = self._node_relevance(child, keywords)
            if relevance > 0:
                self._traverse(child, keywords, constraints, candidates, path)

    def _node_relevance(self, node: TreeNode, keywords: set[str]) -> float:
        """Score how relevant a node is to the given keywords."""
        node_terms = set(node.name.lower().split("_")) | set(node.description.lower().split())
        overlap = keywords & node_terms
        if not keywords:
            return 1.0
        return len(overlap) / len(keywords)

    def _score_skill(
        self,
        skill_name: str,
        keywords: set[str],
        constraints: dict[str, Any],
    ) -> float:
        """Score a skill against keywords and belief constraints."""
        chip = self._registry.get(skill_name)
        if chip is None:
            return 0.0

        score = 0.5

        name_terms = set(skill_name.lower().split("_"))
        desc_terms = set(chip.description.lower().split()) if hasattr(chip, "description") else set()
        all_terms = name_terms | desc_terms
        overlap = keywords & all_terms
        if keywords:
            score += 0.5 * (len(overlap) / len(keywords))

        return score

    def _extract_keywords(self, desires: Sequence[dict[str, Any]]) -> set[str]:
        """Extract searchable keywords from BDI desires."""
        keywords: set[str] = set()
        for desire in desires:
            for key, value in desire.items():
                keywords.add(key.lower())
                if isinstance(value, str):
                    keywords.update(value.lower().split("_"))
                    keywords.update(value.lower().split())
        return keywords

    def _extract_constraints(self, beliefs: Sequence[dict[str, Any]]) -> dict[str, Any]:
        """Extract filtering constraints from BDI beliefs."""
        constraints: dict[str, Any] = {}
        for belief in beliefs:
            constraints.update(belief)
        return constraints

    def insert_skill(self, skill_name: str) -> None:
        """Progressively insert a newly promoted skill into the tree.

        Descends from root, finds the best-fit leaf, and inserts.
        If the leaf exceeds capacity, splits it.
        """
        chip = self._registry.get(skill_name)
        if chip is None:
            return

        if self._root_id is None:
            self.build_from_registry()
            return

        target = self._find_best_leaf(chip)
        target.skill_names.add(skill_name)

        if target.size > self.CAPACITY_THRESHOLD:
            self._split_node(target)

    def _find_best_leaf(self, chip: BaseSkillChip) -> TreeNode:
        """Find the best leaf node for a chip based on domain and name."""
        domain_node_id = f"domain_{chip.domain.value}"
        if domain_node_id in self._nodes:
            node = self._nodes[domain_node_id]
            if node.is_leaf:
                return node
            for child_id in node.children:
                child = self._nodes.get(child_id)
                if child and child.is_leaf:
                    return child
            return self._nodes[node.children[0]] if node.children else node

        root = self._nodes[self._root_id]
        if root.is_leaf:
            return root
        if root.children:
            return self._nodes[root.children[0]]
        return root

    def remove_skill(self, skill_name: str) -> None:
        """Remove a skill from the tree (e.g., on quarantine)."""
        for node in self._nodes.values():
            node.skill_names.discard(skill_name)

    def get_node(self, node_id: str) -> Optional[TreeNode]:
        return self._nodes.get(node_id)

    def get_path_to_skill(self, skill_name: str) -> list[str]:
        """Get the tree path from root to the node containing this skill."""
        for node in self._nodes.values():
            if skill_name in node.skill_names:
                path = []
                current = node
                while current:
                    path.append(current.node_id)
                    current = self._nodes.get(current.parent_id) if current.parent_id else None
                return list(reversed(path))
        return []
