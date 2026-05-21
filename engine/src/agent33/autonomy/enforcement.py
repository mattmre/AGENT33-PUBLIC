"""Runtime enforcement for autonomy budgets.

Implements enforcement points EF-01 through EF-08 and stop conditions
SC-01 through SC-10 from ``core/orchestrator/AUTONOMY_ENFORCEMENT.md``.
"""

from __future__ import annotations

import fnmatch
import logging
import re
from typing import Any

from agent33.autonomy.models import (
    AutonomyBudget,
    EnforcementContext,
    EnforcementResult,
    EscalationRecord,
    EscalationUrgency,
    StopAction,
)

logger = logging.getLogger(__name__)


class RuntimeEnforcer:
    """Enforce budget rules at runtime and track consumption."""

    def __init__(self, budget: AutonomyBudget) -> None:
        self._budget = budget
        self._context = EnforcementContext(budget_id=budget.budget_id)
        self._escalations: list[EscalationRecord] = []

    @property
    def context(self) -> EnforcementContext:
        return self._context

    @property
    def escalations(self) -> list[EscalationRecord]:
        return list(self._escalations)

    def snapshot_state(self) -> dict[str, Any]:
        """Return JSON-serializable runtime enforcement state."""
        return {
            "context": self._context.model_dump(mode="json"),
            "escalations": [esc.model_dump(mode="json") for esc in self._escalations],
        }

    def restore_state(
        self,
        *,
        context: dict[str, Any] | None = None,
        escalations: list[dict[str, Any]] | None = None,
    ) -> None:
        """Restore runtime context and escalations from persisted payloads."""
        if context is not None:
            self._context = EnforcementContext.model_validate(context)
        if escalations is not None:
            self._escalations = [EscalationRecord.model_validate(item) for item in escalations]

    # ------------------------------------------------------------------
    # EF-01: File read check
    # ------------------------------------------------------------------

    def check_file_read(self, path: str) -> EnforcementResult:
        """EF-01: Check if file read is allowed."""
        normalized = path.replace("\\", "/")

        # Check deny list first
        for pattern in self._budget.files.deny:
            if fnmatch.fnmatch(normalized, pattern.replace("\\", "/")):
                self._context.add_violation(f"File read denied: {path}")
                return EnforcementResult.BLOCKED

        # If read patterns exist, enforce them
        if self._budget.files.read and not any(
            fnmatch.fnmatch(normalized, p.replace("\\", "/")) for p in self._budget.files.read
        ):
            self._context.add_violation(f"File read not in allowlist: {path}")
            return EnforcementResult.BLOCKED

        return EnforcementResult.ALLOWED

    # ------------------------------------------------------------------
    # EF-02: File write check
    # ------------------------------------------------------------------

    def check_file_write(self, path: str, lines: int = 0) -> EnforcementResult:
        """EF-02: Check if file write is allowed."""
        normalized = path.replace("\\", "/")

        for pattern in self._budget.files.deny:
            if fnmatch.fnmatch(normalized, pattern.replace("\\", "/")):
                self._context.add_violation(f"File write denied: {path}")
                return EnforcementResult.BLOCKED

        if self._budget.files.write and not any(
            fnmatch.fnmatch(normalized, p.replace("\\", "/")) for p in self._budget.files.write
        ):
            self._context.add_violation(f"File write not in allowlist: {path}")
            return EnforcementResult.BLOCKED

        self._context.record_file_modified(lines)

        # EF-07: Files modified limit
        result = self._check_file_limit()
        if result != EnforcementResult.ALLOWED:
            return result

        # EF-08: Lines changed limit
        return self._check_line_limit()

    # ------------------------------------------------------------------
    # EF-03: Command execution check
    # ------------------------------------------------------------------

    def check_command(self, command: str) -> EnforcementResult:
        """EF-03: Check if command execution is allowed."""
        cmd_name = command.split()[0] if command else ""

        # Denied commands
        if cmd_name in self._budget.denied_commands:
            self._context.add_violation(f"Command denied: {cmd_name}")
            return EnforcementResult.BLOCKED

        # Require approval
        if cmd_name in self._budget.require_approval_commands:
            self._context.add_warning(f"Command requires approval: {cmd_name}")
            return EnforcementResult.WARNED

        # Allowed commands (if list is defined, enforce it)
        if self._budget.allowed_commands:
            allowed = False
            for perm in self._budget.allowed_commands:
                if perm.command == cmd_name:
                    # Check args pattern
                    if perm.args_pattern:
                        args = command[len(cmd_name) :].strip()
                        if not re.match(perm.args_pattern, args):
                            continue
                    allowed = True
                    break
            if not allowed:
                self._context.add_violation(f"Command not in allowlist: {cmd_name}")
                return EnforcementResult.BLOCKED

        self._context.record_tool_call()
        return self._check_tool_call_limit()

    # ------------------------------------------------------------------
    # EF-04: Network request check
    # ------------------------------------------------------------------

    def check_network(self, domain: str) -> EnforcementResult:
        """EF-04: Check if network request to domain is allowed."""
        if not self._budget.network.enabled:
            self._context.add_violation("Network access disabled")
            return EnforcementResult.BLOCKED

        domain_lower = domain.lower()

        # Denied domains
        for d in self._budget.network.denied_domains:
            if domain_lower == d.lower() or domain_lower.endswith(f".{d.lower()}"):
                self._context.add_violation(f"Domain denied: {domain}")
                return EnforcementResult.BLOCKED

        # Allowed domains (if list exists)
        if self._budget.network.allowed_domains and not any(
            domain_lower == d.lower() or domain_lower.endswith(f".{d.lower()}")
            for d in self._budget.network.allowed_domains
        ):
            self._context.add_violation(f"Domain not in allowlist: {domain}")
            return EnforcementResult.BLOCKED

        self._context.record_network_request()

        # Network request limit
        if (
            self._budget.network.max_requests > 0
            and self._context.network_requests > self._budget.network.max_requests
        ):
            self._context.add_violation("Network request limit exceeded")
            return EnforcementResult.BLOCKED

        return EnforcementResult.ALLOWED

    # ------------------------------------------------------------------
    # EF-05: Iteration check
    # ------------------------------------------------------------------

    def record_iteration(self) -> EnforcementResult:
        """EF-05: Record an iteration and check limit."""
        self._context.record_iteration()
        if self._context.iterations > self._budget.limits.max_iterations:
            self._context.mark_stopped("SC-05: Max iterations reached")
            self._escalate("Max iterations reached", "orchestrator")
            return EnforcementResult.BLOCKED
        return EnforcementResult.ALLOWED

    # ------------------------------------------------------------------
    # EF-06: Duration check
    # ------------------------------------------------------------------

    def check_duration(self) -> EnforcementResult:
        """EF-06: Check if execution has exceeded max duration."""
        elapsed = self._context.elapsed_minutes()
        if elapsed > self._budget.limits.max_duration_minutes:
            self._context.mark_stopped("SC-06: Max duration exceeded")
            self._escalate("Max duration exceeded", "orchestrator")
            return EnforcementResult.BLOCKED
        return EnforcementResult.ALLOWED

    # ------------------------------------------------------------------
    # Internal limit checks
    # ------------------------------------------------------------------

    def _check_file_limit(self) -> EnforcementResult:
        """EF-07: Check files modified limit."""
        if self._context.files_modified > self._budget.limits.max_files_modified:
            self._context.mark_stopped("SC-07: Max files modified exceeded")
            self._escalate("Max files modified exceeded", "orchestrator")
            return EnforcementResult.BLOCKED
        return EnforcementResult.ALLOWED

    def _check_line_limit(self) -> EnforcementResult:
        """EF-08: Check lines changed limit."""
        if self._context.lines_changed > self._budget.limits.max_lines_changed:
            self._context.mark_stopped("SC-08: Max lines changed exceeded")
            self._escalate("Max lines changed exceeded", "orchestrator")
            return EnforcementResult.BLOCKED
        return EnforcementResult.ALLOWED

    def _check_tool_call_limit(self) -> EnforcementResult:
        """Check tool calls limit."""
        if (
            self._budget.limits.max_tool_calls > 0
            and self._context.tool_calls > self._budget.limits.max_tool_calls
        ):
            self._context.mark_stopped("Max tool calls exceeded")
            return EnforcementResult.BLOCKED
        return EnforcementResult.ALLOWED

    # ------------------------------------------------------------------
    # Stop condition evaluation
    # ------------------------------------------------------------------

    def evaluate_stop_conditions(self) -> list[str]:
        """Evaluate all stop conditions against current context.

        Returns list of triggered stop condition descriptions.
        """
        triggered: list[str] = []

        for sc in self._budget.stop_conditions:
            # Auto-trigger resource-based stop conditions
            desc = sc.description.lower()
            iter_exceeded = self._context.iterations >= self._budget.limits.max_iterations
            dur_exceeded = (
                self._context.elapsed_minutes() >= self._budget.limits.max_duration_minutes
            )
            if "iteration" in desc and iter_exceeded:
                triggered.append(sc.description)
                if sc.action == StopAction.STOP:
                    self._context.mark_stopped(sc.description)
                elif sc.action == StopAction.ESCALATE:
                    self._escalate(
                        sc.description,
                        self._budget.default_escalation_target,
                    )
            elif "duration" in desc and dur_exceeded:
                triggered.append(sc.description)
                if sc.action == StopAction.STOP:
                    self._context.mark_stopped(sc.description)

        return triggered

    # ------------------------------------------------------------------
    # Escalation
    # ------------------------------------------------------------------

    def _escalate(
        self,
        description: str,
        target: str,
        urgency: EscalationUrgency = EscalationUrgency.NORMAL,
    ) -> EscalationRecord:
        """Create an escalation record."""
        record = EscalationRecord(
            budget_id=self._budget.budget_id,
            trigger_description=description,
            target=target,
            urgency=urgency,
        )
        self._escalations.append(record)
        logger.warning(
            "escalation_triggered budget=%s target=%s: %s",
            self._budget.budget_id,
            target,
            description,
        )
        return record

    def trigger_escalation(
        self,
        description: str,
        target: str = "",
        urgency: EscalationUrgency = EscalationUrgency.NORMAL,
    ) -> EscalationRecord:
        """Manually trigger an escalation."""
        if not target:
            target = self._budget.default_escalation_target
        return self._escalate(description, target, urgency)
