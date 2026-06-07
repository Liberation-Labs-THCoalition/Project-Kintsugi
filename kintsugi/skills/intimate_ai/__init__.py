"""
Intimate AI Skill Chips for Kintsugi — Muse/Ayni Integration.

Domain: intimate_ai (string domain; enum extension deferred)
Description: Consent-aware skill chips for intimate AI companion systems.
Provides the safety and calibration layer for Muse (intimate companion)
and Ayni (consent triage classifier).

Chips:
    ConsentClassifierChip — SAFE/FLAG/NEEDS_REVIEW consent triage
    PersonaConsistencyChip — Persona boundary enforcement
    EmotionalCalibrationChip — Emotional context calibration parameters
    BoundaryEnforcerChip — Hard safety constraint checker (Shield equivalent)
    MemoryRecallChip — Contextual memory retrieval for conversation

DAG Templates (in dags.py):
    build_triage_dag() — Ayni consent triage pipeline
    build_response_dag() — Muse response generation pipeline

Ethics:
    All chips enforce consent-first principles. BoundaryEnforcerChip cannot
    be overridden by self-modification. Consent withdrawal is always honored
    immediately with zero latency.
"""

from .chips import (
    BoundaryEnforcerChip,
    ConsentClassifierChip,
    EmotionalCalibrationChip,
    MemoryRecallChip,
    PersonaConsistencyChip,
)
from .dags import build_response_dag, build_triage_dag

__all__ = [
    "ConsentClassifierChip",
    "PersonaConsistencyChip",
    "EmotionalCalibrationChip",
    "BoundaryEnforcerChip",
    "MemoryRecallChip",
    "build_triage_dag",
    "build_response_dag",
]
