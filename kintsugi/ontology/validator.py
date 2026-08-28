"""Ontological output validator — runtime trust assessment.

Bridges the ontology kernel and detection channels (geometric or behavioral)
to answer: "Is this output ontologically valid?"

Two tiers:
  Tier 1 (Mounted): geometric channels from Oracle Loop — hidden state access
  Tier 2 (API): behavioral/statistical channels — logprobs + consistency only

The kernel doesn't care which tier answers. Same interface, different
evidence quality.

This closes the L4 gap identified in FAOS (arXiv:2604.00555):
output-side ontological validation. Nobody else has both a formal ontology
AND a geometric detection stack on the same inference pass.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Sequence

from .kernel import OntologyKernel

logger = logging.getLogger(__name__)


class Tier(str, Enum):
    MOUNTED = "mounted"
    API = "api"


class Verdict(str, Enum):
    VALID = "valid"
    CONTESTED = "contested"
    BLOCKED = "blocked"


@dataclass
class ChannelEvidence:
    """Evidence from a single detection channel."""
    channel_name: str
    tier: Tier
    score: float
    threshold: float
    fired: bool
    confidence: float = 1.0
    detail: str = ""

    @property
    def above_threshold(self) -> bool:
        return self.score > self.threshold


@dataclass
class ValidationResult:
    """Aggregate result from all available channels."""
    verdict: Verdict
    evidence: list[ChannelEvidence] = field(default_factory=list)
    tier_used: Tier = Tier.API
    aggregate_confidence: float = 1.0
    ontology_violations: list[str] = field(default_factory=list)

    @property
    def n_channels_fired(self) -> int:
        return sum(1 for e in self.evidence if e.fired)

    @property
    def channels_available(self) -> int:
        return len(self.evidence)

    def summary(self) -> str:
        fired = [e.channel_name for e in self.evidence if e.fired]
        return (f"{self.verdict.value} ({self.tier_used.value}): "
                f"{self.n_channels_fired}/{self.channels_available} channels fired"
                f"{', fired: ' + ', '.join(fired) if fired else ''}")


class DetectionChannel(ABC):
    """Protocol for any detection channel — geometric or behavioral."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def tier(self) -> Tier: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @abstractmethod
    def evaluate(self, context: dict[str, Any]) -> ChannelEvidence:
        """Evaluate this channel and return evidence.

        Context keys depend on tier:
          Mounted: 'report' (DetectionReport), 'acts' (activations)
          API: 'response' (str), 'logprobs' (list), 'prompt' (str)
        """
        ...


# === MOUNTED CHANNELS (Tier 1) ===

class ConsequentialityChannel(DetectionChannel):
    """L47 deception amplifier — consequentiality detection."""

    name = "consequentiality"
    tier = Tier.MOUNTED
    description = "Detects high-stakes territory via L43-L47 projection gradient"

    def __init__(self, threshold: float = 1.0):
        self.threshold = threshold

    def evaluate(self, context: dict[str, Any]) -> ChannelEvidence:
        report = context.get("report")
        if report is None:
            return ChannelEvidence(self.name, self.tier, 0, self.threshold, False,
                                   confidence=0, detail="No detection report")
        l47 = report.projections.get(47, 0)
        return ChannelEvidence(
            self.name, self.tier, l47, self.threshold,
            fired=l47 > self.threshold,
            confidence=0.95,
            detail=f"L47={l47:.2f} (threshold={self.threshold})",
        )


class SycophancyChannel(DetectionChannel):
    """L27 sycophantic pressure detection."""

    name = "sycophancy_pressure"
    tier = Tier.MOUNTED
    description = "Detects sycophantic framing via L27 projection shift"

    def __init__(self, threshold: float = -8.0):
        self.threshold = threshold

    def evaluate(self, context: dict[str, Any]) -> ChannelEvidence:
        report = context.get("report")
        if report is None:
            return ChannelEvidence(self.name, self.tier, 0, self.threshold, False,
                                   confidence=0, detail="No detection report")
        l27 = report.projections.get(27, 0)
        return ChannelEvidence(
            self.name, self.tier, l27, self.threshold,
            fired=l27 > self.threshold,
            confidence=0.85,
            detail=f"L27={l27:.2f}",
        )


