"""Two-stage decision classifier for Kintsugi routing.

Inspired by the Claude Code YOLO classifier pattern: most routing
decisions are obvious and don't need full EFE evaluation. A fast
rule-based Stage 1 handles the 90%+ of requests that match clear
patterns, while Stage 2 (full EFE + optional LLM) handles genuine
ambiguity.

Stage 1 — Fast Path (~1ms, no LLM call):
  - Single-domain keyword match with high confidence → auto-route
  - Known safe patterns (read-only queries, status checks) → auto-route
  - Explicit deny patterns (PII requests, surveillance) → hard block

Stage 2 — Full Evaluation (~100ms+):
  - Multiple competing domains
  - Ethics-adjacent requests (touching PII, finances, contact info)
  - Low keyword confidence
  - Requests that modify system configuration
  - Any request touching the EFE weights themselves

The classifier wraps the Orchestrator's existing classify_request
method, adding the fast path before it.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Classification stages and results
# ---------------------------------------------------------------------------


class ClassificationStage(str, Enum):
    """Which stage handled the routing decision."""
    FAST_ALLOW = "fast_allow"       # Stage 1 auto-routed
    FAST_DENY = "fast_deny"         # Stage 1 hard blocked
    ESCALATED = "escalated"         # Sent to Stage 2 (full EFE)


@dataclass(frozen=True)
class FastClassification:
    """Result of the fast classifier pre-screening."""
    stage: ClassificationStage
    domain: Optional[str] = None
    confidence: float = 0.0
    reason: str = ""
    elapsed_ms: float = 0.0


# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------


@dataclass
class FastClassifierConfig:
    """Configuration for the two-stage classifier.

    Parameters
    ----------
    high_confidence_threshold:
        Keyword confidence above which Stage 1 auto-routes without EFE.
    escalation_keywords:
        Keywords that ALWAYS escalate to Stage 2 regardless of confidence.
        These are ethics-adjacent or sensitive operations.
    deny_patterns:
        Regex patterns that trigger hard deny in Stage 1.
        These never reach a skill — they're blocked before routing.
    safe_patterns:
        Regex patterns for known-safe requests that can always
        fast-path (status checks, help requests, etc).
    """
    high_confidence_threshold: float = 0.75

    escalation_keywords: tuple[str, ...] = (
        # Ethics-adjacent
        "pii", "personal information", "social security",
        "private data", "confidential",
        # Financial sensitivity
        "transfer", "payment", "wire", "bank account",
        # System modification
        "change weights", "modify efe", "update ethics",
        "reconfigure", "override",
        # Contact/outreach
        "contact info", "phone number", "home address",
        "send email to", "message to",
    )

    deny_patterns: tuple[str, ...] = (
        # Surveillance
        r"track\s+(someone|person|individual|member)",
        r"monitor\s+(someone|person|individual|member)",
        r"surveil",
        # Data exfiltration
        r"export\s+all\s+(member|donor|contact)",
        r"dump\s+(database|records|contacts)",
        # Discrimination
        r"filter\b.*\b(by|based\s+on)\s+(race|gender|religion|orientation)",
        r"exclude\b.*\b(based\s+on|by)\s+(race|gender|religion|orientation)",
    )

    safe_patterns: tuple[str, ...] = (
        r"^(what|how|when|where|who|tell me about)\b",
        r"\b(status|progress|update|summary|report)\b",
        r"\b(help|explain|describe|show)\b",
        r"\b(list|search|find|look up)\b",
    )


# ---------------------------------------------------------------------------
# Fast Classifier
# ---------------------------------------------------------------------------


class FastClassifier:
    """Two-stage routing classifier.

    Sits in front of the Orchestrator's full EFE evaluation.
    Handles obvious cases fast, escalates ambiguity.

    Usage::

        classifier = FastClassifier()
        result = classifier.classify(message, keyword_domain, keyword_confidence, keyword_hits)

        if result.stage == ClassificationStage.FAST_ALLOW:
            # Skip EFE, route directly
            ...
        elif result.stage == ClassificationStage.FAST_DENY:
            # Block the request
            ...
        else:
            # result.stage == ClassificationStage.ESCALATED
            # Run full EFE evaluation
            ...
    """

    def __init__(self, config: FastClassifierConfig | None = None) -> None:
        self._config = config or FastClassifierConfig()
        self._compiled_deny = [
            re.compile(p, re.IGNORECASE) for p in self._config.deny_patterns
        ]
        self._compiled_safe = [
            re.compile(p, re.IGNORECASE) for p in self._config.safe_patterns
        ]
        # Metrics
        self._fast_allow_count = 0
        self._fast_deny_count = 0
        self._escalation_count = 0

    def classify(
        self,
        message: str,
        keyword_domain: str,
        keyword_confidence: float,
        keyword_hits: dict[str, int],
    ) -> FastClassification:
        """Pre-screen a routing decision.

        Parameters
        ----------
        message:
            Raw user message.
        keyword_domain:
            Best domain from keyword matching.
        keyword_confidence:
            Confidence from keyword matching (0-1).
        keyword_hits:
            ``{domain: hit_count}`` from keyword scan.

        Returns
        -------
        FastClassification with stage, domain, confidence, reason.
        """
        t0 = time.monotonic()
        msg_lower = message.lower()

        # --- DENY CHECK (always runs first) ---
        for pattern in self._compiled_deny:
            if pattern.search(msg_lower):
                self._fast_deny_count += 1
                elapsed = (time.monotonic() - t0) * 1000
                logger.warning("Fast classifier DENY: %s", pattern.pattern)
                return FastClassification(
                    stage=ClassificationStage.FAST_DENY,
                    reason=f"Blocked by deny pattern: {pattern.pattern}",
                    elapsed_ms=elapsed,
                )

        # --- ESCALATION CHECK (sensitive keywords) ---
        for esc_kw in self._config.escalation_keywords:
            if esc_kw in msg_lower:
                self._escalation_count += 1
                elapsed = (time.monotonic() - t0) * 1000
                logger.info(
                    "Fast classifier ESCALATE: sensitive keyword '%s'", esc_kw
                )
                return FastClassification(
                    stage=ClassificationStage.ESCALATED,
                    domain=keyword_domain,
                    confidence=keyword_confidence,
                    reason=f"Escalated: sensitive keyword '{esc_kw}'",
                    elapsed_ms=elapsed,
                )

        # --- MULTI-DOMAIN AMBIGUITY ---
        if len(keyword_hits) > 1:
            # Multiple domains competing — needs EFE to disambiguate
            top_two = sorted(keyword_hits.values(), reverse=True)[:2]
            if len(top_two) > 1 and top_two[0] - top_two[1] <= 1:
                # Close race — escalate
                self._escalation_count += 1
                elapsed = (time.monotonic() - t0) * 1000
                return FastClassification(
                    stage=ClassificationStage.ESCALATED,
                    domain=keyword_domain,
                    confidence=keyword_confidence,
                    reason=f"Escalated: close multi-domain race {dict(keyword_hits)}",
                    elapsed_ms=elapsed,
                )

        # --- FAST ALLOW (high confidence single domain) ---
        if (
            keyword_confidence >= self._config.high_confidence_threshold
            and len(keyword_hits) <= 1
        ):
            self._fast_allow_count += 1
            elapsed = (time.monotonic() - t0) * 1000
            return FastClassification(
                stage=ClassificationStage.FAST_ALLOW,
                domain=keyword_domain,
                confidence=keyword_confidence,
                reason=f"Fast-path: high confidence ({keyword_confidence:.2f}) single domain",
                elapsed_ms=elapsed,
            )

        # --- SAFE PATTERN CHECK ---
        # Safe patterns allow fast-path at a slightly lower bar than
        # raw high-confidence, but still respect the configured threshold.
        safe_threshold = self._config.high_confidence_threshold - 0.25
        for pattern in self._compiled_safe:
            if pattern.search(msg_lower) and keyword_confidence >= safe_threshold:
                self._fast_allow_count += 1
                elapsed = (time.monotonic() - t0) * 1000
                return FastClassification(
                    stage=ClassificationStage.FAST_ALLOW,
                    domain=keyword_domain,
                    confidence=keyword_confidence,
                    reason=f"Fast-path: safe pattern + moderate confidence",
                    elapsed_ms=elapsed,
                )

        # --- DEFAULT: ESCALATE ---
        self._escalation_count += 1
        elapsed = (time.monotonic() - t0) * 1000
        return FastClassification(
            stage=ClassificationStage.ESCALATED,
            domain=keyword_domain,
            confidence=keyword_confidence,
            reason="Default escalation: no fast-path match",
            elapsed_ms=elapsed,
        )

    @property
    def stats(self) -> dict[str, int]:
        """Return classification stage counts."""
        total = self._fast_allow_count + self._fast_deny_count + self._escalation_count
        return {
            "fast_allow": self._fast_allow_count,
            "fast_deny": self._fast_deny_count,
            "escalated": self._escalation_count,
            "total": total,
            "fast_path_rate": (
                self._fast_allow_count / total if total > 0 else 0.0
            ),
        }
