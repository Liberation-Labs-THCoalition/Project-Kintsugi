"""Tests for kintsugi.memory.tgs_verification."""

from __future__ import annotations

from kintsugi.memory.tgs_verification import GraphResult, TextGraphVerifier


class FakeTextStore:
    def __init__(self, results):
        self._results = results

    def search(self, query, n_results=10):
        return self._results[:n_results]


class FakeGraphStore:
    def __init__(self, entities=None, mentions=None):
        self._entities = entities or set()
        self._mentions = mentions or {}

    def walk(self, query, max_hops=2, max_nodes=20):
        return GraphResult(nodes=[], edges=[], visited_entities=set(self._entities))

    def get_entity_mentions(self, entity):
        return self._mentions.get(entity, [])


class TestGraphVotesOnText:
    def test_entity_overlap_confirms_memory(self):
        text_store = FakeTextStore([
            {"id": "1", "content": "Alice met Bob to discuss the budget", "score": 0.6},
        ])
        graph_store = FakeGraphStore(entities={"Alice", "Bob"})
        verifier = TextGraphVerifier(text_store, graph_store)

        report = verifier.retrieve("Alice and Bob")

        assert len(report.verified_memories) == 1
        vm = report.verified_memories[0]
        assert vm.verification == "confirmed"
        assert set(vm.entity_overlap) == {"Alice", "Bob"}
        assert vm.combined_score > 0

    def test_no_entity_overlap_but_high_text_score_is_text_only(self):
        text_store = FakeTextStore([
            {"id": "1", "content": "unrelated content here", "score": 0.9},
        ])
        graph_store = FakeGraphStore(entities={"SomeoneElse"})
        verifier = TextGraphVerifier(text_store, graph_store)

        report = verifier.retrieve("query")
        assert report.verified_memories[0].verification == "text_only"

    def test_no_overlap_and_low_text_score_is_weakened(self):
        text_store = FakeTextStore([
            {"id": "1", "content": "unrelated content", "score": 0.2},
        ])
        graph_store = FakeGraphStore(entities={"SomeoneElse"})
        verifier = TextGraphVerifier(text_store, graph_store)

        report = verifier.retrieve("query")
        assert report.verified_memories[0].verification == "weakened"

    def test_empty_graph_entities_gives_zero_coverage(self):
        text_store = FakeTextStore([
            {"id": "1", "content": "some content", "score": 0.5},
        ])
        graph_store = FakeGraphStore(entities=set())
        verifier = TextGraphVerifier(text_store, graph_store, graph_weight=0.4)

        report = verifier.retrieve("query")
        vm = report.verified_memories[0]
        # No graph signal at all -> combined score is purely the text contribution
        assert vm.combined_score == vm.text_score * (1 - verifier.graph_weight)


class TestOrphanBridging:
    def test_orphan_entity_gets_bridged_and_boosts_score(self):
        text_store = FakeTextStore([
            {"id": "1", "content": "Carol was also involved in the project", "score": 0.8},
        ])
        # "Carol" isn't in the graph walk, but get_entity_mentions confirms it exists elsewhere
        graph_store = FakeGraphStore(entities=set(), mentions={"Carol": ["mem-42"]})
        verifier = TextGraphVerifier(text_store, graph_store, orphan_threshold=0.3)

        report = verifier.retrieve("query")

        assert report.orphan_entities_found >= 1
        assert report.orphan_entities_bridged == 1
        assert "Carol" in report.verified_memories[0].bridged_entities

    def test_below_orphan_threshold_is_not_bridged(self):
        text_store = FakeTextStore([
            {"id": "1", "content": "Dave was mentioned in passing", "score": 0.1},
        ])
        graph_store = FakeGraphStore(entities=set(), mentions={"Dave": ["mem-1"]})
        verifier = TextGraphVerifier(text_store, graph_store, orphan_threshold=0.5)

        report = verifier.retrieve("query")
        assert report.orphan_entities_bridged == 0


class TestRetrieveOrdering:
    def test_results_sorted_by_combined_score_descending(self):
        text_store = FakeTextStore([
            {"id": "low", "content": "weak match", "score": 0.1},
            {"id": "high", "content": "Alice strong match", "score": 0.9},
        ])
        graph_store = FakeGraphStore(entities={"Alice"})
        verifier = TextGraphVerifier(text_store, graph_store)

        report = verifier.retrieve("query", n_results=2)
        scores = [vm.combined_score for vm in report.verified_memories]
        assert scores == sorted(scores, reverse=True)

    def test_n_results_caps_output(self):
        text_store = FakeTextStore([
            {"id": str(i), "content": f"item {i}", "score": 0.5} for i in range(10)
        ])
        graph_store = FakeGraphStore()
        verifier = TextGraphVerifier(text_store, graph_store)

        report = verifier.retrieve("query", n_results=3)
        assert len(report.verified_memories) == 3


def test_verification_report_summarize_does_not_error():
    text_store = FakeTextStore([{"id": "1", "content": "content", "score": 0.5}])
    graph_store = FakeGraphStore()
    verifier = TextGraphVerifier(text_store, graph_store)
    report = verifier.retrieve("query")
    assert isinstance(report.summarize(), str)
