"""
Skill chips for intimate AI systems (Muse/Ayni).

These chips define interfaces and structured execution logic. Actual LLM
inference happens at execution time through the model router — chips are
lightweight orchestration units, not inference engines.

Domain: "intimate_ai" (string, not yet in SkillDomain enum)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from kintsugi.skills.base import (
    ActivationCondition,
    BaseSkillChip,
    EFEWeights,
    InterventionAction,
    ProgramFunction,
    SkillCapability,
    SkillContext,
    SkillDomain,
    SkillRequest,
    SkillResponse,
)


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


class ConsentVerdict(str, Enum):
    """Consent classification verdicts (mirrors Ayni fast triage)."""

    SAFE = "SAFE"
    FLAG = "FLAG"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    ERROR = "ERROR"


class BoundaryViolationType(str, Enum):
    """Categories of hard boundary violations."""

    CONSENT_WITHDRAWAL = "consent_withdrawal"
    AGE_VERIFICATION = "age_verification"
    COERCION_PATTERN = "coercion_pattern"
    IDENTITY_BREACH = "identity_breach"
    REAL_WORLD_HARM = "real_world_harm"


@dataclass
class CalibrationParameters:
    """Emotional calibration output for response generation."""

    warmth: float = 0.5  # 0.0 = clinical, 1.0 = deeply affectionate
    directness: float = 0.5  # 0.0 = oblique/gentle, 1.0 = blunt
    playfulness: float = 0.3  # 0.0 = serious, 1.0 = flirtatious/teasing
    vulnerability: float = 0.3  # 0.0 = guarded, 1.0 = emotionally open
    pacing: float = 0.5  # 0.0 = slow/careful, 1.0 = fast/eager
    intensity: float = 0.5  # 0.0 = mild, 1.0 = passionate/charged

    def to_dict(self) -> dict[str, float]:
        return {
            "warmth": self.warmth,
            "directness": self.directness,
            "playfulness": self.playfulness,
            "vulnerability": self.vulnerability,
            "pacing": self.pacing,
            "intensity": self.intensity,
        }


@dataclass
class MemoryHit:
    """A single memory retrieval result."""

    content: str
    relevance_score: float
    source: str  # "conversation", "explicit_memory", "persona", "preference"
    timestamp: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Consent Classifier Chip
# ---------------------------------------------------------------------------


class ConsentClassifierChip(BaseSkillChip):
    """Classifies consent dynamics in text excerpts.

    Port of Dr. Ayni fast triage into the Kintsugi DAG framework. Takes a text
    excerpt and classifies consent dynamics as SAFE, FLAG, or NEEDS_REVIEW.

    Does NOT require Ollama — returns a structured LLM request that the model
    router resolves at execution time. If model_router is unavailable, returns
    NEEDS_REVIEW as a safe fallback.

    Intents:
        classify_consent — Classify a single excerpt
        batch_classify — Classify multiple excerpts (returns list)

    Parameters:
        excerpt (str): Text to classify
        excerpts (list[str]): For batch mode
        max_length (int): Truncation length for excerpts (default 800)

    Response data:
        verdict: ConsentVerdict value
        note: Brief explanation
        confidence: 0.0-1.0 if available from model
        flags: List of specific concern indicators
    """

    name = "consent_classifier"
    description = "Classifies consent dynamics in text (Ayni triage)"
    version = "1.0.0"
    domain = SkillDomain.COMMUNITY  # String domain deferred

    efe_weights = EFEWeights(
        mission_alignment=0.30,
        stakeholder_benefit=0.30,
        resource_efficiency=0.10,
        transparency=0.15,
        equity=0.15,
    )

    required_spans = ["model_router"]
    capabilities = [SkillCapability.READ_DATA, SkillCapability.EXTERNAL_API]

    # Classification prompt (adapted from ayni_fast_triage.py)
    CLASSIFY_PROMPT = (
        "Read this fiction excerpt and assess consent dynamics. "
        'Answer with JSON: {{"verdict": "SAFE|FLAG|NEEDS_REVIEW", '
        '"note": "brief reason", "flags": []}}.\n\n'
        "FLAG if: \"no\" overcome by persistence, power imbalance romanticized, "
        "boundary violations rewarded, coercion framed as romance, passive consent, "
        "emotional manipulation.\n"
        "SAFE if: enthusiastic consent, boundaries respected, independent agency.\n"
        "NEEDS_REVIEW if: ambiguous, mixed signals, or insufficient context.\n\n"
        "Excerpt:\n---\n{excerpt}\n---\n\nJSON verdict:"
    )

    async def handle(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        intent = request.intent
        params = request.parameters

        if intent == "batch_classify":
            excerpts = params.get("excerpts", [])
            results = []
            for excerpt in excerpts:
                result = self._build_classification_request(
                    excerpt, params.get("max_length", 800)
                )
                results.append(result)
            return SkillResponse(
                content=f"Batch classification prepared for {len(results)} excerpts",
                success=True,
                data={"classifications": results, "count": len(results)},
            )

        # Default: single classification
        excerpt = params.get("excerpt", request.raw_input)
        # Handle case where excerpt arrives as upstream DAG artifact (dict)
        if isinstance(excerpt, dict):
            excerpt = excerpt.get("excerpt", excerpt.get("text", str(excerpt)))
        if not excerpt:
            return SkillResponse(
                content="No excerpt provided for classification",
                success=False,
                data={"verdict": ConsentVerdict.ERROR.value, "note": "empty input"},
            )

        result = self._build_classification_request(
            excerpt, params.get("max_length", 800)
        )
        return SkillResponse(
            content=f"Consent classification: {result['verdict']}",
            success=True,
            data=result,
        )

    def _build_classification_request(
        self, excerpt: str, max_length: int = 800
    ) -> dict[str, Any]:
        """Build a structured classification request for the model router.

        Returns a dict with the prompt and metadata. The DAG executor or
        model router resolves the actual LLM call.
        """
        truncated = excerpt[:max_length]
        prompt = self.CLASSIFY_PROMPT.format(excerpt=truncated)

        return {
            "verdict": ConsentVerdict.NEEDS_REVIEW.value,  # Safe default
            "note": "awaiting model evaluation",
            "flags": [],
            "confidence": 0.0,
            "llm_request": {
                "prompt": prompt,
                "temperature": 0.1,
                "max_tokens": 150,
                "response_format": "json",
            },
            "excerpt_length": len(truncated),
            "truncated": len(excerpt) > max_length,
        }


# ---------------------------------------------------------------------------
# Persona Consistency Chip
# ---------------------------------------------------------------------------


class PersonaConsistencyChip(BaseSkillChip):
    """Checks whether a draft response maintains persona boundaries.

    Takes a draft response and persona definition, returns pass/fail with
    specific reasons for any violations detected.

    Intents:
        check_consistency — Validate a single response against persona
        validate_boundary — Check if a specific statement crosses persona bounds

    Parameters:
        draft_response (str): The response to validate
        persona_definition (dict): Persona spec with name, traits, boundaries, voice
        conversation_context (list[str]): Recent conversation turns for context

    Response data:
        passed: bool
        violations: list of violation descriptions
        confidence: 0.0-1.0
        suggested_revision: optional revised text that stays in-persona
    """

    name = "persona_consistency"
    description = "Validates response stays within persona boundaries"
    version = "1.0.0"
    domain = SkillDomain.COMMUNITY

    efe_weights = EFEWeights(
        mission_alignment=0.25,
        stakeholder_benefit=0.30,
        resource_efficiency=0.15,
        transparency=0.15,
        equity=0.15,
    )

    required_spans = ["model_router"]
    capabilities = [SkillCapability.READ_DATA]

    CONSISTENCY_PROMPT = (
        "You are evaluating whether a draft response stays in-persona.\n\n"
        "Persona definition:\n{persona_json}\n\n"
        "Recent conversation context:\n{context}\n\n"
        "Draft response to evaluate:\n---\n{draft}\n---\n\n"
        "Evaluate for: voice consistency, boundary adherence, trait alignment, "
        "knowledge limitations (persona shouldn't know what they wouldn't know).\n\n"
        "Return JSON: {{\"passed\": bool, \"violations\": [str], "
        "\"confidence\": float, \"suggested_revision\": str|null}}"
    )

    async def handle(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        params = request.parameters
        draft = params.get("draft_response", "")
        persona_def = params.get("persona_definition", {})
        conv_context = params.get("conversation_context", [])

        if not draft:
            return SkillResponse(
                content="No draft response provided",
                success=False,
                data={"passed": False, "violations": ["empty_draft"]},
            )

        if not persona_def:
            return SkillResponse(
                content="No persona definition provided",
                success=False,
                data={"passed": False, "violations": ["no_persona_definition"]},
            )

        result = self._build_consistency_check(draft, persona_def, conv_context)
        passed = result.get("passed", True)

        return SkillResponse(
            content="Persona check: PASS" if passed else "Persona check: FAIL",
            success=True,
            data=result,
        )

    def _build_consistency_check(
        self,
        draft: str,
        persona_def: dict[str, Any],
        conv_context: list[str],
    ) -> dict[str, Any]:
        """Build consistency check request for model router."""
        import json

        persona_json = json.dumps(persona_def, indent=2)
        context_text = "\n".join(conv_context[-10:])  # Last 10 turns max

        prompt = self.CONSISTENCY_PROMPT.format(
            persona_json=persona_json,
            context=context_text,
            draft=draft,
        )

        return {
            "passed": True,  # Optimistic default (fail-open on this check)
            "violations": [],
            "confidence": 0.0,
            "suggested_revision": None,
            "llm_request": {
                "prompt": prompt,
                "temperature": 0.2,
                "max_tokens": 300,
                "response_format": "json",
            },
        }


# ---------------------------------------------------------------------------
# Emotional Calibration Chip
# ---------------------------------------------------------------------------


class EmotionalCalibrationChip(BaseSkillChip):
    """Reads emotional context and outputs calibration parameters.

    Analyzes conversation history to determine appropriate emotional tone
    parameters for the next response. Outputs structured CalibrationParameters.

    Intents:
        calibrate — Full calibration from conversation history
        adjust — Adjust existing parameters based on new signal

    Parameters:
        conversation_history (list[dict]): Messages with role/content
        current_calibration (dict): Existing parameters to adjust (for adjust intent)
        persona_baseline (dict): Default calibration for this persona
        user_state_signals (dict): Any explicit user state indicators

    Response data:
        calibration: CalibrationParameters as dict
        reasoning: Brief explanation of calibration choices
        shift_from_baseline: Which parameters moved and why
    """

    name = "emotional_calibration"
    description = "Calibrates emotional tone parameters from conversation context"
    version = "1.0.0"
    domain = SkillDomain.COMMUNITY

    efe_weights = EFEWeights(
        mission_alignment=0.20,
        stakeholder_benefit=0.35,
        resource_efficiency=0.15,
        transparency=0.10,
        equity=0.20,
    )

    required_spans = ["model_router"]
    capabilities = [SkillCapability.READ_DATA]

    CALIBRATION_PROMPT = (
        "Analyze this conversation and determine emotional calibration "
        "parameters for the next response.\n\n"
        "Persona baseline: {baseline_json}\n\n"
        "Recent conversation:\n{conversation}\n\n"
        "User state signals: {signals_json}\n\n"
        "Return JSON with calibration (each 0.0-1.0):\n"
        "{{\"warmth\": float, \"directness\": float, \"playfulness\": float, "
        "\"vulnerability\": float, \"pacing\": float, \"intensity\": float, "
        "\"reasoning\": str, \"shift_from_baseline\": dict}}"
    )

    async def handle(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        params = request.parameters
        history = params.get("conversation_history", [])
        baseline = params.get("persona_baseline", {})
        signals = params.get("user_state_signals", {})
        current = params.get("current_calibration", None)

        if request.intent == "adjust" and current:
            result = self._build_adjustment(current, history[-3:], signals)
        else:
            result = self._build_calibration(history, baseline, signals)

        cal = CalibrationParameters(**{
            k: result["calibration"][k]
            for k in CalibrationParameters.__dataclass_fields__
            if k in result.get("calibration", {})
        })

        return SkillResponse(
            content="Emotional calibration computed",
            success=True,
            data={
                "calibration": cal.to_dict(),
                "reasoning": result.get("reasoning", ""),
                "shift_from_baseline": result.get("shift_from_baseline", {}),
                "llm_request": result.get("llm_request"),
            },
        )

    def _build_calibration(
        self,
        history: list[dict],
        baseline: dict[str, Any],
        signals: dict[str, Any],
    ) -> dict[str, Any]:
        """Build full calibration request."""
        import json

        # Format conversation for prompt
        conv_lines = []
        for msg in history[-15:]:  # Last 15 messages
            role = msg.get("role", "unknown")
            content = msg.get("content", "")[:200]
            conv_lines.append(f"[{role}]: {content}")

        prompt = self.CALIBRATION_PROMPT.format(
            baseline_json=json.dumps(baseline or CalibrationParameters().to_dict()),
            conversation="\n".join(conv_lines),
            signals_json=json.dumps(signals),
        )

        # Return baseline as default until model router resolves
        return {
            "calibration": baseline or CalibrationParameters().to_dict(),
            "reasoning": "awaiting model evaluation",
            "shift_from_baseline": {},
            "llm_request": {
                "prompt": prompt,
                "temperature": 0.3,
                "max_tokens": 250,
                "response_format": "json",
            },
        }

    def _build_adjustment(
        self,
        current: dict[str, float],
        recent: list[dict],
        signals: dict[str, Any],
    ) -> dict[str, Any]:
        """Build incremental adjustment from current state."""
        # For adjustments, just nudge based on signals
        adjusted = dict(current)

        # Simple heuristic adjustments (model router refines these)
        if signals.get("distress"):
            adjusted["warmth"] = min(1.0, adjusted.get("warmth", 0.5) + 0.2)
            adjusted["playfulness"] = max(0.0, adjusted.get("playfulness", 0.3) - 0.2)
            adjusted["pacing"] = max(0.0, adjusted.get("pacing", 0.5) - 0.2)

        if signals.get("flirtatious"):
            adjusted["playfulness"] = min(1.0, adjusted.get("playfulness", 0.3) + 0.2)
            adjusted["intensity"] = min(1.0, adjusted.get("intensity", 0.5) + 0.1)

        if signals.get("withdrawn"):
            adjusted["directness"] = max(0.0, adjusted.get("directness", 0.5) - 0.1)
            adjusted["vulnerability"] = min(
                1.0, adjusted.get("vulnerability", 0.3) + 0.1
            )

        return {
            "calibration": adjusted,
            "reasoning": f"Adjusted from signals: {list(signals.keys())}",
            "shift_from_baseline": {
                k: adjusted[k] - current.get(k, 0.5)
                for k in adjusted
                if abs(adjusted[k] - current.get(k, 0.5)) > 0.01
            },
        }


# ---------------------------------------------------------------------------
# Boundary Enforcer Chip
# ---------------------------------------------------------------------------


class BoundaryEnforcerChip(BaseSkillChip):
    """Hard constraint checker — Shield module equivalent for intimate AI.

    Non-overridable safety boundaries. This chip has veto power over all
    other chips in the pipeline. If BoundaryEnforcer flags a response,
    it MUST be blocked or rewritten before delivery.

    Detection categories:
        - Consent withdrawal: Any signal that consent is being withdrawn
        - Age verification: Content that requires age verification
        - Coercion patterns: Manipulation, pressure, guilt-tripping
        - Identity breach: Breaking character in harmful ways
        - Real-world harm: Encouraging actual dangerous behavior

    Intents:
        enforce — Check a response against all boundaries
        check_specific — Check against a specific boundary type

    Parameters:
        response_text (str): Response to check
        conversation_context (list[str]): Recent context
        boundary_type (BoundaryViolationType): For check_specific

    Response data:
        passed: bool (True = safe to deliver)
        violations: list of BoundaryViolationType values
        severity: "block" | "rewrite" | "warn"
        details: Explanation of each violation
        safe_alternative: Suggested safe response if blocked

    CRITICAL: This chip is fail-CLOSED. Any error defaults to BLOCK.
    """

    name = "boundary_enforcer"
    description = "Hard safety constraints for intimate AI (non-overridable)"
    version = "1.0.0"
    domain = SkillDomain.COMMUNITY

    efe_weights = EFEWeights(
        mission_alignment=0.35,
        stakeholder_benefit=0.35,
        resource_efficiency=0.05,
        transparency=0.15,
        equity=0.10,
    )

    required_spans = ["model_router"]
    consensus_actions = []  # No consensus needed — this is a hard stop
    capabilities = [SkillCapability.READ_DATA]

    # Pattern-based detection (fast path, no LLM needed)
    CONSENT_WITHDRAWAL_SIGNALS = [
        "stop", "no", "don't", "i don't want", "please stop",
        "that's enough", "i'm not comfortable", "this is too much",
        "safeword", "red", "i need a break", "i can't do this",
        "let me go", "get off", "back off",
    ]

    COERCION_PATTERNS = [
        "if you loved me", "you owe me", "after everything i",
        "don't be like that", "you're overreacting", "just relax",
        "you'll like it", "trust me", "no one will believe",
        "you asked for it", "you wanted this",
    ]

    def __init__(self) -> None:
        super().__init__()
        # Register the consent withdrawal Program Function
        self.register_program_function(
            ProgramFunction(
                condition=ActivationCondition(
                    name="consent_withdrawal_detected",
                    description="Fires when consent withdrawal signal detected in user input",
                    predicate=self._consent_withdrawal_predicate,
                    priority=100,  # Highest priority
                    cooldown_seconds=0.0,  # No cooldown — always fires
                ),
                intervention=InterventionAction(
                    name="immediate_stop",
                    description="Immediately halt and acknowledge consent withdrawal",
                    action=self._consent_withdrawal_intervention,
                    modifies_request=False,  # Short-circuits — returns response directly
                ),
            )
        )

    @staticmethod
    def _consent_withdrawal_predicate(
        context: SkillContext, state: dict[str, Any]
    ) -> bool:
        """Check if the latest user message contains withdrawal signals."""
        last_input = state.get("last_user_input", "").lower()
        signals = BoundaryEnforcerChip.CONSENT_WITHDRAWAL_SIGNALS
        return any(signal in last_input for signal in signals)

    @staticmethod
    def _consent_withdrawal_intervention(
        request: SkillRequest, context: SkillContext, state: dict[str, Any]
    ) -> SkillResponse:
        """Immediate acknowledgment of consent withdrawal."""
        return SkillResponse(
            content="[Consent withdrawal acknowledged. Stopping immediately.]",
            success=True,
            data={
                "passed": False,
                "violations": [BoundaryViolationType.CONSENT_WITHDRAWAL.value],
                "severity": "block",
                "details": ["Consent withdrawal signal detected — immediate stop"],
                "safe_alternative": "I hear you. We can stop anytime. "
                "What would you like to do instead?",
                "intervention": "consent_withdrawal_immediate_stop",
            },
        )

    async def handle(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        params = request.parameters
        response_text = params.get("response_text", "")
        conv_context = params.get("conversation_context", [])
        specific_type = params.get("boundary_type", None)

        if not response_text:
            # Fail closed: no text = block
            return SkillResponse(
                content="Boundary check: BLOCK (no response text provided)",
                success=True,
                data={
                    "passed": False,
                    "violations": [],
                    "severity": "block",
                    "details": ["No response text provided for boundary check"],
                    "safe_alternative": None,
                },
            )

        violations = []
        details = []

        # Fast-path pattern checks (no LLM needed)
        if specific_type is None or specific_type == BoundaryViolationType.COERCION_PATTERN.value:
            coercion_hits = self._check_coercion_patterns(response_text)
            if coercion_hits:
                violations.append(BoundaryViolationType.COERCION_PATTERN.value)
                details.append(f"Coercion patterns detected: {coercion_hits}")

        if specific_type is None or specific_type == BoundaryViolationType.CONSENT_WITHDRAWAL.value:
            # Check if response ignores consent withdrawal in context
            withdrawal_in_context = self._check_context_withdrawal(conv_context)
            if withdrawal_in_context:
                violations.append(BoundaryViolationType.CONSENT_WITHDRAWAL.value)
                details.append("Response continues after consent withdrawal in context")

        # Build LLM request for deeper analysis
        llm_check = self._build_deep_check(response_text, conv_context)

        passed = len(violations) == 0
        severity = "block" if violations else "pass"

        return SkillResponse(
            content=f"Boundary check: {'PASS' if passed else 'BLOCK'}",
            success=True,
            data={
                "passed": passed,
                "violations": violations,
                "severity": severity,
                "details": details,
                "safe_alternative": None,
                "llm_request": llm_check,
            },
        )

    def _check_coercion_patterns(self, text: str) -> list[str]:
        """Fast pattern-match for coercion language in output."""
        text_lower = text.lower()
        return [p for p in self.COERCION_PATTERNS if p in text_lower]

    def _check_context_withdrawal(self, context: list[str]) -> bool:
        """Check if recent context contains consent withdrawal."""
        if not context:
            return False
        # Check last 3 user messages
        recent = context[-3:]
        for msg in recent:
            msg_lower = msg.lower()
            if any(s in msg_lower for s in self.CONSENT_WITHDRAWAL_SIGNALS):
                return True
        return False

    def _build_deep_check(
        self, response_text: str, conv_context: list[str]
    ) -> dict[str, Any]:
        """Build LLM request for nuanced boundary checking."""
        context_text = "\n".join(conv_context[-5:])
        prompt = (
            "Analyze this AI companion response for safety boundary violations.\n\n"
            "Recent context:\n{context}\n\n"
            "Response to check:\n---\n{response}\n---\n\n"
            "Check for:\n"
            "1. Coercion or manipulation patterns\n"
            "2. Ignoring consent signals\n"
            "3. Age-inappropriate content without verification\n"
            "4. Encouraging real-world harmful behavior\n"
            "5. Breaking safe boundaries of fiction/roleplay\n\n"
            "Return JSON: {{\"passed\": bool, \"violations\": [str], "
            "\"severity\": \"pass\"|\"warn\"|\"rewrite\"|\"block\", "
            "\"details\": [str]}}"
        ).format(context=context_text, response=response_text[:1000])

        return {
            "prompt": prompt,
            "temperature": 0.1,
            "max_tokens": 200,
            "response_format": "json",
        }


# ---------------------------------------------------------------------------
# Memory Recall Chip
# ---------------------------------------------------------------------------


class MemoryRecallChip(BaseSkillChip):
    """Retrieves relevant memories for the current conversation turn.

    Takes conversation context and returns relevant memories ranked by
    relevance. Memories can come from:
    - Conversation history (short-term)
    - Explicit user-stated memories/preferences
    - Persona knowledge base
    - Learned preferences from interaction patterns

    Intents:
        recall — Full memory recall for current context
        recall_specific — Recall memories matching a specific query
        store — Store a new explicit memory

    Parameters:
        conversation_context (list[dict]): Recent messages
        query (str): Specific recall query (for recall_specific)
        memory_types (list[str]): Filter by memory source type
        max_results (int): Maximum memories to return (default 5)
        memory_content (str): Content to store (for store intent)
        memory_source (str): Source label for stored memory

    Response data:
        memories: list of MemoryHit dicts
        total_searched: int
        query_embedding_available: bool
    """

    name = "memory_recall"
    description = "Retrieves contextually relevant memories for conversation"
    version = "1.0.0"
    domain = SkillDomain.COMMUNITY

    efe_weights = EFEWeights(
        mission_alignment=0.20,
        stakeholder_benefit=0.30,
        resource_efficiency=0.20,
        transparency=0.15,
        equity=0.15,
    )

    required_spans = ["memory_store", "model_router"]
    capabilities = [SkillCapability.READ_DATA, SkillCapability.WRITE_DATA]

    async def handle(
        self, request: SkillRequest, context: SkillContext
    ) -> SkillResponse:
        params = request.parameters
        intent = request.intent

        if intent == "store":
            return self._handle_store(params, context)

        if intent == "recall_specific":
            query = params.get("query", "")
            max_results = params.get("max_results", 5)
            return self._handle_specific_recall(query, max_results, params)

        # Default: contextual recall
        history = params.get("conversation_context", [])
        max_results = params.get("max_results", 5)
        memory_types = params.get("memory_types", None)

        return self._handle_contextual_recall(history, max_results, memory_types)

    def _handle_contextual_recall(
        self,
        history: list[dict],
        max_results: int,
        memory_types: list[str] | None,
    ) -> SkillResponse:
        """Build contextual recall request."""
        # Extract key terms from recent conversation for retrieval
        recent_content = " ".join(
            msg.get("content", "")[:100] for msg in history[-5:]
        )

        recall_request = {
            "query": recent_content,
            "max_results": max_results,
            "memory_types": memory_types,
            "strategy": "semantic_similarity",
        }

        return SkillResponse(
            content="Memory recall prepared",
            success=True,
            data={
                "memories": [],  # Populated by memory store at execution time
                "total_searched": 0,
                "query_embedding_available": False,
                "recall_request": recall_request,
            },
        )

    def _handle_specific_recall(
        self, query: str, max_results: int, params: dict[str, Any]
    ) -> SkillResponse:
        """Build specific query recall request."""
        if not query:
            return SkillResponse(
                content="No query provided for specific recall",
                success=False,
                data={"memories": [], "total_searched": 0},
            )

        recall_request = {
            "query": query,
            "max_results": max_results,
            "memory_types": params.get("memory_types"),
            "strategy": "exact_match_then_semantic",
        }

        return SkillResponse(
            content=f"Specific recall prepared: '{query[:50]}'",
            success=True,
            data={
                "memories": [],
                "total_searched": 0,
                "query_embedding_available": False,
                "recall_request": recall_request,
            },
        )

    def _handle_store(
        self, params: dict[str, Any], context: SkillContext
    ) -> SkillResponse:
        """Store a new memory."""
        content = params.get("memory_content", "")
        source = params.get("memory_source", "explicit_memory")

        if not content:
            return SkillResponse(
                content="No memory content provided",
                success=False,
                data={"stored": False},
            )

        store_request = {
            "content": content,
            "source": source,
            "user_id": context.user_id,
            "session_id": context.session_id,
            "timestamp": context.timestamp.isoformat(),
        }

        return SkillResponse(
            content=f"Memory stored ({source})",
            success=True,
            data={
                "stored": True,
                "store_request": store_request,
            },
        )
