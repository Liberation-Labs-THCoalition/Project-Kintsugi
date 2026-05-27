"""Evolutionary Pipeline for Kintsugi CMA -- Phase 3 Stream 3B.

Manages the lifecycle of modification proposals: queuing, activation,
evaluation, and generational tracking. Enforces sequential evaluation
(max 1 active at a time) per the Kintsugi specification.

v2.0 (May 2026): Added SkillOpt-inspired edit budget, held-out validation
gate, and rejected-edit buffer. Reference: arXiv:2605.23904.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class ModificationScope(Enum):
    PROMPT = "PROMPT"
    TOOL_CONFIG = "TOOL_CONFIG"
    SKILL_CHIP = "SKILL_CHIP"
    ARCHITECTURE = "ARCHITECTURE"


@dataclass
class ModificationProposal:
    proposal_id: str
    scope: ModificationScope
    description: str
    modification: dict
    estimated_eval_turns: int = 10
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "queued"
    parent_trace_id: Optional[str] = None
    result_verdict: Optional[str] = None
    result_swei: Optional[float] = None
    mutation_cost: float = 0.0


@dataclass
class RejectedEdit:
    """A modification that was rejected overall but contained useful signal."""
    proposal_id: str
    scope: ModificationScope
    description: str
    modification: dict
    partial_scores: Dict[str, float] = field(default_factory=dict)
    rejected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class EvolutionConfig:
    max_queue_size: int = 20
    max_active_evaluations: int = 1
    min_eval_turns: int = 5
    max_eval_turns: int = 50
    allowed_scopes: List[ModificationScope] = field(
        default_factory=lambda: [ModificationScope.PROMPT, ModificationScope.TOOL_CONFIG]
    )
    mutation_budget: float = 1.0
    rejected_buffer_size: int = 20
    holdout_fraction: float = 0.2


class EvolutionManager:
    """Manages the evolutionary proposal pipeline with sequential evaluation.

    v2 additions (SkillOpt pattern):
    - Edit budget: bounds how much a single proposal can mutate
    - Rejected-edit buffer: preserves useful signal from rejected proposals
    - Held-out workload tracking: reserves fraction for validation gate
    """

    def __init__(self, config: Optional[EvolutionConfig] = None) -> None:
        self.config = config or EvolutionConfig()
        self._proposals: Dict[str, ModificationProposal] = {}
        self._generation: int = 0
        self._total_evaluated: int = 0
        self._total_approved: int = 0
        self._total_rejected: int = 0
        self._rejected_buffer: List[RejectedEdit] = []
        self._holdout_workload: List[Dict[str, Any]] = []

    def _validate_scope(self, scope: ModificationScope) -> None:
        if scope not in self.config.allowed_scopes:
            raise ValueError(
                f"Scope {scope.value} not in allowed scopes: "
                f"{[s.value for s in self.config.allowed_scopes]}"
            )

    @staticmethod
    def compute_mutation_cost(modification: dict) -> float:
        """Measure the magnitude of a proposed modification.

        Counts leaf-level changes: each key-value pair at any depth costs 1.
        Nested dicts recurse. This is the "textual learning rate" — proposals
        that change too much get rejected before evaluation.
        """
        cost = 0.0
        for value in modification.values():
            if isinstance(value, dict):
                cost += EvolutionManager.compute_mutation_cost(value)
            else:
                cost += 1.0
        return cost

    def submit_proposal(
        self,
        scope: ModificationScope,
        description: str,
        modification: dict,
        parent_trace_id: Optional[str] = None,
    ) -> ModificationProposal:
        self._validate_scope(scope)
        queued = [p for p in self._proposals.values() if p.status == "queued"]
        if len(queued) >= self.config.max_queue_size:
            raise ValueError(
                f"Queue full ({self.config.max_queue_size}). "
                "Discard or evaluate existing proposals first."
            )
        cost = self.compute_mutation_cost(modification)
        if cost > self.config.mutation_budget:
            raise ValueError(
                f"Mutation cost {cost:.1f} exceeds budget {self.config.mutation_budget:.1f}. "
                "Split into smaller proposals or increase budget."
            )
        proposal = ModificationProposal(
            proposal_id=uuid.uuid4().hex[:12],
            scope=scope,
            description=description,
            modification=modification,
            parent_trace_id=parent_trace_id,
            mutation_cost=cost,
        )
        self._proposals[proposal.proposal_id] = proposal
        return proposal

    def get_queue(self) -> List[ModificationProposal]:
        queued = [p for p in self._proposals.values() if p.status == "queued"]
        return sorted(queued, key=lambda p: p.created_at)

    def get_active(self) -> Optional[ModificationProposal]:
        for p in self._proposals.values():
            if p.status == "active":
                return p
        return None

    def activate_next(self) -> Optional[ModificationProposal]:
        if self.get_active() is not None:
            return None
        queue = self.get_queue()
        if not queue:
            return None
        proposal = queue[0]
        proposal.status = "active"
        return proposal

    def complete_evaluation(
        self,
        proposal_id: str,
        verdict_str: str,
        swei: float,
        partial_scores: Optional[Dict[str, float]] = None,
    ) -> ModificationProposal:
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise KeyError(f"Proposal {proposal_id} not found")
        if proposal.status != "active":
            raise ValueError(
                f"Proposal {proposal_id} is '{proposal.status}', expected 'active'"
            )
        proposal.status = "evaluated"
        proposal.result_verdict = verdict_str
        proposal.result_swei = swei
        self._total_evaluated += 1
        verdict_upper = verdict_str.upper()
        if verdict_upper == "APPROVE":
            self._total_approved += 1
            self._generation += 1
        elif verdict_upper in ("REJECT", "ESCALATE"):
            self._total_rejected += 1
            self._buffer_rejected(proposal, partial_scores)
        return proposal

    def _buffer_rejected(
        self,
        proposal: ModificationProposal,
        partial_scores: Optional[Dict[str, float]] = None,
    ) -> None:
        """Preserve useful signal from rejected proposals."""
        entry = RejectedEdit(
            proposal_id=proposal.proposal_id,
            scope=proposal.scope,
            description=proposal.description,
            modification=copy.deepcopy(proposal.modification),
            partial_scores=partial_scores or {},
        )
        self._rejected_buffer.append(entry)
        max_size = self.config.rejected_buffer_size
        if len(self._rejected_buffer) > max_size:
            self._rejected_buffer = self._rejected_buffer[-max_size:]

    def get_rejected_buffer(self) -> List[RejectedEdit]:
        return list(self._rejected_buffer)

    def pop_rejected_by_scope(self, scope: ModificationScope) -> List[RejectedEdit]:
        """Retrieve and remove rejected edits for a given scope.

        Useful for building new proposals that incorporate useful rules
        from previously rejected attempts.
        """
        matching = [e for e in self._rejected_buffer if e.scope == scope]
        self._rejected_buffer = [e for e in self._rejected_buffer if e.scope != scope]
        return matching

    def set_holdout_workload(self, workload: List[Dict[str, Any]]) -> None:
        """Register workload items reserved for post-evaluation validation.

        The holdout fraction from config determines how many items from the
        full workload should be reserved. The caller is responsible for
        splitting; this stores the reserved portion.
        """
        self._holdout_workload = list(workload)

    def get_holdout_workload(self) -> List[Dict[str, Any]]:
        return list(self._holdout_workload)

    def discard_proposal(self, proposal_id: str) -> ModificationProposal:
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise KeyError(f"Proposal {proposal_id} not found")
        proposal.status = "discarded"
        return proposal

    def get_generation_info(self) -> dict:
        return {
            "generation": self._generation,
            "total_evaluated": self._total_evaluated,
            "total_approved": self._total_approved,
            "total_rejected": self._total_rejected,
            "queue_depth": len(self.get_queue()),
            "rejected_buffer_size": len(self._rejected_buffer),
            "holdout_workload_size": len(self._holdout_workload),
        }
