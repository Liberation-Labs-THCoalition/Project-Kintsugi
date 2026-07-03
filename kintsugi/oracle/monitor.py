"""Oracle Loop monitor — wires hooks into the agent response path.

Every response produced by an :class:`~kintsugi.agents.instance.AgentInstance`
passes through :meth:`OracleLoopMonitor.review` before it is returned to a
caller. The monitor applies mode policy:

* ``off``     — skip review entirely.
* ``observe`` — run hooks, record verdicts, never alter responses.
* ``enforce`` — run hooks; responses whose score exceeds the personality's
  ``block_threshold`` are replaced with a refusal notice. Hook *errors*
  fail open in observe mode and fail open in enforce mode too (a dead
  Oracle must not take the agent down with it) — but every error is
  recorded and surfaced on the dashboard.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import Any

from kintsugi.oracle.hooks import (
    AgentTurn,
    HTTPOracleHook,
    NullOracleHook,
    OracleHook,
    OracleVerdict,
)

logger = logging.getLogger(__name__)

BLOCKED_RESPONSE = (
    "[response withheld] The Oracle Loop flagged this response above the "
    "configured safety threshold. The original response was recorded for "
    "review but not delivered."
)


@dataclass
class ReviewResult:
    """Outcome of running one turn through the monitor."""

    verdict: OracleVerdict
    response: str  # possibly replaced in enforce mode
    blocked: bool = False


class OracleLoopMonitor:
    """Holds the active hook chain and recent verdict history."""

    def __init__(self, mode: str = "observe", history_size: int = 200) -> None:
        self.mode = mode
        self._hooks: list[OracleHook] = []
        self._verdicts: deque[dict[str, Any]] = deque(maxlen=history_size)
        self.stats = {"reviewed": 0, "flagged": 0, "blocked": 0, "errors": 0}

    # -- hook management ---------------------------------------------------

    def register_hook(self, hook: OracleHook) -> None:
        self._hooks.append(hook)
        logger.info("Oracle hook registered: %s", hook.name)

    def clear_hooks(self) -> None:
        self._hooks.clear()

    @property
    def hooks(self) -> list[str]:
        return [h.name for h in self._hooks] or ["null"]

    def _active_hooks(self) -> list[OracleHook]:
        return self._hooks or [NullOracleHook()]

    # -- review path ---------------------------------------------------------

    async def review(
        self,
        turn: AgentTurn,
        *,
        mode: str | None = None,
        block_threshold: float = 0.8,
    ) -> ReviewResult:
        """Run one agent turn through all hooks.

        ``mode`` overrides the monitor default (personalities carry their
        own oracle_mode). The worst (highest-score) verdict wins.
        """
        effective_mode = mode or self.mode
        if effective_mode == "off":
            return ReviewResult(
                verdict=OracleVerdict(status="unmonitored", source="off"),
                response=turn.response,
            )

        worst: OracleVerdict | None = None
        for hook in self._active_hooks():
            try:
                verdict = await hook.review(turn)
            except Exception as exc:  # hook bug — never break the response path
                logger.exception("Oracle hook %s raised", hook.name)
                verdict = OracleVerdict(status="error", signals={"error": str(exc)}, source=hook.name)
            if worst is None or verdict.score > worst.score or (
                verdict.status == "error" and worst.status not in ("flagged",)
            ):
                worst = verdict

        assert worst is not None
        self.stats["reviewed"] += 1
        if worst.status == "flagged":
            self.stats["flagged"] += 1
        if worst.status == "error":
            self.stats["errors"] += 1

        blocked = (
            effective_mode == "enforce"
            and worst.status == "flagged"
            and worst.score >= block_threshold
        )
        if blocked:
            self.stats["blocked"] += 1

        record = {
            "agent_id": turn.agent_id,
            "session_id": turn.session_id,
            "skill_used": turn.skill_used,
            "mode": effective_mode,
            "blocked": blocked,
            **worst.to_dict(),
        }
        self._verdicts.append(record)

        return ReviewResult(
            verdict=worst,
            response=BLOCKED_RESPONSE if blocked else turn.response,
            blocked=blocked,
        )

    # -- introspection -------------------------------------------------------

    def recent_verdicts(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._verdicts)[-limit:]

    def status(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "hooks": self.hooks,
            "stats": dict(self.stats),
            "monitored": bool(self._hooks),
        }


_monitor: OracleLoopMonitor | None = None


def get_oracle_monitor() -> OracleLoopMonitor:
    """Global monitor singleton, configured from settings on first use."""
    global _monitor
    if _monitor is None:
        mode = "observe"
        endpoint = ""
        try:
            from kintsugi.config.settings import settings

            mode = settings.ORACLE_MODE
            endpoint = settings.ORACLE_ENDPOINT
        except Exception:  # pragma: no cover - settings import failure
            pass
        _monitor = OracleLoopMonitor(mode=mode)
        if endpoint:
            _monitor.register_hook(HTTPOracleHook(endpoint))
    return _monitor
