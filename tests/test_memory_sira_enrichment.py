"""Tests for kintsugi.memory.sira_enrichment."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from kintsugi.memory.sira_enrichment import (
    DomainMapper,
    LLMEnricher,
    QueryExpander,
    SIRAIndex,
    extract_terms,
)


@pytest.fixture
def index():
    idx = SIRAIndex(":memory:")
    yield idx
    idx.close()


def _mock_llm(text: str) -> AsyncMock:
    client = AsyncMock()
    response = AsyncMock()
    response.text = text
    client.complete.return_value = response
    return client


class TestExtractTerms:
    def test_parses_valid_json(self):
        raw = '{"terms": ["alpha", "beta"]}'
        assert extract_terms(raw) == ["alpha", "beta"]

    def test_lowercases_terms(self):
        raw = '{"terms": ["ALPHA"]}'
        assert extract_terms(raw) == ["alpha"]

    def test_handles_surrounding_prose(self):
        raw = 'Here you go:\n{"terms": ["alpha", "beta"]}\nHope that helps.'
        assert extract_terms(raw) == ["alpha", "beta"]

    def test_strips_think_tags(self):
        raw = '<think>reasoning here</think>{"terms": ["gamma"]}'
        assert extract_terms(raw) == ["gamma"]

    def test_empty_response_returns_empty_list(self):
        assert extract_terms("") == []

    def test_malformed_json_returns_empty_list(self):
        assert extract_terms("{not valid json") == []

    def test_filters_single_char_terms(self):
        raw = '{"terms": ["a", "valid"]}'
        assert extract_terms(raw) == ["valid"]


class TestSIRAIndex:
    def test_add_document_returns_id(self, index):
        doc_id = index.add_document("some content", "doc1")
        assert isinstance(doc_id, int)

    def test_add_document_duplicate_key_returns_existing_id(self, index):
        id1 = index.add_document("content a", "same-key")
        id2 = index.add_document("content b", "same-key")
        assert id1 == id2

    def test_search_before_enrichment_finds_nothing(self, index):
        index.add_document("aardvark migration patterns", "doc1")
        # No enrichment yet -> nothing indexed into doc_fts
        assert index.search("aardvark") == []

    def test_set_enrichment_makes_document_searchable(self, index):
        doc_id = index.add_document("aardvark migration patterns", "doc1")
        index.set_enrichment(doc_id, ["mammal", "wildlife"])
        results = index.search("mammal")
        assert len(results) == 1
        assert results[0]["doc_key"] == "doc1"

    def test_get_unenriched_lists_pending_docs(self, index):
        index.add_document("content", "doc1")
        unenriched = index.get_unenriched()
        assert len(unenriched) == 1

    def test_validate_term_not_in_index(self, index):
        valid, reason = index.validate_term("nonexistent")
        assert valid is False
        assert reason == "not_in_index"

    def test_validate_term_too_common(self, index):
        d1 = index.add_document("shared term everywhere", "d1")
        d2 = index.add_document("shared term again", "d2")
        index.set_enrichment(d1, [])
        index.set_enrichment(d2, [])
        index.build_term_stats()

        valid, reason = index.validate_term("shared", tau=0.1)
        assert valid is False
        assert "too_common" in reason

    def test_stats_reports_counts(self, index):
        doc_id = index.add_document("content", "doc1")
        index.set_enrichment(doc_id, ["term1"])
        index.build_term_stats()

        stats = index.stats()
        assert stats["total_docs"] == 1
        assert stats["enriched_docs"] == 1


class TestDomainMapper:
    def test_enrich_document_matches_trigger(self, index):
        mapper = DomainMapper(index, {"nyc": ["new york city", "big apple"]})
        doc_id = index.add_document("meeting in NYC next week", "doc1")

        terms = mapper.enrich_document(doc_id, "meeting in NYC next week")
        assert set(terms) == {"new york city", "big apple"}

    def test_enrich_document_no_match_returns_empty(self, index):
        mapper = DomainMapper(index, {"nyc": ["new york city"]})
        doc_id = index.add_document("meeting in London", "doc1")

        terms = mapper.enrich_document(doc_id, "meeting in London")
        assert terms == []

    def test_add_mapping_lowercases(self, index):
        mapper = DomainMapper(index)
        mapper.add_mapping("NYC", ["New York City"])
        assert mapper.mappings == {"nyc": ["new york city"]}

    def test_enrich_all_processes_pending_docs(self, index):
        mapper = DomainMapper(index, {"nyc": ["new york city"]})
        index.add_document("trip to NYC", "doc1")
        index.add_document("trip to LA", "doc2")

        result = mapper.enrich_all()
        assert result["total"] == 2
        assert result["enriched"] == 1


class TestLLMEnricher:
    @pytest.mark.asyncio
    async def test_enrich_document_stores_terms(self, index):
        llm = _mock_llm('{"terms": ["alpha", "beta"]}')
        doc_id = index.add_document("some content", "doc1")

        enricher = LLMEnricher(index, llm)
        terms = await enricher.enrich_document(doc_id, "some content")

        assert terms == ["alpha", "beta"]
        assert index.search("alpha") != []

    @pytest.mark.asyncio
    async def test_enrich_all_processes_all_pending(self, index):
        llm = _mock_llm('{"terms": ["alpha"]}')
        index.add_document("doc a", "a")
        index.add_document("doc b", "b")

        enricher = LLMEnricher(index, llm)
        result = await enricher.enrich_all(delay=0)

        assert result["total"] == 2
        assert result["enriched"] == 2
        assert llm.complete.await_count == 2


class TestQueryExpander:
    @pytest.mark.asyncio
    async def test_expand_accepts_valid_terms(self, index):
        d1 = index.add_document("content about widgets", "d1")
        index.set_enrichment(d1, ["gadget"])
        # A second, unrelated document keeps "gadget"'s doc-frequency ratio
        # low enough to pass validate_term's too-common check.
        d2 = index.add_document("something else entirely", "d2")
        index.set_enrichment(d2, [])
        index.build_term_stats()

        llm = _mock_llm('{"terms": ["gadget"]}')
        expander = QueryExpander(index, llm, tau=0.9)

        result = await expander.expand("widgets")
        assert "gadget" in result["added_terms"]
        assert "gadget" in result["expanded"]

    @pytest.mark.asyncio
    async def test_expand_rejects_unknown_terms(self, index):
        llm = _mock_llm('{"terms": ["never_seen_term"]}')
        expander = QueryExpander(index, llm)

        result = await expander.expand("query")
        assert result["added_terms"] == []
        assert result["expanded"] == "query"
