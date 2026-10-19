"""
Base skill chip abstractions for Kintsugi CMA.

This module provides the foundational classes and types for all 22 skill chips
in the Kintsugi CMA system. Skill chips are modular, domain-specific handlers
that process user intents and execute actions within ethical guardrails.

Key concepts:
- SkillDomain: The functional area a chip operates in (fundraising, operations, etc.)
- EFEWeights: Ethical Framing Engine weights for domain-specific prioritization
- SkillContext: Runtime context including organization, user, and BDI state
- BaseSkillChip: Abstract base class all skill chips inherit from
"""

import contextlib
import contextvars
import functools
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Optional


class SkillDomain(str, Enum):
    """Domains that skill chips operate in.

    Deployments extend this with their own domains via register_domain().
    Core domains cover common use cases; specialized domains (intimate,
    investigation, security) are registered by their respective scaffolds.
    """
    # Core domains (always available)
    GENERAL = "general"
    OPERATIONS = "operations"
    COMMUNICATIONS = "communications"
    SHELL = "shell"

    # Prosocial / nonprofit domains
    FUNDRAISING = "fundraising"
    PROGRAMS = "programs"
    FINANCE = "finance"
    GOVERNANCE = "governance"
    COMMUNITY = "community"
    MUTUAL_AID = "mutual_aid"
    ADVOCACY = "advocacy"
    MEMBER_SERVICES = "member_services"

    # Companion domains (Ayni)
    INTIMATE = "intimate"
    CONSENT = "consent"
    MEMORY = "memory"
    DEVICE = "device"
    PRESENCE = "presence"

    # Investigation domains (Scout, Emet)
    INVESTIGATION = "investigation"
    RESEARCH = "research"
    SECURITY = "security"


@dataclass
class EFEWeights:
    """Ethical Framing Engine weights for domain-specific prioritization.

    The EFE uses these weights to evaluate actions and decisions within
    ethical guardrails. Each skill chip can customize weights based on
    its domain's priorities.

    Each weight must be between 0.0 and 1.0. Weights should sum to ~1.0
    for proper normalization in scoring algorithms.

    Attributes:
        mission_alignment: How well an action aligns with org mission
        stakeholder_benefit: Benefit to members, community, beneficiaries
        resource_efficiency: Efficient use of limited nonprofit resources
        transparency: Openness and accountability in operations
        equity: Fair and equitable treatment across populations

    Example:
        # Fundraising chip might prioritize mission and stakeholder benefit
        weights = EFEWeights(
            mission_alignment=0.30,
            stakeholder_benefit=0.30,
            resource_efficiency=0.15,
            transparency=0.15,
            equity=0.10,
        )
    """
    mission_alignment: float = 0.25
    stakeholder_benefit: float = 0.25
    resource_efficiency: float = 0.20
    transparency: float = 0.15
    equity: float = 0.15

    def __post_init__(self) -> None:
        """Validate that all weights are in valid range."""
        weight_names = [
            'mission_alignment',
            'stakeholder_benefit',
            'resource_efficiency',
            'transparency',
            'equity',
        ]
        for name in weight_names:
            val = getattr(self, name)
            if not 0.0 <= val <= 1.0:
                raise ValueError(f"{name} must be between 0.0 and 1.0, got {val}")

    def to_dict(self) -> dict[str, float]:
        """Convert weights to dictionary for serialization.

        Returns:
            Dictionary mapping weight names to their float values.
        """
        return {
            'mission_alignment': self.mission_alignment,
            'stakeholder_benefit': self.stakeholder_benefit,
            'resource_efficiency': self.resource_efficiency,
            'transparency': self.transparency,
            'equity': self.equity,
        }

    def total(self) -> float:
        """Calculate total of all weights.

        Returns:
            Sum of all weight values. Should be ~1.0 for normalized weights.
        """
        return (
            self.mission_alignment +
            self.stakeholder_benefit +
            self.resource_efficiency +
            self.transparency +
            self.equity
        )


