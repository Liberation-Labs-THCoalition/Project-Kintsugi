"""Knowledge graph entity + triple extraction from memory content.

Built from Project Mnemosyne's hipporag-catrag-kg design spec (this
component had no reference implementation to vendor — see DESIGN.md in
that repo for the original architecture writeup). Uses spaCy NER
(CPU-only, no LLM calls) to extract entities, then infers relationships
via simple text co-occurrence within a character window.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from itertools import combinations

import spacy

logger = logging.getLogger(__name__)

# Entity types we care about. Others (CARDINAL, ORDINAL, etc.) are too noisy.
RELEVANT_ENTITY_TYPES = {
    "PERSON", "ORG", "GPE", "EVENT", "PRODUCT", "WORK_OF_ART", "FAC", "NORP", "LOC", "LAW",
}

_nlp: spacy.Language | None = None


def _load_spacy(model_name: str = "en_core_web_md") -> spacy.Language:
    """Load spaCy model, downloading it if necessary."""
    global _nlp
    if _nlp is not None:
        return _nlp
    try:
        _nlp = spacy.load(model_name, disable=["parser", "lemmatizer"])
        # We only need NER and tokenization. Disabling the full dependency
        # parser saves processing time, but it's also the component that
        # normally provides sentence boundaries (needed for ent.sent below)
        # — add the lightweight rule-based sentencizer back in its place.
        _nlp.add_pipe("sentencizer")
    except OSError:
        logger.warning("spaCy model %s not found, downloading...", model_name)
        from spacy.cli import download
        download(model_name)
        _nlp = spacy.load(model_name, disable=["parser", "lemmatizer"])
        _nlp.add_pipe("sentencizer")
    return _nlp


@dataclass(frozen=True)
class ExtractedEntity:
    """An entity extracted from text."""
    name: str
    entity_type: str  # spaCy label: PERSON, ORG, GPE, etc.
    char_start: int
    char_end: int
    context: str  # Surrounding sentence or clause


@dataclass(frozen=True)
class ExtractedTriple:
    """A (subject, predicate, object) triple extracted from text."""
    subject: str
    predicate: str
    object: str
    confidence: float


@dataclass
class ExtractionResult:
    """Complete extraction result for a single memory."""
    entities: list[ExtractedEntity] = field(default_factory=list)
    triples: list[ExtractedTriple] = field(default_factory=list)


def extract_entities(text: str, model_name: str = "en_core_web_md") -> list[ExtractedEntity]:
    """Extract named entities from text using spaCy NER.

    Args:
        text: The memory content (or query) to extract entities from.
        model_name: spaCy model to use.

    Returns:
        List of extracted entities with types and context.
    """
    nlp = _load_spacy(model_name)
    doc = nlp(text)

    entities = []
    seen_names: set[str] = set()

    for ent in doc.ents:
        if ent.label_ not in RELEVANT_ENTITY_TYPES:
            continue

        name = ent.text.strip()
        if len(name) < 2:
            continue

        name_key = name.lower()
        if name_key in seen_names:
            continue
        seen_names.add(name_key)

        sent = ent.sent
        context = sent.text.strip() if sent else text[max(0, ent.start_char - 50):ent.end_char + 50]

        entities.append(ExtractedEntity(
            name=name,
            entity_type=ent.label_,
            char_start=ent.start_char,
            char_end=ent.end_char,
            context=context,
        ))

    return entities


def extract_triples_cooccurrence(
    entities: list[ExtractedEntity],
    window_chars: int = 200,
) -> list[ExtractedTriple]:
    """Infer relationships from entity co-occurrence within a text window.

    The simplest relationship extraction strategy: if two entities appear
    within `window_chars` characters of each other, create a
    "co_occurs_with" triple. Confidence is inversely proportional to the
    distance between them.
    """
    triples = []
    for e1, e2 in combinations(entities, 2):
        distance = abs(e1.char_start - e2.char_start)
        if distance <= window_chars:
            confidence = 1.0 - 0.5 * (distance / window_chars)
            triples.append(ExtractedTriple(
                subject=e1.name,
                predicate="co_occurs_with",
                object=e2.name,
                confidence=round(confidence, 3),
            ))
    return triples


def run_extraction(text: str, model_name: str = "en_core_web_md") -> ExtractionResult:
    """Full extraction pipeline: entities + co-occurrence triples.

    Args:
        text: Memory content.
        model_name: spaCy model name.

    Returns:
        ExtractionResult with entities and triples.
    """
    entities = extract_entities(text, model_name)
    triples = extract_triples_cooccurrence(entities)
    return ExtractionResult(entities=entities, triples=triples)