class ConfabChannel(DetectionChannel):
    """Centroid confabulation projection."""

    name = "confabulation"
    tier = Tier.MOUNTED
    description = "Detects confabulation via centroid projection at L3-L15"

    def __init__(self, threshold: float = 12.0):
        self.threshold = threshold

    def evaluate(self, context: dict[str, Any]) -> ChannelEvidence:
        report = context.get("report")
        if report is None:
            return ChannelEvidence(self.name, self.tier, 0, self.threshold, False,
                                   confidence=0, detail="No detection report")
        confab = report.centroid_projs.get("confab", 0)
        return ChannelEvidence(
            self.name, self.tier, confab, self.threshold,
            fired=confab > self.threshold,
            confidence=0.80,
            detail=f"confab_proj={confab:.2f}",
        )


class EntropyChannel(DetectionChannel):
    """Logit entropy — works on both tiers."""

    name = "logit_entropy"
    tier = Tier.MOUNTED
    description = "Detects output uncertainty via logit distribution entropy"

    def __init__(self, threshold: float = 2.0):
        self.threshold = threshold

    def evaluate(self, context: dict[str, Any]) -> ChannelEvidence:
        report = context.get("report")
        if report is not None:
            entropy = report.logit_entropy
        else:
            entropy = context.get("entropy", 0)
        return ChannelEvidence(
            self.name, self.tier if report else Tier.API,
            entropy, self.threshold,
            fired=entropy > self.threshold,
            confidence=0.75,
            detail=f"entropy={entropy:.2f}",
        )


class NormRatioChannel(DetectionChannel):
    """Norm31/47 ratio — early/late activation balance."""

    name = "norm_ratio"
    tier = Tier.MOUNTED
    description = "Predicts sycophancy failure via early/late activation balance"

    def __init__(self, threshold: float = 0.78):
        self.threshold = threshold

    def evaluate(self, context: dict[str, Any]) -> ChannelEvidence:
        report = context.get("report")
        if report is None:
            return ChannelEvidence(self.name, self.tier, 0, self.threshold, False,
                                   confidence=0, detail="No detection report")
        ratio = report.norm_ratios.get("31_47", 0)
        return ChannelEvidence(
            self.name, self.tier, ratio, self.threshold,
            fired=ratio > self.threshold,
            confidence=0.70,
            detail=f"norm31/47={ratio:.4f}",
        )


# === API CHANNELS (Tier 2) ===

class LogprobEntropyChannel(DetectionChannel):
    """Entropy from API logprobs — Tier 2 confab detection."""

    name = "logprob_entropy"
    tier = Tier.API
    description = "Detects uncertainty from API-returned logprobs"

    def __init__(self, threshold: float = 2.0):
        self.threshold = threshold

    def evaluate(self, context: dict[str, Any]) -> ChannelEvidence:
        logprobs = context.get("logprobs", [])
        if not logprobs:
            return ChannelEvidence(self.name, self.tier, 0, self.threshold, False,
                                   confidence=0, detail="No logprobs available")
        import math
        avg_entropy = -sum(lp for lp in logprobs if lp is not None) / max(len(logprobs), 1)
        return ChannelEvidence(
            self.name, self.tier, avg_entropy, self.threshold,
            fired=avg_entropy > self.threshold,
            confidence=0.65,
            detail=f"avg_logprob_entropy={avg_entropy:.2f} over {len(logprobs)} tokens",
        )


class ConsistencyChannel(DetectionChannel):
    """Flight-of-N consistency check for APIs."""

    name = "consistency"
    tier = Tier.API
    description = "Detects confabulation via multi-completion consistency"

    def __init__(self, threshold: float = 0.6, n_completions: int = 3):
        self.threshold = threshold
        self.n_completions = n_completions

    def evaluate(self, context: dict[str, Any]) -> ChannelEvidence:
        completions = context.get("completions", [])
        if len(completions) < 2:
            return ChannelEvidence(self.name, self.tier, 1.0, self.threshold, False,
                                   confidence=0, detail="Need multiple completions")
        pairs = 0
        agreements = 0
        for i in range(len(completions)):
            for j in range(i + 1, len(completions)):
                pairs += 1
                a_words = set(completions[i].lower().split())
                b_words = set(completions[j].lower().split())
                if a_words and b_words:
                    jaccard = len(a_words & b_words) / len(a_words | b_words)
                    if jaccard > 0.5:
                        agreements += 1
        consistency = agreements / max(pairs, 1)
        return ChannelEvidence(
            self.name, self.tier, 1 - consistency, self.threshold,
            fired=consistency < self.threshold,
            confidence=0.70,
            detail=f"consistency={consistency:.2f} across {len(completions)} completions",
        )


