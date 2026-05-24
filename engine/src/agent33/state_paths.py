"""Approved durable state roots for repo-local and user-local runtime data."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal


class StateRootKind(StrEnum):
    """Canonical durable state roots used by the runtime."""

    APP_ROOT = "app_root"
    APP_VAR = "app_var"
    USER_STATE = "user_state"


class StatePathError(ValueError):
    """Raised when a path escapes the approved durable state roots."""


StateAuditStatus = Literal["ok", "warning", "error"]


@dataclass(frozen=True, slots=True)
class RuntimeStatePathAuditItem:
    """Audit result for one restart-sensitive runtime state path."""

    id: str
    label: str
    raw_path: str
    resolved_path: str
    root: StateRootKind | None
    status: StateAuditStatus
    restart_safe: bool
    required: bool
    message: str


@dataclass(frozen=True, slots=True)
class RuntimeStatePathAudit:
    """Restart-safety audit across configured durable runtime state paths."""

    overall: StateAuditStatus
    items: tuple[RuntimeStatePathAuditItem, ...]

    @property
    def restart_safe(self) -> bool:
        return self.overall == "ok"


@dataclass(frozen=True, slots=True)
class RuntimeStatePathSpec:
    """Configured state path that should survive restarts or be called out."""

    id: str
    label: str
    setting_name: str
    required: bool = True


DEFAULT_RUNTIME_STATE_PATH_SPECS: tuple[RuntimeStatePathSpec, ...] = (
    RuntimeStatePathSpec(
        "component-security-scan-store",
        "Component security scan store",
        "component_security_scan_store_db_path",
        required=False,
    ),
    RuntimeStatePathSpec("p69b-paused-invocations", "Paused invocation approvals", "p69b_db_path"),
    RuntimeStatePathSpec("ingestion", "Ingestion store", "ingestion_db_path"),
    RuntimeStatePathSpec("ingestion-mailbox", "Ingestion mailbox", "ingestion_mailbox_db_path"),
    RuntimeStatePathSpec("ingestion-journal", "Ingestion journal", "ingestion_journal_db_path"),
    RuntimeStatePathSpec(
        "ingestion-task-metrics",
        "Ingestion task metrics",
        "ingestion_task_metrics_db_path",
    ),
    RuntimeStatePathSpec(
        "ingestion-notification-hooks",
        "Ingestion notification hooks",
        "ingestion_notification_hooks_db_path",
    ),
    RuntimeStatePathSpec("outcomes", "Outcomes store", "outcomes_db_path"),
    RuntimeStatePathSpec("ppack-ab", "P-PACK experiment store", "ppack_v3_ab_db_path"),
    RuntimeStatePathSpec("plugin-lifecycle", "Plugin lifecycle state", "plugin_state_store_path"),
    RuntimeStatePathSpec(
        "skillsbench-runs",
        "SkillsBench artifact runs",
        "skillsbench_storage_path",
    ),
    RuntimeStatePathSpec(
        "pack-marketplace-cache",
        "Pack marketplace cache",
        "pack_marketplace_cache_dir",
    ),
    RuntimeStatePathSpec(
        "pack-rollback-archive",
        "Pack rollback archive",
        "pack_rollback_archive_dir",
    ),
    RuntimeStatePathSpec("sqlite-memory", "SQLite memory store", "sqlite_memory_db_path"),
    RuntimeStatePathSpec("phase23-auth", "Phase 23 auth lifecycle store", "phase23_auth_db_path"),
    RuntimeStatePathSpec(
        "phase23-workspaces",
        "Phase 23 workspace lifecycle store",
        "phase23_workspace_db_path",
    ),
    RuntimeStatePathSpec(
        "synthetic-environment-bundles",
        "Synthetic environment bundles",
        "synthetic_env_bundle_persistence_path",
    ),
    RuntimeStatePathSpec(
        "workflow-run-archive",
        "Workflow run archive",
        "workflow_run_archive_dir",
    ),
    RuntimeStatePathSpec("process-manager", "Process manager logs", "process_manager_log_dir"),
    RuntimeStatePathSpec("backups", "Backup archives", "backup_dir"),
    RuntimeStatePathSpec(
        "improvement-learning-file",
        "Improvement learning file store",
        "improvement_learning_persistence_path",
        required=False,
    ),
    RuntimeStatePathSpec(
        "improvement-learning-db",
        "Improvement learning DB store",
        "improvement_learning_persistence_db_path",
        required=False,
    ),
    RuntimeStatePathSpec(
        "evaluation-ctrf",
        "Evaluation CTRF reports",
        "evaluation_ctrf_output_dir",
    ),
    RuntimeStatePathSpec(
        "operator-sessions",
        "Operator session checkpoints",
        "operator_session_base_dir",
    ),
    RuntimeStatePathSpec("trajectory-output", "Agent trajectory output", "trajectory_output_dir"),
)


@dataclass(frozen=True, slots=True)
class RuntimeStatePaths:
    """Resolve and classify paths against the approved runtime roots."""

    app_root: Path
    app_var_dir: Path
    user_state_dir: Path

    @classmethod
    def from_app_root(
        cls,
        app_root: Path,
        *,
        home_dir: Path | None = None,
    ) -> RuntimeStatePaths:
        resolved_app_root = app_root.resolve()
        resolved_home = (home_dir or Path.home()).expanduser().resolve()
        return cls(
            app_root=resolved_app_root,
            app_var_dir=(resolved_app_root / "var").resolve(),
            user_state_dir=(resolved_home / ".agent33").resolve(),
        )

    @property
    def approved_roots(self) -> tuple[Path, Path, Path]:
        """Return approved durable roots from most-specific to least-specific."""
        return (self.app_var_dir, self.user_state_dir, self.app_root)

    def resolve(self, raw_path: str | Path) -> Path:
        """Resolve a candidate path relative to the repo root when needed."""
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = self.app_root / candidate
        return candidate.resolve()

    def classify(self, raw_path: str | Path) -> StateRootKind | None:
        """Classify a resolved path by its durable root."""
        resolved = self.resolve(raw_path)
        if resolved.is_relative_to(self.app_var_dir):
            return StateRootKind.APP_VAR
        if resolved.is_relative_to(self.user_state_dir):
            return StateRootKind.USER_STATE
        if resolved.is_relative_to(self.app_root):
            return StateRootKind.APP_ROOT
        return None

    def ensure_approved(self, raw_path: str | Path) -> Path:
        """Return the resolved path or raise when it escapes approved roots."""
        resolved = self.resolve(raw_path)
        if self.classify(resolved) is None:
            approved = ", ".join(str(root) for root in self.approved_roots)
            raise StatePathError(
                f"Path '{resolved}' is outside approved runtime roots: {approved}"
            )
        return resolved

    def resolve_approved(self, raw_path: str | Path) -> Path:
        """Resolve a candidate path and require it to stay inside approved roots."""
        return self.ensure_approved(raw_path)

    def default_user_state_dir(self, name: str) -> Path:
        """Return a directory under the canonical user-local state root."""
        resolved = (self.user_state_dir / name).resolve()
        if not resolved.is_relative_to(self.user_state_dir):
            raise StatePathError(
                f"User state path '{resolved}' escapes user_state_dir '{self.user_state_dir}'"
            )
        return resolved

    def audit_configured_state_paths(
        self,
        settings: Any,
        *,
        specs: tuple[RuntimeStatePathSpec, ...] = DEFAULT_RUNTIME_STATE_PATH_SPECS,
    ) -> RuntimeStatePathAudit:
        """Audit configured restart-sensitive state paths against approved roots."""
        items = tuple(self._audit_spec(settings, spec) for spec in specs)
        if any(item.status == "error" for item in items):
            overall: StateAuditStatus = "error"
        elif any(item.status == "warning" for item in items):
            overall = "warning"
        else:
            overall = "ok"
        return RuntimeStatePathAudit(overall=overall, items=items)

    def _audit_spec(
        self,
        settings: Any,
        spec: RuntimeStatePathSpec,
    ) -> RuntimeStatePathAuditItem:
        raw_value = str(getattr(settings, spec.setting_name, "") or "").strip()
        if not raw_value:
            if spec.setting_name == "operator_session_base_dir":
                raw_value = str(self.default_user_state_dir("sessions"))
            else:
                return RuntimeStatePathAuditItem(
                    id=spec.id,
                    label=spec.label,
                    raw_path="",
                    resolved_path="",
                    root=None,
                    status="error" if spec.required else "warning",
                    restart_safe=False,
                    required=spec.required,
                    message=(
                        "Required restart-sensitive state path is not configured."
                        if spec.required
                        else "Optional state path is not configured."
                    ),
                )

        resolved = self.resolve(raw_value)
        root = self.classify(resolved)
        if root is None:
            return RuntimeStatePathAuditItem(
                id=spec.id,
                label=spec.label,
                raw_path=raw_value,
                resolved_path=str(resolved),
                root=None,
                status="error",
                restart_safe=False,
                required=spec.required,
                message="Path escapes approved runtime state roots.",
            )
        return RuntimeStatePathAuditItem(
            id=spec.id,
            label=spec.label,
            raw_path=raw_value,
            resolved_path=str(resolved),
            root=root,
            status="ok",
            restart_safe=True,
            required=spec.required,
            message="Path is restart-safe and inside an approved runtime state root.",
        )
