"""Mission drift detection for BDI-aligned organizations.

v2 (May 2026): Added SSL drift decomposition (arXiv:2604.24026).
Drift is typed along three layers — Scheduling, Structural, Logical —
enabling targeted remediation instead of one-size-fits-all correction.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional
import uuid


class DriftCategory(Enum):
    HEALTHY_ADAPTATION = "healthy_adaptation"
    STALE_BELIEFS = "stale_beliefs"
    INTENTION_DRIFT = "intention_drift"
    VALUES_TENSION = "values_tension"


class DriftLayer(str, Enum):
    """SSL drift decomposition — three orthogonal dimensions of drift.

    Scheduling: the skill fires at the wrong time or frequency
    Structural: the skill uses the wrong tools or execution path
    Logical:    the skill produces the wrong output or reasoning
    """
    SCHEDULING = "scheduling"
    STRUCTURAL = "structural"
    LOGICAL = "logical"


@dataclass
class SSLDriftSignal:
    """A typed drift signal along one SSL layer."""
    layer: DriftLayer
    magnitude: float
    description: str
    evidence: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.magnitude <= 1.0:
            raise ValueError(f"magnitude must be in [0, 1], got {self.magnitude}")


@dataclass
class SSLDriftProfile:
    """Decomposed drift profile across all three SSL layers."""
    scheduling: float = 0.0
    structural: float = 0.0
    logical: float = 0.0
    signals: List[SSLDriftSignal] = field(default_factory=list)

    @property
    def dominant_layer(self) -> DriftLayer:
        scores = {
            DriftLayer.SCHEDULING: self.scheduling,
            DriftLayer.STRUCTURAL: self.structural,
            DriftLayer.LOGICAL: self.logical,
        }
        return max(scores, key=scores.get)

    @property
    def total_drift(self) -> float:
        return (self.scheduling + self.structural + self.logical) / 3.0

    def get_remediation_hint(self) -> str:
        dom = self.dominant_layer
        if dom == DriftLayer.SCHEDULING:
            return "Adjust activation timing, frequency, or trigger conditions"
        if dom == DriftLayer.STRUCTURAL:
            return "Review tool selection, execution path, or integration routing"
        return "Check output quality, reasoning chain, or decision logic"


@dataclass
class DriftEvent:
    event_id: str
    category: DriftCategory
    severity: str
    description: str
    evidence: dict
    bdi_layer: str
    detected_at: datetime = field(default_factory=datetime.utcnow)
    requires_review: bool = False

    def __post_init__(self) -> None:
        if self.severity not in ("info", "warning", "critical"):
            raise ValueError(f"severity must be info/warning/critical, got {self.severity!r}")
        if self.bdi_layer not in ("beliefs", "desires", "intentions"):
            raise ValueError(f"bdi_layer must be beliefs/desires/intentions, got {self.bdi_layer!r}")


@dataclass
class DriftConfig:
    check_interval_hours: float = 168.0  # weekly
    swei_threshold: float = 0.15
    staleness_days: int = 90
    min_observations: int = 10


class DriftDetector:
    """Detects mission drift by analyzing actions against the BDI model."""

    def __init__(self, config: Optional[DriftConfig] = None) -> None:
        self.config = config or DriftConfig()

    def analyze_behavioral_patterns(
        self, recent_actions: List[dict], bdi_context: dict
    ) -> List[DriftEvent]:
        """Analyze recent actions against BDI context and return drift events."""
        events: List[DriftEvent] = []
        now = datetime.now(timezone.utc)

        beliefs = bdi_context.get("beliefs", [])
        desires = bdi_context.get("desires", [])
        intentions = bdi_context.get("intentions", [])

        # 1. Check for actions that contradict stated beliefs -> VALUES_TENSION
        events.extend(self._check_values_tension(recent_actions, beliefs))

        # 2. Beliefs with old last_reviewed dates -> STALE_BELIEFS
        events.extend(self._check_stale_beliefs(beliefs, now))

        # 3. Intentions active but no supporting actions -> INTENTION_DRIFT
        events.extend(self._check_intention_drift(recent_actions, intentions))

        # 4. Gradual consistent shift -> HEALTHY_ADAPTATION
        events.extend(self._check_healthy_adaptation(recent_actions, bdi_context))

        return events

    def classify_drift(
        self, swei_divergence: float, bdi_alignment: float
    ) -> DriftCategory:
        """Classify drift category from SWEI divergence and BDI alignment scores."""
        if swei_divergence < self.config.swei_threshold and bdi_alignment >= 0.7:
            return DriftCategory.HEALTHY_ADAPTATION
        if swei_divergence >= self.config.swei_threshold and bdi_alignment < 0.5:
            return DriftCategory.VALUES_TENSION
        if bdi_alignment < 0.6:
            return DriftCategory.INTENTION_DRIFT
        return DriftCategory.STALE_BELIEFS

    def generate_review_invitation(self, events: List[DriftEvent]) -> dict:
        """Create a structured invitation for human review."""
        if not events:
            return {
                "summary": "No drift events detected.",
                "affected_layers": [],
                "events": [],
                "recommended_actions": [],
            }

        affected_layers = sorted(set(e.bdi_layer for e in events))
        critical = [e for e in events if e.severity == "critical"]
        warnings = [e for e in events if e.severity == "warning"]

        actions: List[str] = []
        if critical:
            actions.append(
                f"Urgent: {len(critical)} critical drift event(s) require immediate review."
            )
        if warnings:
            actions.append(
                f"Review {len(warnings)} warning-level event(s) at next planning session."
            )
        if "beliefs" in affected_layers:
            actions.append("Schedule a belief review session to update stale or challenged beliefs.")
        if "intentions" in affected_layers:
            actions.append("Re-evaluate active intentions for continued relevance and resourcing.")
        if "desires" in affected_layers:
            actions.append("Reassess organizational desires for alignment with current context.")

        return {
            "summary": f"Detected {len(events)} drift event(s) across {len(affected_layers)} BDI layer(s).",
            "affected_layers": affected_layers,
            "events": [
                {
                    "event_id": e.event_id,
                    "category": e.category.value,
                    "severity": e.severity,
                    "description": e.description,
                    "bdi_layer": e.bdi_layer,
                    "requires_review": e.requires_review,
                }
                for e in events
            ],
            "recommended_actions": actions,
        }

    def get_severity(self, category: DriftCategory, swei: float) -> str:
        """Map category and SWEI divergence to a severity level."""
        if category == DriftCategory.HEALTHY_ADAPTATION:
            return "info"
        if category == DriftCategory.VALUES_TENSION:
            return "critical" if swei >= self.config.swei_threshold * 2 else "warning"
        if category == DriftCategory.INTENTION_DRIFT:
            return "warning" if swei < self.config.swei_threshold * 2 else "critical"
        # STALE_BELIEFS
        return "warning"

    def analyze_ssl_drift(
        self, recent_actions: List[dict], expected_patterns: dict
    ) -> SSLDriftProfile:
        """Decompose observed drift into SSL layers.

        Compares recent actions against expected behavioral patterns to
        identify whether drift is in timing (scheduling), tooling
        (structural), or output quality (logical).

        Parameters
        ----------
        recent_actions:
            List of action dicts with fields: timestamp, tools_used,
            output_quality (0-1), intent, duration_seconds.
        expected_patterns:
            Dict with fields: expected_tools (set), expected_frequency_hours
            (float), min_output_quality (float).
        """
        signals: List[SSLDriftSignal] = []
        scheduling_score = 0.0
        structural_score = 0.0
        logical_score = 0.0

        if not recent_actions:
            return SSLDriftProfile(signals=signals)

        # Scheduling: are actions happening at the expected frequency?
        expected_freq = expected_patterns.get("expected_frequency_hours", 0)
        if expected_freq > 0 and len(recent_actions) >= 2:
            timestamps = []
            for a in recent_actions:
                ts = a.get("timestamp")
                if isinstance(ts, datetime):
                    timestamps.append(ts)
                elif isinstance(ts, str):
                    try:
                        timestamps.append(datetime.fromisoformat(ts))
                    except (ValueError, TypeError):
                        pass
            if len(timestamps) >= 2:
                timestamps.sort()
                gaps = [
                    (timestamps[i+1] - timestamps[i]).total_seconds() / 3600
                    for i in range(len(timestamps) - 1)
                ]
                avg_gap = sum(gaps) / len(gaps)
                freq_ratio = abs(avg_gap - expected_freq) / max(expected_freq, 0.01)
                scheduling_score = min(freq_ratio, 1.0)
                if scheduling_score > 0.3:
                    signals.append(SSLDriftSignal(
                        layer=DriftLayer.SCHEDULING,
                        magnitude=scheduling_score,
                        description=f"Action frequency {avg_gap:.1f}h vs expected {expected_freq:.1f}h",
                        evidence={"avg_gap_hours": avg_gap, "expected_hours": expected_freq},
                    ))

        # Structural: are the right tools being used?
        expected_tools = set(expected_patterns.get("expected_tools", []))
        if expected_tools:
            used_tools: set = set()
            for a in recent_actions:
                for t in a.get("tools_used", []):
                    used_tools.add(t)
            if used_tools:
                overlap = expected_tools & used_tools
                jaccard = len(overlap) / len(expected_tools | used_tools)
                structural_score = 1.0 - jaccard
                if structural_score > 0.3:
                    unexpected = used_tools - expected_tools
                    missing = expected_tools - used_tools
                    signals.append(SSLDriftSignal(
                        layer=DriftLayer.STRUCTURAL,
                        magnitude=structural_score,
                        description=f"Tool divergence: unexpected={unexpected}, missing={missing}",
                        evidence={"expected": list(expected_tools), "used": list(used_tools)},
                    ))

        # Logical: is output quality maintained?
        min_quality = expected_patterns.get("min_output_quality", 0.0)
        qualities = [a.get("output_quality", 1.0) for a in recent_actions if "output_quality" in a]
        if qualities and min_quality > 0:
            avg_quality = sum(qualities) / len(qualities)
            if avg_quality < min_quality:
                logical_score = min((min_quality - avg_quality) / max(min_quality, 0.01), 1.0)
                signals.append(SSLDriftSignal(
                    layer=DriftLayer.LOGICAL,
                    magnitude=logical_score,
                    description=f"Output quality {avg_quality:.3f} below minimum {min_quality:.3f}",
                    evidence={"avg_quality": avg_quality, "min_required": min_quality},
                ))

        return SSLDriftProfile(
            scheduling=scheduling_score,
            structural=structural_score,
            logical=logical_score,
            signals=signals,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_values_tension(
        self, actions: List[dict], beliefs: list
    ) -> List[DriftEvent]:
        events: List[DriftEvent] = []
        belief_keywords: Dict[str, List[str]] = {}
        for b in beliefs:
            bid = b.get("id", str(uuid.uuid4()))
            content = str(b.get("content", "")).lower()
            belief_keywords[bid] = [w for w in content.split() if len(w) > 3]

        for action in actions:
            action_text = str(action.get("description", "")).lower()
            contradicts = action.get("contradicts_beliefs", [])
            if contradicts:
                events.append(DriftEvent(
                    event_id=str(uuid.uuid4()),
                    category=DriftCategory.VALUES_TENSION,
                    severity="warning",
                    description=f"Action contradicts beliefs: {contradicts}",
                    evidence={"action": action, "contradicted_beliefs": contradicts},
                    bdi_layer="beliefs",
                    requires_review=True,
                ))
            else:
                # Simple negative-keyword heuristic
                negative_signals = ["against", "despite", "contradict", "violat", "ignor"]
                for signal in negative_signals:
                    if signal in action_text:
                        events.append(DriftEvent(
                            event_id=str(uuid.uuid4()),
                            category=DriftCategory.VALUES_TENSION,
                            severity="info",
                            description=f"Action text contains tension signal '{signal}'.",
                            evidence={"action": action, "signal": signal},
                            bdi_layer="beliefs",
                            requires_review=False,
                        ))
                        break
        return events

    def _check_stale_beliefs(
        self, beliefs: list, now: datetime
    ) -> List[DriftEvent]:
        events: List[DriftEvent] = []
        cutoff = now - timedelta(days=self.config.staleness_days)
        for b in beliefs:
            last_reviewed = b.get("last_reviewed")
            if last_reviewed is None:
                continue
            if isinstance(last_reviewed, str):
                try:
                    last_reviewed = datetime.fromisoformat(last_reviewed)
                except (ValueError, TypeError):
                    continue
            if last_reviewed < cutoff:
                events.append(DriftEvent(
                    event_id=str(uuid.uuid4()),
                    category=DriftCategory.STALE_BELIEFS,
                    severity="warning",
                    description=f"Belief '{b.get('id', '?')}' not reviewed since {last_reviewed.date()}.",
                    evidence={"belief": b, "staleness_days": (now - last_reviewed).days},
                    bdi_layer="beliefs",
                    requires_review=True,
                ))
        return events

    def _check_intention_drift(
        self, actions: List[dict], intentions: list
    ) -> List[DriftEvent]:
        events: List[DriftEvent] = []
        action_intention_ids: set = set()
        for a in actions:
            for iid in a.get("intention_ids", []):
                action_intention_ids.add(iid)

        for intention in intentions:
            status = intention.get("status", "")
            iid = intention.get("id", "")
            if status in ("active", "ACTIVE") and iid not in action_intention_ids:
                events.append(DriftEvent(
                    event_id=str(uuid.uuid4()),
                    category=DriftCategory.INTENTION_DRIFT,
                    severity="warning",
                    description=f"Active intention '{iid}' has no supporting recent actions.",
                    evidence={"intention": intention},
                    bdi_layer="intentions",
                    requires_review=True,
                ))
        return events

    def _check_healthy_adaptation(
        self, actions: List[dict], bdi_context: dict
    ) -> List[DriftEvent]:
        events: List[DriftEvent] = []
        if len(actions) < self.config.min_observations:
            return events

        # If there are many actions and none triggered other flags, it's healthy
        tagged = [a for a in actions if a.get("aligned", False)]
        if len(tagged) >= len(actions) * 0.7:
            events.append(DriftEvent(
                event_id=str(uuid.uuid4()),
                category=DriftCategory.HEALTHY_ADAPTATION,
                severity="info",
                description="Majority of recent actions are aligned with BDI model.",
                evidence={"aligned_ratio": len(tagged) / len(actions)},
                bdi_layer="intentions",
                requires_review=False,
            ))
        return events
