"""Sync engine with dry-run support.

Implements the sync workflow from ``core/orchestrator/RELEASE_CADENCE.md``
and ``core/orchestrator/distribution/DISTRIBUTION_SYNC_SPEC.md``.
"""

from __future__ import annotations

import fnmatch
import hashlib
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
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

    def _record_failed_execution(
        self,
        *,
        rule_id: str,
        release_version: str,
        dry_run: bool,
        errors: list[str],
        io_mode: str = "failed",
        approved_dry_run_execution_id: str = "",
        source_root: str = "",
        target_root: str = "",
    ) -> SyncExecution:
        exe = SyncExecution(
            rule_id=rule_id,
            release_version=release_version,
            status=SyncStatus.FAILED,
            dry_run=dry_run,
            io_mode=io_mode,
            approved_dry_run_execution_id=approved_dry_run_execution_id,
            source_root=source_root,
            target_root=target_root,
            errors=errors,
            completed_at=datetime.now(UTC),
        )
        self._executions[exe.execution_id] = exe
        self._mark_changed()
        return exe

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

    @staticmethod
    def _target_path(rule: SyncRule, source_path: str) -> str:
        normalized = source_path.replace("\\", "/")
        if not rule.target_path:
            return normalized
        target_root = rule.target_path.strip("/")
        return f"{target_root}/{PurePosixPath(normalized).name}"

    @staticmethod
    def _validate_relative_path(path: str, *, label: str) -> str | None:
        candidate = Path(path.replace("\\", "/"))
        if candidate.is_absolute() or ".." in candidate.parts:
            return f"{label} must be a relative path inside the configured sync root: {path}"
        return None

    @staticmethod
    def compute_file_checksum(path: Path) -> str:
        """Compute SHA-256 checksum of file bytes."""
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _validate_execute_approval(
        self,
        *,
        rule_id: str,
        release_version: str,
        matched_files: list[str],
        approved_dry_run_execution_id: str,
    ) -> list[str]:
        if not approved_dry_run_execution_id:
            return ["Real sync requires approved_dry_run_execution_id from a prior dry run."]

        approved = self._executions.get(approved_dry_run_execution_id)
        if approved is None:
            return [f"Approved dry-run execution not found: {approved_dry_run_execution_id}"]
        if approved.status != SyncStatus.DRY_RUN or not approved.dry_run:
            return ["Approved execution must be a successful dry-run result."]
        if approved.rule_id != rule_id:
            return ["Approved dry-run rule_id does not match this sync rule."]
        if approved.release_version != release_version:
            return ["Approved dry-run release_version does not match this execution."]

        approved_sources = {
            result.source_path.replace("\\", "/") for result in approved.file_results
        }
        matched_sources = {path.replace("\\", "/") for path in matched_files}
        if approved_sources != matched_sources:
            return ["Approved dry-run file set does not match this execution request."]
        return []

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
            return self._record_failed_execution(
                rule_id=rule_id,
                release_version=release_version,
                dry_run=True,
                errors=[f"Rule not found: {rule_id}"],
            )

        matched = self.match_files(rule, available_files)

        file_results: list[SyncFileResult] = []
        for f in matched:
            file_results.append(
                SyncFileResult(
                    source_path=f,
                    target_path=self._target_path(rule, f),
                    action="added",
                    checksum_valid=True,
                )
            )

        exe = SyncExecution(
            rule_id=rule_id,
            release_version=release_version,
            status=SyncStatus.DRY_RUN,
            dry_run=True,
            io_mode="dry_run",
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
        *,
        approved_dry_run_execution_id: str = "",
        source_root: str = "",
        target_root: str = "",
        confirm_real_io: bool = False,
    ) -> SyncExecution:
        """Execute a real local-file sync after an approved dry run.

        Phase 19 intentionally fails closed when callers omit a dry-run
        approval or concrete source/target roots. Older simulation-only
        behavior is preserved only as dry-run evidence, never as completed
        execution.
        """
        rule = self._rules.get(rule_id)
        if rule is None:
            return self._record_failed_execution(
                rule_id=rule_id,
                release_version=release_version,
                dry_run=False,
                io_mode="local_copy",
                approved_dry_run_execution_id=approved_dry_run_execution_id,
                source_root=source_root,
                target_root=target_root,
                errors=[f"Rule not found: {rule_id}"],
            )

        matched = self.match_files(rule, available_files)
        errors = self._validate_execute_approval(
            rule_id=rule_id,
            release_version=release_version,
            matched_files=matched,
            approved_dry_run_execution_id=approved_dry_run_execution_id,
        )
        if not confirm_real_io:
            errors.append("Real sync requires confirm_real_io=true.")
        if not source_root or not target_root:
            errors.append("Real sync requires source_root and target_root.")
        if errors:
            return self._record_failed_execution(
                rule_id=rule_id,
                release_version=release_version,
                dry_run=False,
                io_mode="local_copy",
                approved_dry_run_execution_id=approved_dry_run_execution_id,
                source_root=source_root,
                target_root=target_root,
                errors=errors,
            )

        source_base = Path(source_root).expanduser().resolve()
        target_base = Path(target_root).expanduser().resolve()
        if not source_base.is_dir():
            return self._record_failed_execution(
                rule_id=rule_id,
                release_version=release_version,
                dry_run=False,
                io_mode="local_copy",
                approved_dry_run_execution_id=approved_dry_run_execution_id,
                source_root=str(source_base),
                target_root=str(target_base),
                errors=[f"source_root is not a directory: {source_base}"],
            )
        if target_base.exists() and not target_base.is_dir():
            return self._record_failed_execution(
                rule_id=rule_id,
                release_version=release_version,
                dry_run=False,
                io_mode="local_copy",
                approved_dry_run_execution_id=approved_dry_run_execution_id,
                source_root=str(source_base),
                target_root=str(target_base),
                errors=[f"target_root is not a directory: {target_base}"],
            )

        file_results: list[SyncFileResult] = []
        planned_ops: list[tuple[str, Path, Path]] = []
        for f in matched:
            normalized = f.replace("\\", "/")
            target_relative = self._target_path(rule, normalized)
            path_error = self._validate_relative_path(normalized, label="source_path")
            if path_error is not None:
                errors.append(path_error)
                continue
            target_error = self._validate_relative_path(target_relative, label="target_path")
            if target_error is not None:
                errors.append(target_error)
                continue
            source_path = (source_base / normalized).resolve()
            target_path = (target_base / target_relative).resolve()
            if not source_path.is_relative_to(source_base):
                errors.append(f"source_path escapes source_root: {normalized}")
                continue
            if not target_path.is_relative_to(target_base):
                errors.append(f"target_path escapes target_root: {target_relative}")
                continue
            if not source_path.is_file():
                errors.append(f"source_path is not a file: {normalized}")
                continue
            planned_ops.append((normalized, source_path, target_path))

        if errors:
            return self._record_failed_execution(
                rule_id=rule_id,
                release_version=release_version,
                dry_run=False,
                io_mode="local_copy",
                approved_dry_run_execution_id=approved_dry_run_execution_id,
                source_root=str(source_base),
                target_root=str(target_base),
                errors=errors,
            )

        files_added = 0
        files_modified = 0
        for normalized, source_path, target_path in planned_ops:
            source_checksum = self.compute_file_checksum(source_path)
            if target_path.exists():
                target_checksum_before = self.compute_file_checksum(target_path)
                action = "unchanged" if target_checksum_before == source_checksum else "modified"
            else:
                action = "added"
            if action != "unchanged":
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)
            target_checksum = self.compute_file_checksum(target_path)
            checksum_valid = not rule.validate_checksum or source_checksum == target_checksum
            if action == "added":
                files_added += 1
            elif action == "modified":
                files_modified += 1
            file_results.append(
                SyncFileResult(
                    source_path=normalized,
                    target_path=str(target_path.relative_to(target_base)).replace("\\", "/"),
                    action=action,
                    checksum_valid=checksum_valid,
                    source_checksum=source_checksum,
                    target_checksum=target_checksum,
                )
            )
            if not checksum_valid:
                errors.append(f"Checksum invalid after copy: {normalized}")

        exe = SyncExecution(
            rule_id=rule_id,
            release_version=release_version,
            status=SyncStatus.FAILED if errors else SyncStatus.COMPLETED,
            dry_run=False,
            io_mode="local_copy",
            approved_dry_run_execution_id=approved_dry_run_execution_id,
            source_root=str(source_base),
            target_root=str(target_base),
            files_added=files_added,
            files_modified=files_modified,
            file_results=file_results,
            errors=errors,
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
