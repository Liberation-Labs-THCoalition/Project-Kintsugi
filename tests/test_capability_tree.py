"""
Tests for the capability tree module.

Tests hierarchical skill organization, BDI-driven retrieval,
progressive insertion, removal, and capacity splitting.
"""

import pytest

from kintsugi.skills.base import (
    BaseSkillChip,
    EFEWeights,
    SkillCapability,
    SkillContext,
    SkillDomain,
    SkillRequest,
    SkillResponse,
)
from kintsugi.skills.registry import SkillRegistry
from kintsugi.skills.capability_tree import CapabilityTree, TreeNode, RetrievalResult


# ============================================================================
# Mock Skill Chips
# ============================================================================


class MockChip(BaseSkillChip):
    """Configurable mock skill chip for tree tests."""

    def __init__(
        self,
        name: str,
        domain: SkillDomain,
        description: str = "",
        capabilities: list[SkillCapability] | None = None,
    ):
        self.name = name
        self.domain = domain
        self.description = description or f"Mock chip: {name}"
        self.capabilities = capabilities or []
        self.version = "1.0.0"
        self.efe_weights = EFEWeights()
        self.consensus_actions = []
        self.required_spans = []

    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        return SkillResponse(content=f"Mock response from {self.name}", success=True)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def registry():
    """Fresh SkillRegistry for each test."""
    return SkillRegistry()


@pytest.fixture
def tree(registry):
    """CapabilityTree wrapping a fresh registry."""
    return CapabilityTree(registry)


@pytest.fixture
def ops_chip():
    return MockChip("ops_task_manager", SkillDomain.OPERATIONS, "Manage operational tasks")


@pytest.fixture
def fundraising_chip():
    return MockChip("grant_search", SkillDomain.FUNDRAISING, "Search for grants")


@pytest.fixture
def crisis_chip():
    return MockChip(
        "crisis_response",
        SkillDomain.MUTUAL_AID,
        "Handle crisis response coordination",
    )


@pytest.fixture
def community_chip():
    return MockChip("coalition_builder", SkillDomain.COMMUNITY, "Build coalitions")


# ============================================================================
# Test: build_from_empty_registry
# ============================================================================


class TestBuildFromEmptyRegistry:
    def test_build_from_empty_registry(self, tree):
        """Empty registry produces a tree with only the root node."""
        tree.build_from_registry()

        assert tree.root is not None
        assert tree.root.node_id == "root"
        assert tree.root.children == []
        assert tree.size == 1


# ============================================================================
# Test: build_from_single_domain
# ============================================================================


class TestBuildFromSingleDomain:
    def test_build_from_single_domain(self, registry, ops_chip):
        """One domain creates root + one domain node."""
        registry.register(ops_chip)
        tree = CapabilityTree(registry)
        tree.build_from_registry()

        assert tree.root is not None
        assert len(tree.root.children) == 1

        domain_node = tree.get_node(tree.root.children[0])
        assert domain_node is not None
        assert domain_node.name == "operations"
        assert "ops_task_manager" in domain_node.skill_names


# ============================================================================
# Test: build_from_multiple_domains
# ============================================================================


class TestBuildFromMultipleDomains:
    def test_build_from_multiple_domains(self, registry, ops_chip, fundraising_chip, crisis_chip):
        """Multiple domains create proper tree structure with one node per domain."""
        registry.register(ops_chip)
        registry.register(fundraising_chip)
        registry.register(crisis_chip)

        tree = CapabilityTree(registry)
        tree.build_from_registry()

        assert tree.root is not None
        assert len(tree.root.children) == 3

        domain_names = set()
        for child_id in tree.root.children:
            node = tree.get_node(child_id)
            domain_names.add(node.name)

        assert "operations" in domain_names
        assert "fundraising" in domain_names
        assert "mutual_aid" in domain_names


# ============================================================================
# Test: tree_depth
# ============================================================================


