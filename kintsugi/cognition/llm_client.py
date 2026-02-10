"""Anthropic LLM client for Kintsugi CMA.

Provides async Claude API integration for:
- Intent classification (Orchestrator disambiguation)
- Content generation (LOI drafts, responses)
- Structured extraction (entity parsing)

Uses the tiered model routing system to select appropriate models
based on task complexity and budget constraints.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from anthropic import AsyncAnthropic

from kintsugi.cognition.model_router import CostTracker, ModelRouter, ModelTier
from kintsugi.config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Response from an LLM completion call."""

    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    stop_reason: str | None = None


class AnthropicClient:
    """Async Anthropic client with tiered model routing and cost tracking.

    Parameters
    ----------
    api_key:
        Anthropic API key. Falls back to ``settings.ANTHROPIC_API_KEY``.
    model_router:
        Router for resolving model tiers to concrete IDs.
    cost_tracker:
        Optional cost tracker for budget enforcement.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_router: ModelRouter | None = None,
        cost_tracker: CostTracker | None = None,
    ) -> None:
        self._api_key = api_key or settings.ANTHROPIC_API_KEY
        if not self._api_key:
            raise ValueError(
                "No Anthropic API key configured. Set ANTHROPIC_API_KEY in environment."
            )

        self._client = AsyncAnthropic(api_key=self._api_key)
        self._router = model_router or ModelRouter()
        self._cost_tracker = cost_tracker

    async def complete(
        self,
        prompt: str,
        *,
        tier: ModelTier = ModelTier.BALANCED,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        stop_sequences: list[str] | None = None,
    ) -> LLMResponse:
        """Generate a completion using the specified model tier.

        Parameters
        ----------
        prompt:
            The user message / prompt text.
        tier:
            Model capability tier (FAST/BALANCED/POWERFUL).
        system:
            Optional system prompt.
        max_tokens:
            Maximum tokens to generate.
        temperature:
            Sampling temperature (0-1).
        stop_sequences:
            Optional stop sequences.

        Returns
        -------
        LLMResponse with text, token counts, and cost estimate.
        """
        model_id = self._router.resolve(tier)
        logger.debug("Resolved tier %s to model %s", tier, model_id)

        messages = [{"role": "user", "content": prompt}]

        response = await self._client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            system=system or "",
            messages=messages,
            temperature=temperature,
            stop_sequences=stop_sequences or [],
        )

        # Extract response text
        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text

        # Calculate cost
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = self._router.estimate_cost(model_id, input_tokens, output_tokens)

        # Track cost if tracker provided
        if self._cost_tracker:
            self._cost_tracker.record(model_id, cost)

        return LLMResponse(
            text=text,
            model=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            stop_reason=response.stop_reason,
        )

    async def classify_intent(
        self,
        message: str,
        domains: list[str],
    ) -> tuple[str, float]:
        """Classify a message into one of the given domains.

        This is designed to be used as the ``llm_classifier`` callback
        for the Orchestrator.

        Parameters
        ----------
        message:
            User message to classify.
        domains:
            List of valid domain names.

        Returns
        -------
        Tuple of (domain, confidence).
        """
        domain_list = ", ".join(domains)

        prompt = f"""Classify the following user message into exactly one of these domains: {domain_list}

User message: "{message}"

Respond with ONLY a JSON object in this exact format:
{{"domain": "<chosen_domain>", "confidence": <0.0-1.0>}}

Choose the single best matching domain. If unsure, use confidence below 0.5."""

        response = await self.complete(
            prompt,
            tier=ModelTier.FAST,
            max_tokens=100,
            temperature=0.0,
        )

        # Parse JSON response
        import json

        try:
            result = json.loads(response.text.strip())
            domain = result.get("domain", "general")
            confidence = float(result.get("confidence", 0.5))

            # Validate domain is in list
            if domain not in domains:
                logger.warning("LLM returned unknown domain %r, falling back", domain)
                domain = "general"
                confidence = 0.3

            return domain, confidence
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Failed to parse LLM classification response: %s", e)
            return "general", 0.3

    async def generate_content(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | None = None,
        tier: ModelTier = ModelTier.BALANCED,
        system: str | None = None,
    ) -> str:
        """Generate content with optional context injection.

        Parameters
        ----------
        prompt:
            Generation prompt.
        context:
            Optional context dict to inject into system prompt.
        tier:
            Model tier for generation.
        system:
            Base system prompt.

        Returns
        -------
        Generated text content.
        """
        full_system = system or ""

        if context:
            context_str = "\n".join(f"- {k}: {v}" for k, v in context.items())
            full_system = f"{full_system}\n\nContext:\n{context_str}"

        response = await self.complete(
            prompt,
            tier=tier,
            system=full_system.strip() or None,
            max_tokens=2048,
            temperature=0.7,
        )

        return response.text

    async def extract_entities(
        self,
        text: str,
        entity_schema: dict[str, str],
    ) -> dict[str, Any]:
        """Extract structured entities from text.

        Parameters
        ----------
        text:
            Text to extract entities from.
        entity_schema:
            Dict of {entity_name: description} to extract.

        Returns
        -------
        Dict of extracted entities.
        """
        schema_desc = "\n".join(
            f'- "{name}": {desc}' for name, desc in entity_schema.items()
        )

        prompt = f"""Extract the following entities from the text:
{schema_desc}

Text: "{text}"

Respond with ONLY a JSON object containing the extracted entities.
Use null for entities not found in the text."""

        response = await self.complete(
            prompt,
            tier=ModelTier.FAST,
            max_tokens=500,
            temperature=0.0,
        )

        import json

        try:
            return json.loads(response.text.strip())
        except json.JSONDecodeError:
            logger.warning("Failed to parse entity extraction response")
            return {}


# Convenience factory
def create_llm_client(
    cost_tracker: CostTracker | None = None,
) -> AnthropicClient:
    """Create a configured AnthropicClient instance.

    Uses settings from environment/config automatically.
    """
    return AnthropicClient(
        api_key=settings.ANTHROPIC_API_KEY,
        model_router=ModelRouter(deployment_tier=settings.DEPLOYMENT_TIER),
        cost_tracker=cost_tracker,
    )