@dataclass
class SkillContext:
    """Context passed to skill chip handlers.

    Contains all runtime information a skill chip needs to execute,
    including organization identity, user identity, platform details,
    and the current BDI (Belief-Desire-Intention) state from the
    cognitive architecture.

    Attributes:
        org_id: Unique identifier for the organization
        user_id: Unique identifier for the requesting user
        session_id: Optional session identifier for conversation tracking
        platform: Source platform (slack, discord, webchat, etc.)
        channel_id: Platform-specific channel identifier
        thread_id: Platform-specific thread identifier
        metadata: Additional context data
        timestamp: When the request was created (UTC)
        beliefs: Current beliefs from BDI state
        desires: Current desires/goals from BDI state
        intentions: Current intentions/plans from BDI state

    Example:
        context = SkillContext(
            org_id="org_12345",
            user_id="user_67890",
            platform="slack",
            channel_id="C0123456789",
            beliefs=[{"type": "budget_status", "value": "healthy"}],
        )
    """
    org_id: str
    user_id: str
    session_id: str | None = None
    platform: str | None = None  # slack, discord, webchat
    channel_id: str | None = None
    thread_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # BDI context (populated by orchestrator)
    beliefs: list[dict[str, Any]] = field(default_factory=list)
    desires: list[dict[str, Any]] = field(default_factory=list)
    intentions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SkillRequest:
    """Request to a skill chip.

    Encapsulates what the user wants to do, extracted entities,
    and any additional parameters needed for execution.

    Attributes:
        intent: Classified intent (e.g., "grant_search", "donor_lookup")
        entities: Extracted entities from user input (names, dates, amounts, etc.)
        raw_input: Original unprocessed user input
        parameters: Additional parameters for the skill handler

    Example:
        request = SkillRequest(
            intent="grant_search",
            entities={"amount_min": 10000, "focus_area": "education"},
            raw_input="Find grants over $10k for education programs",
        )
    """
    intent: str  # What the user wants to do
    entities: dict[str, Any] = field(default_factory=dict)  # Extracted entities
    raw_input: str = ""  # Original user input
    parameters: dict[str, Any] = field(default_factory=dict)  # Additional params


@dataclass
class SkillResponse:
    """Response from a skill chip.

    Contains the result of skill execution including the content to
    display, structured data, and metadata about the response.

    Attributes:
        content: Human-readable response content
        success: Whether the skill executed successfully
        data: Structured response data for programmatic use
        suggestions: Follow-up actions or questions to suggest
        requires_consensus: Whether this action needs approval before execution
        consensus_action: Which specific action needs approval
        attachments: File attachments or rich media
        metadata: Additional response metadata

    Example:
        response = SkillResponse(
            content="Found 5 matching grants for your search.",
            success=True,
            data={"grants": [...], "total": 5},
            suggestions=["Would you like me to draft an application?"],
        )
    """
    content: str
    success: bool = True
    data: dict[str, Any] = field(default_factory=dict)  # Structured response data
    suggestions: list[str] = field(default_factory=list)  # Follow-up suggestions
    requires_consensus: bool = False  # Needs approval before execution
    consensus_action: str | None = None  # Which action needs approval
    attachments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class SkillCapability(str, Enum):
    """Standard capabilities that chips can declare.

    Capabilities are used for security, auditing, and feature gating.
    Each chip declares which capabilities it uses, enabling:
    - Permission checking before execution
    - Audit logging of sensitive operations
    - Feature flags and gradual rollouts

    Attributes:
        READ_DATA: Read organizational data from storage
        WRITE_DATA: Write/modify organizational data
        EXTERNAL_API: Make external API calls
        SEND_NOTIFICATIONS: Send emails, SMS, or push notifications
        FINANCIAL_OPERATIONS: Process financial transactions
        PII_ACCESS: Access personally identifiable information
        SCHEDULE_TASKS: Schedule future automated tasks
        GENERATE_REPORTS: Generate reports and documents
    """
    READ_DATA = "read_data"
    WRITE_DATA = "write_data"
    EXTERNAL_API = "external_api"
    SEND_NOTIFICATIONS = "send_notifications"
    FINANCIAL_OPERATIONS = "financial_operations"
    PII_ACCESS = "pii_access"
    SCHEDULE_TASKS = "schedule_tasks"
    GENERATE_REPORTS = "generate_reports"
    EXECUTE_SHELL = "execute_shell"


