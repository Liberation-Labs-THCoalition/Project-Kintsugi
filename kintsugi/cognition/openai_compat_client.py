"""OpenAI-compatible LLM client for Kintsugi and Ayni.

Talks to any server that exposes /v1/chat/completions:
  - Ollama (localhost:11434/v1)
  - vLLM (localhost:8000/v1)
  - llama-server (localhost:8080/v1)
  - LM Studio (localhost:1234/v1)
  - OpenRouter (openrouter.ai/api/v1)
  - Any OpenAI-compatible endpoint

Drop-in alternative to AnthropicClient. Same LLMResponse format,
same ModelRouter integration, same cost tracking interface.

Usage:
    client = OpenAICompatClient(base_url="http://localhost:11434/v1")
    response = await client.complete("What is 2+2?", model="qwen3.5:27b")

    # Or with tier routing:
    client = OpenAICompatClient(
        base_url="http://localhost:8000/v1",
        model_router=router,
    )
    response = await client.complete("Draft a grant proposal", tier=ModelTier.POWERFUL)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

import httpx

from kintsugi.cognition.llm_client import LLMResponse
from kintsugi.cognition.model_router import CostTracker, ModelRouter, ModelTier

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen3.5:27b"


class OpenAICompatClient:
    """Async client for OpenAI-compatible inference endpoints.

    Parameters
    ----------
    base_url:
        Base URL of the OpenAI-compatible endpoint (no trailing slash).
        Examples: "http://localhost:11434/v1" (Ollama),
                  "http://localhost:8000/v1" (vLLM),
                  "https://openrouter.ai/api/v1" (OpenRouter)
    api_key:
        API key if required (OpenRouter, hosted endpoints).
        Not needed for local servers.
    default_model:
        Model ID to use when no tier routing is configured.
    model_router:
        Optional ModelRouter for tier-based model selection.
    cost_tracker:
        Optional cost tracker for budget enforcement.
    timeout:
        Request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = "",
        default_model: str = DEFAULT_MODEL,
        model_router: Optional[ModelRouter] = None,
        cost_tracker: Optional[CostTracker] = None,
        timeout: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._router = model_router
        self._cost_tracker = cost_tracker

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=timeout,
        )

    async def complete(
        self,
        prompt: str,
        *,
        tier: Optional[ModelTier] = None,
        model: Optional[str] = None,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        stop_sequences: Optional[list[str]] = None,
        tools: Optional[list[dict]] = None,
    ) -> LLMResponse:
        """Generate a completion.

        Parameters
        ----------
        prompt:
            The user message.
        tier:
            Model capability tier (uses ModelRouter to resolve).
        model:
            Explicit model ID (overrides tier routing).
        system:
            Optional system prompt.
        max_tokens:
            Maximum tokens to generate.
        temperature:
            Sampling temperature.
        stop_sequences:
            Optional stop sequences.
        tools:
            Optional tool/function definitions for function calling.

        Returns
        -------
        LLMResponse matching AnthropicClient's format.
        """
        if model:
            model_id = model
        elif tier and self._router:
            model_id = self._router.resolve(tier)
        else:
            model_id = self._default_model

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        return await self.chat(
            messages=messages,
            model=model_id,
            max_tokens=max_tokens,
            temperature=temperature,
            stop_sequences=stop_sequences,
            tools=tools,
        )

    async def chat(
        self,
        messages: list[dict],
        *,
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        stop_sequences: Optional[list[str]] = None,
        tools: Optional[list[dict]] = None,
    ) -> LLMResponse:
        """Send a chat completion request.

        This is the core method — complete() is a convenience wrapper.
        """
        model_id = model or self._default_model

        payload: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }

        if stop_sequences:
            payload["stop"] = stop_sequences
        if tools:
            payload["tools"] = tools

        logger.debug("OpenAI-compat request to %s model=%s", self._base_url, model_id)

        try:
            resp = await self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("OpenAI-compat HTTP error: %s %s", e.response.status_code, e.response.text[:200])
            raise
        except httpx.RequestError as e:
            logger.error("OpenAI-compat request failed: %s", e)
            raise

        # Parse response
        choices = data.get("choices", [])
        if not choices:
            return LLMResponse(
                text="", model=model_id,
                input_tokens=0, output_tokens=0, cost_usd=0.0,
                stop_reason="no_choices",
            )

        message = choices[0].get("message", {})
        text = message.get("content", "") or ""
        finish_reason = choices[0].get("finish_reason")

        # Token usage (format varies by provider but the field names are standard)
        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

        # Cost estimate (if router available)
        cost = 0.0
        if self._router:
            cost = self._router.estimate_cost(model_id, input_tokens, output_tokens)
        if self._cost_tracker:
            self._cost_tracker.record(model_id, cost)

        # Handle tool calls if present
        tool_calls = message.get("tool_calls")
        response = LLMResponse(
            text=text,
            model=data.get("model", model_id),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            stop_reason=finish_reason,
        )

        # Attach tool calls as extra data if present
        if tool_calls:
            response._tool_calls = tool_calls

        return response

    async def chat_stream(
        self,
        messages: list[dict],
        *,
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Stream a chat completion, yielding text chunks."""
        model_id = model or self._default_model

        payload = {
            "model": model_id,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }

        async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except (json.JSONDecodeError, IndexError):
                    continue

    async def list_models(self) -> list[str]:
        """List available models on the endpoint."""
        try:
            resp = await self._client.get("/models")
            resp.raise_for_status()
            data = resp.json()
            return [m.get("id", "") for m in data.get("data", [])]
        except Exception as e:
            logger.warning("Failed to list models: %s", e)
            return []

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


def create_openai_compat_client(
    base_url: str = DEFAULT_BASE_URL,
    api_key: str = "",
    model: str = DEFAULT_MODEL,
    **kwargs,
) -> OpenAICompatClient:
    """Factory function matching create_llm_client pattern."""
    return OpenAICompatClient(
        base_url=base_url,
        api_key=api_key,
        default_model=model,
        **kwargs,
    )
