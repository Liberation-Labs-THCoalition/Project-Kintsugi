# MCP Server Pattern — Plug-In Agent Architecture

Every Liberation Labs agent can expose its capabilities as MCP tools,
letting users keep their existing runtime (Claude Code, Desktop, Hermes)
and add our scaffolding on top.

**The scaffold wraps, it doesn't replace.**

## Pattern

```
Agent (FastAPI/standalone)
  ↓ wrap
MCP Server (stdio transport)
  ↓ expose as
Tools + Resources
  ↓ consumed by
Any MCP Client (Claude Code, Desktop, Hermes, etc.)
```

## Standard Tool Set (per agent)

Every agent MCP server should expose at minimum:

| Tool | Purpose | Input |
|------|---------|-------|
| `{agent}_ask` | Core capability — route through the full pipeline | message, context |
| `{agent}_plan` | Generate a plan for a task | task, domain |
| `{agent}_health` | Status, drift detection, coherence | (none) |

Optional per agent:
- `{agent}_memory` — query agent's memory/knowledge
- `{agent}_skills` — list available capabilities
- `{agent}_review` — review/audit a specific artifact

## Standard Resource Set

| Resource | Purpose |
|----------|---------|
| `{agent}://{id}/config` | Current configuration |
| `{agent}://{id}/beliefs` | Active beliefs/constraints |
| `{agent}://{id}/state` | Current operational state |

## Implementation Checklist

1. Create `{agent}/mcp_server.py`
2. Import core agent capabilities (orchestrator, security, memory)
3. Define tools with typed inputSchema
4. Define resources for state inspection
5. Use stdio transport for Claude Code/Desktop compatibility
6. Handle MCP SDK absence gracefully (ImportError → helpful message)
7. Accept `--org-id` or equivalent identity parameter

## Client Configuration

```json
// .claude/mcp.json (Claude Code)
{
  "mcpServers": {
    "kintsugi": {
      "command": "python",
      "args": ["-m", "kintsugi.mcp_server", "--org-id", "<uuid>"]
    }
  }
}

// claude_desktop_config.json (Claude Desktop)
{
  "mcpServers": {
    "kintsugi": {
      "command": "python",
      "args": ["-m", "kintsugi.mcp_server", "--org-id", "<uuid>"]
    }
  }
}
```

## Agents in the Fleet

| Agent | Status | Core tool |
|-------|--------|-----------|
| Kintsugi | MCP server built | `kintsugi_ask` — BDI + ethics gates |
| Rivet | FastAPI only (needs MCP wrapper) | `rivet_review` — discipline-gated code review |
| Emet | Docker deployment (needs MCP wrapper) | `emet_investigate` — entity investigation |
| Ayni | FastAPI only (needs MCP wrapper) | `ayni_check` — authenticity monitoring |
| Cura | FastAPI only (needs MCP wrapper) | `cura_assist` — caregiver support |
| Raíz | FastAPI only (needs MCP wrapper) | `raiz_monitor` — environmental justice |

## Security Notes

- PII redaction runs BEFORE the message reaches the LLM
- Security monitor blocks malicious input at the tool handler level
- The MCP transport doesn't bypass any gates — same pipeline as FastAPI
- Org-scoped: each server instance serves one organization's data
