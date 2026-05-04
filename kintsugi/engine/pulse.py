"""Pulse — the universal agent heartbeat.

A configurable wake → check → act → report → sleep cycle that any
Kintsugi-derived agent can customize for its domain. The pulse is
what makes an agent feel alive — it doesn't just respond to requests,
it periodically reaches out, checks on things, and acts.

The Dreamer is a pulse. Ember's heartbeat_loop is a pulse. Sovereign's
market scanner is a pulse. This module makes the pattern explicit and
reusable.

Usage:
    pulse = Pulse(
        name="investigation_scanner",
        interval=timedelta(hours=1),
        checks=[check_new_entities, check_stale_leads],
        actions=[auto_pursue_lead, alert_on_hit],
    )
    await pulse.run_cycle()  # One heartbeat
    await pulse.run_forever()  # Continuous

Each derivative agent customizes the checks and actions:
    Emet: scan sources, pursue leads, alert on sanctions
    Sovereign: check markets, trigger analysis, alert on signals
    Muse: sense availability, initiate contact, check boundaries
    Kintsugi: check VALUES.json alignment, plan actions, report drift
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    """Result of a single pulse check."""
    name: str
    triggered: bool
    details: dict[str, Any] = field(default_factory=dict)
    urgency: float = 0.0  # 0-1
    suggested_action: str = ""


@dataclass
class PulseAction:
    """An action taken during a pulse cycle."""
    name: str
    trigger: str  # which check triggered this
    result: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: str = ""


@dataclass
class CycleReport:
    """Report from a single pulse cycle."""
    cycle_number: int
    timestamp: datetime
    checks_run: int = 0
    checks_triggered: int = 0
    actions_taken: int = 0
    actions_succeeded: int = 0
    duration_seconds: float = 0.0
    check_results: list[CheckResult] = field(default_factory=list)
    actions: list[PulseAction] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def had_activity(self) -> bool:
        return self.checks_triggered > 0 or self.actions_taken > 0

    def summary(self) -> str:
        if not self.had_activity:
            return f"Cycle {self.cycle_number}: quiet ({self.duration_seconds:.1f}s)"
        parts = []
        if self.checks_triggered:
            parts.append(f"{self.checks_triggered}/{self.checks_run} checks triggered")
        if self.actions_taken:
            ok = self.actions_succeeded
            parts.append(f"{ok}/{self.actions_taken} actions succeeded")
        return f"Cycle {self.cycle_number}: {'; '.join(parts)} ({self.duration_seconds:.1f}s)"


# Type aliases for check and action callables
CheckFn = Callable[..., Awaitable[CheckResult]]
ActionFn = Callable[[CheckResult], Awaitable[PulseAction]]


class Pulse:
    """The universal agent heartbeat.

    Args:
        name: Identifier for this pulse (used in logs and reports).
        interval: Time between cycles.
        checks: Async callables that inspect the world and return CheckResults.
        actions: Async callables that act on triggered checks.
        on_cycle_complete: Optional callback after each cycle (e.g., send report).
        max_actions_per_cycle: Safety limit on actions per heartbeat.
        quiet_log: If True, only log cycles with activity.
    """

    def __init__(
        self,
        name: str,
        interval: timedelta = timedelta(hours=1),
        checks: list[CheckFn] | None = None,
        actions: dict[str, ActionFn] | None = None,
        on_cycle_complete: Callable[[CycleReport], Awaitable[None]] | None = None,
        max_actions_per_cycle: int = 10,
        quiet_log: bool = True,
    ) -> None:
        self.name = name
        self.interval = interval
        self._checks = checks or []
        self._actions = actions or {}
        self._on_cycle_complete = on_cycle_complete
        self._max_actions = max_actions_per_cycle
        self._quiet_log = quiet_log
        self._cycle_count = 0
        self._running = False
        self._history: list[CycleReport] = []

    def add_check(self, check: CheckFn) -> None:
        """Register a check function."""
        self._checks.append(check)

    def add_action(self, trigger_name: str, action: ActionFn) -> None:
        """Register an action for a specific check trigger."""
        self._actions[trigger_name] = action

    async def run_cycle(self) -> CycleReport:
        """Run one heartbeat cycle: check → act → report."""
        self._cycle_count += 1
        t0 = time.perf_counter()
        now = datetime.now(timezone.utc)

        report = CycleReport(
            cycle_number=self._cycle_count,
            timestamp=now,
        )

        # Phase 1: Run all checks
        triggered: list[CheckResult] = []
        for check_fn in self._checks:
            try:
                result = await check_fn()
                report.checks_run += 1
                report.check_results.append(result)
                if result.triggered:
                    report.checks_triggered += 1
                    triggered.append(result)
            except Exception as e:
                report.errors.append(f"check {check_fn.__name__}: {e}")
                logger.warning("Pulse %s check failed: %s", self.name, e)

        # Phase 2: Run actions for triggered checks (sorted by urgency)
        triggered.sort(key=lambda r: -r.urgency)
        actions_taken = 0

        for check_result in triggered:
            if actions_taken >= self._max_actions:
                break

            action_fn = self._actions.get(check_result.name)
            if action_fn is None:
                # Check if there's a default action
                action_fn = self._actions.get("_default")
            if action_fn is None:
                continue

            try:
                action = await action_fn(check_result)
                report.actions.append(action)
                report.actions_taken += 1
                if action.success:
                    report.actions_succeeded += 1
                actions_taken += 1
            except Exception as e:
                report.errors.append(f"action for {check_result.name}: {e}")
                report.actions.append(PulseAction(
                    name=check_result.suggested_action,
                    trigger=check_result.name,
                    success=False,
                    error=str(e),
                ))
                report.actions_taken += 1

        report.duration_seconds = round(time.perf_counter() - t0, 2)

        # Phase 3: Report
        if not self._quiet_log or report.had_activity:
            logger.info("Pulse [%s] %s", self.name, report.summary())

        if self._on_cycle_complete:
            try:
                await self._on_cycle_complete(report)
            except Exception as e:
                logger.warning("Pulse %s report callback failed: %s", self.name, e)

        self._history.append(report)
        if len(self._history) > 100:
            self._history = self._history[-100:]

        return report

    async def run_forever(self) -> None:
        """Run the pulse continuously until stopped."""
        self._running = True
        logger.info("Pulse [%s] started (interval=%s)", self.name, self.interval)

        while self._running:
            await self.run_cycle()
            await asyncio.sleep(self.interval.total_seconds())

    def stop(self) -> None:
        """Stop the pulse loop."""
        self._running = False
        logger.info("Pulse [%s] stopped after %d cycles", self.name, self._cycle_count)

    @property
    def cycle_count(self) -> int:
        return self._cycle_count

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def history(self) -> list[CycleReport]:
        return list(self._history)

    @property
    def last_report(self) -> CycleReport | None:
        return self._history[-1] if self._history else None


# ── Pre-built check patterns ──

async def check_values_alignment(
    get_bdi_snapshot, coherence_checker
) -> CheckResult:
    """Check if current state aligns with VALUES.json via BDI coherence."""
    snapshot = get_bdi_snapshot()
    score = coherence_checker.check_coherence(snapshot)
    return CheckResult(
        name="values_alignment",
        triggered=score.overall < 0.5,
        details={"coherence": score.overall, "issues": list(score.issues)[:3]},
        urgency=1.0 - score.overall,
        suggested_action="Review organizational alignment and address drift",
    )


async def check_stale_activity(
    get_activity_age, threshold_days: int = 14
) -> CheckResult:
    """Check if any domain has gone quiet too long."""
    age_days = get_activity_age()
    return CheckResult(
        name="stale_activity",
        triggered=age_days > threshold_days,
        details={"days_since_activity": age_days},
        urgency=min(1.0, (age_days - threshold_days) / 30),
        suggested_action=f"Review activity — {age_days} days since last action",
    )


async def check_pending_items(
    get_pending_count, threshold: int = 3
) -> CheckResult:
    """Check if pending items have accumulated."""
    count = get_pending_count()
    return CheckResult(
        name="pending_items",
        triggered=count >= threshold,
        details={"pending_count": count},
        urgency=min(1.0, count / 10),
        suggested_action=f"Triage {count} pending items",
    )
