"""Shadow fork execution for safe modification testing.

A shadow fork runs a parallel agent with proposed modifications in an
isolated environment.  Tool calls are intercepted and answered with
mock/cached responses so the shadow never touches real resources.

Supports two execution modes:

- **mock** (default): Records inputs and returns pre-configured mock
  responses.  No LLM calls are made.  Used for unit testing and fast
  feedback loops.

- **live**: Calls the LLM client with the modified agent configuration
  while still intercepting all tool calls through the mock tool layer.
  Only the LLM *reasoning* changes — tools remain sandboxed.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import time
import uuid
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Literal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class ShadowStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


@dataclass
class ShadowConfig:
    """Configuration for a shadow fork execution.

    Parameters
    ----------
    modification:
        Dict of config overrides to merge into the primary config.
    timeout_seconds:
        Maximum wall-clock time for shadow execution.
    max_memory_mb:
        Maximum memory budget (advisory; enforced at the process level).
    mock_tool_responses:
        ``{tool_name: response}`` map for intercepting tool calls.
    execute_mode:
        ``"mock"`` preserves the original simulation behaviour.
        ``"live"`` calls an LLM client with the modified config while
        still intercepting all tool calls through the mock layer.
    """

    modification: Dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 300
    max_memory_mb: int = 512
    mock_tool_responses: Dict[str, Any] = field(default_factory=dict)
    execute_mode: Literal["mock", "live"] = "mock"


@dataclass
class ShadowState:
    """Tracks the runtime state of a shadow fork."""

    outputs: List[Dict[str, Any]] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    start_time: float = 0.0
    elapsed_seconds: float = 0.0
    status: ShadowStatus = ShadowStatus.RUNNING


@dataclass(frozen=True)
class OutputComparison:
    """Structured comparison between primary and shadow outputs.

    Parameters
    ----------
    response_similarity:
        Text similarity score in ``[0, 1]`` (1 = identical).
    tool_call_differences:
        List of tool call discrepancies between primary and shadow.
    latency_delta_seconds:
        Shadow elapsed time minus primary elapsed time.
    summary:
        Human-readable summary of the comparison.
    """

    response_similarity: float
    tool_call_differences: List[Dict[str, Any]]
    latency_delta_seconds: float
    summary: str


# ---------------------------------------------------------------------------
# LLM caller protocol
# ---------------------------------------------------------------------------

# Any async callable that takes (prompt, config) and returns a response dict.
LLMCaller = Callable[..., Coroutine[Any, Any, Dict[str, Any]]]


# ---------------------------------------------------------------------------
# ShadowFork
# ---------------------------------------------------------------------------

class ShadowFork:
    """Creates and manages isolated shadow agent executions.

    The shadow receives the same inputs as the primary agent but runs
    with a modified configuration and a mock tool layer that intercepts
    all tool calls.

    Parameters
    ----------
    primary_config:
        The primary agent's configuration dict.
    shadow_config:
        Shadow-specific settings (modifications, timeouts, mode).
    llm_caller:
        Optional async callable for live-mode LLM execution.  Required
        when ``shadow_config.execute_mode == "live"``.
    """

    def __init__(
        self,
        primary_config: dict,
        shadow_config: ShadowConfig,
        llm_caller: LLMCaller | None = None,
    ) -> None:
        self._primary_config = copy.deepcopy(primary_config)
        self._shadow_config = shadow_config
        self._shadows: Dict[str, ShadowState] = {}
        self._shadow_configs: Dict[str, dict] = {}
        self._llm_caller = llm_caller

    # -- public API ---------------------------------------------------------

    def fork(self) -> str:
        """Create a new shadow fork and return its unique ID."""
        shadow_id = f"shadow-{uuid.uuid4().hex[:12]}"
        merged = copy.deepcopy(self._primary_config)
        merged.update(self._shadow_config.modification)
        self._shadow_configs[shadow_id] = merged

        state = ShadowState(start_time=time.monotonic())
        self._shadows[shadow_id] = state
        logger.info("Forked shadow %s", shadow_id)
        return shadow_id

    def execute_turn(self, shadow_id: str, input_message: str) -> dict:
        """Process *input_message* through the shadow fork.

        In **mock** mode, records inputs and returns pre-configured mock
        responses without any LLM call.

        In **live** mode (synchronous fallback), records tool calls and
        returns a placeholder.  For true async live execution, use
        :meth:`execute_turn_async`.
        """
        state = self._get_state_or_raise(shadow_id)
        if state.status != ShadowStatus.RUNNING:
            raise RuntimeError(
                f"Shadow {shadow_id} is not running (status={state.status})"
            )

        if not self._check_resource_limits(shadow_id):
            state.status = ShadowStatus.TIMEOUT
            state.elapsed_seconds = time.monotonic() - state.start_time
            raise RuntimeError(f"Shadow {shadow_id} exceeded resource limits")

        if self._shadow_config.execute_mode == "live":
            return self._execute_live_turn(shadow_id, input_message, state)

        return self._execute_mock_turn(shadow_id, input_message, state)

    async def execute_turn_async(
        self, shadow_id: str, input_message: str
    ) -> dict:
        """Async version of :meth:`execute_turn` for live-mode execution.

        Uses ``asyncio.wait_for`` to enforce the timeout in live mode.
        Falls back to synchronous mock execution when in mock mode.
        """
        state = self._get_state_or_raise(shadow_id)
        if state.status != ShadowStatus.RUNNING:
            raise RuntimeError(
                f"Shadow {shadow_id} is not running (status={state.status})"
            )

        if not self._check_resource_limits(shadow_id):
            state.status = ShadowStatus.TIMEOUT
            state.elapsed_seconds = time.monotonic() - state.start_time
            raise RuntimeError(f"Shadow {shadow_id} exceeded resource limits")

        if (
            self._shadow_config.execute_mode == "live"
            and self._llm_caller is not None
        ):
            remaining = self._shadow_config.timeout_seconds - (
                time.monotonic() - state.start_time
            )
            if remaining <= 0:
                state.status = ShadowStatus.TIMEOUT
                state.elapsed_seconds = time.monotonic() - state.start_time
                raise RuntimeError(
                    f"Shadow {shadow_id} exceeded resource limits"
                )

            try:
                result = await asyncio.wait_for(
                    self._execute_live_turn_async(
                        shadow_id, input_message, state
                    ),
                    timeout=remaining,
                )
                return result
            except asyncio.TimeoutError:
                state.status = ShadowStatus.TIMEOUT
                state.elapsed_seconds = time.monotonic() - state.start_time
                logger.warning(
                    "Shadow %s timed out during live execution", shadow_id
                )
                raise RuntimeError(
                    f"Shadow {shadow_id} exceeded resource limits"
                )

        return self._execute_mock_turn(shadow_id, input_message, state)

    def get_state(self, shadow_id: str) -> ShadowState:
        """Return the current state of *shadow_id*."""
        return self._get_state_or_raise(shadow_id)

    def terminate(self, shadow_id: str) -> ShadowState:
        """Terminate a shadow fork and return its final state."""
        state = self._get_state_or_raise(shadow_id)
        state.elapsed_seconds = time.monotonic() - state.start_time
        if state.status == ShadowStatus.RUNNING:
            if state.elapsed_seconds > self._shadow_config.timeout_seconds:
                state.status = ShadowStatus.TIMEOUT
            else:
                state.status = ShadowStatus.COMPLETED
        logger.info(
            "Terminated shadow %s with status %s", shadow_id, state.status
        )
        return state

    def distribute_input(self, input_message: str) -> tuple[dict, dict]:
        """Structure parallel dispatch of the same input to primary and shadow.

        Returns ``(primary_result, shadow_result)`` as dispatch descriptors.
        Does NOT call any LLM -- just structures the dispatch.
        """
        shadow_id = self.fork()
        primary_result = {
            "agent": "primary",
            "config": copy.deepcopy(self._primary_config),
            "input": input_message,
        }
        shadow_result = {
            "agent": "shadow",
            "shadow_id": shadow_id,
            "config": self._shadow_configs[shadow_id],
            "input": input_message,
        }
        return primary_result, shadow_result

    @staticmethod
    def compare_outputs(
        primary_outputs: List[Dict[str, Any]],
        shadow_outputs: List[Dict[str, Any]],
        primary_elapsed: float = 0.0,
        shadow_elapsed: float = 0.0,
    ) -> OutputComparison:
        """Compare primary and shadow outputs and return a structured diff.

        Parameters
        ----------
        primary_outputs:
            Collected outputs from the primary agent.
        shadow_outputs:
            Collected outputs from the shadow fork.
        primary_elapsed:
            Wall-clock seconds for primary execution.
        shadow_elapsed:
            Wall-clock seconds for shadow execution.
        """
        p_text = " ".join(str(o) for o in primary_outputs)
        s_text = " ".join(str(o) for o in shadow_outputs)
        similarity = (
            SequenceMatcher(None, p_text, s_text).ratio()
            if (p_text or s_text)
            else 1.0
        )

        p_tools = _extract_tool_calls(primary_outputs)
        s_tools = _extract_tool_calls(shadow_outputs)
        tool_diffs = _diff_tool_calls(p_tools, s_tools)

        latency_delta = shadow_elapsed - primary_elapsed

        parts = [f"similarity={similarity:.3f}"]
        if tool_diffs:
            parts.append(f"{len(tool_diffs)} tool call difference(s)")
        if abs(latency_delta) > 0.01:
            parts.append(f"latency_delta={latency_delta:+.3f}s")

        return OutputComparison(
            response_similarity=similarity,
            tool_call_differences=tool_diffs,
            latency_delta_seconds=latency_delta,
            summary="; ".join(parts),
        )

    # -- internal -----------------------------------------------------------

    def _execute_mock_turn(
        self, shadow_id: str, input_message: str, state: ShadowState
    ) -> dict:
        """Original mock execution path — no LLM calls."""
        tool_calls: List[dict] = []
        mock_responses = self._shadow_config.mock_tool_responses
        for tool_name, mock_response in mock_responses.items():
            tool_calls.append({
                "tool": tool_name,
                "input": input_message,
                "response": mock_response,
                "intercepted": True,
            })

        output = {
            "shadow_id": shadow_id,
            "input": input_message,
            "config": self._shadow_configs.get(shadow_id, {}),
            "mock_tool_results": {k: v for k, v in mock_responses.items()},
        }

        state.outputs.append(output)
        state.tool_calls.extend(tool_calls)
        state.elapsed_seconds = time.monotonic() - state.start_time

        logger.debug(
            "Shadow %s mock turn completed: %d tool calls",
            shadow_id,
            len(tool_calls),
        )
        return {
            "shadow_id": shadow_id,
            "output": output,
            "tool_calls": tool_calls,
        }

    def _execute_live_turn(
        self, shadow_id: str, input_message: str, state: ShadowState
    ) -> dict:
        """Synchronous live execution fallback.

        Intercepts tool calls and returns a placeholder response.
        For true async live execution, use :meth:`execute_turn_async`.
        """
        config = self._shadow_configs.get(shadow_id, {})
        tool_calls: List[dict] = []
        for tool_name, mock_response in self._shadow_config.mock_tool_responses.items():
            tool_calls.append({
                "tool": tool_name,
                "input": input_message,
                "response": mock_response,
                "intercepted": True,
            })

        output = {
            "shadow_id": shadow_id,
            "input": input_message,
            "config": config,
            "mode": "live",
            "response": f"[live-sync placeholder for: {input_message[:80]}]",
            "tool_results": dict(self._shadow_config.mock_tool_responses),
        }

        state.outputs.append(output)
        state.tool_calls.extend(tool_calls)
        state.elapsed_seconds = time.monotonic() - state.start_time
        return {
            "shadow_id": shadow_id,
            "output": output,
            "tool_calls": tool_calls,
        }

    async def _execute_live_turn_async(
        self, shadow_id: str, input_message: str, state: ShadowState
    ) -> dict:
        """Async live execution — calls the injected LLM caller.

        Tool calls are still intercepted; only reasoning changes.
        """
        config = self._shadow_configs.get(shadow_id, {})

        llm_response: Dict[str, Any] = {}
        if self._llm_caller is not None:
            llm_response = await self._llm_caller(input_message, config)

        tool_calls: List[dict] = []
        mock_responses = self._shadow_config.mock_tool_responses

        # Intercept any tool calls the LLM requested
        llm_tool_calls = llm_response.get("tool_calls", [])
        for tc in llm_tool_calls:
            tool_name = tc.get("tool", "unknown")
            mock_resp = mock_responses.get(
                tool_name, f"[mocked: {tool_name}]"
            )
            tool_calls.append({
                "tool": tool_name,
                "input": tc.get("input", ""),
                "response": mock_resp,
                "intercepted": True,
            })

        # Also add configured mock tools not triggered by the LLM
        llm_tool_names = {tc.get("tool") for tc in llm_tool_calls}
        for tool_name, mock_response in mock_responses.items():
            if tool_name not in llm_tool_names:
                tool_calls.append({
                    "tool": tool_name,
                    "input": input_message,
                    "response": mock_response,
                    "intercepted": True,
                })

        output = {
            "shadow_id": shadow_id,
            "input": input_message,
            "config": config,
            "mode": "live",
            "response": llm_response.get("text", ""),
            "tool_results": {tc["tool"]: tc["response"] for tc in tool_calls},
        }

        state.outputs.append(output)
        state.tool_calls.extend(tool_calls)
        state.elapsed_seconds = time.monotonic() - state.start_time
        return {
            "shadow_id": shadow_id,
            "output": output,
            "tool_calls": tool_calls,
        }

    def _check_resource_limits(self, shadow_id: str) -> bool:
        """Return True if the shadow is within resource limits."""
        state = self._get_state_or_raise(shadow_id)
        elapsed = time.monotonic() - state.start_time
        if elapsed > self._shadow_config.timeout_seconds:
            logger.warning("Shadow %s timed out (%.1fs)", shadow_id, elapsed)
            return False
        return True

    def _get_state_or_raise(self, shadow_id: str) -> ShadowState:
        if shadow_id not in self._shadows:
            raise KeyError(f"Unknown shadow ID: {shadow_id}")
        return self._shadows[shadow_id]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_tool_calls(
    outputs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Extract tool call records from a list of output dicts."""
    calls: List[Dict[str, Any]] = []
    for o in outputs:
        if isinstance(o, dict):
            if "tool" in o and "intercepted" in o:
                calls.append(o)
            for v in o.values():
                if isinstance(v, list):
                    for item in v:
                        if isinstance(item, dict) and "tool" in item:
                            calls.append(item)
    return calls


def _diff_tool_calls(
    primary: List[Dict[str, Any]], shadow: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Compute differences between primary and shadow tool call lists."""
    diffs: List[Dict[str, Any]] = []
    p_tools = [tc.get("tool", "") for tc in primary]
    s_tools = [tc.get("tool", "") for tc in shadow]

    for tool in set(s_tools) - set(p_tools):
        diffs.append({"type": "added_in_shadow", "tool": tool})
    for tool in set(p_tools) - set(s_tools):
        diffs.append({"type": "missing_in_shadow", "tool": tool})
    for tool in set(p_tools) & set(s_tools):
        p_count = p_tools.count(tool)
        s_count = s_tools.count(tool)
        if p_count != s_count:
            diffs.append({
                "type": "count_mismatch",
                "tool": tool,
                "primary_count": p_count,
                "shadow_count": s_count,
            })

    return diffs
