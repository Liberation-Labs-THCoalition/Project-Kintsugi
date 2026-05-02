"""Proactive Advisor — cross-domain pattern recognition for organizations.

Scans organizational activity across all skill chip domains, identifies
patterns that need attention, and generates EFE-scored suggestions.

The advisor makes Kintsugi feel like a colleague, not a tool:
  "You submitted a grant 2 weeks ago and haven't followed up."
  "Three volunteers signed up this week but none were onboarded."
  "The food access program has 12 pending requests — want to triage?"

Architecture:
  - ActivityScanner reads recent memory/interaction history
  - PatternDetector identifies actionable patterns (missed follow-ups,
    stale leads, resource gaps, upcoming deadlines)
  - EFE scores each suggestion by organizational risk vs value
  - Top suggestions surfaced to the operator

Designed to run periodically (on session start, or on a timer)
rather than on every interaction.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from kintsugi.cognition.efe import (
    EFECalculator,
    EFEScore,
    EFEWeights,
    DEFAULT_WEIGHTS,
    GRANTS_WEIGHTS,
    FINANCE_WEIGHTS,
    COMMUNICATIONS_WEIGHTS,
)

logger = logging.getLogger(__name__)


# Suggestion weight profiles — how important/risky is each type?
SUGGESTION_WEIGHTS = {
    "missed_followup": EFEWeights(risk=0.3, ambiguity=0.2, epistemic=0.5),
    "stale_task": EFEWeights(risk=0.2, ambiguity=0.3, epistemic=0.5),
    "resource_gap": EFEWeights(risk=0.4, ambiguity=0.3, epistemic=0.3),
    "deadline_approaching": EFEWeights(risk=0.5, ambiguity=0.2, epistemic=0.3),
    "unprocessed_intake": EFEWeights(risk=0.4, ambiguity=0.2, epistemic=0.4),
    "opportunity": EFEWeights(risk=0.1, ambiguity=0.3, epistemic=0.6),
    "capacity_alert": EFEWeights(risk=0.5, ambiguity=0.3, epistemic=0.2),
}


@dataclass
class Suggestion:
    """A proactive suggestion for the organization."""
    id: str
    pattern_type: str
    title: str
    description: str
    suggested_action: str
    skill_domain: str
    urgency: float  # 0-1, higher = more urgent
    efe_score: EFEScore | None = None
    source_activities: list[str] = field(default_factory=list)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def priority(self) -> float:
        """Combined priority from urgency and EFE score."""
        efe_val = abs(self.efe_score.total) if self.efe_score else 0.5
        return self.urgency * 0.6 + (1.0 - min(efe_val, 1.0)) * 0.4


@dataclass
class ActivityRecord:
    """A record of organizational activity for pattern detection."""
    timestamp: datetime
    domain: str
    action: str
    details: dict[str, Any] = field(default_factory=dict)
    status: str = "completed"
    follow_up_needed: bool = False
    follow_up_by: datetime | None = None


class ProactiveAdvisor:
    """Scans organizational activity and generates proactive suggestions.

    Args:
        lookback_days: How far back to scan for patterns.
        max_suggestions: Maximum suggestions per scan.
        follow_up_grace_days: Days before a follow-up is considered missed.
    """

    def __init__(
        self,
        lookback_days: int = 30,
        max_suggestions: int = 5,
        follow_up_grace_days: int = 7,
    ) -> None:
        self.lookback_days = lookback_days
        self.max_suggestions = max_suggestions
        self.follow_up_grace_days = follow_up_grace_days
        self._efe = EFECalculator()

    def scan(self, activities: list[ActivityRecord]) -> list[Suggestion]:
        """Scan activities and generate scored suggestions.

        Args:
            activities: Recent organizational activity records.

        Returns:
            Suggestions sorted by priority (highest first).
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=self.lookback_days)
        recent = [a for a in activities if a.timestamp >= cutoff]

        suggestions: list[Suggestion] = []
        suggestions.extend(self._detect_missed_followups(recent, now))
        suggestions.extend(self._detect_stale_tasks(recent, now))
        suggestions.extend(self._detect_unprocessed_intakes(recent, now))
        suggestions.extend(self._detect_capacity_alerts(recent, now))
        suggestions.extend(self._detect_opportunities(recent, now))

        # Score each suggestion with EFE
        for suggestion in suggestions:
            weights = SUGGESTION_WEIGHTS.get(
                suggestion.pattern_type, DEFAULT_WEIGHTS
            )
            suggestion.efe_score = self._efe.calculate_efe(
                policy_id=suggestion.id,
                predicted_outcome={
                    "value_delivered": suggestion.urgency,
                    "effort_required": 0.3,
                },
                desired_outcome={
                    "value_delivered": 1.0,
                    "effort_required": 0.0,
                },
                uncertainty=0.3 if suggestion.source_activities else 0.6,
                information_gain=suggestion.urgency * 0.8,
                weights=weights,
            )

        suggestions.sort(key=lambda s: s.priority, reverse=True)
        return suggestions[:self.max_suggestions]

    def _detect_missed_followups(
        self, activities: list[ActivityRecord], now: datetime
    ) -> list[Suggestion]:
        """Find activities that needed follow-up but didn't get it."""
        suggestions = []
        grace = timedelta(days=self.follow_up_grace_days)

        needs_followup = [
            a for a in activities
            if a.follow_up_needed and a.status == "completed"
        ]

        for activity in needs_followup:
            deadline = activity.follow_up_by or (activity.timestamp + grace)
            if now > deadline:
                days_overdue = (now - deadline).days
                suggestions.append(Suggestion(
                    id=f"followup_{activity.domain}_{activity.timestamp.date()}",
                    pattern_type="missed_followup",
                    title=f"Follow-up needed: {activity.action}",
                    description=(
                        f"{activity.action} in {activity.domain} was completed "
                        f"{(now - activity.timestamp).days} days ago but hasn't "
                        f"been followed up ({days_overdue} days overdue)."
                    ),
                    suggested_action=f"Draft follow-up for: {activity.details.get('subject', activity.action)}",
                    skill_domain=activity.domain,
                    urgency=min(1.0, 0.5 + days_overdue * 0.05),
                    source_activities=[f"{activity.domain}:{activity.action}"],
                ))

        return suggestions

    def _detect_stale_tasks(
        self, activities: list[ActivityRecord], now: datetime
    ) -> list[Suggestion]:
        """Find domains with no recent activity that usually have some."""
        domain_last_active: dict[str, datetime] = {}
        for a in activities:
            if a.domain not in domain_last_active or a.timestamp > domain_last_active[a.domain]:
                domain_last_active[a.domain] = a.timestamp

        suggestions = []
        stale_threshold = timedelta(days=14)

        for domain, last_active in domain_last_active.items():
            if now - last_active > stale_threshold:
                days_stale = (now - last_active).days
                suggestions.append(Suggestion(
                    id=f"stale_{domain}",
                    pattern_type="stale_task",
                    title=f"No activity in {domain} for {days_stale} days",
                    description=(
                        f"The {domain} domain hasn't had any activity in "
                        f"{days_stale} days. This may indicate a dropped "
                        f"initiative or a gap in coverage."
                    ),
                    suggested_action=f"Review status of {domain} tasks and priorities",
                    skill_domain=domain,
                    urgency=min(1.0, 0.3 + (days_stale - 14) * 0.03),
                    source_activities=[f"{domain}:last_active={last_active.date()}"],
                ))

        return suggestions

    def _detect_unprocessed_intakes(
        self, activities: list[ActivityRecord], now: datetime
    ) -> list[Suggestion]:
        """Find intake requests that haven't been triaged."""
        pending = [
            a for a in activities
            if a.action in ("intake", "request", "referral")
            and a.status in ("pending", "received")
        ]

        if len(pending) >= 3:
            oldest = min(a.timestamp for a in pending)
            days_waiting = (now - oldest).days
            return [Suggestion(
                id=f"intake_backlog_{now.date()}",
                pattern_type="unprocessed_intake",
                title=f"{len(pending)} pending requests need triage",
                description=(
                    f"There are {len(pending)} unprocessed intake requests. "
                    f"The oldest has been waiting {days_waiting} days. "
                    f"Domains: {', '.join(set(a.domain for a in pending))}."
                ),
                suggested_action="Triage pending requests: prioritize by urgency and match to available resources",
                skill_domain="mutual_aid",
                urgency=min(1.0, 0.4 + len(pending) * 0.05 + days_waiting * 0.03),
                source_activities=[f"{a.domain}:{a.action}" for a in pending[:5]],
            )]
        return []

    def _detect_capacity_alerts(
        self, activities: list[ActivityRecord], now: datetime
    ) -> list[Suggestion]:
        """Detect when activity volume suggests capacity issues."""
        week = timedelta(days=7)
        this_week = [a for a in activities if now - a.timestamp <= week]
        last_week = [
            a for a in activities
            if week < now - a.timestamp <= week * 2
        ]

        if len(this_week) > 0 and len(last_week) > 0:
            ratio = len(this_week) / len(last_week)
            if ratio > 2.0:
                return [Suggestion(
                    id=f"capacity_{now.date()}",
                    pattern_type="capacity_alert",
                    title="Activity surge detected — capacity check recommended",
                    description=(
                        f"This week's activity ({len(this_week)} actions) is "
                        f"{ratio:.1f}x last week ({len(last_week)} actions). "
                        f"This may indicate increased demand or a crisis response."
                    ),
                    suggested_action="Review volunteer capacity and consider activating additional support",
                    skill_domain="volunteer_coordination",
                    urgency=min(1.0, 0.3 + (ratio - 2.0) * 0.2),
                    source_activities=[f"volume:this_week={len(this_week)},last_week={len(last_week)}"],
                )]
        return []

    def _detect_opportunities(
        self, activities: list[ActivityRecord], now: datetime
    ) -> list[Suggestion]:
        """Detect positive patterns worth acting on."""
        suggestions = []

        # New volunteers not yet onboarded
        new_volunteers = [
            a for a in activities
            if a.action in ("volunteer_signup", "new_volunteer")
            and a.status in ("pending", "new")
            and (now - a.timestamp).days <= 7
        ]
        if new_volunteers:
            suggestions.append(Suggestion(
                id=f"onboard_{now.date()}",
                pattern_type="opportunity",
                title=f"{len(new_volunteers)} new volunteers ready for onboarding",
                description=(
                    f"{len(new_volunteers)} people signed up to volunteer "
                    f"in the past week. Prompt onboarding increases retention."
                ),
                suggested_action="Schedule orientation for new volunteers",
                skill_domain="staff_onboarding",
                urgency=0.6,
                source_activities=[f"volunteer:{a.details.get('name', 'unnamed')}" for a in new_volunteers],
            ))

        return suggestions
