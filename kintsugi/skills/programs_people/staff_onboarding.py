"""Skill Chip: Staff Onboarding

Domain: OPERATIONS
Spans: hris_api, training_lms, document_store
EFE Profile: risk=0.33, ambiguity=0.34, epistemic=0.33
Description: Guides new staff through onboarding workflows, training assignments, and policy orientation.

Staff Onboarding Skill Chip for Kintsugi CMA.

Guides new staff through onboarding workflows including training assignments,
policy orientation, checklist tracking, and onboarding completion. Emphasizes
stakeholder benefit and resource efficiency in onboarding processes.

Example:
    chip = StaffOnboardingChip()
    request = SkillRequest(
        intent="onboard_start",
        entities={"employee_id": "emp_001", "department": "programs"},
    )
    response = await chip.handle(request, context)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any
from uuid import uuid4

from kintsugi.skills.honesty import not_connected
from kintsugi.skills import (
    BaseSkillChip,
    EFEWeights,
    SkillCapability,
    SkillContext,
    SkillDomain,
    SkillRequest,
    SkillResponse,
)


@dataclass
class OnboardingPlan:
    """Represents an employee's onboarding plan."""
    plan_id: str
    employee_id: str
    employee_name: str
    department: str
    start_date: datetime
    supervisor: str
    status: str = "not_started"  # not_started, in_progress, completed
    target_completion: datetime | None = None
    checklist_items: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TrainingModule:
    """Represents a training module assignment."""
    module_id: str
    title: str
    description: str
    category: str  # required, role_specific, optional
    duration_minutes: int
    format: str  # video, interactive, reading, workshop
    due_date: datetime | None = None
    completed: bool = False
    completion_date: datetime | None = None
    score: float | None = None


@dataclass
class PolicyDocument:
    """Represents a policy document for review."""
    policy_id: str
    title: str
    category: str  # hr, safety, operations, ethics
    version: str
    acknowledgment_required: bool = True
    acknowledged: bool = False
    acknowledgment_date: datetime | None = None


