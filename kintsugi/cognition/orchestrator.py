"""Hierarchical Supervisor routing — classify and dispatch requests.

The :class:`Orchestrator` maps incoming user messages to *skill domains*
(grants, volunteers, finance, ...) using keyword matching with an optional
LLM classification fallback for ambiguous requests.

When multiple candidate domains are detected or keyword confidence is below
threshold, the EFE (Expected Free Energy) calculator is invoked to score
each candidate and select the best policy, applying domain-specific weight
profiles for risk/ambiguity/epistemic trade-offs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from kintsugi.cognition.efe import (
    COMMUNICATIONS_WEIGHTS,
    DEFAULT_WEIGHTS,
    EFECalculator,
    EFEScore,
    EFEWeights,
    FINANCE_WEIGHTS,
    GRANTS_WEIGHTS,
)
from kintsugi.cognition.model_router import ModelRouter, ModelTier

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain-specific EFE weight mapping
# ---------------------------------------------------------------------------

DOMAIN_EFE_WEIGHTS: dict[str, EFEWeights] = {
    "grants": GRANTS_WEIGHTS,
    "finance": FINANCE_WEIGHTS,
    "communications": COMMUNICATIONS_WEIGHTS,
    "volunteers": DEFAULT_WEIGHTS,
    "impact": DEFAULT_WEIGHTS,
    "general": DEFAULT_WEIGHTS,
}


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoutingDecision:
    """Immutable record of a routing outcome."""

    skill_domain: str
    confidence: float
    reasoning: str
    model_tier: ModelTier
    efe_score: Optional[EFEScore] = None


@dataclass
class OrchestratorConfig:
    """Configuration for the :class:`Orchestrator`.

    Parameters
    ----------
    routing_table:
        ``{keyword: skill_domain}`` map used for fast keyword matching.
    fallback_domain:
        Domain returned when no keyword matches and LLM classification is
        unavailable or below threshold.
    confidence_threshold:
        Minimum confidence to accept a keyword match without escalation.
    """

    routing_table: dict[str, str] = field(default_factory=dict)
    fallback_domain: str = "general"
    confidence_threshold: float = 0.6


# ---------------------------------------------------------------------------
# Default routing table
# ---------------------------------------------------------------------------

_DEFAULT_ROUTING_TABLE: dict[str, str] = {
    # grants
    "grant": "grants",
    "funding": "grants",
    "proposal": "grants",
    "funder": "grants",
    "rfp": "grants",
    # volunteers
    "volunteer": "volunteers",
    "recruitment": "volunteers",
    "onboarding": "volunteers",
    "hours": "volunteers",
    # finance
    "budget": "finance",
    "expense": "finance",
    "revenue": "finance",
    "invoice": "finance",
    "financial": "finance",
    "accounting": "finance",
    # impact
    "impact": "impact",
    "outcome": "impact",
    "metric": "impact",
    "evaluation": "impact",
    "indicator": "impact",
    # communications
    "email": "communications",
    "newsletter": "communications",
    "social media": "communications",
    "press": "communications",
    "outreach": "communications",
    "donor": "communications",
    # general (catch-all keywords are not needed; it's the fallback)
}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Orchestrator:
    """Classify incoming messages and route them to skill domains.

    Parameters
    ----------
    config:
        Routing configuration.  Uses sensible defaults when *None*.
    model_router:
        Used to determine model tier for the routed task.
    llm_classifier:
        Optional async callable ``(message, domains) -> (domain, confidence)``
        injected for LLM-based disambiguation.  Keeps this module free of
        direct API dependencies.
    efe_calculator:
        Optional EFE calculator for active-inference-informed routing.
        Created automatically when *None*.
    """

    def __init__(
        self,
        config: OrchestratorConfig | None = None,
        model_router: ModelRouter | None = None,
        llm_classifier: Callable[..., Awaitable[tuple[str, float]]] | None = None,
        efe_calculator: EFECalculator | None = None,
    ) -> None:
        self._config = config or OrchestratorConfig(
            routing_table=dict(_DEFAULT_ROUTING_TABLE),
        )
        if not self._config.routing_table:
            self._config.routing_table = dict(_DEFAULT_ROUTING_TABLE)
        self._model_router = model_router or ModelRouter()
        self._llm_classifier = llm_classifier
        self._efe = efe_calculator or EFECalculator()

    # -- public API ---------------------------------------------------------

    async def classify_request(
        self,
        message: str,
        org_context: dict[str, Any] | None = None,
    ) -> RoutingDecision:
        """Classify *message* into a skill domain.

        1. Try keyword matching against the routing table.
        2. If multiple candidate domains are found or confidence is below
           threshold, use EFE scoring to disambiguate and select the best.
        3. If confidence is still below threshold **and** an LLM classifier
           was injected, delegate to the LLM.
        4. Otherwise fall back to ``config.fallback_domain``.
        """
        domain, confidence, reasoning, candidate_hits = self._keyword_match(message)

        efe_score: EFEScore | None = None

        # Use EFE scoring when there are multiple candidate domains or low confidence
        if len(candidate_hits) > 1 or confidence < self._config.confidence_threshold:
            efe_score = self._score_candidates_with_efe(candidate_hits, confidence)
            if efe_score is not None:
                domain = efe_score.policy_id
                reasoning = (
                    f"EFE-selected '{domain}' "
                    f"(total={efe_score.total:.3f}, "
                    f"risk={efe_score.risk_component:.3f}, "
                    f"ambiguity={efe_score.ambiguity_component:.3f}, "
                    f"epistemic={efe_score.epistemic_component:.3f})"
                )
                # Boost confidence when EFE provides a clear winner
                confidence = max(
                    confidence, 0.5 + 0.3 * (1.0 - max(efe_score.total, 0.0))
                )

        if (
            confidence < self._config.confidence_threshold
            and self._llm_classifier is not None
        ):
            try:
                domains = list(set(self._config.routing_table.values()))
                domains.append(self._config.fallback_domain)
                llm_domain, llm_confidence = await self._llm_classifier(
                    message, domains
                )
                if llm_confidence > confidence:
                    domain = llm_domain
                    confidence = llm_confidence
                    reasoning = "LLM classification"
                    efe_score = None
            except Exception:
                logger.exception("LLM classifier failed — using keyword result")

        tier = self._tier_for_domain(domain, efe_score)
        return RoutingDecision(
            skill_domain=domain,
            confidence=confidence,
            reasoning=reasoning,
            model_tier=tier,
            efe_score=efe_score,
        )

    async def route(
        self,
        message: str,
        org_id: str,
        context: dict[str, Any] | None = None,
    ) -> RoutingDecision:
        """Full routing pipeline: classify, validate, and log.

        Parameters
        ----------
        message:
            The user-facing request text.
        org_id:
            UUID of the organisation (used for logging context).
        context:
            Optional additional context forwarded to classification.
        """
        decision = await self.classify_request(message, org_context=context)

        # Build a dict suitable for temporal memory / audit trail.
        log_entry: dict[str, Any] = {
            "org_id": org_id,
            "message_preview": message[:120],
            "skill_domain": decision.skill_domain,
            "confidence": decision.confidence,
            "reasoning": decision.reasoning,
            "model_tier": decision.model_tier.value,
        }
        if decision.efe_score is not None:
            log_entry["efe_total"] = decision.efe_score.total
        logger.info("Routing decision: %s", log_entry)

        return decision

    def register_domain(self, domain: str, keywords: list[str]) -> None:
        """Add or update keywords for *domain* in the routing table."""
        for kw in keywords:
            self._config.routing_table[kw.lower()] = domain

    def get_routing_table(self) -> dict[str, str]:
        """Return a **copy** of the current routing table."""
        return dict(self._config.routing_table)

    # -- internals ----------------------------------------------------------

    def _keyword_match(
        self, message: str
    ) -> tuple[str, float, str, dict[str, int]]:
        """Return ``(domain, confidence, reasoning, hits)`` via keyword scan."""
        msg_lower = message.lower()
        hits: dict[str, int] = {}
        for keyword, domain in self._config.routing_table.items():
            count = len(re.findall(re.escape(keyword), msg_lower))
            if count:
                hits[domain] = hits.get(domain, 0) + count

        if not hits:
            return self._config.fallback_domain, 0.3, "no keyword match", hits

        best_domain = max(hits, key=hits.__getitem__)
        total_hits = sum(hits.values())
        confidence = min(0.95, 0.5 + 0.1 * hits[best_domain])
        reasoning = (
            f"keyword match: {hits[best_domain]}/{total_hits} hits for '{best_domain}'"
        )
        return best_domain, confidence, reasoning, hits

    def _score_candidates_with_efe(
        self,
        candidate_hits: dict[str, int],
        keyword_confidence: float,
    ) -> EFEScore | None:
        """Score candidate domains with EFE and return the best.

        Maps keyword-match confidence to the ``uncertainty`` parameter and
        domain specificity (hit count relative to total) to ``information_gain``.
        Applies domain-specific EFE weight profiles for each candidate.

        Parameters
        ----------
        candidate_hits:
            ``{domain: hit_count}`` from keyword matching.
        keyword_confidence:
            Overall confidence from keyword matching (0-1).

        Returns
        -------
        The best EFEScore, or None if no candidates to score.
        """
        if not candidate_hits:
            return None

        total_hits = max(sum(candidate_hits.values()), 1)
        uncertainty = 1.0 - keyword_confidence

        scores: list[EFEScore] = []
        for domain, hit_count in candidate_hits.items():
            weights = DOMAIN_EFE_WEIGHTS.get(domain, DEFAULT_WEIGHTS)
            information_gain = hit_count / total_hits

            predicted = {
                "relevance": information_gain,
                "specificity": hit_count / total_hits,
            }
            desired = {"relevance": 1.0, "specificity": 1.0}

            score = self._efe.calculate_efe(
                policy_id=domain,
                predicted_outcome=predicted,
                desired_outcome=desired,
                uncertainty=uncertainty,
                information_gain=information_gain,
                weights=weights,
            )
            scores.append(score)

        return self._efe.select_policy(scores)

    def _tier_for_domain(
        self,
        domain: str,
        efe_score: EFEScore | None = None,
    ) -> ModelTier:
        """EFE-informed tier assignment per domain.

        When an EFE score is available, higher risk components route to
        higher model tiers (BALANCED or POWERFUL) rather than FAST.  Without
        an EFE score, falls back to domain-based heuristics.

        Parameters
        ----------
        domain:
            The selected skill domain.
        efe_score:
            Optional EFE score from candidate scoring.
        """
        if efe_score is not None:
            if efe_score.risk_component > 0.3:
                return ModelTier.POWERFUL
            if efe_score.risk_component > 0.15:
                return ModelTier.BALANCED
            if efe_score.ambiguity_component > 0.2:
                return ModelTier.BALANCED

        # Fallback heuristic when no EFE score available
        if domain in ("finance", "grants"):
            return ModelTier.BALANCED
        return ModelTier.FAST
