"""Ontology kernel — queryable concept hierarchy with constraint inheritance.

Provides the semantic foundation that all Kintsugi modules query against.
Lightweight Python implementation — no OWL tooling required, upgrade path
exists via JSON-LD export.

Three sub-ontologies (FAOS-inspired):
  R (Role): WHO can do WHAT — maps to PersonaGate + Shield
  D (Domain): WHAT concepts exist — maps to SkillDomain + CapabilityTree
  I (Interaction): HOW actions flow — maps to DAGExecutor + shadow fork

Architecture: sits between CapabilityTree and EFE. Tree finds candidates,
kernel checks if they're admissible in context.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)


class ConceptType(str, Enum):
    ENTITY = "entity"
    ROLE = "role"
    ACTION = "action"
    CONSTRAINT = "constraint"
    WORKFLOW = "workflow"
    DOMAIN = "domain"


@dataclass
class Concept:
    """A node in the ontology graph."""
    name: str
    type: ConceptType
    description: str = ""
    parent: str = ""
    properties: dict[str, Any] = field(default_factory=dict)
    constraint_names: list[str] = field(default_factory=list)


@dataclass
class Constraint:
    """A formal restriction on actions or assertions."""
    name: str
    description: str
    scope: str = ""
    enforced: bool = True
    severity: str = "block"


@dataclass
class Relation:
    """A typed edge between concepts."""
    subject: str
    predicate: str
    object: str
    constraint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Triple:
    """A BDI-compatible typed belief triple."""
    subject: str
    predicate: str
    object: str
    ontology_type: str = ""
    confidence: float = 1.0
    source: str = ""
    timestamp: str = ""


@dataclass
class WorkflowStep:
    """A single step in a workflow."""
    name: str
    is_gate: bool = False
    gate_role: str = ""
    description: str = ""


@dataclass
class Workflow:
    """A sequence of steps governing an action type."""
    name: str
    steps: list[WorkflowStep] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    target_time: str = ""

    @property
    def gates(self) -> list[WorkflowStep]:
        return [s for s in self.steps if s.is_gate]


class OntologyKernel:
    """Queryable concept hierarchy with constraint inheritance.

    The kernel that all modules check against. Additive, not invasive —
    every existing module continues to work without it. The kernel adds
    validation; it never removes capability.
    """

    def __init__(self):
        self.concepts: dict[str, Concept] = {}
        self.constraints: dict[str, Constraint] = {}
        self.relations: list[Relation] = []
        self.workflows: dict[str, Workflow] = {}
        self._domain_extensions: dict[str, "OntologyKernel"] = {}

    # === REGISTRATION ===

    def add_concept(self, concept: Concept) -> None:
        self.concepts[concept.name] = concept

    def add_constraint(self, constraint: Constraint) -> None:
        self.constraints[constraint.name] = constraint

    def add_relation(self, subject: str, predicate: str, obj: str,
                     constraint: str = "", **metadata) -> None:
        self.relations.append(Relation(
            subject, predicate, obj, constraint, metadata))

    def add_workflow(self, workflow: Workflow) -> None:
        self.workflows[workflow.name] = workflow

    def register_domain(self, name: str, extension: "OntologyKernel") -> None:
        """Register a domain-specific ontology extension.

        Extensions are queried alongside the core kernel. This is how
        projects (Cabildo, Oracle Loop, Ayni) plug their concepts in.
        """
        self._domain_extensions[name] = extension
        for cname, concept in extension.concepts.items():
            if cname not in self.concepts:
                self.concepts[cname] = concept
        for cname, constraint in extension.constraints.items():
            if cname not in self.constraints:
                self.constraints[cname] = constraint
        self.relations.extend(extension.relations)
        for wname, workflow in extension.workflows.items():
            if wname not in self.workflows:
                self.workflows[wname] = workflow
        logger.info("Registered domain extension '%s': %d concepts, "
                    "%d constraints", name, len(extension.concepts),
                    len(extension.constraints))

    # === QUERIES ===

    def get(self, name: str) -> Optional[Concept]:
        return self.concepts.get(name)

    def children_of(self, parent: str) -> list[Concept]:
        return [c for c in self.concepts.values() if c.parent == parent]

    def ancestors_of(self, name: str) -> list[str]:
        """Walk up the parent chain."""
        ancestors = []
        current = self.concepts.get(name)
        while current and current.parent:
            ancestors.append(current.parent)
            current = self.concepts.get(current.parent)
        return ancestors

    def constraints_for(self, concept_name: str) -> list[Constraint]:
        """Get all constraints for a concept, including inherited."""
        constraint_names: set[str] = set()

        concept = self.concepts.get(concept_name)
        if not concept:
            return []

        constraint_names.update(concept.constraint_names)

        for ancestor in self.ancestors_of(concept_name):
            anc = self.concepts.get(ancestor)
            if anc:
                constraint_names.update(anc.constraint_names)

        for rel in self.relations:
            if rel.subject == concept_name and rel.predicate == "requires":
                constraint_names.add(rel.object)
            if rel.constraint:
                constraint_names.add(rel.constraint)

        return [self.constraints[n] for n in constraint_names
                if n in self.constraints]

    def relations_for(self, subject: str,
                      predicate: str = "") -> list[Relation]:
        rels = [r for r in self.relations if r.subject == subject]
        if predicate:
            rels = [r for r in rels if r.predicate == predicate]
        return rels

    def workflow_for(self, concept_name: str) -> Optional[Workflow]:
        """Find the workflow governing a concept (checks parents too)."""
        for rel in self.relations:
            if rel.subject == concept_name and rel.predicate == "follows":
                return self.workflows.get(rel.object)
        concept = self.concepts.get(concept_name)
        if concept and concept.parent:
            return self.workflow_for(concept.parent)
        return None

    # === VALIDATION ===

    def validate_action(self, action: str, actor_role: str = "",
                        context: dict[str, Any] | None = None) -> tuple[bool, list[str]]:
        """Check if an action is ontologically admissible.

        Returns (admissible, violations).
        """
        violations = []

        actor = self.concepts.get(actor_role)
        if actor:
            for cname in actor.constraint_names:
                violation = self._check_action_constraint(action, cname)
                if violation:
                    violations.append(violation)

        for constraint in self.constraints_for(action):
            violation = self._check_action_constraint(action, constraint.name)
            if violation:
                violations.append(violation)

        workflow = self.workflow_for(action)
        if workflow:
            for gate in workflow.gates:
                if gate.gate_role and actor_role != gate.gate_role:
                    violations.append(
                        f"Workflow '{workflow.name}' requires "
                        f"'{gate.gate_role}' at gate '{gate.name}', "
                        f"current role is '{actor_role}'")

        return len(violations) == 0, violations

    def _check_action_constraint(self, action: str,
                                  constraint_name: str) -> str:
        """Check one constraint against an action. Returns violation or ''."""
        constraint = self.constraints.get(constraint_name)
        if not constraint or not constraint.enforced:
            return ""

        if constraint.scope == "pre_action":
            return f"{action} blocked by pre-action constraint: {constraint.description}"

        return ""

    def filter_admissible(self, candidates: Sequence[str],
                          actor_role: str = "",
                          context: dict[str, Any] | None = None) -> list[str]:
        """Filter a list of skill/action candidates to only admissible ones."""
        admissible = []
        for candidate in candidates:
            ok, violations = self.validate_action(candidate, actor_role, context)
            if ok:
                admissible.append(candidate)
            else:
                logger.debug("Filtered %s: %s", candidate, violations)
        return admissible

    # === TYPED BELIEFS ===

    def type_belief(self, subject: str, predicate: str,
                    obj: str) -> Triple:
        """Create a typed belief triple from the ontology."""
        ont_type = ""
        concept = self.concepts.get(subject)
        if concept:
            ont_type = f"{concept.parent}.{concept.name}" if concept.parent else concept.name
        return Triple(subject, predicate, obj, ontology_type=ont_type)

    # === SERIALIZATION ===

    def to_dict(self) -> dict:
        return {
            "concepts": {
                name: {
                    "type": c.type.value,
                    "description": c.description,
                    "parent": c.parent,
                    "properties": c.properties,
                    "constraints": c.constraint_names,
                }
                for name, c in self.concepts.items()
            },
            "constraints": {
                name: {
                    "description": c.description,
                    "scope": c.scope,
                    "enforced": c.enforced,
                    "severity": c.severity,
                }
                for name, c in self.constraints.items()
            },
            "relations": [
                {"subject": r.subject, "predicate": r.predicate,
                 "object": r.object, "constraint": r.constraint}
                for r in self.relations
            ],
            "workflows": {
                name: {
                    "steps": [{"name": s.name, "is_gate": s.is_gate,
                               "gate_role": s.gate_role} for s in w.steps],
                    "constraints": w.constraints,
                }
                for name, w in self.workflows.items()
            },
            "domain_extensions": list(self._domain_extensions.keys()),
        }

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def from_dict(cls, data: dict) -> "OntologyKernel":
        kernel = cls()
        for name, cdata in data.get("concepts", {}).items():
            kernel.add_concept(Concept(
                name=name,
                type=ConceptType(cdata["type"]),
                description=cdata.get("description", ""),
                parent=cdata.get("parent", ""),
                properties=cdata.get("properties", {}),
                constraint_names=cdata.get("constraints", []),
            ))
        for name, cdata in data.get("constraints", {}).items():
            kernel.add_constraint(Constraint(
                name=name,
                description=cdata.get("description", ""),
                scope=cdata.get("scope", ""),
                enforced=cdata.get("enforced", True),
                severity=cdata.get("severity", "block"),
            ))
        for rdata in data.get("relations", []):
            kernel.add_relation(
                rdata["subject"], rdata["predicate"], rdata["object"],
                rdata.get("constraint", ""))
        for name, wdata in data.get("workflows", {}).items():
            kernel.add_workflow(Workflow(
                name=name,
                steps=[WorkflowStep(**s) for s in wdata.get("steps", [])],
                constraints=wdata.get("constraints", []),
            ))
        return kernel

    @classmethod
    def load(cls, path: str | Path) -> "OntologyKernel":
        return cls.from_dict(json.loads(Path(path).read_text()))

    def summary(self) -> str:
        types = {}
        for c in self.concepts.values():
            types[c.type.value] = types.get(c.type.value, 0) + 1
        type_str = ", ".join(f"{k}: {v}" for k, v in sorted(types.items()))
        ext_str = ", ".join(self._domain_extensions.keys()) or "none"
        return (f"OntologyKernel: {len(self.concepts)} concepts ({type_str}), "
                f"{len(self.constraints)} constraints, "
                f"{len(self.relations)} relations, "
                f"{len(self.workflows)} workflows, "
                f"extensions: [{ext_str}]")