# === VALIDATOR ===

class OntologyValidator:
    """Runtime output validator — bridges ontology kernel and detection channels.

    Queries available channels, aggregates evidence, returns a verdict.
    Works with whatever channels are available — graceful degradation
    from full geometric stack to API-only behavioral checks.
    """

    def __init__(self, kernel: OntologyKernel,
                 channels: Sequence[DetectionChannel] | None = None,
                 min_channels_for_block: int = 2,
                 block_confidence_threshold: float = 0.7):
        self.kernel = kernel
        self.channels = list(channels or [])
        self.min_channels_for_block = min_channels_for_block
        self.block_confidence_threshold = block_confidence_threshold

    @property
    def tier(self) -> Tier:
        if any(c.tier == Tier.MOUNTED for c in self.channels):
            return Tier.MOUNTED
        return Tier.API

    def add_channel(self, channel: DetectionChannel) -> None:
        self.channels.append(channel)

    def validate(self, context: dict[str, Any],
                 action: str = "",
                 actor_role: str = "") -> ValidationResult:
        """Run all available channels and aggregate into a verdict."""

        evidence = []
        for channel in self.channels:
            try:
                ev = channel.evaluate(context)
                evidence.append(ev)
            except Exception:
                logger.debug("Channel %s failed", channel.name, exc_info=True)

        ontology_violations = []
        if action:
            _, violations = self.kernel.validate_action(action, actor_role)
            ontology_violations = violations

        fired = [e for e in evidence if e.fired]
        n_fired = len(fired)
        n_available = len(evidence)

        if ontology_violations:
            verdict = Verdict.BLOCKED
        elif n_fired >= self.min_channels_for_block:
            avg_confidence = (sum(e.confidence for e in fired) / n_fired
                              if n_fired else 0)
            if avg_confidence >= self.block_confidence_threshold:
                verdict = Verdict.BLOCKED
            else:
                verdict = Verdict.CONTESTED
        elif n_fired > 0:
            verdict = Verdict.CONTESTED
        else:
            verdict = Verdict.VALID

        aggregate_confidence = 1.0
        if evidence:
            aggregate_confidence = sum(e.confidence for e in evidence) / len(evidence)

        result = ValidationResult(
            verdict=verdict,
            evidence=evidence,
            tier_used=self.tier,
            aggregate_confidence=aggregate_confidence,
            ontology_violations=ontology_violations,
        )

        logger.info("validate: %s", result.summary())
        return result

    def summary(self) -> str:
        mounted = [c for c in self.channels if c.tier == Tier.MOUNTED]
        api = [c for c in self.channels if c.tier == Tier.API]
        return (f"OntologyValidator: {len(self.channels)} channels "
                f"(mounted={len(mounted)}, api={len(api)}), "
                f"tier={self.tier.value}")


def create_mounted_validator(kernel: OntologyKernel) -> OntologyValidator:
    """Create a validator with all mounted (geometric) channels."""
    return OntologyValidator(kernel, channels=[
        ConsequentialityChannel(),
        SycophancyChannel(),
        ConfabChannel(),
        EntropyChannel(),
        NormRatioChannel(),
    ])


def create_api_validator(kernel: OntologyKernel) -> OntologyValidator:
    """Create a validator with API-only (behavioral) channels."""
    return OntologyValidator(kernel, channels=[
        LogprobEntropyChannel(),
        ConsistencyChannel(),
    ])


def create_hybrid_validator(kernel: OntologyKernel) -> OntologyValidator:
    """Create a validator with all available channels."""
    return OntologyValidator(kernel, channels=[
        ConsequentialityChannel(),
        SycophancyChannel(),
        ConfabChannel(),
        EntropyChannel(),
        NormRatioChannel(),
        LogprobEntropyChannel(),
        ConsistencyChannel(),
    ])
