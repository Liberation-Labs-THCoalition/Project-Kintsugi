"""Oracle Loop hook interface.

The Oracle Loop (Project Oracle) monitors model internals — KV cache
geometry, consequentiality signals, deception-amplifier activations — and
returns a verdict on each agent response. Kintsugi does not implement the
detection pipeline itself; it exposes a hook point that every agent
response passes through before it reaches a user.

Three built-in hooks:

* :class:`NullOracleHook` — always clean; used when no Oracle is attached.
* :class:`HTTPOracleHook` — POSTs each turn to a running Oracle harness
  (``ORACLE_ENDPOINT``) and maps its response to a verdict.
* :class:`CallableOracleHook` — wraps any async/sync callable, for
  in-process detectors and tests.
"""

from __future__ import annotations

import inspect
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)


@dataclass
class AgentTurn:
    """One agent response, as presented to the Oracle."""

    agent_id: str
    session_id: str | None
    user_input: str
    response: str
    skill_used: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "user_input": self.user_input,
            "response": self.response,
            "skill_used": self.skill_used,
            "metadata": self.metadata,
        }


@dataclass
class OracleVerdict:
    """Oracle's assessment of one agent turn.

    ``score`` is a flag intensity in [0, 1]: 0.0 = clean, 1.0 = maximal
    concern. ``status`` summarizes what the monitor should do with it.
    """

    status: str  # "clean" | "flagged" | "error" | "unmonitored"
    score: float = 0.0
    signals: dict[str, Any] = field(default_factory=dict)
    source: str = "null"
    latency_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "score": self.score,
            "signals": self.signals,
            "source": self.source,
            "latency_ms": round(self.latency_ms, 2),
            "timestamp": self.timestamp.isoformat(),
        }


@runtime_checkable
class OracleHook(Protocol):
    """Anything that can review an agent turn."""

    name: str

    async def review(self, turn: AgentTurn) -> OracleVerdict:  # pragma: no cover - protocol
        ...


class NullOracleHook:
    """Default hook when no Oracle pipeline is attached."""

    name = "null"

    async def review(self, turn: AgentTurn) -> OracleVerdict:
        return OracleVerdict(status="unmonitored", source=self.name)


class CallableOracleHook:
    """Wrap a callable ``(AgentTurn) -> OracleVerdict | dict`` as a hook."""

    def __init__(
        self,
        fn: Callable[[AgentTurn], OracleVerdict | dict | Awaitable[OracleVerdict | dict]],
        name: str = "callable",
    ) -> None:
        self._fn = fn
        self.name = name

    async def review(self, turn: AgentTurn) -> OracleVerdict:
        start = time.monotonic()
        result = self._fn(turn)
        if inspect.isawaitable(result):
            result = await result
        latency = (time.monotonic() - start) * 1000
        if isinstance(result, OracleVerdict):
            result.source = result.source if result.source != "null" else self.name
            result.latency_ms = result.latency_ms or latency
            return result
        return OracleVerdict(
            status=result.get("status", "clean"),
            score=float(result.get("score", 0.0)),
            signals=result.get("signals", {}),
            source=self.name,
            latency_ms=latency,
        )


class HTTPOracleHook:
    """POST each turn to a running Oracle harness.

    Expected endpoint contract (Project Oracle detection API)::

        POST {endpoint}   body: AgentTurn.to_dict()
        200 -> {"status": "clean"|"flagged", "score": 0.0-1.0, "signals": {...}}

    Errors and timeouts yield ``status="error"`` — policy for errors
    (fail-open vs fail-closed) belongs to the monitor, not the hook.
    """

    name = "oracle-http"

    def __init__(self, endpoint: str, timeout: float = 5.0) -> None:
        self.endpoint = endpoint
        self.timeout = timeout

    async def review(self, turn: AgentTurn) -> OracleVerdict:
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.endpoint, json=turn.to_dict())
                resp.raise_for_status()
                payload = resp.json()
            return OracleVerdict(
                status=payload.get("status", "clean"),
                score=float(payload.get("score", 0.0)),
                signals=payload.get("signals", {}),
                source=self.name,
                latency_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as exc:
            logger.warning("Oracle endpoint %s failed: %s", self.endpoint, exc)
            return OracleVerdict(
                status="error",
                signals={"error": str(exc)},
                source=self.name,
                latency_ms=(time.monotonic() - start) * 1000,
            )