# Shared by every path that runs a skill: the direct route and the agent path (agent, session and dashboard messages).
# Two paths with two copies of a guard is how the second path ended up with none (Vera's re-check, 2026-10-18).

# Parameters only the server may set. A caller-supplied "approved" used to authorize BashSkillChip's approval tier
# (Vera, 2026-09-24).
RESERVED_PARAMETERS = frozenset({"approved"})


# Set on the context by BaseSkillChip's wrapper, and only there, once the approved replay's token is redeemed. Its
# value is the token object itself, which only the consumer can mint and no JSON from a caller can be: a caller's
# `"_consent_redeemed": true` is just a bool (Vera's review of the consumer, 2026-10-18, item 3).
CONSENT_REDEEMED = "_consent_redeemed"


def consent_given(context) -> bool:
    """Whether this call is the approved run of a held action. A handler that used to flag its act (or act, then
    flag) checks this, so an approved run carries the act out instead of asking again."""
    from kintsugi.governance.consumer import is_token
    return is_token((getattr(context, "metadata", None) or {}).get(CONSENT_REDEEMED))


def failure_reference(log, what: str) -> str:
    """Log the exception being handled, with its traceback, under a short id, and return the id. Callers get a fixed
    sentence and the id, never the exception's text, which can carry paths, ids or a SQL fragment (Vera, 2026-10-18)."""
    import uuid
    ref = uuid.uuid4().hex[:8]
    log.exception("%s failed [error %s]", what, ref)
    return ref


def is_shell_capable(chip) -> bool:
    """Whether a chip can run shell commands. Keyed on capability, not name: a renamed shell chip is still a shell
    (Vera, 2026-09-29)."""
    return SkillCapability.EXECUTE_SHELL in (getattr(chip, "capabilities", None) or ())


@dataclass
class ActivationCondition:
    """Predicate that determines when a Program Function fires.

    An activation condition inspects the current state (context, recent
    outputs, BDI beliefs) and returns True when the intervention should
    trigger. Conditions can match on specific failure patterns, state
    thresholds, or domain events.

    Attributes:
        name: Identifier for this condition
        description: Human-readable description of when this fires
        predicate: Callable that takes (context, state_snapshot) and returns bool
        priority: Higher priority conditions are evaluated first (default 0)
        cooldown_seconds: Minimum time between activations (prevents loops)
    """
    name: str
    description: str
    predicate: Callable[[SkillContext, dict[str, Any]], bool]
    priority: int = 0
    cooldown_seconds: float = 0.0


@dataclass
class InterventionAction:
    """Action taken when an ActivationCondition fires.

    An intervention modifies the next action, injects corrective context,
    or redirects the execution path. It does NOT replace the skill's
    normal handle method — it augments it.

    Attributes:
        name: Identifier for this action
        description: Human-readable description of what this does
        action: Callable that takes (request, context, state_snapshot) and returns
                a modified SkillRequest or SkillResponse
        modifies_request: If True, the action returns a modified SkillRequest
                         that replaces the original. If False, it returns a
                         SkillResponse that short-circuits execution.
    """
    name: str
    description: str
    action: Callable[..., Any]
    modifies_request: bool = True