class TestTreeDepth:
    def test_empty_tree_depth_zero(self, tree):
        """Empty tree (no nodes) has depth 0."""
        assert tree.depth == 0

    def test_root_only_depth_one(self, tree):
        """Tree with only root has depth 1."""
        tree.build_from_registry()
        assert tree.depth == 1

    def test_single_domain_depth_two(self, registry, ops_chip):
        """Root + one domain node means depth = 2."""
        registry.register(ops_chip)
        tree = CapabilityTree(registry)
        tree.build_from_registry()

        assert tree.depth == 2


# ============================================================================
# Test: retrieve_with_matching_desires
# ============================================================================


class TestRetrieveWithMatchingDesires:
    def test_retrieve_with_matching_desires(self, registry, crisis_chip):
        """Desires matching a domain keyword find skills in that domain."""
        registry.register(crisis_chip)
        tree = CapabilityTree(registry)
        tree.build_from_registry()

        # Use "mutual" and "aid" which match the domain node name/description
        result = tree.retrieve(desires=[{"mutual": "aid"}])

        assert isinstance(result, RetrievalResult)
        assert "crisis_response" in result.skill_names

    def test_retrieve_scores_are_populated(self, registry, crisis_chip):
        """Retrieved results have scores for matched skills."""
        registry.register(crisis_chip)
        tree = CapabilityTree(registry)
        tree.build_from_registry()

        result = tree.retrieve(desires=[{"type": "crisis"}])

        for name in result.skill_names:
            assert name in result.scores
            assert result.scores[name] > 0


# ============================================================================
# Test: retrieve_with_no_match
# ============================================================================


class TestRetrieveWithNoMatch:
    def test_retrieve_empty_desires_returns_results(self, registry, ops_chip, fundraising_chip):
        """Empty desires still return results (broad search)."""
        registry.register(ops_chip)
        registry.register(fundraising_chip)
        tree = CapabilityTree(registry)
        tree.build_from_registry()

        result = tree.retrieve(desires=[])

        # With no keywords, node_relevance returns 1.0 for all nodes
        assert len(result.skill_names) > 0

    def test_retrieve_on_empty_tree(self, tree):
        """Retrieve on unbuilt tree returns empty result."""
        result = tree.retrieve(desires=[{"type": "anything"}])

        assert result.skill_names == []
        assert result.path == []


# ============================================================================
# Test: retrieve_max_results
# ============================================================================


class TestRetrieveMaxResults:
    def test_retrieve_max_results(self, registry):
        """Respects max_results limit."""
        # Register many chips in same domain
        for i in range(5):
            chip = MockChip(f"ops_chip_{i}", SkillDomain.OPERATIONS, f"Operations chip {i}")
            registry.register(chip)

        tree = CapabilityTree(registry)
        tree.build_from_registry()

        result = tree.retrieve(desires=[{"type": "operations"}], max_results=3)

        assert len(result.skill_names) <= 3

    def test_retrieve_max_results_one(self, registry, ops_chip, fundraising_chip):
        """max_results=1 returns at most one skill."""
        registry.register(ops_chip)
        registry.register(fundraising_chip)
        tree = CapabilityTree(registry)
        tree.build_from_registry()

        result = tree.retrieve(desires=[], max_results=1)

        assert len(result.skill_names) <= 1


# ============================================================================
# Test: insert_skill
# ============================================================================


class TestInsertSkill:
    def test_insert_skill_adds_to_correct_domain(self, registry, ops_chip):
        """Progressive insertion adds skill to the correct domain leaf."""
        registry.register(ops_chip)
        tree = CapabilityTree(registry)
        tree.build_from_registry()

        # Register a new chip and insert into tree
        new_chip = MockChip("ops_scheduler", SkillDomain.OPERATIONS, "Schedule operations")
        registry.register(new_chip)
        tree.insert_skill("ops_scheduler")

        # The skill should be reachable via retrieval
        result = tree.retrieve(desires=[{"type": "operations"}])
        assert "ops_scheduler" in result.skill_names

    def test_insert_skill_builds_tree_if_empty(self, registry, ops_chip):
        """Insert on unbuilt tree triggers build_from_registry."""
        registry.register(ops_chip)
        tree = CapabilityTree(registry)

        tree.insert_skill("ops_task_manager")

        assert tree.root is not None

    def test_insert_nonexistent_skill_is_noop(self, registry, ops_chip):
        """Inserting a name not in registry does nothing."""
        registry.register(ops_chip)
        tree = CapabilityTree(registry)
        tree.build_from_registry()

        original_size = tree.size
        tree.insert_skill("nonexistent_skill")
        assert tree.size == original_size


