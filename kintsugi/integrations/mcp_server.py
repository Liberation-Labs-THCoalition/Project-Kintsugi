"""Kintsugi Memory — real MCP (Model Context Protocol) server.

Unlike kintsugi/integrations/mcp_host.py (an in-process tool dispatcher
used by the FastAPI routes), this is a genuine MCP server: it speaks the
stdio/JSON-RPC transport via the official `mcp` SDK, so it can be
registered in `.mcp.json` and discovered as tools by an MCP client such
as Claude Code.

Run standalone with:

    python -m kintsugi.integrations.mcp_server

Requires ANTHROPIC_API_KEY and DATABASE_URL in the environment (or a
.env file) — this runs as its own process, separate from any client's
own auth.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from sqlalchemy import func

from kintsugi.cognition.llm_client import AnthropicClient, create_llm_client
from kintsugi.config.settings import settings
from kintsugi.db import async_session
from kintsugi.memory.embeddings import EmbeddingProvider, get_embedding_provider
from kintsugi.memory.kg_store import process_memory_for_kg
from kintsugi.memory.tgs_adapter import create_kintsugi_verifier
from kintsugi.memory.temporal import Category, TemporalLog
from kintsugi.memory.temporal_scorer import ScoringWeights, TemporalScorer
from kintsugi.memory.temporal_tree import TemporalTree

logger = logging.getLogger("kintsugi.mcp_server")

TOOL_DEFINITIONS = [
    Tool(
        name="kintsugi_memory_search",
        description=(
            "Search Kintsugi's memory system using hybrid retrieval "
            "(dense + lexical fusion, verified against the knowledge graph "
            "when available)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "org_id": {"type": "string", "description": "Organization UUID"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query", "org_id"],
        },
    ),
    Tool(
        name="kintsugi_memory_store",
        description=(
            "Store a new memory: embeds and indexes the content, and extracts "
            "knowledge-graph entities/relationships from it."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "org_id": {"type": "string", "description": "Organization UUID"},
                "significance": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
            },
            "required": ["content", "org_id"],
        },
    ),
    Tool(
        name="kintsugi_memory_temporal_search",
        description=(
            "Time-aware memory search using the temporal tree (Ebbinghaus "
            "decay, reinforcement/contradiction tracking)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="kintsugi_memory_events_recent",
        description="Query the append-only temporal event log (audit trail).",
        inputSchema={
            "type": "object",
            "properties": {
                "org_id": {"type": "string", "description": "Organization UUID"},
                "category": {"type": "string", "description": "Optional event category filter"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["org_id"],
        },
    ),
]


class _Backend:
    """Lazily-initialized shared dependencies for tool handlers."""

    def __init__(self) -> None:
        self.llm_client: AnthropicClient | None = None
        self.embedder: EmbeddingProvider | None = None
        self.temporal_tree: TemporalTree | None = None
        self.temporal_log = TemporalLog()

    def ensure_ready(self) -> None:
        if self.llm_client is None:
            self.llm_client = create_llm_client()
        if self.embedder is None:
            self.embedder = get_embedding_provider(settings.EMBEDDING_MODE)
        if self.temporal_tree is None:
            self.temporal_tree = TemporalTree()


async def _handle_memory_search(args: dict[str, Any], backend: _Backend) -> dict:
    org_id = uuid.UUID(args["org_id"])
    query = args["query"]
    limit = args.get("limit", 10)

    query_embedding = (await backend.embedder.embed(query)).tolist()

    async with async_session() as session:
        verifier = await create_kintsugi_verifier(
            session, org_id, query, query_embedding, n_results=limit
        )
        report = verifier.retrieve(query, n_results=limit)

    return {
        "query": query,
        "results": [
            {
                "memory_id": vm.memory_id,
                "content": vm.content,
                "score": vm.combined_score,
                "verification": vm.verification,
                "entity_overlap": vm.entity_overlap,
            }
            for vm in report.verified_memories
        ],
        "graph_nodes_consulted": report.graph_nodes,
    }


async def _handle_memory_store(args: dict[str, Any], backend: _Backend) -> dict:
    from kintsugi.models.base import MemoryEmbedding, MemoryLexical, MemoryUnit

    org_id = uuid.UUID(args["org_id"])
    content = args["content"]
    significance = args.get("significance", 5)

    embedding = (await backend.embedder.embed(content)).tolist()

    async with async_session() as session:
        memory = MemoryUnit(org_id=org_id, content=content, significance=significance)
        session.add(memory)
        await session.flush()

        session.add(MemoryEmbedding(memory_id=memory.id, embedding=embedding))
        session.add(MemoryLexical(
            memory_id=memory.id,
            tsv=func.to_tsvector("english", content),
        ))

        kg_result = await process_memory_for_kg(
            session, org_id, memory.id, content,
            embedder=backend.embedder, spacy_model=settings.KG_SPACY_MODEL,
        )

        await session.commit()

    return {
        "memory_id": str(memory.id),
        "knowledge_graph": kg_result,
    }


async def _handle_temporal_search(args: dict[str, Any], backend: _Backend) -> dict:
    from kintsugi.memory.temporal_scorer import QueryScoper

    query = args["query"]
    limit = args.get("limit", 10)

    scoper = QueryScoper()
    scope, time_hint = scoper.scope_query(query)

    nodes = backend.temporal_tree.search(scope, time_hint)[:limit]
    scorer = TemporalScorer(backend.temporal_tree, ScoringWeights())
    scored = scorer.score_results(
        [{"content": n.content, "tgs_score": 0.5, "id": n.id} for n in nodes],
        query_time_hint=time_hint,
    )

    return {
        "query": query,
        "scope": scope.value,
        "results": [
            {
                "node_id": r.node_id,
                "content": r.content,
                "combined_score": r.combined_score,
                "robustness_score": r.robustness_score,
                "contradicted": r.contradicted,
            }
            for r in scored
        ],
    }


async def _handle_events_recent(args: dict[str, Any], backend: _Backend) -> dict:
    org_id = args["org_id"]
    category = args.get("category")
    limit = args.get("limit", 20)

    async with async_session() as session:
        events = await backend.temporal_log.query_events(
            org_id=org_id, category=category, limit=limit, session=session,
        )

    return {
        "events": [
            {
                "id": e.id,
                "category": e.category,
                "message": e.message,
                "created_at": e.created_at.isoformat() if isinstance(e.created_at, datetime) else str(e.created_at),
            }
            for e in events
        ],
    }


_TOOL_HANDLERS = {
    "kintsugi_memory_search": _handle_memory_search,
    "kintsugi_memory_store": _handle_memory_store,
    "kintsugi_memory_temporal_search": _handle_temporal_search,
    "kintsugi_memory_events_recent": _handle_events_recent,
}


def create_mcp_server() -> Server:
    server = Server("kintsugi-memory")
    backend = _Backend()

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        return TOOL_DEFINITIONS

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        handler = _TOOL_HANDLERS.get(name)
        if handler is None:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

        try:
            backend.ensure_ready()
            result = await handler(arguments, backend)
        except Exception as exc:
            logger.exception("Tool %s failed", name)
            result = {"error": str(exc)}

        return [TextContent(type="text", text=json.dumps(result, default=str))]

    return server


def main() -> None:
    """Entry point for running the MCP server over stdio."""
    import asyncio

    logging.basicConfig(level=logging.INFO)
    server = create_mcp_server()

    async def run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            init_options = server.create_initialization_options()
            await server.run(read_stream, write_stream, init_options)
        logger.info("stdio_server context exited, shutting down.")

    asyncio.run(run())


if __name__ == "__main__":
    main()
