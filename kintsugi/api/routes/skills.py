"""Skill registry endpoints — discovery, direct execution, and hot-swap."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from kintsugi.plugins.loader import PluginLoader, PluginLoadError
from kintsugi.plugins.registry import PluginRegistry
from kintsugi.skills.base import SkillContext, SkillRequest
from kintsugi.skills.registry import get_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])

# Process-level plugin machinery for hot-swap. Separate from the static
# skill registry: plugins load from PLUGIN_DIRS and register chips into
# the same global skill registry on load.
_plugin_loader: PluginLoader | None = None
_plugin_registry: PluginRegistry | None = None


def _get_plugin_machinery() -> tuple[PluginLoader, PluginRegistry]:
    global _plugin_loader, _plugin_registry
    if _plugin_loader is None:
        _plugin_loader = PluginLoader()
    if _plugin_registry is None:
        _plugin_registry = PluginRegistry()
    return _plugin_loader, _plugin_registry


class ExecuteSkillRequest(BaseModel):
    intent: str = ""
    raw_input: str = Field(min_length=1)
    org_id: str = "default"
    user_id: str = "api"
    entities: dict[str, Any] = {}
    parameters: dict[str, Any] = {}


@router.get("")
async def list_skills() -> dict:
    registry = get_registry()
    return {"skills": registry.list_all(), "count": len(registry)}


@router.get("/plugins")
async def list_plugins() -> dict:
    loader, plugin_registry = _get_plugin_machinery()
    discovered = [m.to_dict() if hasattr(m, "to_dict") else vars(m) for m in loader.discover()]
    registered = [p.to_dict() for p in plugin_registry.get_all_plugins()]
    return {"discovered": discovered, "registered": registered}


@router.post("/plugins/{plugin_name}/load")
async def load_plugin(plugin_name: str) -> dict:
    loader, plugin_registry = _get_plugin_machinery()
    try:
        loaded = loader.load(plugin_name)
        plugin_registry.register(loaded)
    except PluginLoadError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"loaded": plugin_name, "state": loaded.state.value}


@router.post("/plugins/{plugin_name}/reload")
async def reload_plugin(plugin_name: str) -> dict:
    """Hot-swap: unload the plugin and reload it from disk."""
    loader, plugin_registry = _get_plugin_machinery()
    try:
        plugin_registry.unregister(plugin_name)
        loaded = loader.reload(plugin_name)
        plugin_registry.register(loaded)
    except (PluginLoadError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"reloaded": plugin_name, "state": loaded.state.value}


@router.delete("/plugins/{plugin_name}")
async def unload_plugin(plugin_name: str) -> dict:
    loader, plugin_registry = _get_plugin_machinery()
    plugin_registry.unregister(plugin_name)
    loader.unload(plugin_name)
    return {"unloaded": plugin_name}


@router.get("/{skill_name}")
async def get_skill(skill_name: str) -> dict:
    chip = get_registry().get(skill_name)
    if chip is None:
        raise HTTPException(status_code=404, detail=f"unknown skill {skill_name!r}")
    return {
        "name": chip.name,
        "description": chip.description,
        "version": chip.version,
        "domain": chip.domain.value,
        "capabilities": [c.value for c in chip.capabilities],
        "required_spans": chip.required_spans,
        "consensus_actions": chip.consensus_actions,
    }


@router.post("/{skill_name}/execute")
async def execute_skill(skill_name: str, body: ExecuteSkillRequest) -> dict:
    """Execute one skill chip directly, bypassing orchestrator routing.

    Still subject to the chip's own guardrails (consensus flags are
    returned, not silently executed).
    """
    chip = get_registry().get(skill_name)
    if chip is None:
        raise HTTPException(status_code=404, detail=f"unknown skill {skill_name!r}")

    request = SkillRequest(
        intent=body.intent or skill_name,
        entities=body.entities,
        raw_input=body.raw_input,
        parameters=body.parameters,
    )
    context = SkillContext(
        org_id=body.org_id,
        user_id=body.user_id,
        platform="api",
        metadata={"direct_execution": True},
    )
    try:
        response = await chip.handle(request, context)
    except Exception as exc:
        logger.exception("direct execution of %s failed", skill_name)
        raise HTTPException(status_code=500, detail=f"skill execution failed: {exc}")
    return {
        "skill": chip.name,
        "success": response.success,
        "content": response.content,
        "data": response.data,
        "suggestions": response.suggestions,
        "requires_consensus": response.requires_consensus,
        "consensus_action": response.consensus_action,
    }
