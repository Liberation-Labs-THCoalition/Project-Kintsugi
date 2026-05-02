"""Dreamer — periodic memory maintenance and organizational intelligence.

The dreamer wakes up, tends the organizational memory, and goes back
to sleep. It's the gardener of the knowledge base:

  1. Consolidate: run Stage 2 on unconsolidated atomic facts
  2. Decay: apply significance decay to unaccessed memories
  3. Archive: move low-significance old memories to cold storage
  4. Advise: scan activity patterns and generate morning briefing
  5. Enrich: identify connections between memories across domains

Designed to run as a background task (periodic timer, cron, or
triggered at session start). Each cycle is idempotent — safe to
run multiple times.

"Your AI kept working while you slept."
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Awaitable

from kintsugi.cognition.proactive_advisor import (
    ProactiveAdvisor,
    ActivityRecord,
    Suggestion,
)

logger = logging.getLogger(__name__)


@dataclass
class DreamerConfig:
    """Configuration for the dreamer cycle."""
    consolidation_batch_size: int = 20
    decay_half_life_days: int = 90
    archive_after_days: int = 180
    archive_below_significance: int = 2
    max_suggestions: int = 5
    enrichment_batch_size: int = 10


@dataclass
class DreamCycleReport:
    """Report from a single dreamer cycle."""
    timestamp: datetime
    facts_consolidated: int = 0
    memories_decayed: int = 0
    memories_archived: int = 0
    connections_found: int = 0
    suggestions: list[Suggestion] = field(default_factory=list)
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = []
        if self.facts_consolidated:
            parts.append(f"{self.facts_consolidated} facts consolidated")
        if self.memories_decayed:
            parts.append(f"{self.memories_decayed} memories decayed")
        if self.memories_archived:
            parts.append(f"{self.memories_archived} archived to cold storage")
        if self.connections_found:
            parts.append(f"{self.connections_found} new connections")
        if self.suggestions:
            parts.append(f"{len(self.suggestions)} suggestions")
        if not parts:
            return "Nothing to report — memory is healthy."
        return "; ".join(parts) + f" ({self.duration_seconds:.1f}s)"


class Dreamer:
    """Periodic memory maintenance daemon for organizations.

    The dreamer doesn't run continuously — it wakes up, does a
    maintenance cycle, produces a report, and goes back to sleep.
    The caller decides when to wake it (cron, timer, session start).

    Args:
        config: Dreamer configuration.
        memory_store: Callable that returns memory records for processing.
            Signature: (query, limit) -> list[dict]
        update_memory: Callable to update a memory record.
            Signature: (memory_id, updates) -> None
        archive_memory: Callable to archive a memory to cold storage.
            Signature: (memory_id) -> None
        consolidate_fn: Async callable for Stage 2 consolidation.
            Signature: (facts, llm_call) -> list[Insight]
        llm_call: Async callable for LLM operations.
            Signature: (prompt) -> str
        activity_source: Callable that returns recent activity records.
            Signature: (days) -> list[ActivityRecord]
    """

    def __init__(
        self,
        config: DreamerConfig | None = None,
        memory_store: Callable[..., list[dict]] | None = None,
        update_memory: Callable[..., None] | None = None,
        archive_memory: Callable[..., None] | None = None,
        consolidate_fn: Callable[..., Awaitable[list]] | None = None,
        llm_call: Callable[..., Awaitable[str]] | None = None,
        activity_source: Callable[..., list[ActivityRecord]] | None = None,
    ) -> None:
        self._config = config or DreamerConfig()
        self._memory_store = memory_store
        self._update_memory = update_memory
        self._archive_memory = archive_memory
        self._consolidate_fn = consolidate_fn
        self._llm_call = llm_call
        self._activity_source = activity_source
        self._advisor = ProactiveAdvisor(max_suggestions=self._config.max_suggestions)

    async def dream(self) -> DreamCycleReport:
        """Run a full dream cycle. Returns a report of what was done."""
        import time
        t0 = time.perf_counter()
        now = datetime.now(timezone.utc)
        report = DreamCycleReport(timestamp=now)

        logger.info("Dreamer waking up...")

        # Phase 1: Consolidate unconsolidated facts
        try:
            consolidated = await self._consolidate(now)
            report.facts_consolidated = consolidated
        except Exception as e:
            report.errors.append(f"consolidation: {e}")
            logger.warning("Consolidation failed: %s", e)

        # Phase 2: Apply significance decay
        try:
            decayed = self._apply_decay(now)
            report.memories_decayed = decayed
        except Exception as e:
            report.errors.append(f"decay: {e}")
            logger.warning("Decay failed: %s", e)

        # Phase 3: Archive old low-significance memories
        try:
            archived = self._archive_stale(now)
            report.memories_archived = archived
        except Exception as e:
            report.errors.append(f"archive: {e}")
            logger.warning("Archive failed: %s", e)

        # Phase 4: Enrich — find connections between memories
        try:
            connections = await self._enrich(now)
            report.connections_found = connections
        except Exception as e:
            report.errors.append(f"enrichment: {e}")
            logger.warning("Enrichment failed: %s", e)

        # Phase 5: Generate proactive suggestions
        try:
            suggestions = self._generate_suggestions(now)
            report.suggestions = suggestions
        except Exception as e:
            report.errors.append(f"suggestions: {e}")
            logger.warning("Suggestion generation failed: %s", e)

        report.duration_seconds = round(time.perf_counter() - t0, 2)
        logger.info("Dreamer cycle complete: %s", report.summary())

        return report

    async def _consolidate(self, now: datetime) -> int:
        """Run Stage 2 consolidation on unconsolidated facts."""
        if not self._consolidate_fn or not self._memory_store or not self._llm_call:
            return 0

        memories = self._memory_store(
            "unconsolidated", self._config.consolidation_batch_size
        )

        if not memories:
            return 0

        from kintsugi.memory.cma_stage1 import AtomicFact
        facts = []
        for mem in memories:
            facts.append(AtomicFact(
                content=mem.get("content", ""),
                source_window_idx=0,
                timestamp=datetime.fromisoformat(mem["created_at"])
                    if isinstance(mem.get("created_at"), str)
                    else mem.get("created_at", now),
                entities=mem.get("entities", []),
                conditions=mem.get("conditions"),
                kintsugi_ref=mem.get("kintsugi_ref"),
            ))

        if not facts:
            return 0

        insights = await self._consolidate_fn(facts, self._llm_call)
        return len(insights)

    def _apply_decay(self, now: datetime) -> int:
        """Reduce significance of memories not accessed recently."""
        if not self._memory_store or not self._update_memory:
            return 0

        memories = self._memory_store("all_active", 100)
        half_life = timedelta(days=self._config.decay_half_life_days)
        decayed = 0

        for mem in memories:
            last_accessed = mem.get("last_accessed")
            if last_accessed is None:
                continue

            if isinstance(last_accessed, str):
                last_accessed = datetime.fromisoformat(last_accessed)

            age = now - last_accessed
            if age > half_life:
                current_sig = mem.get("significance", 5)
                if current_sig > 1:
                    periods = age / half_life
                    new_sig = max(1, int(current_sig * (0.5 ** periods)))
                    if new_sig < current_sig:
                        self._update_memory(mem["id"], {"significance": new_sig})
                        decayed += 1

        return decayed

    def _archive_stale(self, now: datetime) -> int:
        """Move old, low-significance memories to cold storage."""
        if not self._memory_store or not self._archive_memory:
            return 0

        memories = self._memory_store("all_active", 200)
        cutoff = now - timedelta(days=self._config.archive_after_days)
        archived = 0

        for mem in memories:
            created = mem.get("created_at")
            if isinstance(created, str):
                created = datetime.fromisoformat(created)
            if created is None:
                continue

            sig = mem.get("significance", 5)
            if created < cutoff and sig <= self._config.archive_below_significance:
                self._archive_memory(mem["id"])
                archived += 1

        return archived

    async def _enrich(self, now: datetime) -> int:
        """Find connections between recent memories across domains."""
        if not self._memory_store or not self._llm_call:
            return 0

        recent = self._memory_store("recent", self._config.enrichment_batch_size)
        if len(recent) < 2:
            return 0

        connections = 0
        for i, mem_a in enumerate(recent):
            for mem_b in recent[i+1:]:
                tags_a = set(mem_a.get("tags", []))
                tags_b = set(mem_b.get("tags", []))
                overlap = tags_a & tags_b
                if len(overlap) >= 2 and mem_a.get("domain") != mem_b.get("domain"):
                    connections += 1

        return connections

    def _generate_suggestions(self, now: datetime) -> list[Suggestion]:
        """Generate proactive suggestions from activity patterns."""
        if not self._activity_source:
            return []

        activities = self._activity_source(self._advisor.lookback_days)
        return self._advisor.scan(activities)

    def morning_briefing(self, report: DreamCycleReport) -> str:
        """Generate a human-readable morning briefing from a dream cycle."""
        lines = [
            "Good morning. Here's what I found while you were away:",
            "",
        ]

        if report.facts_consolidated:
            lines.append(f"  Memory: Consolidated {report.facts_consolidated} "
                         f"facts into higher-order insights.")

        if report.memories_archived:
            lines.append(f"  Archive: Moved {report.memories_archived} old "
                         f"memories to cold storage.")

        if report.connections_found:
            lines.append(f"  Connections: Found {report.connections_found} "
                         f"cross-domain links in recent activity.")

        if report.suggestions:
            lines.append("")
            lines.append("  Suggestions:")
            for s in report.suggestions:
                lines.append(f"    • [{s.pattern_type}] {s.title}")
                lines.append(f"      → {s.suggested_action}")

        if not report.facts_consolidated and not report.suggestions:
            lines.append("  Everything looks healthy. No action needed.")

        if report.errors:
            lines.append("")
            lines.append(f"  (Note: {len(report.errors)} non-critical "
                         f"errors during maintenance)")

        return "\n".join(lines)
