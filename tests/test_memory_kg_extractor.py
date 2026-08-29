"""Tests for kintsugi.memory.kg_extractor.

Uses the real en_core_web_md spaCy model (required dependency — see
settings.KG_SPACY_MODEL / pyproject.toml).
"""

from __future__ import annotations

from kintsugi.memory.kg_extractor import (
    ExtractedEntity,
    extract_entities,
    extract_triples_cooccurrence,
    run_extraction,
)


class TestExtractEntities:
    def test_extracts_person_and_org(self):
        text = "Alice Chen met with representatives from Acme Corporation yesterday."
        entities = extract_entities(text)
        names = {e.name for e in entities}
        assert "Alice Chen" in names
        assert "Acme Corporation" in names

    def test_deduplicates_case_insensitively(self):
        text = "Acme Corporation announced results. ACME CORPORATION stock rose."
        entities = extract_entities(text)
        names_lower = [e.name.lower() for e in entities]
        assert names_lower.count("acme corporation") == 1

    def test_skips_very_short_entities(self):
        text = "X met with Y about it."
        entities = extract_entities(text)
        assert all(len(e.name) >= 2 for e in entities)

    def test_no_entities_in_plain_text(self):
        text = "the quick brown fox jumps over the lazy dog"
        entities = extract_entities(text)
        assert entities == []

    def test_entity_has_context(self):
        text = "Bob Smith works at Globex. He started in March."
        entities = extract_entities(text)
        bob = next(e for e in entities if "Bob" in e.name)
        assert "Bob Smith" in bob.context


class TestExtractTriplesCooccurrence:
    def test_nearby_entities_form_triple(self):
        entities = [
            ExtractedEntity(name="Alice", entity_type="PERSON", char_start=0, char_end=5, context=""),
            ExtractedEntity(name="Bob", entity_type="PERSON", char_start=10, char_end=13, context=""),
        ]
        triples = extract_triples_cooccurrence(entities, window_chars=200)
        assert len(triples) == 1
        assert triples[0].subject == "Alice"
        assert triples[0].object == "Bob"
        assert triples[0].predicate == "co_occurs_with"

    def test_distant_entities_no_triple(self):
        entities = [
            ExtractedEntity(name="Alice", entity_type="PERSON", char_start=0, char_end=5, context=""),
            ExtractedEntity(name="Bob", entity_type="PERSON", char_start=5000, char_end=5003, context=""),
        ]
        triples = extract_triples_cooccurrence(entities, window_chars=200)
        assert triples == []

    def test_confidence_decreases_with_distance(self):
        close_entities = [
            ExtractedEntity(name="A", entity_type="PERSON", char_start=0, char_end=1, context=""),
            ExtractedEntity(name="B", entity_type="PERSON", char_start=10, char_end=11, context=""),
        ]
        far_entities = [
            ExtractedEntity(name="A", entity_type="PERSON", char_start=0, char_end=1, context=""),
            ExtractedEntity(name="B", entity_type="PERSON", char_start=190, char_end=191, context=""),
        ]
        close_triple = extract_triples_cooccurrence(close_entities, window_chars=200)[0]
        far_triple = extract_triples_cooccurrence(far_entities, window_chars=200)[0]
        assert close_triple.confidence > far_triple.confidence

    def test_single_entity_no_triples(self):
        entities = [
            ExtractedEntity(name="Alice", entity_type="PERSON", char_start=0, char_end=5, context=""),
        ]
        assert extract_triples_cooccurrence(entities) == []


class TestRunExtraction:
    def test_full_pipeline_returns_entities_and_triples(self):
        text = "Alice Chen and Bob Diaz co-founded Acme Corporation in Springfield."
        result = run_extraction(text)
        assert len(result.entities) >= 2
        assert len(result.triples) >= 1
