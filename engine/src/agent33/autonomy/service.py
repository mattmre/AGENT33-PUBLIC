"""Autonomy budget service — CRUD, lifecycle, and enforcement orchestration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import ValidationError

from agent33.autonomy.enforcement import RuntimeEnforcer
from agent33.autonomy.models import (
    AutonomyBudget,
    BudgetState,
    EnforcementResult,
    EscalationRecord,
    EscalationUrgency,
    PreflightReport,
    PreflightStatus,
)
from agent33.autonomy.preflight import PreflightChecker

if TYPE_CHECKING:
    from agent33.services.orchestration_state import OrchestrationStateStore

logger = logging.getLogger(__name__)

# Valid state transitions for budget lifecycle
_VALID_TRANSITIONS: dict[BudgetState, frozenset[BudgetState]] = {
    BudgetState.DRAFT: frozenset({BudgetState.PENDING_APPROVAL, BudgetState.ACTIVE}),
    BudgetState.PENDING_APPROVAL: frozenset(
        {
            BudgetState.ACTIVE,
            BudgetState.REJECTED,
        }
    ),
    BudgetState.ACTIVE: frozenset(
        {
            BudgetState.SUSPENDED,
            BudgetState.EXPIRED,
            BudgetState.COMPLETED,
        }
    ),
    BudgetState.SUSPENDED: frozenset({BudgetState.ACTIVE, BudgetState.EXPIRED}),
    BudgetState.REJECTED: frozenset({BudgetState.DRAFT}),
    BudgetState.EXPIRED: frozenset(),
    BudgetState.COMPLETED: frozenset(),
}


class BudgetNotFoundError(Exception):
    """Raised when a budget is not found."""


class InvalidStateTransitionError(Exception):
    """Raised when a budget state transition is invalid."""

    def __init__(self, from_state: BudgetState, to_state: BudgetState) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Invalid transition: {from_state.value} → {to_state.value}")


class EnforcerNotFoundError(Exception):
    """Raised when an enforcer is not found for a budget."""


class PreflightFailedError(Exception):
    """Raised when an active budget does not pass preflight."""

    def __init__(self, report: PreflightReport) -> None:
        self.report = report
        failed = [
            f"{check.check_id}: {check.message or check.name}"
            for check in report.checks
            if check.status == PreflightStatus.FAIL
        ]
        detail = "; ".join(failed) if failed else f"Preflight status {report.overall.value}"
        super().__init__(f"Budget preflight failed for {report.budget_id}: {detail}")


class AutonomyService:
    """Budget CRUD, lifecycle management, and enforcement orchestration."""

    def __init__(self, state_store: OrchestrationStateStore | None = None) -> None:
        self._state_store = state_store
        self._budgets: dict[str, AutonomyBudget] = {}
        self._enforcers: dict[str, RuntimeEnforcer] = {}
        self._escalations: dict[str, EscalationRecord] = {}
        self._checker = PreflightChecker()
        if state_store is None:
            logger.warning(
                "autonomy_service_no_persistence: state_store is None, all autonomy budgets "
                "are in-memory only and will be lost on restart. Set "
                "ORCHESTRATION_STATE_STORE_PATH to enable durable persistence."
            )
        self._load_state()

    def _persist_state(self) -> None:
        if self._state_store is None:
            return
        self._state_store.write_namespace(
            "autonomy",
            {
                "budgets": {
                    budget_id: budget.model_dump(mode="json")
                    for budget_id, budget in self._budgets.items()
                },
                "enforcers": {
                    budget_id: enforcer.snapshot_state()
                    for budget_id, enforcer in self._enforcers.items()
                },
                "escalations": {
                    escalation_id: escalation.model_dump(mode="json")
                    for escalation_id, escalation in self._escalations.items()
                },
            },
        )

    def _load_state(self) -> None:
        if self._state_store is None:
            return
        payload = self._state_store.read_namespace("autonomy")
        budgets_payload = payload.get("budgets", {})
        if isinstance(budgets_payload, dict):
            for budget_id, budget_data in budgets_payload.items():
                if not isinstance(budget_id, str):
                    continue
                try:
                    self._budgets[budget_id] = AutonomyBudget.model_validate(budget_data)
                except ValidationError:
                    logger.warning("autonomy_budget_restore_failed id=%s", budget_id)

        escalations_payload = payload.get("escalations", {})
        if isinstance(escalations_payload, dict):
            for escalation_id, escalation_data in escalations_payload.items():
                if not isinstance(escalation_id, str):
                    continue
                try:
                    self._escalations[escalation_id] = EscalationRecord.model_validate(
                        escalation_data
                    )
                except ValidationError:
                    logger.warning("autonomy_escalation_restore_failed id=%s", escalation_id)

        enforcers_payload = payload.get("enforcers", {})
        if isinstance(enforcers_payload, dict):
            for budget_id, enforcer_data in enforcers_payload.items():
                budget = self._budgets.get(budget_id)
                if budget is None or not isinstance(enforcer_data, dict):
                    continue
                enforcer = RuntimeEnforcer(budget)
                try:
                    enforcer.restore_state(
                        context=enforcer_data.get("context"),
                        escalations=enforcer_data.get("escalations"),
                    )
                except ValidationError:
                    logger.warning("autonomy_enforcer_restore_failed budget_id=%s", budget_id)
                    continue
                self._enforcers[budget_id] = enforcer

    # ------------------------------------------------------------------
    # Budget CRUD
    # ------------------------------------------------------------------

    def create_budget(
        self,
        task_id: str = "",
        agent_id: str = "",
        **kwargs: object,
    ) -> AutonomyBudget:
        """Create a new autonomy budget in DRAFT state."""
        budget = AutonomyBudget(task_id=task_id, agent_id=agent_id, **kwargs)
        self._budgets[budget.budget_id] = budget
        logger.info(
            "budget_created id=%s task=%s agent=%s",
            budget.budget_id,
            task_id,
            agent_id,
        )
        self._persist_state()
        return budget

    def register_budget(self, budget: AutonomyBudget) -> AutonomyBudget:
        """Register an already constructed budget and persist it.

        This is used when a caller selects a templated autonomy level.  The
        generated level budget still receives a durable budget_id and runtime
        enforcer state instead of remaining an untracked transient object.
        """
        if budget.budget_id in self._budgets:
            raise ValueError(f"Budget already exists: {budget.budget_id}")
        self._budgets[budget.budget_id] = budget
        self._persist_state()
        return budget

    def get_budget(self, budget_id: str) -> AutonomyBudget:
        """Get a budget by ID."""
        budget = self._budgets.get(budget_id)
        if budget is None:
            raise BudgetNotFoundError(f"Budget not found: {budget_id}")
        return budget

    def list_budgets(
        self,
        state: BudgetState | None = None,
        task_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 100,
    ) -> list[AutonomyBudget]:
        """List budgets with optional filters."""
        results = list(self._budgets.values())
        if state is not None:
            results = [b for b in results if b.state == state]
        if task_id is not None:
            results = [b for b in results if b.task_id == task_id]
        if agent_id is not None:
            results = [b for b in results if b.agent_id == agent_id]
        results.sort(key=lambda b: b.created_at, reverse=True)
        return results[:limit]

    def delete_budget(self, budget_id: str) -> None:
        """Delete a budget (only if in DRAFT or REJECTED state)."""
        budget = self.get_budget(budget_id)
        if budget.state not in (BudgetState.DRAFT, BudgetState.REJECTED):
            raise InvalidStateTransitionError(budget.state, BudgetState.DRAFT)
        del self._budgets[budget_id]
        self._enforcers.pop(budget_id, None)
        self._persist_state()

    # ------------------------------------------------------------------
    # Lifecycle transitions
    # ------------------------------------------------------------------

    def transition(
        self, budget_id: str, to_state: BudgetState, approved_by: str = ""
    ) -> AutonomyBudget:
        """Transition a budget to a new state."""
        budget = self.get_budget(budget_id)
        valid = _VALID_TRANSITIONS.get(budget.state, frozenset())
        if to_state not in valid:
            raise InvalidStateTransitionError(budget.state, to_state)

        budget.state = to_state
        if approved_by:
            budget.approved_by = approved_by

        logger.info(
            "budget_transition id=%s to=%s",
            budget_id,
            to_state.value,
        )
        self._persist_state()
        return budget

    def activate(self, budget_id: str, approved_by: str = "") -> AutonomyBudget:
        """Activate a budget (from DRAFT or PENDING_APPROVAL)."""
        return self.transition(budget_id, BudgetState.ACTIVE, approved_by)

    def suspend(self, budget_id: str) -> AutonomyBudget:
        """Suspend an active budget."""
        return self.transition(budget_id, BudgetState.SUSPENDED)

    def complete(self, budget_id: str) -> AutonomyBudget:
        """Mark a budget as completed."""
        return self.transition(budget_id, BudgetState.COMPLETED)

    # ------------------------------------------------------------------
    # Preflight
    # ------------------------------------------------------------------

    def run_preflight(self, budget_id: str) -> PreflightReport:
        """Run preflight checks on a budget."""
        budget = self.get_budget(budget_id)
        return self._checker.check(budget)

    # ------------------------------------------------------------------
    # Enforcement
    # ------------------------------------------------------------------

    def create_enforcer(self, budget_id: str) -> RuntimeEnforcer:
        """Create a runtime enforcer for an active budget."""
        budget = self.get_budget(budget_id)
        if budget.state != BudgetState.ACTIVE:
            raise InvalidStateTransitionError(budget.state, BudgetState.ACTIVE)
        report = self._checker.check(budget)
        if report.overall != PreflightStatus.PASS:
            raise PreflightFailedError(report)
        enforcer = RuntimeEnforcer(budget)
        self._enforcers[budget_id] = enforcer
        self._persist_state()
        return enforcer

    def get_enforcer(self, budget_id: str) -> RuntimeEnforcer | None:
        """Get the runtime enforcer for a budget."""
        return self._enforcers.get(budget_id)

    def enforce_file(
        self, budget_id: str, path: str, mode: str = "read", lines: int = 0
    ) -> EnforcementResult:
        """Run an enforcer file check and persist resulting mutable state."""
        enforcer = self.get_enforcer(budget_id)
        if enforcer is None:
            raise EnforcerNotFoundError(f"No enforcer for budget: {budget_id}")
        if mode == "write":
            result = enforcer.check_file_write(path, lines=lines)
        else:
            result = enforcer.check_file_read(path)
        self._persist_state()
        return result

    def enforce_command(self, budget_id: str, command: str) -> EnforcementResult:
        """Run an enforcer command check and persist resulting mutable state."""
        enforcer = self.get_enforcer(budget_id)
        if enforcer is None:
            raise EnforcerNotFoundError(f"No enforcer for budget: {budget_id}")
        result = enforcer.check_command(command)
        self._persist_state()
        return result

    def enforce_network(self, budget_id: str, domain: str) -> EnforcementResult:
        """Run an enforcer network check and persist resulting mutable state."""
        enforcer = self.get_enforcer(budget_id)
        if enforcer is None:
            raise EnforcerNotFoundError(f"No enforcer for budget: {budget_id}")
        result = enforcer.check_network(domain)
        self._persist_state()
        return result

    def trigger_escalation(
        self,
        budget_id: str,
        description: str,
        target: str = "",
        urgency: EscalationUrgency = EscalationUrgency.NORMAL,
    ) -> EscalationRecord:
        """Trigger escalation on a budget's enforcer and persist state."""
        enforcer = self.get_enforcer(budget_id)
        if enforcer is None:
            raise EnforcerNotFoundError(f"No enforcer for budget: {budget_id}")
        record = enforcer.trigger_escalation(
            description=description,
            target=target,
            urgency=urgency,
        )
        self._persist_state()
        return record

    # ------------------------------------------------------------------
    # Escalations
    # ------------------------------------------------------------------

    def list_escalations(
        self,
        budget_id: str | None = None,
        unresolved_only: bool = False,
        limit: int = 100,
    ) -> list[EscalationRecord]:
        """List escalation records."""
        # Collect from all enforcers
        all_escalations: list[EscalationRecord] = []
        for enforcer in self._enforcers.values():
            all_escalations.extend(enforcer.escalations)
        # Also include manually stored ones
        all_escalations.extend(self._escalations.values())

        if budget_id is not None:
            all_escalations = [e for e in all_escalations if e.budget_id == budget_id]
        if unresolved_only:
            all_escalations = [e for e in all_escalations if not e.resolved]
        all_escalations.sort(key=lambda e: e.created_at, reverse=True)
        return all_escalations[:limit]

    def acknowledge_escalation(self, escalation_id: str) -> bool:
        """Acknowledge an escalation."""
        for enforcer in self._enforcers.values():
            for esc in enforcer.escalations:
                if esc.escalation_id == escalation_id:
                    esc.acknowledged = True
                    self._persist_state()
                    return True
        found_esc = self._escalations.get(escalation_id)
        if found_esc:
            found_esc.acknowledged = True
            self._persist_state()
            return True
        return False

    def resolve_escalation(self, escalation_id: str) -> bool:
        """Resolve an escalation."""
        for enforcer in self._enforcers.values():
            for esc in enforcer.escalations:
                if esc.escalation_id == escalation_id:
                    esc.resolved = True
                    self._persist_state()
                    return True
        found_esc = self._escalations.get(escalation_id)
        if found_esc:
            found_esc.resolved = True
            self._persist_state()
            return True
        return False
