"""Tests for kintsugi.kintsugi_engine.scaffold_generator."""

import json

import pytest

from kintsugi.kintsugi_engine.scaffold_generator import (
    SCAFFOLD_SYSTEM_PROMPT,
    ScaffoldGenerator,
    ScaffoldMemory,
    ScaffoldProposal,
)
from kintsugi.skills.base import BaseSkillChip, SkillDomain, SkillRequest, SkillResponse
from kintsugi.skills.dag import DAGNode, SkillDAG
from kintsugi.skills.registry import SkillRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubChip(BaseSkillChip):
    """Minimal concrete skill chip for registry population."""

    def __init__(self, name: str, description: str = "", domain: SkillDomain = SkillDomain.GENERAL):
        self.name = name
        self.description = description
        self.domain = domain
        super().__init__()

    async def handle(self, request: SkillRequest, context):
        return SkillResponse(content="ok", success=True)


class _MockLLM:
    """Controllable mock for the LLMClient protocol."""

    def __init__(self, response: str = "{}"):
        self.response = response
        self.calls: list[dict] = []

    def generate(self, prompt: str, system: str = "", **kwargs) -> str:
        self.calls.append({"prompt": prompt, "system": system, **kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class _ExplodingLLM:
    """LLM that always raises."""

    def generate(self, prompt: str, system: str = "", **kwargs) -> str:
        raise RuntimeError("LLM is down")


def _make_registry(*names: str) -> SkillRegistry:
    """Build a registry with stub chips for the given names."""
    reg = SkillRegistry()
    for name in names:
        reg.register(_StubChip(name, description=f"Does {name} things"))
    return reg


def _valid_json_response(
    strategy: str = "quality",
    nodes: list[dict] | None = None,
    rationale: str = "test rationale",
    confidence: str = "high",
) -> str:
    """Return a well-formed JSON scaffold response."""
    if nodes is None:
        nodes = [
            {"skill": "alpha", "layer": 0, "input_keys": ["question"], "output_keys": ["alpha_out"]},
            {"skill": "beta", "layer": 1, "input_keys": ["alpha_out"], "output_keys": ["beta_out"]},
        ]
    return json.dumps({
        "strategy": strategy,
        "rationale": rationale,
        "confidence": confidence,
        "nodes": nodes,
    })


# ---------------------------------------------------------------------------
# ScaffoldProposal dataclass
# ---------------------------------------------------------------------------


class TestScaffoldProposal:
    def test_defaults(self):
        dag = SkillDAG()
        p = ScaffoldProposal(dag=dag, strategy="quality", rationale="reason")
        assert p.confidence == "medium"
        assert p.source == "generated"
        assert p.strategy == "quality"
        assert p.rationale == "reason"
        assert p.dag is dag

    def test_custom_fields(self):
        dag = SkillDAG()
        p = ScaffoldProposal(
            dag=dag,
            strategy="efficiency",
            rationale="fast",
            confidence="high",
            source="heuristic",
        )
        assert p.confidence == "high"
        assert p.source == "heuristic"


# ---------------------------------------------------------------------------
# ScaffoldMemory dataclass
# ---------------------------------------------------------------------------


class TestScaffoldMemory:
    def test_defaults(self):
        m = ScaffoldMemory()
        assert m.preferred_patterns == []
        assert m.avoided_patterns == []
        assert m.win_rates == {}

    def test_custom_values(self):
        m = ScaffoldMemory(
            preferred_patterns=["parallel"],
            avoided_patterns=["sequential"],
            win_rates={"quality": 0.8},
        )
        assert "parallel" in m.preferred_patterns
        assert m.win_rates["quality"] == 0.8

    def test_independent_defaults(self):
        """Default mutable fields are not shared across instances."""
        m1 = ScaffoldMemory()
        m2 = ScaffoldMemory()
        m1.preferred_patterns.append("x")
        assert m2.preferred_patterns == []


# ---------------------------------------------------------------------------
# ScaffoldGenerator -- no LLM (heuristic fallback)
# ---------------------------------------------------------------------------


class TestHeuristicScaffold:
    def test_generate_returns_valid_proposal(self):
        reg = _make_registry("analyze", "summarize", "report")
        gen = ScaffoldGenerator(registry=reg)
        proposal = gen.generate("Do something useful")
        assert isinstance(proposal, ScaffoldProposal)
        assert proposal.strategy == "simplicity"
        assert proposal.source == "heuristic"
        assert proposal.confidence == "low"
        assert "Heuristic fallback" in proposal.rationale

    def test_generate_dag_has_correct_nodes(self):
        reg = _make_registry("a", "b", "c")
        gen = ScaffoldGenerator(registry=reg)
        proposal = gen.generate("task")
        dag = proposal.dag
        assert len(dag.nodes) == 3
        assert dag.strategy == "simplicity"
        assert dag.metadata["task"] == "task"

    def test_generate_dag_sequential_edges(self):
        reg = _make_registry("a", "b", "c")
        gen = ScaffoldGenerator(registry=reg)
        proposal = gen.generate("task")
        dag = proposal.dag
        assert len(dag.edges) == 2

    def test_generate_limits_to_five_skills(self):
        reg = _make_registry("s1", "s2", "s3", "s4", "s5", "s6", "s7")
        gen = ScaffoldGenerator(registry=reg)
        proposal = gen.generate("task")
        assert len(proposal.dag.nodes) <= 5

    def test_generate_empty_registry(self):
        reg = SkillRegistry()
        gen = ScaffoldGenerator(registry=reg)
        proposal = gen.generate("task")
        assert len(proposal.dag.nodes) == 0
        assert proposal.strategy == "simplicity"

    def test_generate_truncates_long_task(self):
        reg = _make_registry("a")
        gen = ScaffoldGenerator(registry=reg)
        long_task = "x" * 500
        proposal = gen.generate(long_task)
        assert len(proposal.dag.metadata["task"]) <= 200

    def test_generate_pair_returns_two_proposals(self):
        reg = _make_registry("a", "b")
        gen = ScaffoldGenerator(registry=reg)
        exploit, explore = gen.generate_pair("task")
        assert isinstance(exploit, ScaffoldProposal)
        assert isinstance(explore, ScaffoldProposal)

    def test_generate_pair_explore_source(self):
        reg = _make_registry("a", "b")
        gen = ScaffoldGenerator(registry=reg)
        exploit, explore = gen.generate_pair("task")
        assert exploit.source == "heuristic"
        assert explore.source == "heuristic_explore"


# ---------------------------------------------------------------------------
# ScaffoldGenerator -- with mock LLM
# ---------------------------------------------------------------------------


class TestLLMScaffold:
    def test_generate_calls_llm(self):
        reg = _make_registry("alpha", "beta")
        llm = _MockLLM(_valid_json_response())
        gen = ScaffoldGenerator(registry=reg, llm=llm)
        gen.generate("test task")
        assert len(llm.calls) == 1

    def test_generate_prompt_contains_skills(self):
        reg = _make_registry("alpha", "beta")
        llm = _MockLLM(_valid_json_response())
        gen = ScaffoldGenerator(registry=reg, llm=llm)
        gen.generate("test task")
        prompt = llm.calls[0]["prompt"]
        assert "alpha" in prompt
        assert "beta" in prompt
        assert "Available skills:" in prompt

    def test_generate_prompt_contains_memory(self):
        reg = _make_registry("alpha", "beta")
        llm = _MockLLM(_valid_json_response())
        memory = ScaffoldMemory(preferred_patterns=["parallel execution"])
        gen = ScaffoldGenerator(registry=reg, llm=llm, memory=memory)
        gen.generate("test task")
        prompt = llm.calls[0]["prompt"]
        assert "parallel execution" in prompt

    def test_generate_sends_system_prompt(self):
        reg = _make_registry("alpha", "beta")
        llm = _MockLLM(_valid_json_response())
        gen = ScaffoldGenerator(registry=reg, llm=llm)
        gen.generate("test task")
        assert llm.calls[0]["system"] == SCAFFOLD_SYSTEM_PROMPT

    def test_generate_sends_kwargs(self):
        reg = _make_registry("alpha", "beta")
        llm = _MockLLM(_valid_json_response())
        gen = ScaffoldGenerator(registry=reg, llm=llm)
        gen.generate("test task")
        assert llm.calls[0]["max_tokens"] == 500
        assert llm.calls[0]["temperature"] == 0.3

    def test_generate_parses_valid_json(self):
        reg = _make_registry("alpha", "beta")
        llm = _MockLLM(_valid_json_response(strategy="efficiency", confidence="high"))
        gen = ScaffoldGenerator(registry=reg, llm=llm)
        proposal = gen.generate("test task")
        assert proposal.strategy == "efficiency"
        assert proposal.confidence == "high"
        assert proposal.source == "generated"
        assert len(proposal.dag.nodes) == 2

    def test_generate_parses_json_with_markdown_fences(self):
        reg = _make_registry("alpha", "beta")
        raw = _valid_json_response()
        fenced = f"```json\n{raw}\n```"
        llm = _MockLLM(fenced)
        gen = ScaffoldGenerator(registry=reg, llm=llm)
        proposal = gen.generate("test task")
        assert proposal.source == "generated"
        assert len(proposal.dag.nodes) == 2

    def test_generate_skips_unknown_skills(self):
        reg = _make_registry("alpha")
        nodes = [
            {"skill": "alpha", "layer": 0, "input_keys": [], "output_keys": ["a"]},
            {"skill": "nonexistent", "layer": 1, "input_keys": ["a"], "output_keys": ["b"]},
        ]
        llm = _MockLLM(_valid_json_response(nodes=nodes))
        gen = ScaffoldGenerator(registry=reg, llm=llm)
        proposal = gen.generate("task")
        # Only "alpha" should be in the DAG; "nonexistent" is silently skipped
        assert len(proposal.dag.nodes) == 1
        node_skills = [n.skill_name for n in proposal.dag.nodes.values()]
        assert "alpha" in node_skills
        assert "nonexistent" not in node_skills

    def test_generate_falls_back_on_malformed_json(self):
        reg = _make_registry("alpha")
        llm = _MockLLM("this is not json at all")
        gen = ScaffoldGenerator(registry=reg, llm=llm)
        proposal = gen.generate("task")
        assert proposal.source == "heuristic"
        assert proposal.strategy == "simplicity"

    def test_generate_falls_back_on_llm_exception(self):
        reg = _make_registry("alpha")
        gen = ScaffoldGenerator(registry=reg, llm=_ExplodingLLM())
        proposal = gen.generate("task")
        assert proposal.source == "heuristic"
        assert proposal.strategy == "simplicity"

    def test_generate_pair_requests_different_strategy(self):
        reg = _make_registry("alpha", "beta")
        call_count = 0

        class _TwoCallLLM:
            def generate(self, prompt: str, system: str = "", **kwargs) -> str:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return _valid_json_response(strategy="quality", rationale="first approach")
                return _valid_json_response(strategy="efficiency", rationale="second approach")

        gen = ScaffoldGenerator(registry=reg, llm=_TwoCallLLM())
        exploit, explore = gen.generate_pair("task")
        assert call_count == 2
        assert exploit.source == "generated"
        assert explore.source == "generated_explore"

    def test_generate_pair_explore_falls_back_on_failure(self):
        reg = _make_registry("alpha", "beta")
        call_count = 0

        class _FailSecondLLM:
            def generate(self, prompt: str, system: str = "", **kwargs) -> str:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return _valid_json_response()
                raise RuntimeError("second call fails")

        gen = ScaffoldGenerator(registry=reg, llm=_FailSecondLLM())
        exploit, explore = gen.generate_pair("task")
        assert exploit.source == "generated"
        assert explore.source == "heuristic_explore"

    def test_generate_pair_alt_strategy_mapping(self):
        """Verify the strategy rotation: quality->efficiency->simplicity->quality."""
        reg = _make_registry("alpha", "beta")

        for initial, expected_alt in [
            ("quality", "efficiency"),
            ("efficiency", "simplicity"),
            ("simplicity", "quality"),
        ]:
            prompts = []

            class _CaptureLLM:
                def generate(self, prompt: str, system: str = "", **kwargs) -> str:
                    prompts.append(prompt)
                    return _valid_json_response(strategy=initial)

            gen = ScaffoldGenerator(registry=reg, llm=_CaptureLLM())
            gen.generate_pair("task")
            # The second prompt should contain the expected alternative strategy
            assert len(prompts) == 2
            assert f'"{expected_alt}"' in prompts[1]

    def test_generate_dag_metadata(self):
        reg = _make_registry("alpha", "beta")
        llm = _MockLLM(_valid_json_response(rationale="because reasons"))
        gen = ScaffoldGenerator(registry=reg, llm=llm)
        proposal = gen.generate("my important task")
        assert proposal.dag.metadata["task"] == "my important task"
        assert proposal.dag.metadata["rationale"] == "because reasons"

    def test_generate_dag_edges_across_layers(self):
        reg = _make_registry("alpha", "beta", "gamma")
        nodes = [
            {"skill": "alpha", "layer": 0, "input_keys": [], "output_keys": ["a"]},
            {"skill": "beta", "layer": 0, "input_keys": [], "output_keys": ["b"]},
            {"skill": "gamma", "layer": 1, "input_keys": ["a", "b"], "output_keys": ["c"]},
        ]
        llm = _MockLLM(_valid_json_response(nodes=nodes))
        gen = ScaffoldGenerator(registry=reg, llm=llm)
        proposal = gen.generate("task")
        dag = proposal.dag
        assert len(dag.nodes) == 3
        # gamma should have edges from layer 0 nodes
        assert len(dag.edges) > 0

    def test_generate_node_ids_contain_skill_name(self):
        reg = _make_registry("alpha", "beta")
        llm = _MockLLM(_valid_json_response())
        gen = ScaffoldGenerator(registry=reg, llm=llm)
        proposal = gen.generate("task")
        for node_id in proposal.dag.nodes:
            assert "alpha" in node_id or "beta" in node_id


# ---------------------------------------------------------------------------
# available_skills_block()
# ---------------------------------------------------------------------------


class TestAvailableSkillsBlock:
    def test_format(self):
        reg = _make_registry("analyze", "summarize")
        gen = ScaffoldGenerator(registry=reg)
        block = gen.available_skills_block()
        assert block.startswith("Available skills:")
        assert "  - analyze:" in block
        assert "  - summarize:" in block

    def test_sorted_output(self):
        reg = _make_registry("zebra", "alpha", "middle")
        gen = ScaffoldGenerator(registry=reg)
        block = gen.available_skills_block()
        lines = block.strip().split("\n")
        skill_lines = [l.strip() for l in lines[1:]]
        names = [l.split(":")[0].strip("- ") for l in skill_lines]
        assert names == sorted(names)

    def test_includes_descriptions(self):
        reg = SkillRegistry()
        reg.register(_StubChip("mytool", description="Does clever things"))
        gen = ScaffoldGenerator(registry=reg)
        block = gen.available_skills_block()
        assert "Does clever things" in block

    def test_empty_registry(self):
        reg = SkillRegistry()
        gen = ScaffoldGenerator(registry=reg)
        block = gen.available_skills_block()
        assert block == "Available skills:"


# ---------------------------------------------------------------------------
# memory_block()
# ---------------------------------------------------------------------------


class TestMemoryBlock:
    def test_empty_memory_returns_empty_string(self):
        gen = ScaffoldGenerator(registry=SkillRegistry())
        assert gen.memory_block() == ""

    def test_preferred_patterns(self):
        mem = ScaffoldMemory(preferred_patterns=["parallel", "layered"])
        gen = ScaffoldGenerator(registry=SkillRegistry(), memory=mem)
        block = gen.memory_block()
        assert "Past experience:" in block
        assert "Preferred patterns: parallel, layered" in block

    def test_avoided_patterns(self):
        mem = ScaffoldMemory(avoided_patterns=["deep nesting"])
        gen = ScaffoldGenerator(registry=SkillRegistry(), memory=mem)
        block = gen.memory_block()
        assert "Avoid: deep nesting" in block

    def test_win_rates_sorted(self):
        mem = ScaffoldMemory(
            preferred_patterns=["x"],
            win_rates={"quality": 0.9, "efficiency": 0.7, "simplicity": 0.5, "other": 0.3},
        )
        gen = ScaffoldGenerator(registry=SkillRegistry(), memory=mem)
        block = gen.memory_block()
        assert "Best strategies:" in block
        # Top 3 by win rate
        assert "quality (90%)" in block
        assert "efficiency (70%)" in block
        assert "simplicity (50%)" in block
        # 4th should not appear
        assert "other" not in block

    def test_no_win_rates_line_when_empty(self):
        mem = ScaffoldMemory(preferred_patterns=["a"])
        gen = ScaffoldGenerator(registry=SkillRegistry(), memory=mem)
        block = gen.memory_block()
        assert "Best strategies" not in block

    def test_both_preferred_and_avoided(self):
        mem = ScaffoldMemory(preferred_patterns=["fast"], avoided_patterns=["slow"])
        gen = ScaffoldGenerator(registry=SkillRegistry(), memory=mem)
        block = gen.memory_block()
        assert "Preferred patterns: fast" in block
        assert "Avoid: slow" in block


# ---------------------------------------------------------------------------
# _parse_response() edge cases
# ---------------------------------------------------------------------------


class TestParseResponse:
    def _gen(self, *skill_names: str) -> ScaffoldGenerator:
        reg = _make_registry(*skill_names)
        return ScaffoldGenerator(registry=reg)

    def test_no_json_raises(self):
        gen = self._gen("alpha")
        with pytest.raises(ValueError, match="No JSON found"):
            gen._parse_response("There is no json here at all", "task")

    def test_empty_string_raises(self):
        gen = self._gen("alpha")
        with pytest.raises(ValueError, match="No JSON found"):
            gen._parse_response("", "task")

    def test_partial_json_raises(self):
        gen = self._gen("alpha")
        with pytest.raises((ValueError, json.JSONDecodeError)):
            gen._parse_response('{"strategy": "quality", "nodes": [', "task")

    def test_valid_json_no_nodes(self):
        gen = self._gen("alpha")
        resp = '{"strategy": "quality", "rationale": "empty"}'
        proposal = gen._parse_response(resp, "task")
        assert len(proposal.dag.nodes) == 0
        assert proposal.strategy == "quality"

    def test_json_with_surrounding_text(self):
        gen = self._gen("alpha")
        payload = _valid_json_response(
            nodes=[{"skill": "alpha", "layer": 0, "input_keys": [], "output_keys": ["a"]}],
        )
        resp = f"Here is my answer:\n{payload}\nDone!"
        proposal = gen._parse_response(resp, "task")
        assert len(proposal.dag.nodes) == 1

    def test_json_with_triple_backtick_fence(self):
        gen = self._gen("alpha")
        payload = _valid_json_response(
            nodes=[{"skill": "alpha", "layer": 0, "input_keys": [], "output_keys": ["a"]}],
        )
        resp = f"```json\n{payload}\n```"
        proposal = gen._parse_response(resp, "task")
        assert len(proposal.dag.nodes) == 1

    def test_json_with_plain_backtick_fence(self):
        gen = self._gen("alpha")
        payload = _valid_json_response(
            nodes=[{"skill": "alpha", "layer": 0, "input_keys": [], "output_keys": ["a"]}],
        )
        resp = f"```\n{payload}\n```"
        proposal = gen._parse_response(resp, "task")
        assert len(proposal.dag.nodes) == 1

    def test_multiple_json_blocks_uses_outermost(self):
        gen = self._gen("alpha")
        # The parser uses find("{") and rfind("}"), so it gets the outermost object
        inner = '{"nested": true}'
        outer = _valid_json_response(
            nodes=[{"skill": "alpha", "layer": 0, "input_keys": [], "output_keys": ["a"]}],
        )
        resp = f"text {outer} more text"
        proposal = gen._parse_response(resp, "task")
        assert len(proposal.dag.nodes) == 1

    def test_defaults_for_missing_fields(self):
        gen = self._gen("alpha")
        resp = '{"nodes": [{"skill": "alpha", "layer": 0}]}'
        proposal = gen._parse_response(resp, "task")
        assert proposal.strategy == "quality"  # default
        assert proposal.rationale == ""  # default
        assert proposal.confidence == "medium"  # default

    def test_node_default_output_keys(self):
        gen = self._gen("alpha")
        resp = '{"nodes": [{"skill": "alpha", "layer": 0}]}'
        proposal = gen._parse_response(resp, "task")
        node = list(proposal.dag.nodes.values())[0]
        assert node.output_keys == ["alpha"]

    def test_task_truncated_in_metadata(self):
        gen = self._gen("alpha")
        long_task = "z" * 500
        resp = '{"strategy": "quality"}'
        proposal = gen._parse_response(resp, long_task)
        assert len(proposal.dag.metadata["task"]) <= 200

    def test_task_truncated_in_node_sub_task(self):
        gen = self._gen("alpha")
        long_task = "z" * 500
        resp = '{"nodes": [{"skill": "alpha", "layer": 0}]}'
        proposal = gen._parse_response(resp, long_task)
        node = list(proposal.dag.nodes.values())[0]
        assert len(node.sub_task) <= 100
