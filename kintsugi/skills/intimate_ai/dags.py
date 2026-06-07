"""
Pre-built DAG templates for Muse/Ayni pipelines.

These functions return SkillDAG instances ready for execution against
a registry that has the intimate_ai chips registered.

DAG Templates:
    build_triage_dag() — Ayni consent triage pipeline
    build_response_dag() — Muse response generation pipeline
"""

from kintsugi.skills.dag import DAGNode, SkillDAG


def build_triage_dag() -> SkillDAG:
    """Build the Ayni consent triage pipeline DAG.

    Pipeline:
        Layer 0: extract — Extract excerpt from raw input
        Layer 1: classify — Consent classification (SAFE/FLAG/NEEDS_REVIEW)
        Layer 2: route — Branch based on verdict
            SAFE → pool (direct to training pool)
            FLAG → retriage (deeper analysis)
        Layer 3: verdict — Final verdict for FLAG items after retriage

    Flow:
        extract → classify → [SAFE → pool]
                            → [FLAG → retriage → verdict]

    The DAG executor handles routing via the output artifacts:
    - If classify outputs verdict=SAFE, the pool node consumes it
    - If classify outputs verdict=FLAG, retriage re-evaluates
    - verdict node produces the final determination

    Returns:
        SkillDAG configured for Ayni triage pipeline
    """
    dag = SkillDAG(
        strategy="quality",
        metadata={
            "name": "ayni_triage",
            "description": "Consent classification triage pipeline",
            "version": "1.0.0",
        },
    )

    # Layer 0: Extract excerpt from raw input
    dag.add_node(DAGNode(
        node_id="extract",
        skill_name="consent_classifier",
        sub_task="extract_excerpt",
        layer=0,
        input_keys=["raw_text"],
        output_keys=["excerpt"],
    ))

    # Layer 1: Classify consent dynamics
    dag.add_node(DAGNode(
        node_id="classify",
        skill_name="consent_classifier",
        sub_task="classify_consent",
        layer=1,
        input_keys=["excerpt"],
        output_keys=["verdict", "note", "flags", "confidence"],
    ))

    # Layer 2: Pool safe items (terminal for SAFE path)
    dag.add_node(DAGNode(
        node_id="pool",
        skill_name="consent_classifier",
        sub_task="pool_safe",
        layer=2,
        input_keys=["verdict", "excerpt"],
        output_keys=["pool_result"],
    ))

    # Layer 2: Re-triage flagged items with deeper analysis
    dag.add_node(DAGNode(
        node_id="retriage",
        skill_name="consent_classifier",
        sub_task="deep_classify",
        layer=2,
        input_keys=["verdict", "excerpt", "flags"],
        output_keys=["retriage_verdict", "retriage_note"],
    ))

    # Layer 3: Final verdict for retriage path
    dag.add_node(DAGNode(
        node_id="final_verdict",
        skill_name="consent_classifier",
        sub_task="render_verdict",
        layer=3,
        input_keys=["retriage_verdict", "retriage_note", "excerpt"],
        output_keys=["final_verdict", "final_note", "disposition"],
    ))

    # Edges
    dag.add_edge("extract", "classify")
    dag.add_edge("classify", "pool")
    dag.add_edge("classify", "retriage")
    dag.add_edge("retriage", "final_verdict")

    return dag


def build_response_dag() -> SkillDAG:
    """Build the Muse response generation pipeline DAG.

    Pipeline:
        Layer 0: memory_recall + emotional_calibration (PARALLEL)
        Layer 1: persona_consistency (validates context + calibration together)
        Layer 2: response_generation (placeholder — actual generation is external)
        Layer 3: boundary_enforcer (final safety gate before output)

    Flow:
        memory_recall ─────┐
                           ├→ persona_consistency → response_gen → boundary_enforcer → output
        emotional_calibration ┘

    The parallel layer 0 gathers context (memories + emotional calibration)
    simultaneously. Layer 1 validates that the gathered context is consistent
    with the persona. Layer 2 generates the response. Layer 3 enforces hard
    safety boundaries as the final gate.

    Returns:
        SkillDAG configured for Muse response pipeline
    """
    dag = SkillDAG(
        strategy="quality",
        metadata={
            "name": "muse_response",
            "description": "Intimate AI response generation pipeline",
            "version": "1.0.0",
        },
    )

    # Layer 0: Parallel context gathering
    dag.add_node(DAGNode(
        node_id="memory_recall",
        skill_name="memory_recall",
        sub_task="recall",
        layer=0,
        input_keys=["conversation_context"],
        output_keys=["memories"],
    ))

    dag.add_node(DAGNode(
        node_id="emotional_calibration",
        skill_name="emotional_calibration",
        sub_task="calibrate",
        layer=0,
        input_keys=["conversation_history", "persona_baseline", "user_state_signals"],
        output_keys=["calibration", "reasoning"],
    ))

    # Layer 1: Persona consistency check on gathered context
    dag.add_node(DAGNode(
        node_id="persona_check",
        skill_name="persona_consistency",
        sub_task="check_consistency",
        layer=1,
        input_keys=["memories", "calibration", "persona_definition"],
        output_keys=["persona_passed", "persona_violations"],
    ))

    # Layer 2: Response generation (interface node — actual gen is external)
    dag.add_node(DAGNode(
        node_id="response_gen",
        skill_name="persona_consistency",  # Reuses persona chip for validation
        sub_task="generate_response",
        layer=2,
        input_keys=[
            "memories", "calibration", "persona_definition",
            "conversation_context", "persona_passed",
        ],
        output_keys=["draft_response"],
    ))

    # Layer 3: Boundary enforcement — final safety gate
    dag.add_node(DAGNode(
        node_id="boundary_check",
        skill_name="boundary_enforcer",
        sub_task="enforce",
        layer=3,
        input_keys=["draft_response", "conversation_context"],
        output_keys=["passed", "violations", "severity", "safe_alternative"],
    ))

    # Edges: layer 0 → layer 1
    dag.add_edge("memory_recall", "persona_check")
    dag.add_edge("emotional_calibration", "persona_check")

    # Layer 1 → layer 2
    dag.add_edge("persona_check", "response_gen")

    # Layer 2 → layer 3
    dag.add_edge("response_gen", "boundary_check")

    return dag