@dataclass
class ProgramFunction:
    """A state-action intervention function.

    Program Functions are the proactive complement to a skill's handle method.
    While handle responds to explicit user requests, Program Functions fire
    when the system detects a state that warrants intervention — a failure
    pattern, an anomaly, a drift signal, or an opportunity.

    Inspired by HASP (arXiv:2605.17734): skills as executable intervention
    functions with explicit activation conditions.

    Attributes:
        condition: When to fire
        intervention: What to do
        enabled: Whether this PF is active
        activation_count: How many times this PF has fired
        last_activated: When this PF last fired
    """
    condition: ActivationCondition
    intervention: InterventionAction
    enabled: bool = True
    activation_count: int = 0
    last_activated: Optional[datetime] = None

    def should_fire(self, context: SkillContext, state: dict[str, Any]) -> bool:
        if not self.enabled:
            return False
        if (
            self.last_activated is not None
            and self.condition.cooldown_seconds > 0
        ):
            elapsed = (datetime.now(timezone.utc) - self.last_activated).total_seconds()
            if elapsed < self.condition.cooldown_seconds:
                return False
        return self.condition.predicate(context, state)

    def fire(
        self,
        request: "SkillRequest",
        context: SkillContext,
        state: dict[str, Any],
    ) -> Any:
        self.activation_count += 1
        self.last_activated = datetime.now(timezone.utc)
        return self.intervention.action(request, context, state)


# ---- data held inside chips, one copy per organisation (Vera's re-check, 2026-10-18) ----------------------------------
# A chip instance serves every org in the process. Its records (needs, offers, incidents, partners...) used to live in
# class-level dicts: one org's key could read and cancel another org's records. Now a chip's records are kept per org,
# the org comes from the request's context (which the API takes from the authenticated key), and reading a store with
# no org in scope raises. There is no "all orgs" view.
_CURRENT_ORG: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar("kintsugi_chip_org", default=None)


class ChipStorageError(RuntimeError):
    """Chip storage was touched with no organisation in scope."""


@contextlib.contextmanager
def org_scope(org_id: Optional[str]):
    """Make `org_id` the organisation whose chip records are read and written inside the block."""
    if not isinstance(org_id, str) or not org_id:
        raise ChipStorageError("a chip call needs the organisation it acts for")
    token = _CURRENT_ORG.set(org_id)
    try:
        yield org_id
    finally:
        _CURRENT_ORG.reset(token)


def current_org() -> Optional[str]:
    return _CURRENT_ORG.get()


class org_scoped:
    """A chip attribute holding records, kept separately for each organisation. `factory()` makes an org's empty store
    on first use; with owner=True it is called as `factory(chip)`. Read or assigned with no org in scope, it raises."""

    def __init__(self, factory: Callable[..., Any] = dict, owner: bool = False) -> None:
        self._factory = factory
        self._owner = owner
        self._name = "store"

    def __set_name__(self, cls, name: str) -> None:
        self._name = name

    def _key(self, obj) -> tuple:
        org = _CURRENT_ORG.get()
        if not org:
            raise ChipStorageError(f"{type(obj).__name__}.{self._name} touched with no organisation in scope")
        return (self._name, org)

    def __get__(self, obj, cls=None):
        if obj is None:
            return self
        stores = obj.__dict__.setdefault("_org_stores", {})
        key = self._key(obj)
        if key not in stores:
            stores[key] = self._factory(obj) if self._owner else self._factory()
        return stores[key]

    def __set__(self, obj, value) -> None:
        obj.__dict__.setdefault("_org_stores", {})[self._key(obj)] = value


def _mark_sample(chip, intent, response):
    """A sample-data chip's response says so before anything else, and carries simulated=True in data and metadata,
    so neither a person nor a program mistakes placeholders for the organization's records."""
    # An instance can say more than its class: a chip configured with the organization's own data (member tiers, say)
    # is no longer on sample data, though the class default is.
    if not isinstance(response, SkillResponse) or not chip.simulated or intent in chip.real_intents:
        return response
    if (response.metadata or {}).get("simulated"):
        return response  # already marked (a chip whose handle() calls super().handle() is wrapped twice)
    from kintsugi.skills.honesty import SAMPLE_NOTICE
    response.content = f"{SAMPLE_NOTICE}\n\n{response.content}"
    response.data = {**(response.data or {}), "simulated": True}
    response.metadata = {**(response.metadata or {}), "simulated": True}
    return response


