"""Agent v2 routes — enhanced with tree discovery, DAG composition, and skill execution.

Replaces the basic route→LLM pattern with:
1. Tree-based skill discovery
2. DAG composition for multi-step requests
3. Actual skill chip execution (not just LLM passthrough)
4. BDI context injection from VALUES.json
"""

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from kintsugi.api.routes.agent import (
    AgentRequest, AgentResponse,
    _get_llm_client, _redactor, _monitor,
)
from kintsugi.cognition.enhanced_orchestrator import EnhancedOrchestrator
from kintsugi.skills.registry import get_registry
from kintsugi.skills.capability_tree import CapabilityTree
from kintsugi.skills.dag import DAGExecutor
from kintsugi.skills.base import SkillContext, SkillRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/agent", tags=["agent-v2"])

_enhanced_orch = None


def _get_enhanced_orchestrator() -> EnhancedOrchestrator:
    global _enhanced_orch
    if _enhanced_orch is not None:
        return _enhanced_orch

    registry = get_registry()

    tree = CapabilityTree(registry)
    tree.build_from_registry()

    _enhanced_orch = EnhancedOrchestrator(
        registry=registry,
        tree=tree,
        dag_executor=DAGExecutor(registry),
    )

    logger.info("Enhanced orchestrator initialized: %d skills, tree depth %d",
                len(registry), tree.depth)
    return _enhanced_orch


def _load_bdi_context() -> tuple[list, list]:
    """Load desires and beliefs from BDI starter config."""
    bdi_path = Path(os.environ.get("KINTSUGI_BDI_STARTER", "config/bdi_starter.json"))
    if not bdi_path.exists():
        return [], []
    try:
        data = json.loads(bdi_path.read_text())
        desires = [{"type": d.get("content", "")} for d in data.get("desires", [])]
        beliefs = [{b.get("id", ""): b.get("content", "")} for b in data.get("beliefs", [])]
        return desires, beliefs
    except Exception as e:
        logger.warning("Failed to load BDI starter: %s", e)
        return [], []


@router.post("/message", response_model=AgentResponse)
async def agent_message_v2(req: AgentRequest) -> AgentResponse:
    """Enhanced message handling with tree discovery and DAG composition."""

    redaction = _redactor.redact(req.message)
    redacted_text = redaction.redacted_text

    verdict = _monitor.check_text(req.message)
    if verdict.verdict.value.lower() == "block":
        return AgentResponse(
            response=f"Message blocked: {verdict.reason}",
            org_id=req.org_id,
            security_verdict="block",
            redacted_input=redacted_text,
            memory_context=[],
        )

    orch = _get_enhanced_orchestrator()
    desires, beliefs = _load_bdi_context()

    decision = await orch.route(
        message=req.message,
        org_id=req.org_id,
        context=req.context,
        desires=desires,
        beliefs=beliefs,
    )

    registry = get_registry()

    if decision.is_composed and decision.dag:
        context = SkillContext(
            org_id=req.org_id,
            user_id=req.context.get("user_id", "unknown") if req.context else "unknown",
            platform=req.context.get("platform", "api") if req.context else "api",
            metadata=req.context or {},
        )

        result = await orch.execute_dag(decision.dag, context)

        parts = []
        for node_id, response in result.node_results.items():
            parts.append(f"**{node_id}**: {response.content}")
        response_text = "\n\n".join(parts) if parts else "DAG execution produced no output."

        if result.node_errors:
            response_text += "\n\n*Some steps encountered errors: " + \
                           ", ".join(result.node_errors.keys()) + "*"

        return AgentResponse(
            response=response_text,
            org_id=req.org_id,
            security_verdict=verdict.verdict.value.lower(),
            redacted_input=redacted_text,
            memory_context=[],
            metadata={
                "routing": decision.skill_domain,
                "confidence": decision.confidence,
                "composed": True,
                "dag_nodes": len(decision.dag.nodes),
                "skills_used": decision.skill_names,
                "tree_path": decision.tree_path,
            },
        )

    if decision.skill_names:
        chip = registry.get(decision.skill_names[0])
        if chip:
            context = SkillContext(
                org_id=req.org_id,
                user_id=req.context.get("user_id", "unknown") if req.context else "unknown",
                platform=req.context.get("platform", "api") if req.context else "api",
                metadata=req.context or {},
            )
            request = SkillRequest(
                intent=decision.skill_domain,
                raw_input=req.message,
            )

            try:
                response = await chip.handle(request, context)
                return AgentResponse(
                    response=response.content,
                    org_id=req.org_id,
                    security_verdict=verdict.verdict.value.lower(),
                    redacted_input=redacted_text,
                    memory_context=[],
                    metadata={
                        "routing": decision.skill_domain,
                        "confidence": decision.confidence,
                        "skill": chip.name,
                        "tree_path": decision.tree_path,
                    },
                )
            except Exception as e:
                logger.error("Skill execution failed: %s", e)

    llm_client = _get_llm_client()
    if llm_client:
        values_path = Path(os.environ.get("KINTSUGI_VALUES_PATH", "config/VALUES.json"))
        values_context = ""
        if values_path.exists():
            values = json.loads(values_path.read_text())
            shield = values.get("shield_rules", [])
            principles = values.get("design_principles", {})
            values_context = f"\nShield rules: {json.dumps(shield[:5])}"
            values_context += f"\nPrinciples: {json.dumps(dict(list(principles.items())[:3]))}"

        system = f"""You are a mutual aid coordination agent for The Multiverse School.
Routed to: {decision.skill_domain} (confidence: {decision.confidence:.0%})
Available skills: {', '.join(decision.skill_names[:5]) if decision.skill_names else 'general'}
{values_context}

Be warm, direct, and real. If someone asks for help, start with yes.
Be explicit about what you can and cannot do (power transparency).
Accommodate neurodivergent communication styles proactively."""

        try:
            resp = await llm_client.complete(
                req.message,
                tier=decision.routing.model_tier,
                system=system,
                max_tokens=1024,
            )
            return AgentResponse(
                response=resp.text,
                org_id=req.org_id,
                security_verdict=verdict.verdict.value.lower(),
                redacted_input=redacted_text,
                memory_context=[],
                metadata={
                    "routing": decision.skill_domain,
                    "confidence": decision.confidence,
                    "tree_path": decision.tree_path,
                },
            )
        except Exception as e:
            logger.error("LLM generation failed: %s", e)

    return AgentResponse(
        response=f"Routed to {decision.skill_domain}. Configure ANTHROPIC_API_KEY for full responses.",
        org_id=req.org_id,
        security_verdict=verdict.verdict.value.lower(),
        redacted_input=redacted_text,
        memory_context=[],
    )
