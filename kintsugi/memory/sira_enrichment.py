"""SIRA Enrichment — vocabulary bridging for agent memory retrieval.

Vendored and adapted from Project Mnemosyne's sira-enrichment component.
Closes the gap between how an agent searches and how memories are stored,
via three modes:
  1. LLM corpus enrichment (offline batch) — generate missing vocabulary per doc
  2. Domain vocabulary mapping (offline, no LLM) — static synonym expansion
  3. Query expansion (online) — predict answer terms, validate against index

Based on arXiv:2605.06647 (Facebook SIRA), adapted for agent memory systems.

Adaptation note: the original used a synchronous ``requests.post()`` call
to a local Ollama server. This version calls Kintsugi's own
``AnthropicClient`` instead (no local model dependency), so ``LLMEnricher``
and ``QueryExpander`` are async. ``SIRAIndex`` and ``DomainMapper`` have no
LLM dependency and are unchanged.
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
from pathlib import Path

from kintsugi.cognition.llm_client import AnthropicClient
from kintsugi.cognition.model_router import ModelTier

DEFAULT_ENRICHMENT_PROMPT = """You are a vocabulary enrichment agent. Given a document, generate additional search terms that would help someone find this document using different vocabulary.

Include:
- Alternate names, abbreviations, and acronyms
- Related technical terms and synonyms
- People referenced by alternate names or roles
- Project names by alternate references
- Key concepts rephrased in different vocabulary

Output ONLY a JSON object: {"terms": ["term1", "term2", ...]}
No explanation. 20-40 terms maximum."""

DEFAULT_QUERY_PROMPT = """You are a retrieval agent. Given a search query, predict terms that would appear in a relevant document.

Think about:
- What alternate vocabulary might the document use?
- What related concepts would be mentioned?
- What names, projects, or technical terms are relevant?