# ============================================================================
# Test: remove_skill
# ============================================================================


class TestRemoveSkill:
    def test_remove_skill_removes_from_all_nodes(self, registry, ops_chip):
        """Removal removes skill from all nodes that contain it."""
        registry.register(ops_chip)
        tree = CapabilityTree(registry)
        tree.build_from_registry()

        tree.remove_skill("ops_task_manager")

        # Skill should not appear in any node
        for node in tree._nodes.values():
            assert "ops_task_manager" not in node.skill_names

    def test_remove_nonexistent_skill_is_safe(self, registry, ops_chip):
        """Removing a skill that doesn't exist in the tree is safe."""
        registry.register(ops_chip)
        tree = CapabilityTree(registry)
        tree.build_from_registry()

        # Should not raise
        tree.remove_skill("never_existed")


# ============================================================================
# Test: get_path_to_skill
# ============================================================================


class TestGetPathToSkill:
    def test_get_path_to_skill(self, registry, ops_chip):
        """Returns path from root to containing node."""
        registry.register(ops_chip)
        tree = CapabilityTree(registry)
        tree.build_from_registry()

        path = tree.get_path_to_skill("ops_task_manager")

        assert len(path) >= 2
        assert path[0] == "root"
        assert "domain_operations" in path

    def test_path_starts_at_root(self, registry, fundraising_chip):
        """Path always starts with root."""
        registry.register(fundraising_chip)
        tree = CapabilityTree(registry)
        tree.build_from_registry()

        path = tree.get_path_to_skill("grant_search")

        assert path[0] == "root"

    def test_path_for_unknown_skill_is_empty(self, registry, ops_chip):
        """Path for a skill not in the tree is empty list."""
        registry.register(ops_chip)
        tree = CapabilityTree(registry)
        tree.build_from_registry()

        path = tree.get_path_to_skill("unknown_skill")

        assert path == []


# ============================================================================
# Test: split_on_capacity
# ============================================================================


class TestSplitOnCapacity:
    def test_split_on_capacity(self, registry):
        """Over-capacity nodes get split into children."""
        # Register more chips than CAPACITY_THRESHOLD in one domain
        for i in range(12):
            chip = MockChip(
                f"ops_chip_{i}",
                SkillDomain.OPERATIONS,
                f"Operations chip {i}",
                capabilities=[SkillCapability.READ_DATA] if i < 6 else [SkillCapability.WRITE_DATA],
            )
            registry.register(chip)

        tree = CapabilityTree(registry)
        tree.build_from_registry()

        # The domain node should have been split (it has children now)
        domain_node = tree.get_node("domain_operations")
        assert domain_node is not None
        assert len(domain_node.children) > 0
        # Original node should have had its skills moved to children
        assert domain_node.size == 0

    def test_split_preserves_all_skills(self, registry):
        """After splitting, all original skills are still reachable."""
        names = []
        for i in range(12):
            name = f"ops_chip_{i}"
            names.append(name)
            chip = MockChip(
                name,
                SkillDomain.OPERATIONS,
                f"Operations chip {i}",
                capabilities=[SkillCapability.READ_DATA] if i < 6 else [SkillCapability.WRITE_DATA],
            )
            registry.register(chip)

        tree = CapabilityTree(registry)
        tree.build_from_registry()

        # All skills should be findable via get_path_to_skill
        for name in names:
            path = tree.get_path_to_skill(name)
            assert len(path) > 0, f"Skill {name} not found in tree after split"
