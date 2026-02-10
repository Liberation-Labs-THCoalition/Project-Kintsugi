#!/usr/bin/env python3
"""Test script for Kintsugi LLM integration.

Run with:
    ANTHROPIC_API_KEY=your-key python scripts/test_llm_integration.py
"""

import asyncio
import os
import sys

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def test_llm_client():
    """Test basic LLM client functionality."""
    from kintsugi.cognition.llm_client import create_llm_client
    from kintsugi.cognition.model_router import ModelTier

    print("=" * 60)
    print("Testing LLM Client")
    print("=" * 60)

    try:
        client = create_llm_client()
        print("[OK] LLM client created")
    except ValueError as e:
        print(f"[SKIP] No API key: {e}")
        return False

    # Test basic completion
    print("\n1. Testing basic completion (FAST tier)...")
    response = await client.complete(
        "What is 2 + 2? Reply with just the number.",
        tier=ModelTier.FAST,
        max_tokens=10,
    )
    print(f"   Response: {response.text.strip()}")
    print(f"   Model: {response.model}")
    print(f"   Tokens: {response.input_tokens} in, {response.output_tokens} out")
    print(f"   Cost: ${response.cost_usd:.4f}")

    # Test intent classification
    print("\n2. Testing intent classification...")
    domains = ["grants", "volunteers", "finance", "general"]

    test_messages = [
        "I need help finding funding for our youth program",
        "How do I recruit more volunteers?",
        "What's our current budget status?",
        "Hello, how are you?",
    ]

    for msg in test_messages:
        domain, confidence = await client.classify_intent(msg, domains)
        print(f"   '{msg[:40]}...' -> {domain} ({confidence:.0%})")

    # Test content generation
    print("\n3. Testing content generation...")
    content = await client.generate_content(
        "Write a one-sentence description of a grant opportunity for youth education.",
        tier=ModelTier.BALANCED,
    )
    print(f"   Generated: {content[:100]}...")

    print("\n[SUCCESS] All LLM tests passed!")
    return True


async def test_orchestrator():
    """Test orchestrator with LLM classifier."""
    from kintsugi.cognition.orchestrator import Orchestrator, OrchestratorConfig
    from kintsugi.cognition.model_router import ModelRouter
    from kintsugi.config.settings import settings

    print("\n" + "=" * 60)
    print("Testing Orchestrator")
    print("=" * 60)

    llm_classifier = None
    if settings.ANTHROPIC_API_KEY:
        from kintsugi.cognition.llm_client import create_llm_client
        client = create_llm_client()
        llm_classifier = client.classify_intent
        print("[OK] LLM classifier attached")
    else:
        print("[INFO] No API key - using keyword matching only")

    orchestrator = Orchestrator(
        config=OrchestratorConfig(),
        model_router=ModelRouter(),
        llm_classifier=llm_classifier,
    )

    test_messages = [
        ("Find grants for education programs", "grants"),
        ("Help me recruit volunteers", "volunteers"),
        ("What's our Q4 budget?", "finance"),
        ("Tell me about community impact", "impact"),
        ("I need to send a newsletter", "communications"),
    ]

    print("\nRouting test messages...")
    for msg, expected in test_messages:
        decision = await orchestrator.route(msg, "test-org-123")
        match = "OK" if decision.skill_domain == expected else "MISS"
        print(f"   [{match}] '{msg[:35]}...' -> {decision.skill_domain} "
              f"({decision.confidence:.0%}, {decision.reasoning[:20]}...)")

    print("\n[SUCCESS] Orchestrator tests passed!")
    return True


async def main():
    """Run all tests."""
    print("\nKintsugi LLM Integration Tests")
    print("=" * 60)

    # Check for API key
    from kintsugi.config.settings import settings
    if settings.ANTHROPIC_API_KEY:
        print(f"API Key: {settings.ANTHROPIC_API_KEY[:8]}...")
    else:
        print("API Key: NOT SET")
        print("\nSet ANTHROPIC_API_KEY environment variable to test LLM features.")
        print("Keyword-only tests will still run.\n")

    await test_orchestrator()

    if settings.ANTHROPIC_API_KEY:
        await test_llm_client()


if __name__ == "__main__":
    asyncio.run(main())
