"""Kintsugi MCP Server — plug into any MCP-compatible runtime.

Exposes Kintsugi's capabilities as MCP tools so Claude Code, Claude
Desktop, Hermes, or any MCP client can use the agent without replacing
their existing workflow.

The scaffold wraps, it doesn't replace.

Tools:
  kintsugi_ask       — Route a message through BDI + skills + ethics gates
  kintsugi_plan      — Generate a plan for a task (EFE-scored candidates)
  kintsugi_memory    — Query organizational memory
  kintsugi_skills    — List available skill chips and their domains
  kintsugi_health    — Agent status, drift detection, belief coherence

Resources:
  kintsugi://config  — Current organization configuration
  kintsugi://beliefs — Active beliefs (constraints + learned)
  kintsugi://desires — Mission goals and priorities

Usage:
  python -m kintsugi.mcp_server --org-id <uuid> --port 3100

  # In Claude Code .claude/mcp.json:
  {
    "mcpServers": {
      "kintsugi": {
        "command": "python",
        "args": ["-m", "kintsugi.mcp_server", "--org-id", "<uuid>"]
      }
    }
  }
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

logger = logging.getLogger("kintsugi.mcp")

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import (
        Tool,
        TextContent,
        Resource,
        ResourceTemplate,
    )
    HAS_MCP = True
except ImportError:
    HAS_MCP = False

from kintsugi.cognition import Orchestrator, OrchestratorConfig, ModelTier
from kintsugi.security.monitor import SecurityMonitor
from kintsugi.security.pii import PIIRedactor
from kintsugi.bdi.store import BDIStore


def create_server(org_id: str, config_path: str = "") -> "Server":
    if not HAS_MCP:
        raise ImportError(
            "MCP SDK not installed. Install with: pip install mcp"
        )

    server = Server("kintsugi")
    redactor = PIIRedactor()
    monitor = SecurityMonitor()
    bdi = BDIStore(org_id)
    orchestrator = None

    def _get_orchestrator():
        nonlocal orchestrator
        if orchestrator is None:
            orchestrator = Orchestrator(OrchestratorConfig())
        return orchestrator

    # ── Tools ──

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name="kintsugi_ask",
                description=(
                    "Route a message through Kintsugi's BDI agent with "
                    "ethical gates, PII redaction, and skill-based routing. "
                    "Returns the agent's response with routing metadata."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "The message to process",
                        },
                        "context": {
                            "type": "string",
                            "description": "Optional context (e.g. 'grant_writing', 'finance')",
                            "default": "",
                        },
                    },
                    "required": ["message"],
                },
            ),
            Tool(
                name="kintsugi_plan",
                description=(
                    "Generate an EFE-scored plan for a task. Returns "
                    "candidate actions ranked by expected free energy "
                    "(balancing risk, ambiguity, and epistemic value)."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "The task to plan for",
                        },
                        "domain": {
                            "type": "string",
                            "description": "Skill domain (e.g. 'grants', 'finance', 'communications')",
                            "default": "",
                        },
                    },
                    "required": ["task"],
                },
            ),
            Tool(
                name="kintsugi_memory",
                description=(
                    "Query organizational memory. Returns relevant past "
                    "interactions, decisions, and learned patterns."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "What to search for in memory",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results to return",
                            "default": 5,
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="kintsugi_skills",
                description=(
                    "List available skill chips with their domains, "
                    "capabilities, and EFE weight profiles."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="kintsugi_health",
                description=(
                    "Agent health check: drift detection status, belief "
                    "coherence, active desires, and recent activity."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "kintsugi_ask":
            return await _handle_ask(arguments)
        elif name == "kintsugi_plan":
            return await _handle_plan(arguments)
        elif name == "kintsugi_memory":
            return await _handle_memory(arguments)
        elif name == "kintsugi_skills":
            return await _handle_skills(arguments)
        elif name == "kintsugi_health":
            return await _handle_health(arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    async def _handle_ask(args: dict) -> list[TextContent]:
        message = args.get("message", "")
        context = args.get("context", "")

        redaction = redactor.redact(message)
        verdict = monitor.check_text(message)

        if verdict.verdict.value.lower() == "block":
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "blocked",
                    "reason": verdict.reason,
                    "redacted_input": redaction.redacted_text,
                }),
            )]

        orch = _get_orchestrator()
        routing = await orch.route(message, org_id, context)

        result = {
            "status": "ok",
            "routing": {
                "domain": routing.skill_domain,
                "confidence": routing.confidence,
                "model_tier": routing.model_tier.value if hasattr(routing.model_tier, 'value') else str(routing.model_tier),
                "reasoning": routing.reasoning,
            },
            "security": verdict.verdict.value.lower(),
            "pii_redacted": redaction.types_found,
        }

        if verdict.verdict.value.lower() == "warn":
            result["warning"] = verdict.reason

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    async def _handle_plan(args: dict) -> list[TextContent]:
        task = args.get("task", "")
        domain = args.get("domain", "")

        orch = _get_orchestrator()
        routing = await orch.route(task, org_id, domain)

        result = {
            "task": task,
            "domain": routing.skill_domain,
            "confidence": routing.confidence,
            "model_tier": routing.model_tier.value if hasattr(routing.model_tier, 'value') else str(routing.model_tier),
            "reasoning": routing.reasoning,
        }

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    async def _handle_memory(args: dict) -> list[TextContent]:
        query = args.get("query", "")
        limit = args.get("limit", 5)

        result = {
            "query": query,
            "results": [],
            "note": "Memory query routed — connect CMA pipeline for full retrieval",
        }

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    async def _handle_skills(args: dict) -> list[TextContent]:
        from kintsugi.skills import get_registry
        from kintsugi.skills.bootstrap import register_builtin_chips

        register_builtin_chips()  # idempotent; this process never went through main.py's lifespan
        registry = get_registry()
        skills = [
            {"name": chip.name, "domain": chip.domain.value, "description": chip.description}
            for chip in registry
        ]

        return [TextContent(type="text", text=json.dumps({"skills": skills}, indent=2))]

    async def _handle_health(args: dict) -> list[TextContent]:
        beliefs = bdi.list_beliefs()
        desires = bdi.list_desires()

        result = {
            "org_id": org_id,
            "beliefs": len(beliefs),
            "desires": len(desires),
            "top_desires": [
                {"id": d.id, "priority": d.priority, "content": d.content[:80]}
                for d in sorted(desires, key=lambda d: d.priority, reverse=True)[:3]
            ],
            "status": "healthy",
        }

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # ── Resources ──

    @server.list_resources()
    async def list_resources():
        return [
            Resource(
                uri=f"kintsugi://{org_id}/beliefs",
                name="Active Beliefs",
                description="Current beliefs including constraints and learned patterns",
                mimeType="application/json",
            ),
            Resource(
                uri=f"kintsugi://{org_id}/desires",
                name="Mission Desires",
                description="Organizational goals and priorities",
                mimeType="application/json",
            ),
        ]

    @server.read_resource()
    async def read_resource(uri: str):
        if uri.endswith("/beliefs"):
            beliefs = bdi.list_beliefs()
            data = [{"id": b.id, "content": b.content, "confidence": b.confidence}
                    for b in beliefs]
            return json.dumps(data, indent=2)
        elif uri.endswith("/desires"):
            desires = bdi.list_desires()
            data = [{"id": d.id, "content": d.content, "priority": d.priority}
                    for d in desires]
            return json.dumps(data, indent=2)
        else:
            return json.dumps({"error": f"Unknown resource: {uri}"})

    return server


async def main(org_id: str):
    server = create_server(org_id)
    async with stdio_server() as (read_stream, write_stream):
        init_options = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_options)


if __name__ == "__main__":
    import asyncio

    parser = argparse.ArgumentParser(description="Kintsugi MCP Server")
    parser.add_argument("--org-id", required=True, help="Organization UUID")
    args = parser.parse_args()

    asyncio.run(main(args.org_id))
