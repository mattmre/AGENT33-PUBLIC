"""Preflight checker for autonomy budgets.

Implements PF-01 through PF-10 from ``core/orchestrator/AUTONOMY_ENFORCEMENT.md``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from agent33.autonomy.models import (
    AutonomyBudget,
    BudgetState,
    PreflightCheck,
    PreflightReport,
    PreflightStatus,
)

logger = logging.getLogger(__name__)


class PreflightChecker:
    """Run preflight checks on an autonomy budget before execution."""

    def check(self, budget: AutonomyBudget) -> PreflightReport:
        """Run all 10 preflight checks and return a report."""
        checks = [
            self._pf01_budget_exists(budget),
            self._pf02_budget_valid(budget),
            self._pf03_budget_not_expired(budget),
            self._pf04_scope_defined(budget),
            self._pf05_files_scoped(budget),
            self._pf06_commands_scoped(budget),
            self._pf07_network_scoped(budget),
            self._pf08_limits_set(budget),
            self._pf09_stop_conditions(budget),
            self._pf10_escalation_path(budget),
        ]

        # Overall status: FAIL if any FAIL, WARN if any WARN, PASS otherwise
        overall = PreflightStatus.PASS
        for c in checks:
            if c.status == PreflightStatus.FAIL:
                overall = PreflightStatus.FAIL
                break
            if c.status == PreflightStatus.WARN:
                overall = PreflightStatus.WARN

        report = PreflightReport(
            budget_id=budget.budget_id,
            overall=overall,
            checks=checks,
        )

        logger.info(
            "preflight_complete budget=%s overall=%s",
            budget.budget_id,
            overall.value,
        )
        return report

    def _pf01_budget_exists(self, budget: AutonomyBudget) -> PreflightCheck:
        """PF-01: Budget exists and has an ID."""
        if not budget.budget_id:
            return PreflightCheck(
                check_id="PF-01",
                name="Budget exists",
                status=PreflightStatus.FAIL,
                message="Budget has no ID",
            )
        return PreflightCheck(
            check_id="PF-01",
            name="Budget exists",
            status=PreflightStatus.PASS,
        )

    def _pf02_budget_valid(self, budget: AutonomyBudget) -> PreflightCheck:
        """PF-02: Budget is in a valid state for execution."""
        if budget.state != BudgetState.ACTIVE:
            return PreflightCheck(
                check_id="PF-02",
                name="Budget valid",
                status=PreflightStatus.FAIL,
                message=f"Budget state is {budget.state.value}, must be active",
            )
        return PreflightCheck(
            check_id="PF-02",
            name="Budget valid",
            status=PreflightStatus.PASS,
        )

    def _pf03_budget_not_expired(self, budget: AutonomyBudget) -> PreflightCheck:
        """PF-03: Budget has not expired."""
        if budget.expires_at is not None and budget.expires_at < datetime.now(UTC):
            return PreflightCheck(
                check_id="PF-03",
                name="Budget not expired",
                status=PreflightStatus.FAIL,
                message="Budget has expired",
            )
        return PreflightCheck(
            check_id="PF-03",
            name="Budget not expired",
            status=PreflightStatus.PASS,
        )

    def _pf04_scope_defined(self, budget: AutonomyBudget) -> PreflightCheck:
        """PF-04: In-scope and out-of-scope are defined."""
        if not budget.in_scope:
            return PreflightCheck(
                check_id="PF-04",
                name="Scope defined",
                status=PreflightStatus.FAIL,
                message="No in_scope items defined",
            )
        return PreflightCheck(
            check_id="PF-04",
            name="Scope defined",
            status=PreflightStatus.PASS,
        )

    def _pf05_files_scoped(self, budget: AutonomyBudget) -> PreflightCheck:
        """PF-05: File read/write patterns are defined."""
        if not budget.files.read and not budget.files.write:
            return PreflightCheck(
                check_id="PF-05",
                name="Files scoped",
                status=PreflightStatus.WARN,
                message="No file read/write patterns defined",
            )
        return PreflightCheck(
            check_id="PF-05",
            name="Files scoped",
            status=PreflightStatus.PASS,
        )

    def _pf06_commands_scoped(self, budget: AutonomyBudget) -> PreflightCheck:
        """PF-06: Command allowlist is defined."""
        if not budget.allowed_commands:
            return PreflightCheck(
                check_id="PF-06",
                name="Commands scoped",
                status=PreflightStatus.WARN,
                message="No command allowlist defined",
            )
        return PreflightCheck(
            check_id="PF-06",
            name="Commands scoped",
            status=PreflightStatus.PASS,
        )

    def _pf07_network_scoped(self, budget: AutonomyBudget) -> PreflightCheck:
        """PF-07: Network permissions are explicit."""
        if budget.network.enabled and not budget.network.allowed_domains:
            return PreflightCheck(
                check_id="PF-07",
                name="Network scoped",
                status=PreflightStatus.WARN,
                message="Network enabled but no domains specified",
            )
        return PreflightCheck(
            check_id="PF-07",
            name="Network scoped",
            status=PreflightStatus.PASS,
        )

    def _pf08_limits_set(self, budget: AutonomyBudget) -> PreflightCheck:
        """PF-08: Resource limits are configured."""
        limits = budget.limits
        if limits.max_iterations <= 0 or limits.max_duration_minutes <= 0:
            return PreflightCheck(
                check_id="PF-08",
                name="Limits set",
                status=PreflightStatus.WARN,
                message="Iteration or duration limit not set",
            )
        return PreflightCheck(
            check_id="PF-08",
            name="Limits set",
            status=PreflightStatus.PASS,
        )

    def _pf09_stop_conditions(self, budget: AutonomyBudget) -> PreflightCheck:
        """PF-09: Stop conditions are defined."""
        if not budget.stop_conditions:
            return PreflightCheck(
                check_id="PF-09",
                name="Stop conditions",
                status=PreflightStatus.WARN,
                message="No stop conditions defined",
            )
        return PreflightCheck(
            check_id="PF-09",
            name="Stop conditions",
            status=PreflightStatus.PASS,
        )

    def _pf10_escalation_path(self, budget: AutonomyBudget) -> PreflightCheck:
        """PF-10: Escalation path is defined."""
        if not budget.escalation_triggers and not budget.default_escalation_target:
            return PreflightCheck(
                check_id="PF-10",
                name="Escalation path",
                status=PreflightStatus.WARN,
                message="No escalation triggers or default target",
            )
        return PreflightCheck(
            check_id="PF-10",
            name="Escalation path",
            status=PreflightStatus.PASS,
        )
