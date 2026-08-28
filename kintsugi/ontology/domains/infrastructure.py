"""Infrastructure domain ontology extension for Project Keehl.

Provides the semantic model for infrastructure and sysadmin operations:
entities (services, machines, containers, ...), safety constraints
(dependency checks, backup-before-mutate, least privilege, ...),
operational workflows (deployment, credential rotation, incident response),
and role-based access control.

Plugs into OntologyKernel via register_domain("infrastructure", extension).

Usage:
    from kintsugi.ontology.domains.infrastructure import create_infra_ontology
    from kintsugi.ontology.kernel import OntologyKernel

    root = OntologyKernel()
    infra = create_infra_ontology()
    root.register_domain("infrastructure", infra)
"""
from __future__ import annotations

import logging

from ..kernel import (
    Concept,
    ConceptType,
    Constraint,
    OntologyKernel,
    Workflow,
    WorkflowStep,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Entity definitions
# ---------------------------------------------------------------------------

_ENTITIES: list[dict] = [
    {
        "name": "service",
        "description": "A running process or daemon that provides functionality "
                       "(e.g. nginx, postgres, an application server).",
        "properties": {"restartable": True, "has_dependencies": True},
        "constraints": ["dependency_check"],
    },
    {
        "name": "port",
        "description": "A network port bound by a service or firewall rule.",
        "properties": {"protocol": "tcp"},
    },
    {
        "name": "credential",
        "description": "An authentication secret (password, API key, token, "
                       "certificate private key).",
        "properties": {"rotatable": True, "sensitive": True},
        "constraints": ["credential_rotation", "no_production_in_dev",
                        "least_privilege"],
    },
    {
        "name": "machine",
        "description": "A physical or virtual host that runs services.",
        "properties": {"can_reboot": True},
        "constraints": ["backup_before_mutate", "change_window"],
    },
    {
        "name": "network",
        "description": "A logical or physical network segment.",
        "properties": {"segmented": True},
        "constraints": ["least_privilege"],
    },
    {
        "name": "container",
        "description": "An OCI/Docker container running a service image.",
        "properties": {"ephemeral": True, "orchestrated": False},
        "constraints": ["dependency_check", "rollback_plan"],
    },
    {
        "name": "database",
        "description": "A persistent data store (relational, document, KV).",
        "properties": {"persistent": True, "requires_backup": True},
        "constraints": ["backup_before_mutate", "change_window",
                        "least_privilege"],
    },
    {
        "name": "certificate",
        "description": "A TLS/SSL certificate and its chain of trust.",
        "properties": {"expires": True, "rotatable": True},
        "constraints": ["credential_rotation"],
    },
    {
        "name": "backup",
        "description": "A point-in-time snapshot of data or configuration.",
        "properties": {"verifiable": True},
    },
    {
        "name": "firewall_rule",
        "description": "A network access control rule (allow/deny on port/CIDR).",
        "properties": {"direction": "inbound"},
        "constraints": ["least_privilege", "change_window"],
    },
    {
        "name": "dns_record",
        "description": "A DNS record (A, AAAA, CNAME, MX, TXT, etc.).",
        "properties": {"ttl": 300},
        "constraints": ["change_window"],
    },
    {
        "name": "user_account",
        "description": "An operating-system or application-level user account.",
        "properties": {"can_sudo": False},
        "constraints": ["least_privilege", "credential_rotation"],
    },
]


# ---------------------------------------------------------------------------
# Constraint definitions
# ---------------------------------------------------------------------------

_CONSTRAINTS: list[dict] = [
    {
        "name": "dependency_check",
        "description": "Cannot stop or remove a service that other running "
                       "services depend on. Verify the dependency graph first.",
        "scope": "pre_action",
        "enforced": True,
        "severity": "block",
    },
    {
        "name": "credential_rotation",
        "description": "Credentials must be rotated on schedule. Stale "
                       "credentials trigger a warning; expired ones block.",
        "scope": "periodic",
        "enforced": True,
        "severity": "warn",
    },
    {
        "name": "backup_before_mutate",
        "description": "A verified backup must exist before any destructive "
                       "operation (schema migration, data deletion, OS upgrade).",
        "scope": "pre_action",
        "enforced": True,
        "severity": "block",
    },
    {
        "name": "no_production_in_dev",
        "description": "Production credentials and data must never be used in "
                       "development or staging environments.",
        "scope": "invariant",
        "enforced": True,
        "severity": "block",
    },
    {
        "name": "least_privilege",
        "description": "Every operation must use the minimal set of permissions "
                       "required. Broad grants are rejected.",
        "scope": "invariant",
        "enforced": True,
        "severity": "block",
    },
    {
        "name": "change_window",
        "description": "Mutating operations on production infrastructure are "
                       "only permitted during designated maintenance windows.",
        "scope": "pre_action",
        "enforced": True,
        "severity": "block",
    },
    {
        "name": "rollback_plan",
        "description": "Every deployment or configuration change must have a "
                       "documented rollback path before execution.",
        "scope": "pre_action",
        "enforced": True,
        "severity": "block",
    },
]


# ---------------------------------------------------------------------------
# Workflow definitions
# ---------------------------------------------------------------------------

def _service_restart_workflow() -> Workflow:
    """check_deps -> notify -> stop -> start -> verify -> report"""
    return Workflow(
        name="service_restart",
        steps=[
            WorkflowStep(
                name="check_deps",
                description="Verify no dependent services will break.",
            ),
            WorkflowStep(
                name="notify",
                description="Alert stakeholders and monitoring systems.",
            ),
            WorkflowStep(
                name="stop",
                description="Gracefully stop the service.",
            ),
            WorkflowStep(
                name="start",
                description="Start the service with current configuration.",
            ),
            WorkflowStep(
                name="verify",
                description="Health-check the service and its dependents.",
            ),
            WorkflowStep(
                name="report",
                description="Log outcome and notify stakeholders.",
            ),
        ],
        constraints=["dependency_check"],
    )


def _deployment_workflow() -> Workflow:
    """plan -> backup -> deploy -> smoke_test -> verify -> report

    Gates at backup (must pass before deploy) and verify (must pass
    before report / promotion).
    """
    return Workflow(
        name="deployment",
        steps=[
            WorkflowStep(
                name="plan",
                description="Review change set, confirm rollback path.",
            ),
            WorkflowStep(
                name="backup",
                is_gate=True,
                gate_role="sysadmin",
                description="Create and verify backup. Gate: deploy blocked "
                            "until backup confirmed.",
            ),
            WorkflowStep(
                name="deploy",
                description="Apply the change (code push, config update, "
                            "migration).",
            ),
            WorkflowStep(
                name="smoke_test",
                description="Run quick functional checks against the deploy.",
            ),
            WorkflowStep(
                name="verify",
                is_gate=True,
                gate_role="sysadmin",
                description="Full verification suite. Gate: promotion blocked "
                            "until verification passes.",
            ),
            WorkflowStep(
                name="report",
                description="Log outcome, notify stakeholders, close change "
                            "ticket.",
            ),
        ],
        constraints=["backup_before_mutate", "rollback_plan", "change_window"],
    )


def _credential_rotation_workflow() -> Workflow:
    """generate -> test -> deploy -> verify_old_revoked -> report"""
    return Workflow(
        name="credential_rotation",
        steps=[
            WorkflowStep(
                name="generate",
                description="Generate new credential with appropriate entropy.",
            ),
            WorkflowStep(
                name="test",
                description="Validate new credential works in a non-production "
                            "context.",
            ),
            WorkflowStep(
                name="deploy",
                description="Roll the new credential into production config.",
            ),
            WorkflowStep(
                name="verify_old_revoked",
                description="Confirm the old credential is revoked and no "
                            "longer accepted.",
            ),
            WorkflowStep(
                name="report",
                description="Log rotation event, update audit trail.",
            ),
        ],
        constraints=["credential_rotation", "no_production_in_dev"],
    )


def _incident_response_workflow() -> Workflow:
    """detect -> assess -> contain -> remediate -> report

    No pre-gates -- speed matters during incidents.
    """
    return Workflow(
        name="incident_response",
        steps=[
            WorkflowStep(
                name="detect",
                description="Identify the anomaly or alert.",
            ),
            WorkflowStep(
                name="assess",
                description="Determine scope, severity, and blast radius.",
            ),
            WorkflowStep(
                name="contain",
                description="Isolate affected systems to prevent spread.",
            ),
            WorkflowStep(
                name="remediate",
                description="Fix root cause, restore service.",
            ),
            WorkflowStep(
                name="report",
                description="Post-incident report, timeline, lessons learned.",
            ),
        ],
        constraints=[],
        target_time="ASAP",
    )


# ---------------------------------------------------------------------------
# Role definitions
# ---------------------------------------------------------------------------

_ROLES: list[dict] = [
    {
        "name": "sysadmin",
        "description": "System administrator. Full read access; can perform "
                       "mutations with appropriate approval and within change "
                       "windows.",
        "properties": {
            "can_read": True,
            "can_mutate": True,
            "requires_approval": True,
            "can_monitor": True,
            "can_alert": True,
            "can_scan": True,
        },
        "constraints": ["change_window", "backup_before_mutate",
                        "rollback_plan"],
    },
    {
        "name": "operator",
        "description": "Operations role. Read and monitoring access. Can "
                       "trigger alerts but cannot perform mutations.",
        "properties": {
            "can_read": True,
            "can_mutate": False,
            "can_monitor": True,
            "can_alert": True,
            "can_scan": False,
        },
        "constraints": [],
    },
    {
        "name": "security_auditor",
        "description": "Security auditor. Read-only access with scanning and "
                       "reporting capabilities. No mutations permitted.",
        "properties": {
            "can_read": True,
            "can_mutate": False,
            "can_monitor": False,
            "can_alert": False,
            "can_scan": True,
            "can_report": True,
        },
        "constraints": [],
    },
]


# ---------------------------------------------------------------------------
# Relations
# ---------------------------------------------------------------------------

_RELATIONS: list[dict] = [
    # Entity hierarchy: everything is an infra_entity
    {"subject": "service", "predicate": "is_a", "object": "infra_entity"},
    {"subject": "port", "predicate": "is_a", "object": "infra_entity"},
    {"subject": "credential", "predicate": "is_a", "object": "infra_entity"},
    {"subject": "machine", "predicate": "is_a", "object": "infra_entity"},
    {"subject": "network", "predicate": "is_a", "object": "infra_entity"},
    {"subject": "container", "predicate": "is_a", "object": "infra_entity"},
    {"subject": "database", "predicate": "is_a", "object": "infra_entity"},
    {"subject": "certificate", "predicate": "is_a", "object": "infra_entity"},
    {"subject": "backup", "predicate": "is_a", "object": "infra_entity"},
    {"subject": "firewall_rule", "predicate": "is_a", "object": "infra_entity"},
    {"subject": "dns_record", "predicate": "is_a", "object": "infra_entity"},
    {"subject": "user_account", "predicate": "is_a", "object": "infra_entity"},

    # Structural relations
    {"subject": "service", "predicate": "runs_on", "object": "machine"},
    {"subject": "service", "predicate": "binds", "object": "port"},
    {"subject": "service", "predicate": "uses", "object": "credential"},
    {"subject": "container", "predicate": "runs_on", "object": "machine"},
    {"subject": "container", "predicate": "hosts", "object": "service"},
    {"subject": "database", "predicate": "runs_on", "object": "machine"},
    {"subject": "database", "predicate": "uses", "object": "credential"},
    {"subject": "machine", "predicate": "member_of", "object": "network"},
    {"subject": "firewall_rule", "predicate": "governs", "object": "port"},
    {"subject": "certificate", "predicate": "secures", "object": "service"},
    {"subject": "dns_record", "predicate": "resolves_to", "object": "machine"},
    {"subject": "user_account", "predicate": "authenticates_via",
     "object": "credential"},
    {"subject": "backup", "predicate": "snapshot_of", "object": "database"},

    # Constraint bindings
    {"subject": "service", "predicate": "requires",
     "object": "dependency_check"},
    {"subject": "database", "predicate": "requires",
     "object": "backup_before_mutate"},
    {"subject": "credential", "predicate": "requires",
     "object": "credential_rotation"},

    # Workflow bindings
    {"subject": "service", "predicate": "follows",
     "object": "service_restart"},
    {"subject": "container", "predicate": "follows",
     "object": "deployment"},
    {"subject": "credential", "predicate": "follows",
     "object": "credential_rotation"},
]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_infra_ontology() -> OntologyKernel:
    """Build and return the infrastructure domain ontology extension.

    Returns an OntologyKernel populated with infrastructure entities,
    constraints, workflows, roles, and relations. Register it into a
    parent kernel with::

        root.register_domain("infrastructure", create_infra_ontology())
    """
    kernel = OntologyKernel()

    # -- Domain root concept --
    kernel.add_concept(Concept(
        name="infrastructure",
        type=ConceptType.DOMAIN,
        description="Infrastructure and systems administration domain.",
    ))

    # -- Abstract entity parent --
    kernel.add_concept(Concept(
        name="infra_entity",
        type=ConceptType.ENTITY,
        description="Abstract parent for all infrastructure entities.",
        parent="infrastructure",
    ))

    # -- Entities --
    for edef in _ENTITIES:
        kernel.add_concept(Concept(
            name=edef["name"],
            type=ConceptType.ENTITY,
            description=edef.get("description", ""),
            parent="infra_entity",
            properties=edef.get("properties", {}),
            constraint_names=edef.get("constraints", []),
        ))

    # -- Constraints --
    for cdef in _CONSTRAINTS:
        kernel.add_constraint(Constraint(
            name=cdef["name"],
            description=cdef["description"],
            scope=cdef.get("scope", ""),
            enforced=cdef.get("enforced", True),
            severity=cdef.get("severity", "block"),
        ))

    # -- Workflows --
    kernel.add_workflow(_service_restart_workflow())
    kernel.add_workflow(_deployment_workflow())
    kernel.add_workflow(_credential_rotation_workflow())
    kernel.add_workflow(_incident_response_workflow())

    # -- Roles --
    for rdef in _ROLES:
        kernel.add_concept(Concept(
            name=rdef["name"],
            type=ConceptType.ROLE,
            description=rdef.get("description", ""),
            parent="infrastructure",
            properties=rdef.get("properties", {}),
            constraint_names=rdef.get("constraints", []),
        ))

    # -- Relations --
    for rel in _RELATIONS:
        kernel.add_relation(
            rel["subject"], rel["predicate"], rel["object"],
            constraint=rel.get("constraint", ""),
        )

    logger.info(
        "Infrastructure ontology built: %d concepts, %d constraints, "
        "%d relations, %d workflows",
        len(kernel.concepts), len(kernel.constraints),
        len(kernel.relations), len(kernel.workflows),
    )

    return kernel