Output ONLY a JSON object: {"terms": ["term1", "term2", ...]}
No explanation. 10-20 terms maximum."""


def extract_terms(llm_response: str) -> list[str]:
    if not llm_response:
        return []
    try:
        clean = re.sub(r"<think>.*?</think>", "", llm_response, flags=re.DOTALL).strip()
        start = clean.find("{")
        end = clean.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(clean[start:end])
            terms = data.get("terms", [])
            return [t.lower().strip() for t in terms if isinstance(t, str) and len(t) > 1]
    except json.JSONDecodeError:
        pass
    return []


class SIRAIndex:
    """FTS5-backed enrichment index with document frequency tracking."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self._init_schema()

    def _init_schema(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT,
                doc_key TEXT UNIQUE,
                content TEXT,
                enriched_terms TEXT,
                enriched_at REAL
            )
        """)
        self.conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS doc_fts USING fts5(
                content, enriched_terms, source
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS term_stats (
                term TEXT PRIMARY KEY,
                doc_freq INTEGER DEFAULT 0,
                total_docs INTEGER DEFAULT 0
            )
        """)
        self.conn.commit()

    def add_document(self, content: str, doc_key: str, source: str = "default") -> int | None:
        try:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO documents (source, doc_key, content) VALUES (?, ?, ?)",
                (source, doc_key, content)
            )
            self.conn.commit()
            if cur.lastrowid:
                return cur.lastrowid
            row = self.conn.execute(
                "SELECT id FROM documents WHERE doc_key = ?", (doc_key,)
            ).fetchone()
            return row[0] if row else None
        except sqlite3.Error:
            return None

    def set_enrichment(self, doc_id: int, terms: list[str]):
        terms_str = " ".join(terms)
        content = self.conn.execute(
            "SELECT content, source FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if not content:
            return

        self.conn.execute(
            "UPDATE documents SET enriched_terms = ?, enriched_at = ? WHERE id = ?",
            (terms_str, time.time(), doc_id)
        )
        existing = self.conn.execute(
            "SELECT rowid FROM doc_fts WHERE rowid = ?", (doc_id,)
        ).fetchone()
        if existing:
            self.conn.execute("DELETE FROM doc_fts WHERE rowid = ?", (doc_id,))
        self.conn.execute(
            "INSERT INTO doc_fts(rowid, content, enriched_terms, source) VALUES (?, ?, ?, ?)",
            (doc_id, content[0], terms_str, content[1])
        )
        self.conn.commit()

    def get_unenriched(self) -> list[tuple[int, str]]:
        return self.conn.execute(
            "SELECT id, content FROM documents WHERE enriched_terms IS NULL"
        ).fetchall()

    def build_term_stats(self):
        self.conn.execute("DELETE FROM term_stats")
        rows = self.conn.execute(
            "SELECT id, content, enriched_terms FROM documents WHERE enriched_terms IS NOT NULL"
        ).fetchall()
        total = len(rows)
        counts: dict[str, int] = {}
        for _, content, enriched in rows:
            words = set(re.findall(r'\b\w+\b', f"{content} {enriched}".lower()))
            for w in words:
                counts[w] = counts.get(w, 0) + 1
        for term, freq in counts.items():
            self.conn.execute(
                "INSERT OR REPLACE INTO term_stats (term, doc_freq, total_docs) VALUES (?, ?, ?)",
                (term, freq, total)
            )
        self.conn.commit()
        return len(counts), total

    def validate_term(self, term: str, tau: float = 0.5) -> tuple[bool, str]:
        row = self.conn.execute(
            "SELECT doc_freq, total_docs FROM term_stats WHERE term = ?",
            (term.lower(),)
        ).fetchone()
        if row is None:
            return False, "not_in_index"
        if row[1] > 0 and row[0] / row[1] > tau:
            return False, f"too_common ({row[0]}/{row[1]})"
        return True, "accepted"

    def search(self, query: str, limit: int = 10) -> list[dict]:
        fts_query = " OR ".join(f'"{w}"' for w in query.split() if len(w) > 2)
        if not fts_query:
            return []
        rows = self.conn.execute("""
            SELECT d.id, d.source, d.doc_key,
                   snippet(doc_fts, 0, '', '', '...', 32) as snippet,
                   doc_fts.rank as score
            FROM doc_fts
            JOIN documents d ON d.id = doc_fts.rowid
            WHERE doc_fts MATCH ?
            ORDER BY doc_fts.rank
            LIMIT ?
        """, (fts_query, limit)).fetchall()
        return [
            {"id": r[0], "source": r[1], "doc_key": r[2],
             "snippet": r[3], "score": r[4]}
            for r in rows
        ]

    def stats(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        enriched = self.conn.execute(
            "SELECT COUNT(*) FROM documents WHERE enriched_terms IS NOT NULL"
        ).fetchone()[0]
        terms = self.conn.execute("SELECT COUNT(*) FROM term_stats").fetchone()[0]
        return {"total_docs": total, "enriched_docs": enriched, "unique_terms": terms}

    def close(self):
        self.conn.close()


class LLMEnricher:
    """Phase 1a: LLM-based corpus enrichment (offline batch).

    For each document, sends a truncated snippet to the LLM with a
    domain-appropriate system prompt. LLM generates missing vocabulary.
    Terms are stored in the search index alongside original content.
    """

    def __init__(
        self,
        index: SIRAIndex,
        llm_client: AnthropicClient,
        system_prompt: str | None = None,
    ):
        self.index = index
        self.llm_client = llm_client
        self.system_prompt = system_prompt or DEFAULT_ENRICHMENT_PROMPT

    async def enrich_document(self, doc_id: int, content: str,
                               max_snippet: int = 3000) -> list[str]:
        snippet = content[:max_snippet]
        response = await self.llm_client.complete(
            snippet, system=self.system_prompt,
            tier=ModelTier.FAST, max_tokens=512, temperature=0.1,
        )
        terms = extract_terms(response.text)
        if terms:
            self.index.set_enrichment(doc_id, terms)
        return terms

    async def enrich_all(self, delay: float = 0.5) -> dict:
        unenriched = self.index.get_unenriched()
        results = {"total": len(unenriched), "enriched": 0, "failed": 0, "terms": 0}
        for doc_id, content in unenriched:
            terms = await self.enrich_document(doc_id, content)
            if terms:
                results["enriched"] += 1
                results["terms"] += len(terms)
            else:
                results["failed"] += 1
            if delay > 0:
                await asyncio.sleep(delay)
        self.index.build_term_stats()
        return results


class DomainMapper:
    """Phase 1b: Domain vocabulary mapping (offline, no LLM).

    Static synonym tables map known entities to their alternate names.
    Fast, deterministic, zero inference cost. Good for org memory where
    entities are well-known.
    """

    def __init__(self, index: SIRAIndex, mappings: dict[str, list[str]] | None = None):
        self.index = index
        self.mappings = mappings or {}

    def add_mapping(self, trigger: str, expansions: list[str]):
        self.mappings[trigger.lower()] = [e.lower() for e in expansions]

    def load_mappings(self, path: str):
        data = json.loads(Path(path).read_text())
        for trigger, expansions in data.items():
            self.add_mapping(trigger, expansions)

    def enrich_document(self, doc_id: int, content: str) -> list[str]:
        content_lower = content.lower()
        matched_terms: list[str] = []
        for trigger, expansions in self.mappings.items():
            if trigger in content_lower:
                matched_terms.extend(expansions)
        matched_terms = list(set(matched_terms))
        if matched_terms:
            self.index.set_enrichment(doc_id, matched_terms)
        return matched_terms

    def enrich_all(self) -> dict:
        unenriched = self.index.get_unenriched()
        results = {"total": len(unenriched), "enriched": 0, "terms": 0}
        for doc_id, content in unenriched:
            terms = self.enrich_document(doc_id, content)
            if terms:
                results["enriched"] += 1
                results["terms"] += len(terms)
        self.index.build_term_stats()
        return results

    def save_mappings(self, path: str):
        Path(path).write_text(json.dumps(self.mappings, indent=2))


class QueryExpander:
    """Phase 2: Online query expansion with DF validation.

    Before searching, the LLM predicts expected answer terms. Each term
    is validated against index statistics — must exist in corpus and not
    be too common. Expanded query weights original + expansion terms.
    """

    def __init__(
        self,
        index: SIRAIndex,
        llm_client: AnthropicClient,
        system_prompt: str | None = None,
        tau: float = 0.5,
        weight: float = 0.5,
    ):
        self.index = index
        self.llm_client = llm_client
        self.system_prompt = system_prompt or DEFAULT_QUERY_PROMPT
        self.tau = tau
        self.weight = weight

    async def expand(self, query: str) -> dict:
        response = await self.llm_client.complete(
            query, system=self.system_prompt,
            tier=ModelTier.FAST, max_tokens=256, temperature=0.1,
        )
        candidates = extract_terms(response.text)

        accepted, rejected = [], []
        for term in candidates:
            valid, reason = self.index.validate_term(term, self.tau)
            if valid:
                accepted.append(term)
            else:
                rejected.append((term, reason))

        expanded = f"{query} {' '.join(accepted)}" if accepted else query

        return {
            "original": query,
            "expanded": expanded,
            "added_terms": accepted,
            "rejected_terms": rejected,
            "weight": self.weight,
        }

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        expansion = await self.expand(query)
        return self.index.search(expansion["expanded"], limit)


class MemoryEnricher:
    """Convenience wrapper for domain-mapping enrichment of an agent's
    memory database.

    Reads memories from SQLite, enriches the search_terms column using
    domain mapping. Does NOT modify memory content. (LLM-based enrichment
    is available directly via LLMEnricher; this wrapper stays domain-only
    to avoid threading async through a thin convenience class.)
    """

    def __init__(self, memory_db_path: str, mappings: dict | None = None):
        self.memory_db = memory_db_path
        self.mappings = mappings or {}

    def enrich(self, batch_size: int = 100) -> dict:
        conn = sqlite3.connect(self.memory_db)
        conn.row_factory = sqlite3.Row

        needs_enrichment = conn.execute("""
            SELECT id, content FROM memories
            WHERE search_terms IS NULL OR search_terms = ''
            LIMIT ?
        """, (batch_size,)).fetchall()

        results = {"total": len(needs_enrichment), "enriched": 0, "terms": 0}

        for mem in needs_enrichment:
            content_lower = mem["content"].lower()
            terms: list[str] = []
            for trigger, expansions in self.mappings.items():
                if trigger.lower() in content_lower:
                    terms.extend(expansions)
            terms = list({t.lower() for t in terms})

            if terms:
                terms_str = " ".join(terms)
                conn.execute(
                    "UPDATE memories SET search_terms = ? WHERE id = ?",
                    (terms_str, mem["id"])
                )
                results["enriched"] += 1
                results["terms"] += len(terms)

        conn.commit()
        conn.close()
        return results