class StaffOnboardingChip(BaseSkillChip):
    """Guide new staff through onboarding, training, and policy orientation.

    This chip supports HR and managers in efficiently onboarding new
    employees through structured workflows, training assignments,
    policy reviews, and progress tracking.

    Intents:
        onboard_start: Initialize onboarding for new employee
        training_assign: Assign training modules
        policy_review: Present policies for review
        checklist_status: Check onboarding progress
        onboard_complete: Finalize onboarding

    Example:
        >>> chip = StaffOnboardingChip()
        >>> request = SkillRequest(intent="onboard_start", entities={"employee_id": "emp_001"})
        >>> response = await chip.handle(request, context)
        >>> print(response.data["onboarding_plan"]["checklist_items"])
    """

    name = "staff_onboarding"
    description = "Guide new staff through onboarding, training, and policy orientation"
    version = "1.0.0"
    domain = SkillDomain.OPERATIONS

    efe_weights = EFEWeights(
        mission_alignment=0.25,
        stakeholder_benefit=0.30,
        resource_efficiency=0.20,
        transparency=0.15,
        equity=0.10,
    )

    capabilities = [
        SkillCapability.READ_DATA,
        SkillCapability.WRITE_DATA,
        SkillCapability.SCHEDULE_TASKS,
        SkillCapability.PII_ACCESS,
    ]

    consensus_actions = ["complete_onboarding", "grant_system_access", "update_employee_record"]
    # Consensus: which intents ask for which action, held before handle() runs (kintsugi/governance/consumer.py).
    consensus_intents = {"onboard_complete": "complete_onboarding"}
    # Who approves (Vera, 10-18): money and private info take two people (FINANCIAL, PII); the rest one.
    consensus_categories = {"complete_onboarding": "GENERAL"}
    consensus_no_step = {"complete_onboarding": "no HR system is connected, so completion isn't recorded"}
    consensus_unreachable = {
        "grant_system_access": "no intent performs this yet: declared for a future one, so it can't happen ungated",
        "update_employee_record": "no intent performs this yet: declared for a future one, so it can't happen ungated",
    }

    required_spans = ["hris_api", "training_lms", "document_store"]
    # Honest without its spans (kintsugi/skills/honesty.py): plans and training lists are drafts and suggestions, not
    # saved or assigned; no employee's progress, sign-off or score is invented; completion isn't recorded.
    simulated = False

    async def handle(self, request: SkillRequest, context: SkillContext) -> SkillResponse:
        """Route request to appropriate handler based on intent.

        Args:
            request: Skill request with intent and entities
            context: Execution context with org, user, BDI state

        Returns:
            SkillResponse with result content and data
        """
        intent = request.intent

        bdi = await self.get_bdi_context(
            context.beliefs,
            context.desires,
            context.intentions,
        )

        handlers = {
            "onboard_start": self._start_onboarding,
            "training_assign": self._assign_training,
            "policy_review": self._get_policy_docs,
            "checklist_status": self._check_progress,
            "onboard_complete": self._complete_onboarding,
        }

        handler = handlers.get(intent)
        if not handler:
            return SkillResponse(
                content=f"Unknown intent '{intent}' for staff onboarding.",
                success=False,
                suggestions=[
                    "Try 'onboard_start' to begin onboarding",
                    "Try 'training_assign' to suggest training",
                    "Try 'checklist_status' to check progress",
                ],
            )

        return await handler(request, context, bdi)

    async def get_bdi_context(
        self,
        beliefs: list[dict[str, Any]],
        desires: list[dict[str, Any]],
        intentions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Filter BDI state for onboarding context.

        Extracts beliefs about staff, training needs, and onboarding
        priorities.
        """
        hr_beliefs = [
            b for b in beliefs
            if b.get("domain") in ("hr", "operations", "training")
            or b.get("type") in ("employee_status", "training_completion", "compliance_need")
        ]

        onboarding_desires = [
            d for d in desires
            if d.get("type") in ("efficient_onboarding", "staff_readiness", "compliance")
            or d.get("domain") == "operations"
        ]

        return {
            "beliefs": hr_beliefs,
            "desires": onboarding_desires,
            "intentions": intentions,
        }

    async def _start_onboarding(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """Draft an onboarding plan for a new employee: checklist and timeline, not saved (no HR system)."""
        employee_id = request.entities.get("employee_id", "")
        employee_name = request.entities.get("employee_name", "New Employee")
        department = request.entities.get("department", "general")
        start_date = request.entities.get("start_date", datetime.now(timezone.utc).isoformat())
        supervisor = request.entities.get("supervisor", "Department Manager")

        start_dt = datetime.fromisoformat(start_date) if isinstance(start_date, str) else start_date
        target_completion = start_dt + timedelta(days=30)

        # Build standard checklist items
        checklist_items = [
            # Day 1 items
            {
                "item_id": f"chk_{uuid4().hex[:8]}",
                "category": "day_1",
                "title": "Welcome meeting with supervisor",
                "description": "Introduction to team, role overview, and immediate goals",
                "due_date": start_dt.isoformat(),
                "completed": False,
                "assigned_to": supervisor,
            },
            {
                "item_id": f"chk_{uuid4().hex[:8]}",
                "category": "day_1",
                "title": "Workspace and equipment setup",
                "description": "Computer, phone, desk, supplies, access badge",
                "due_date": start_dt.isoformat(),
                "completed": False,
                "assigned_to": "IT/Facilities",
            },
            {
                "item_id": f"chk_{uuid4().hex[:8]}",
                "category": "day_1",
                "title": "HR paperwork completion",
                "description": "I-9, W-4, benefits enrollment, emergency contacts",
                "due_date": start_dt.isoformat(),
                "completed": False,
                "assigned_to": "HR",
            },
            # Week 1 items
            {
                "item_id": f"chk_{uuid4().hex[:8]}",
                "category": "week_1",
                "title": "System access provisioning",
                "description": "Email, shared drives, databases, software licenses",
                "due_date": (start_dt + timedelta(days=2)).isoformat(),
                "completed": False,
                "assigned_to": "IT",
            },
            {
                "item_id": f"chk_{uuid4().hex[:8]}",
                "category": "week_1",
                "title": "Organization overview training",
                "description": "Mission, history, programs, culture",
                "due_date": (start_dt + timedelta(days=5)).isoformat(),
                "completed": False,
                "assigned_to": employee_name,
            },
            {
                "item_id": f"chk_{uuid4().hex[:8]}",
                "category": "week_1",
                "title": "Required policy reviews",
                "description": "Employee handbook, code of conduct, safety policies",
                "due_date": (start_dt + timedelta(days=5)).isoformat(),
                "completed": False,
                "assigned_to": employee_name,
            },
            # Week 2-4 items
            {
                "item_id": f"chk_{uuid4().hex[:8]}",
                "category": "week_2_4",
                "title": "Department-specific training",
                "description": f"Training modules specific to {department} department",
                "due_date": (start_dt + timedelta(days=14)).isoformat(),
                "completed": False,
                "assigned_to": employee_name,
            },
            {
                "item_id": f"chk_{uuid4().hex[:8]}",
                "category": "week_2_4",
                "title": "Meet with key stakeholders",
                "description": "Scheduled introductions with partner departments",
                "due_date": (start_dt + timedelta(days=14)).isoformat(),
                "completed": False,
                "assigned_to": supervisor,
            },
            {
                "item_id": f"chk_{uuid4().hex[:8]}",
                "category": "week_2_4",
                "title": "Initial project assignment",
                "description": "First project or task to apply learning",
                "due_date": (start_dt + timedelta(days=21)).isoformat(),
                "completed": False,
                "assigned_to": supervisor,
            },
            {
                "item_id": f"chk_{uuid4().hex[:8]}",
                "category": "week_2_4",
                "title": "30-day check-in meeting",
                "description": "Review progress, address questions, adjust plan if needed",
                "due_date": (start_dt + timedelta(days=30)).isoformat(),
                "completed": False,
                "assigned_to": supervisor,
            },
        ]

        plan = OnboardingPlan(
            plan_id=f"onb_{uuid4().hex[:8]}",
            employee_id=employee_id,
            employee_name=employee_name,
            department=department,
            start_date=start_dt,
            supervisor=supervisor,
            status="draft",
            target_completion=target_completion,
            checklist_items=checklist_items,
        )

        return SkillResponse(
            content=(f"Draft onboarding plan for {employee_name} ({department}), starting "
                     f"{start_dt.strftime('%B %d, %Y')}: {len(checklist_items)} checklist items over 30 days. "
                     f"{not_connected('An HR system', 'it has not been saved and nobody has been assigned anything')}"),
            success=True,
            data={
                "onboarding_plan": {
                    "plan_id": plan.plan_id,
                    "employee_id": plan.employee_id,
                    "employee_name": plan.employee_name,
                    "department": plan.department,
                    "start_date": plan.start_date.isoformat(),
                    "supervisor": plan.supervisor,
                    "status": plan.status,
                    "saved": False,
                    "target_completion": plan.target_completion.isoformat() if plan.target_completion else None,
                    "checklist_items": plan.checklist_items,
                },
            },
            suggestions=["Suggest training modules", "Want to customize the checklist?"],
        )

    async def _assign_training(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """Suggest training modules by role and department; none is assigned (no learning system)."""
        employee_id = request.entities.get("employee_id", "")
        department = request.entities.get("department", "general")
        include_optional = request.entities.get("include_optional", False)

        now = datetime.now(timezone.utc)

        # Required training for all employees
        required_modules = [
            TrainingModule(
                module_id=f"trn_{uuid4().hex[:8]}",
                title="Organization Mission and Values",
                description="Introduction to our mission, vision, and core values",
                category="required",
                duration_minutes=30,
                format="video",
                due_date=now + timedelta(days=5),
            ),
            TrainingModule(
                module_id=f"trn_{uuid4().hex[:8]}",
                title="Workplace Safety Fundamentals",
                description="Essential safety protocols and emergency procedures",
                category="required",
                duration_minutes=45,
                format="interactive",
                due_date=now + timedelta(days=5),
            ),
            TrainingModule(
                module_id=f"trn_{uuid4().hex[:8]}",
                title="Harassment Prevention",
                description="Recognizing and preventing workplace harassment",
                category="required",
                duration_minutes=60,
                format="interactive",
                due_date=now + timedelta(days=7),
            ),
            TrainingModule(
                module_id=f"trn_{uuid4().hex[:8]}",
                title="Data Privacy and Security",
                description="Protecting sensitive information and cybersecurity basics",
                category="required",
                duration_minutes=45,
                format="interactive",
                due_date=now + timedelta(days=7),
            ),
            TrainingModule(
                module_id=f"trn_{uuid4().hex[:8]}",
                title="Diversity, Equity, and Inclusion",
                description="Building an inclusive workplace",
                category="required",
                duration_minutes=60,
                format="video",
                due_date=now + timedelta(days=10),
            ),
        ]

        # Department-specific training
        dept_modules = {
            "programs": [
                TrainingModule(
                    module_id=f"trn_{uuid4().hex[:8]}",
                    title="Program Management Fundamentals",
                    description="Planning, implementing, and evaluating programs",
                    category="role_specific",
                    duration_minutes=90,
                    format="interactive",
                    due_date=now + timedelta(days=14),
                ),
                TrainingModule(
                    module_id=f"trn_{uuid4().hex[:8]}",
                    title="Participant Data Management",
                    description="Tracking participant information and outcomes",
                    category="role_specific",
                    duration_minutes=45,
                    format="workshop",
                    due_date=now + timedelta(days=14),
                ),
            ],
            "development": [
                TrainingModule(
                    module_id=f"trn_{uuid4().hex[:8]}",
                    title="Donor Database Training",
                    description="CRM system navigation and data entry",
                    category="role_specific",
                    duration_minutes=90,
                    format="workshop",
                    due_date=now + timedelta(days=14),
                ),
                TrainingModule(
                    module_id=f"trn_{uuid4().hex[:8]}",
                    title="Gift Processing Procedures",
                    description="Acknowledging and recording donations",
                    category="role_specific",
                    duration_minutes=60,
                    format="interactive",
                    due_date=now + timedelta(days=14),
                ),
            ],
            "finance": [
                TrainingModule(
                    module_id=f"trn_{uuid4().hex[:8]}",
                    title="Financial Systems Overview",
                    description="Accounting software and procedures",
                    category="role_specific",
                    duration_minutes=120,
                    format="workshop",
                    due_date=now + timedelta(days=14),
                ),
                TrainingModule(
                    module_id=f"trn_{uuid4().hex[:8]}",
                    title="Grant Financial Compliance",
                    description="Managing restricted funds and grant reporting",
                    category="role_specific",
                    duration_minutes=90,
                    format="interactive",
                    due_date=now + timedelta(days=21),
                ),
            ],
        }

        # Optional training
        optional_modules = [
            TrainingModule(
                module_id=f"trn_{uuid4().hex[:8]}",
                title="Effective Communication Skills",
                description="Professional communication techniques",
                category="optional",
                duration_minutes=45,
                format="video",
                due_date=now + timedelta(days=30),
            ),
            TrainingModule(
                module_id=f"trn_{uuid4().hex[:8]}",
                title="Time Management Strategies",
                description="Productivity and prioritization techniques",
                category="optional",
                duration_minutes=30,
                format="reading",
                due_date=now + timedelta(days=30),
            ),
        ]

        # Compile training list
        all_modules = required_modules.copy()

        if department in dept_modules:
            all_modules.extend(dept_modules[department])
        else:
            # Default role-specific training
            all_modules.append(
                TrainingModule(
                    module_id=f"trn_{uuid4().hex[:8]}",
                    title="Role-Specific Orientation",
                    description="Department-specific procedures and systems",
                    category="role_specific",
                    duration_minutes=60,
                    format="workshop",
                    due_date=now + timedelta(days=14),
                )
            )

        if include_optional:
            all_modules.extend(optional_modules)

        total_duration = sum(m.duration_minutes for m in all_modules)

        training_data = {
            "employee_id": employee_id,
            "department": department,
            "assigned": False,
            "modules": [
                {
                    "module_id": m.module_id,
                    "title": m.title,
                    "description": m.description,
                    "category": m.category,
                    "duration_minutes": m.duration_minutes,
                    "format": m.format,
                    "due_date": m.due_date.isoformat() if m.due_date else None,
                    "completed": m.completed,
                }
                for m in all_modules
            ],
            "summary": {
                "total_modules": len(all_modules),
                "required": len([m for m in all_modules if m.category == "required"]),
                "role_specific": len([m for m in all_modules if m.category == "role_specific"]),
                "optional": len([m for m in all_modules if m.category == "optional"]),
                "total_duration_minutes": total_duration,
                "estimated_hours": round(total_duration / 60, 1),
            },
        }

        return SkillResponse(
            content=(f"Suggested {len(all_modules)} training modules for a {department} employee, about "
                     f"{training_data['summary']['estimated_hours']} hours. "
                     f"{not_connected('A learning system', 'none has been assigned')}"),
            success=True,
            data={"training_assignment": training_data},
            suggestions=["Want to add additional modules?"],
        )

    async def _get_policy_docs(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """A checklist of policies new staff usually get; the organization's own aren't known (no document store)."""
        employee_id = request.entities.get("employee_id", "")
        category = request.entities.get("category", None)

        # No document store is connected: the organization's own policies, versions and acknowledgments aren't known.
        # A checklist of the policies most organizations give new staff, to match against your own.
        checklist = [
            {"title": "Employee handbook", "category": "hr"},
            {"title": "Code of conduct", "category": "ethics"},
            {"title": "Anti-harassment policy", "category": "hr"},
            {"title": "Information security policy", "category": "operations"},
            {"title": "Conflict of interest policy", "category": "ethics"},
            {"title": "Workplace safety procedures", "category": "safety"},
        ]
        if category:
            checklist = [c for c in checklist if c["category"] == category]
        return SkillResponse(
            content=(not_connected("A document store", "I can't show your policies or track acknowledgments")
                     + f" A checklist of {len(checklist)} policies most organizations give new staff, to match against "
                     f"your own."),
            success=True,
            data={"policy_review": {"employee_id": employee_id, "checklist": checklist, "connected": False}},
            suggestions=[],
        )

    async def _check_progress(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """Onboarding progress: not known without an HR system, and never invented."""
        employee_id = request.entities.get("employee_id", "")
        plan_id = request.entities.get("plan_id", "")

        return SkillResponse(
            content=not_connected("An HR system", f"I can't see {employee_id or 'this employee'}'s onboarding progress"),
            success=True,
            data={"onboarding_progress": None, "connected": False},
            suggestions=[],
        )

    async def _complete_onboarding(
        self,
        request: SkillRequest,
        context: SkillContext,
        bdi: dict[str, Any],
    ) -> SkillResponse:
        """Completion can't be checked or recorded without an HR system; the approved run reports no step."""
        employee_id = request.entities.get("employee_id", "")
        plan_id = request.entities.get("plan_id", "")
        force_complete = request.entities.get("force_complete", False)

        # Nothing can be checked or recorded: no HR system is connected. The approved run asks again, so the consumer
        # records "no step" (consensus_no_step) rather than a completion that didn't happen.
        return SkillResponse(
            content=(f"Onboarding for {employee_id or 'this employee'} not recorded as complete: "
                     + not_connected("An HR system", "I can't check what is done or record completion")),
            success=False,
            data={"completion_record": None, "recorded": False, "forced": bool(force_complete)},
            requires_consensus=True,
            consensus_action="complete_onboarding",
            suggestions=[],
        )
