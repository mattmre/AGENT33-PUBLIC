"""Sync engine with dry-run support.

Implements the sync workflow from ``core/orchestrator/RELEASE_CADENCE.md``
and ``core/orchestrator/distribution/DISTRIBUTION_SYNC_SPEC.md``.
"""

from __future__ import annotations

import fnmatch
import hashlib
import logging
from typing import TYPE_CHECKING

from agent33.release.models import (
    SyncExecution,
    SyncFileResult,
    SyncRule,
    SyncStatus,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


class SyncEngine:
    """Execute sync rules with dry-run support and validation."""

    def __init__(self, on_change: Callable[[], None] | None = None) -> None:
        self._rules: dict[str, SyncRule] = {}
        self._executions: dict[str, SyncExecution] = {}
        self._on_change = on_change

    def _mark_changed(self) -> None:
        if self._on_change is not None:
            self._on_change()

    # ------------------------------------------------------------------
    # Rule management
    # ------------------------------------------------------------------

    def add_rule(self, rule: SyncRule) -> SyncRule:
        """Register a sync rule."""
        self._rules[rule.rule_id] = rule
        self._mark_changed()
        logger.info("sync_rule_added id=%s repo=%s", rule.rule_id, rule.target_repo)
        return rule

    def get_rule(self, rule_id: str) -> SyncRule | None:
        return self._rules.get(rule_id)

    def list_rules(self) -> list[SyncRule]:
        return list(self._rules.values())

    def remove_rule(self, rule_id: str) -> bool:
        if rule_id in self._rules:
            del self._rules[rule_id]
            self._mark_changed()
            return True
        return False

    # ------------------------------------------------------------------
    # State snapshot / restore (used by durable persistence)
    # ------------------------------------------------------------------

    def snapshot_state(self) -> dict[str, dict[str, object]]:
        """Return a serializable snapshot of internal state."""
        return {
            "rules": {
                rule_id: rule.model_dump(mode="json") for rule_id, rule in self._rules.items()
            },
            "executions": {
                exec_id: execution.model_dump(mode="json")
                for exec_id, execution in self._executions.items()
            },
        }

    def restore_state(self, data: dict[str, object]) -> None:
        """Restore internal state from a previously captured snapshot."""
        from pydantic import ValidationError

        rules_payload = data.get("rules", {})
        if isinstance(rules_payload, dict):
            for rule_id, rule_data in rules_payload.items():
                if not isinstance(rule_id, str):
                    continue
                try:
                    self._rules[rule_id] = SyncRule.model_validate(rule_data)
                except ValidationError:
                    logger.warning("sync_rule_restore_failed id=%s", rule_id)

        executions_payload = data.get("executions", {})
        if isinstance(executions_payload, dict):
            for exec_id, exec_data in executions_payload.items():
                if not isinstance(exec_id, str):
                    continue
                try:
                    self._executions[exec_id] = SyncExecution.model_validate(exec_data)
                except ValidationError:
                    logger.warning("sync_execution_restore_failed id=%s", exec_id)

    # ------------------------------------------------------------------
    # File matching
    # ------------------------------------------------------------------

    def match_files(self, rule: SyncRule, available_files: list[str]) -> list[str]:
        """Match available files against a rule's patterns."""
        matched: list[str] = []
        for f in available_files:
            normalized = f.replace("\\", "/")
            # Check source pattern
            if not fnmatch.fnmatch(normalized, rule.source_pattern):
                continue
            # Check include patterns (if specified)
            if rule.include_patterns and not any(
                fnmatch.fnmatch(normalized, p) for p in rule.include_patterns
            ):
                continue
            # Check exclude patterns
            if any(fnmatch.fnmatch(normalized, p) for p in rule.exclude_patterns):
                continue
            matched.append(f)
        return matched

    # ------------------------------------------------------------------
    # Sync execution
    # ------------------------------------------------------------------

    def dry_run(
        self,
        rule_id: str,
        available_files: list[str],
        release_version: str = "",
    ) -> SyncExecution:
        """Execute a dry-run sync (no actual file operations)."""
        rule = self._rules.get(rule_id)
        if rule is None:
            exe = SyncExecution(
                rule_id=rule_id,
                release_version=release_version,
                status=SyncStatus.FAILED,
                dry_run=True,
                errors=[f"Rule not found: {rule_id}"],
            )
            self._executions[exe.execution_id] = exe
            self._mark_changed()
            return exe

        matched = self.match_files(rule, available_files)

        file_results: list[SyncFileResult] = []
        for f in matched:
            target = f"{rule.target_path}/{f.split('/')[-1]}" if rule.target_path else f
            file_results.append(
                SyncFileResult(
                    source_path=f,
                    target_path=target,
                    action="added",
                    checksum_valid=True,
                )
            )

        exe = SyncExecution(
            rule_id=rule_id,
            release_version=release_version,
            status=SyncStatus.DRY_RUN,
            dry_run=True,
            files_added=len(file_results),
            file_results=file_results,
        )
        self._executions[exe.execution_id] = exe
        self._mark_changed()
        logger.info("sync_dry_run rule=%s files=%d", rule_id, len(file_results))
        return exe

    def execute(
        self,
        rule_id: str,
        available_files: list[str],
        release_version: str = "",
    ) -> SyncExecution:
        """Execute a real sync (marks as completed, no actual I/O)."""
        rule = self._rules.get(rule_id)
        if rule is None:
            exe = SyncExecution(
                rule_id=rule_id,
                release_version=release_version,
                status=SyncStatus.FAILED,
                dry_run=False,
                errors=[f"Rule not found: {rule_id}"],
            )
            self._executions[exe.execution_id] = exe
            self._mark_changed()
            return exe

        matched = self.match_files(rule, available_files)

        file_results: list[SyncFileResult] = []
        for f in matched:
            target = f"{rule.target_path}/{f.split('/')[-1]}" if rule.target_path else f
            file_results.append(
                SyncFileResult(
                    source_path=f,
                    target_path=target,
                    action="added",
                    checksum_valid=True,
                )
            )

        from datetime import UTC, datetime

        exe = SyncExecution(
            rule_id=rule_id,
            release_version=release_version,
            status=SyncStatus.COMPLETED,
            dry_run=False,
            files_added=len(file_results),
            file_results=file_results,
            completed_at=datetime.now(UTC),
        )
        self._executions[exe.execution_id] = exe
        self._mark_changed()
        logger.info("sync_executed rule=%s files=%d", rule_id, len(file_results))
        return exe

    # ------------------------------------------------------------------
    # Execution queries
    # ------------------------------------------------------------------

    def get_execution(self, execution_id: str) -> SyncExecution | None:
        return self._executions.get(execution_id)

    def list_executions(
        self,
        rule_id: str | None = None,
        limit: int = 50,
    ) -> list[SyncExecution]:
        results = list(self._executions.values())
        if rule_id is not None:
            results = [e for e in results if e.rule_id == rule_id]
        results.sort(key=lambda e: e.started_at, reverse=True)
        return results[:limit]

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def compute_checksum(content: str) -> str:
        """Compute SHA-256 checksum of content."""
        return hashlib.sha256(content.encode()).hexdigest()

    def validate_execution(self, execution_id: str) -> list[str]:
        """Validate a completed sync execution. Returns list of issues."""
        exe = self._executions.get(execution_id)
        if exe is None:
            return [f"Execution not found: {execution_id}"]

        issues: list[str] = []
        for fr in exe.file_results:
            if not fr.checksum_valid:
                issues.append(f"Checksum invalid: {fr.source_path}")
        return issues