def _asks_for(chip, intent, request, context) -> bool:
    """Whether this request asks for its intent's consensus action. With no predicate, every call does; a predicate
    that fails counts as asking, so an error holds rather than runs. A predicate given as a method name is called as
    chip.method(request, context), for a condition that depends on the chip's own records (a per-requester count)."""
    when = (type(chip).consensus_when or {}).get(intent)
    if when is None:
        return True
    try:
        return bool(getattr(chip, when)(request, context) if isinstance(when, str) else when(request))
    except Exception:
        return True


class BaseSkillChip(ABC):
    """Abstract base class for all skill chips.

    Skill chips are modular handlers for specific domains of nonprofit
    operations. Each chip:
    - Handles specific intents routed by the Orchestrator
    - Operates within ethical guardrails defined by EFE weights
    - Declares required MCP tool spans for execution
    - Specifies which actions require consensus approval

    Subclasses must implement the `handle` method and should override
    class-level attributes to define chip identity and behavior.

    Class Attributes:
        name: Unique identifier for the chip
        description: Human-readable description
        version: Semantic version string
        domain: Primary skill domain
        efe_weights: Ethical Framing Engine weights
        required_spans: MCP tool spans this chip needs
        consensus_actions: Actions requiring approval
        capabilities: Declared capabilities

    Example:
        class GrantSearchChip(BaseSkillChip):
            name = "grant_search"
            description = "Search and match grant opportunities"
            version = "1.0.0"
            domain = SkillDomain.FUNDRAISING

            efe_weights = EFEWeights(
                mission_alignment=0.30,
                stakeholder_benefit=0.25,
                resource_efficiency=0.20,
                transparency=0.15,
                equity=0.10,
            )

            required_spans = ["grant_database", "org_profile"]
            capabilities = [SkillCapability.READ_DATA, SkillCapability.EXTERNAL_API]

            async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
                # Implementation here
                ...
    """

    # Class-level attributes (override in subclasses)
    name: str = "base_chip"
    description: str = "Base skill chip"
    version: str = "1.0.0"
    domain: SkillDomain = SkillDomain.OPERATIONS

    # Default EFE weights (override per domain)
    efe_weights: EFEWeights | None = None

    # MCP tool spans this chip needs
    required_spans: list[str] = []

    # Actions that require consensus approval
    consensus_actions: list[str] = []
    # Which intents are which consensus action: intent -> action. A mapped intent is held for consent before handle()
    # runs. Intent names never equal action names, so this map is explicit, and a test dispatches every entry.
    consensus_intents: dict[str, str] = {}
    # Declared actions no intent reaches, each with the reason; a declared action is in one map or the other.
    consensus_unreachable: dict[str, str] = {}
    # Optional: action -> ConsentCategory value (default GENERAL, one approval; FINANCIAL and PII need two).
    consensus_categories: dict[str, str] = {}
    # Held actions this chip can't yet carry out once approved (its handler only ever asks): action -> why. The hold
    # says so at once, so nobody approves expecting something to happen (Vera, 10-18 follow-ons). Still held, so an
    # act step added later is gated from its first day.
    consensus_no_step: dict[str, str] = {}
    # Optional: intent -> predicate on the request, for an intent that asks for its act only sometimes (a campaign
    # message vs its launch). It mirrors the chip's own condition, and is decided before the chip runs. A method name
    # instead of a function is called as self.method(request, context).
    consensus_when: dict = {}

    # Honesty (kintsugi/skills/honesty.py). A chip runs on sample data until it is connected to the organization's own
    # systems, and every response says so: the wrapper marks it before anyone reads it. A chip sets simulated = False
    # only when every intent is backed by real work; real_intents lists the ones that are, in a chip that is otherwise
    # sample data. Tight by default: a new chip is marked until someone checks it.
    simulated: bool = True
    real_intents: frozenset = frozenset()

    def while_held(self, action: str) -> str:
        """What the person needs to know now, while their request waits for approval: added to the hold message.

        A chip whose action can't reach anyone yet says so here, so nobody waits on an approval that will do nothing
        (a raid report, a bail request). Empty by default."""
        return ""

    # Capabilities this chip uses
    capabilities: list[SkillCapability] = []

    # Program Functions — proactive interventions (v2)
    program_functions: list[ProgramFunction] = []

    def __init_subclass__(cls, **kwargs) -> None:
        """Every chip's handle() runs in its context's organisation, so its records are that org's alone, whichever
        path called it: the API, an agent, a session or the orchestrator."""
        super().__init_subclass__(**kwargs)
        handle = cls.__dict__.get("handle")
        if handle is None or getattr(handle, "_org_scoped", False) or getattr(handle, "__isabstractmethod__", False):
            return

        @functools.wraps(handle)
        async def handle_in_org(self, request, context, *args, **kw):
            with org_scope(getattr(context, "org_id", None)):
                # An intent the chip maps to a consensus action is held before the chip runs, on every path, unless
                # this is the approved replay (kintsugi/governance/consumer.py; Vera's re-check, 2026-10-18).
                intent = getattr(request, "intent", None)
                action = (type(self).consensus_intents or {}).get(intent)
                if action and _asks_for(self, intent, request, context):
                    from kintsugi.governance import consumer
                    md = getattr(context, "metadata", None) or {}
                    done = md.get(CONSENT_REDEEMED)
                    # An outer wrapper of this same approved call already redeemed it (a chip whose handle() calls
                    # super().handle() is wrapped twice); otherwise redeem now, or hold.
                    if not (consumer.is_token(done) and done.action == action and done.org_id == context.org_id):
                        token = md.get(consumer.CONSENT_TOKEN)
                        if not consumer.redeem(token, self.name, request, context, action):
                            return consumer.hold(self, request, context, action)
                        context.metadata[CONSENT_REDEEMED] = token
                return _mark_sample(self, intent, await handle(self, request, context, *args, **kw))

        handle_in_org._org_scoped = True
        cls.handle = handle_in_org

    def __init__(self) -> None:
        """Initialize the skill chip.

        Sets default values for instance-level attributes if not
        already defined at the class level.
        """
        # Initialize instance-level if not set at class level
        if self.efe_weights is None:
            self.efe_weights = EFEWeights()

        # Ensure lists are instance-level to avoid shared state
        if not hasattr(self.__class__, 'required_spans') or self.required_spans is None:
            self.required_spans = []
        if not hasattr(self.__class__, 'consensus_actions') or self.consensus_actions is None:
            self.consensus_actions = []
        if not hasattr(self.__class__, 'capabilities') or self.capabilities is None:
            self.capabilities = []
        self.program_functions = list(self.__class__.program_functions or [])

    @abstractmethod
    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Main execution method - receives routed request from Orchestrator.

        This is the primary entry point for skill chip execution. The
        Orchestrator routes classified intents to the appropriate chip
        and calls this method with the request and context.

        Args:
            request: The skill request with intent and entities
            context: Execution context including org, user, BDI state

        Returns:
            SkillResponse with content and metadata

        Raises:
            NotImplementedError: If subclass doesn't implement this method
        """
        ...

    async def get_bdi_context(
        self,
        beliefs: list[dict[str, Any]],
        desires: list[dict[str, Any]],
        intentions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Extract relevant BDI sections for this chip's domain.

        Override in subclasses to filter BDI state relevant to the
        chip's domain. This allows chips to focus on the beliefs,
        desires, and intentions that matter for their operations.

        Default implementation returns all BDI state unfiltered.

        Args:
            beliefs: Current belief state from cognitive architecture
            desires: Current desires/goals
            intentions: Current intentions/plans

        Returns:
            Dictionary containing filtered BDI state for this chip's domain

        Example:
            # In a FundraisingChip subclass:
            async def get_bdi_context(self, beliefs, desires, intentions):
                return {
                    'beliefs': [b for b in beliefs if b.get('domain') == 'fundraising'],
                    'desires': [d for d in desires if d.get('type') == 'funding_goal'],
                    'intentions': intentions,  # Keep all intentions
                }
        """
        return {
            'beliefs': beliefs,
            'desires': desires,
            'intentions': intentions,
        }

    def requires_consensus(self, action: str) -> bool:
        """Check if an action requires consensus approval.

        Consensus actions are those that need human approval before
        execution, such as financial disbursements or policy changes.

        Args:
            action: The action name to check

        Returns:
            True if the action is in the consensus_actions list
        """
        return action in self.consensus_actions

    def register_program_function(self, pf: ProgramFunction) -> None:
        """Register a Program Function on this skill chip."""
        if not isinstance(self.program_functions, list):
            self.program_functions = []
        self.program_functions.append(pf)

    def evaluate_interventions(
        self, context: SkillContext, state: dict[str, Any]
    ) -> list[ProgramFunction]:
        """Check which Program Functions should fire given the current state.

        Returns PFs in priority order (highest first). The caller decides
        whether to execute them — this method only evaluates conditions.
        """
        if not self.program_functions:
            return []
        triggered = [
            pf for pf in self.program_functions
            if pf.should_fire(context, state)
        ]
        return sorted(triggered, key=lambda pf: pf.condition.priority, reverse=True)

    async def handle_with_interventions(
        self,
        request: SkillRequest,
        context: SkillContext,
        state: dict[str, Any] | None = None,
    ) -> SkillResponse:
        """Execute handle() with Program Function intervention layer.

        Before calling handle(), evaluates all registered PFs against the
        current state. PFs that fire can either:
        - Modify the request (modifies_request=True): the modified request
          is passed to handle()
        - Short-circuit (modifies_request=False): the PF's response is
          returned directly, skipping handle()
        """
        state = state or {}
        triggered = self.evaluate_interventions(context, state)

        current_request = request
        for pf in triggered:
            result = pf.fire(current_request, context, state)
            if pf.intervention.modifies_request:
                if isinstance(result, SkillRequest):
                    current_request = result
            else:
                if isinstance(result, SkillResponse):
                    return result

        return await self.handle(current_request, context)

    def get_info(self) -> dict[str, Any]:
        """Get chip metadata for registration/discovery.

        Returns a dictionary containing all metadata about this chip,
        useful for registration in the SkillRegistry and for UI display.

        Returns:
            Dictionary with chip metadata including name, description,
            version, domain, EFE weights, required spans, consensus
            actions, and capabilities.
        """
        return {
            'name': self.name,
            'description': self.description,
            'version': self.version,
            'domain': self.domain.value,
            'efe_weights': self.efe_weights.to_dict() if self.efe_weights else {},
            'required_spans': list(self.required_spans),
            'consensus_actions': list(self.consensus_actions),
            'capabilities': [c.value for c in self.capabilities],
            'program_functions': [
                {
                    'condition': pf.condition.name,
                    'intervention': pf.intervention.name,
                    'enabled': pf.enabled,
                    'activation_count': pf.activation_count,
                }
                for pf in (self.program_functions or [])
            ],
        }


# Type alias for skill handler functions
SkillHandler = Callable[[SkillRequest, SkillContext], Coroutine[Any, Any, SkillResponse]]
"""Type alias for async skill handler functions.

A skill handler is any async function that takes a SkillRequest and
SkillContext and returns a SkillResponse. This type is useful for
functional-style skill implementations or middleware.

Example:
    async def my_handler(request: SkillRequest, context: SkillContext) -> SkillResponse:
        return SkillResponse(content="Hello!")

    handler: SkillHandler = my_handler
"""
