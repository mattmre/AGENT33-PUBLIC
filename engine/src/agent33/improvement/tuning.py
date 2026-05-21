"""Tuning loop automation for Phase 31 learning thresholds.

Periodically calibrates retention, quality, and intake parameters based on
observed learning signal data, with safety clamping and optional approval gates.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent33.config import Settings
    from agent33.improvement.service import ImprovementService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TuningCycleOutcome(StrEnum):
    """Outcome of a single tuning cycle."""

    APPLIED = "applied"
    GATED = "gated"
    DRY_RUN = "dry_run"
    PROPOSAL_ONLY = "proposal_only"
    SKIPPED = "skipped"
    PENDING_APPROVAL = "pending_approval"


class TuningCycleRecord(BaseModel):
    """Immutable record of one tuning cycle execution."""

    cycle_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    outcome: TuningCycleOutcome = TuningCycleOutcome.SKIPPED
    before_values: dict[str, Any] = Field(default_factory=dict)
    after_values: dict[str, Any] = Field(default_factory=dict)
    deltas: dict[str, Any] = Field(default_factory=dict)
    sample_size: int = 0
    rationale: str = ""
    approved_by: str | None = None
    approved_at: datetime | None = None


class TuningProposalSandboxRecord(TuningCycleRecord):
    """Proposal-only tuning result that cannot mutate production state."""

    outcome: TuningCycleOutcome = TuningCycleOutcome.PROPOSAL_ONLY
    mutation_allowed: bool = False
    production_mutation_attempted: bool = False
    approval_allowed: bool = False
    promotion_required: bool = True
    sandbox_scope: str = "self-improvement-proposal"
    evidence: list[str] = Field(default_factory=list)
    proposed_config_changes: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Safety clamping helpers
# ---------------------------------------------------------------------------

_SEVERITY_ORDER: list[str] = ["low", "medium", "high", "critical"]


def _clamp_delta(
    field: str,
    current: float | int,
    recommended: float | int,
    max_delta: float | int,
) -> tuple[float | int, float | int]:
    """Clamp the change between *current* and *recommended* to *max_delta*.

    Returns ``(new_value, actual_delta)``.
    """
    raw_delta = recommended - current
    if isinstance(current, int) and isinstance(recommended, int):
        clamped_delta = int(max(-max_delta, min(max_delta, raw_delta)))
        return current + clamped_delta, clamped_delta
    clamped_delta_f = float(max(-max_delta, min(max_delta, raw_delta)))
    return round(float(current) + clamped_delta_f, 4), round(clamped_delta_f, 4)


def _clamp_severity(current: str, recommended: str) -> tuple[str, str]:
    """Ensure severity never relaxes below ``medium``.

    Returns ``(new_severity, delta_description)``.
    """
    current_idx = _SEVERITY_ORDER.index(current) if current in _SEVERITY_ORDER else 1
    recommended_idx = _SEVERITY_ORDER.index(recommended) if recommended in _SEVERITY_ORDER else 1
    # Never allow relaxation below medium (index 1)
    final_idx = max(1, recommended_idx)
    # Also don't allow moving more than one step at a time
    if final_idx < current_idx:
        final_idx = max(current_idx - 1, 1)
    elif final_idx > current_idx:
        final_idx = min(current_idx + 1, len(_SEVERITY_ORDER) - 1)
    new_severity = _SEVERITY_ORDER[final_idx]
    delta = f"{current} -> {new_severity}" if new_severity != current else "no change"
    return new_severity, delta


# ---------------------------------------------------------------------------
# ConfigApplyService protocol (optional — used for real config mutation)
# ---------------------------------------------------------------------------


class ConfigApplyService:
    """Optional service for applying tuning changes to live config."""

    def apply(self, request: Any, settings_instance: Any | None = None) -> Any:  # noqa: ANN401
        """Apply config changes. Default is a no-op."""


# ---------------------------------------------------------------------------
# TuningLoopService
# ---------------------------------------------------------------------------

_MAX_HISTORY = 100


class TuningLoopService:
    """Orchestrates periodic calibration of learning thresholds."""

    def __init__(
        self,
        improvement_service: ImprovementService,
        config_apply_service: ConfigApplyService | None = None,
        settings: Settings | None = None,
        *,
        min_sample_size: int | None = None,
    ) -> None:
        self._improvement = improvement_service
        self._config_apply = config_apply_service
        self._settings = settings
        self._history: list[TuningCycleRecord] = []
        # Resolve min sample size: explicit kwarg > settings > default 10
        if min_sample_size is not None:
            self._min_sample_size = min_sample_size
        elif settings is not None:
            self._min_sample_size = settings.improvement_tuning_loop_min_sample_size
        else:
            self._min_sample_size = 10

    # -- public API ----------------------------------------------------------

    def run_cycle(self, dry_run: bool | None = None) -> TuningCycleRecord:
        """Execute one tuning cycle.

        1. Calibrate thresholds from recent learning signals.
        2. Compute clamped deltas with safety constraints.
        3. Decide outcome (SKIPPED / DRY_RUN / PENDING_APPROVAL / APPLIED).
        4. If APPLIED, update the ImprovementService policy and optionally
           push to ConfigApplyService.
        """
        started_at = datetime.now(UTC)

        # Resolve config-level overrides
        effective_dry_run = dry_run
        if effective_dry_run is None and self._settings is not None:
            effective_dry_run = self._settings.improvement_tuning_loop_dry_run
        if effective_dry_run is None:
            effective_dry_run = False

        require_approval = False
        if self._settings is not None:
            require_approval = self._settings.improvement_tuning_loop_require_approval

        max_quality_delta = 0.15
        max_retention_delta = 30
        if self._settings is not None:
            max_quality_delta = self._settings.improvement_tuning_loop_max_quality_delta
            max_retention_delta = self._settings.improvement_tuning_loop_max_retention_delta_days

        # Step 1: Calibrate
        calibration = self._improvement.calibrate_learning_thresholds()

        sample_size = calibration.sample_signals
        policy = self._improvement._persistence_policy

        before_values: dict[str, Any] = {
            "auto_intake_min_quality": policy.auto_intake_min_quality,
            "retention_days": policy.retention_days,
            "auto_intake_max_items": policy.auto_intake_max_items,
            "auto_intake_min_severity": policy.auto_intake_min_severity.value,
        }

        # Step 2: Check minimum sample size
        if sample_size < self._min_sample_size:
            record = TuningCycleRecord(
                started_at=started_at,
                completed_at=datetime.now(UTC),
                outcome=TuningCycleOutcome.SKIPPED,
                before_values=before_values,
                after_values=before_values,
                deltas={},
                sample_size=sample_size,
                rationale=(f"Insufficient sample size ({sample_size} < {self._min_sample_size})."),
            )
            self._store_record(record)
            return record

        # Step 3: Compute clamped deltas
        new_quality, delta_quality = _clamp_delta(
            "auto_intake_min_quality",
            policy.auto_intake_min_quality,
            calibration.recommended_auto_intake_min_quality,
            max_quality_delta,
        )

        current_retention = policy.retention_days if policy.retention_days is not None else 180
        new_retention, delta_retention = _clamp_delta(
            "retention_days",
            current_retention,
            calibration.recommended_retention_days,
            max_retention_delta,
        )
        new_retention = int(new_retention)
        delta_retention = int(delta_retention)

        current_max_items = policy.auto_intake_max_items
        new_max_items, delta_max_items = _clamp_delta(
            "auto_intake_max_items",
            current_max_items,
            calibration.recommended_auto_intake_max_items,
            2,
        )
        new_max_items = int(new_max_items)
        delta_max_items = int(delta_max_items)

        current_severity = policy.auto_intake_min_severity.value
        new_severity, delta_severity = _clamp_severity(
            current_severity,
            calibration.recommended_auto_intake_min_severity,
        )

        deltas: dict[str, Any] = {
            "auto_intake_min_quality": delta_quality,
            "retention_days": delta_retention,
            "auto_intake_max_items": delta_max_items,
            "auto_intake_min_severity": delta_severity,
        }

        after_values: dict[str, Any] = {
            "auto_intake_min_quality": new_quality,
            "retention_days": new_retention,
            "auto_intake_max_items": new_max_items,
            "auto_intake_min_severity": new_severity,
        }

        # Step 4: Skip if no changes
        all_zero = (
            delta_quality == 0
            and delta_retention == 0
            and delta_max_items == 0
            and delta_severity == "no change"
        )
        if all_zero:
            record = TuningCycleRecord(
                started_at=started_at,
                completed_at=datetime.now(UTC),
                outcome=TuningCycleOutcome.SKIPPED,
                before_values=before_values,
                after_values=after_values,
                deltas=deltas,
                sample_size=sample_size,
                rationale="All computed deltas are zero; no changes needed.",
            )
            self._store_record(record)
            return record

        # Step 5: Dry-run
        if effective_dry_run:
            record = TuningCycleRecord(
                started_at=started_at,
                completed_at=datetime.now(UTC),
                outcome=TuningCycleOutcome.DRY_RUN,
                before_values=before_values,
                after_values=after_values,
                deltas=deltas,
                sample_size=sample_size,
                rationale="Dry-run mode; changes not applied.",
            )
            self._store_record(record)
            return record

        # Step 6: Require approval gate
        if require_approval:
            record = TuningCycleRecord(
                started_at=started_at,
                completed_at=datetime.now(UTC),
                outcome=TuningCycleOutcome.PENDING_APPROVAL,
                before_values=before_values,
                after_values=after_values,
                deltas=deltas,
                sample_size=sample_size,
                rationale="Changes require manual approval before applying.",
            )
            self._store_record(record)
            return record

        # Step 7: Apply changes
        self._apply_changes(after_values)

        record = TuningCycleRecord(
            started_at=started_at,
            completed_at=datetime.now(UTC),
            outcome=TuningCycleOutcome.APPLIED,
            before_values=before_values,
            after_values=after_values,
            deltas=deltas,
            sample_size=sample_size,
            rationale="Changes applied successfully.",
        )
        self._store_record(record)
        return record

    def run_proposal_sandbox(self) -> TuningProposalSandboxRecord:
        """Generate a tuning proposal without permitting live mutation."""
        record = self.run_cycle(dry_run=True)
        proposal = TuningProposalSandboxRecord(
            cycle_id=record.cycle_id,
            started_at=record.started_at,
            completed_at=record.completed_at,
            before_values=record.before_values,
            after_values=record.after_values,
            deltas=record.deltas,
            sample_size=record.sample_size,
            rationale=(
                "Proposal-only sandbox; production mutation is disabled and "
                "promotion requires a separate implementation path."
            ),
            evidence=[
                f"sample_size:{record.sample_size}",
                "mutation_allowed:false",
                "source:tuning-loop-calibration",
            ],
            proposed_config_changes=_config_changes_from_values(record.after_values),
        )
        self._history[-1] = proposal
        return proposal

    def approve_cycle(self, cycle_id: str, approved_by: str) -> TuningCycleRecord:
        """Approve a PENDING_APPROVAL cycle, applying its proposed changes."""
        record = self._find_record(cycle_id)
        if record is None:
            raise ValueError(f"Cycle {cycle_id} not found")
        if record.outcome != TuningCycleOutcome.PENDING_APPROVAL:
            raise ValueError(
                f"Cycle {cycle_id} is not pending approval (outcome={record.outcome.value})"
            )
        self._apply_changes(record.after_values)
        record.outcome = TuningCycleOutcome.APPLIED
        record.approved_by = approved_by
        record.approved_at = datetime.now(UTC)
        record.rationale = f"Approved by {approved_by} and applied."
        return record

    def get_history(self, limit: int = 20) -> list[TuningCycleRecord]:
        """Return recent cycle records, newest first."""
        return list(reversed(self._history[-limit:]))

    def get_status(self) -> dict[str, Any]:
        """Return current tuning loop status summary."""
        enabled = False
        dry_run = False
        require_approval = True
        interval_hours = 24.0
        if self._settings is not None:
            enabled = self._settings.improvement_tuning_loop_enabled
            dry_run = self._settings.improvement_tuning_loop_dry_run
            require_approval = self._settings.improvement_tuning_loop_require_approval
            interval_hours = self._settings.improvement_tuning_loop_interval_hours

        last_cycle = self._history[-1] if self._history else None
        return {
            "enabled": enabled,
            "dry_run": dry_run,
            "require_approval": require_approval,
            "interval_hours": interval_hours,
            "total_cycles": len(self._history),
            "last_cycle": last_cycle.model_dump(mode="json") if last_cycle else None,
        }

    # -- internal ------------------------------------------------------------

    def _find_record(self, cycle_id: str) -> TuningCycleRecord | None:
        for record in self._history:
            if record.cycle_id == cycle_id:
                return record
        return None

    def _store_record(self, record: TuningCycleRecord) -> None:
        self._history.append(record)
        if len(self._history) > _MAX_HISTORY:
            self._history = self._history[-_MAX_HISTORY:]

    def _apply_changes(self, after_values: dict[str, Any]) -> None:
        """Push changes to the ImprovementService policy and optional config."""
        from agent33.config_apply import ConfigApplyRequest
        from agent33.improvement.models import LearningSignalSeverity
        from agent33.improvement.service import LearningPersistencePolicy

        policy = self._improvement._persistence_policy
        new_policy = LearningPersistencePolicy(
            dedupe_window_minutes=policy.dedupe_window_minutes,
            retention_days=after_values.get("retention_days", policy.retention_days),
            max_signals=policy.max_signals,
            max_generated_intakes=policy.max_generated_intakes,
            auto_intake_min_quality=after_values.get(
                "auto_intake_min_quality", policy.auto_intake_min_quality
            ),
            auto_intake_min_severity=LearningSignalSeverity(
                after_values.get(
                    "auto_intake_min_severity",
                    policy.auto_intake_min_severity.value,
                )
            ),
            auto_intake_max_items=after_values.get(
                "auto_intake_max_items",
                policy.auto_intake_max_items,
            ),
        )
        self._improvement.update_policy(new_policy)

        if self._config_apply is not None:
            config_changes = _config_changes_from_values(after_values, fallback_policy=policy)
            self._config_apply.apply(
                ConfigApplyRequest(changes=config_changes),
                settings_instance=self._settings,
            )

        logger.info(
            "tuning_cycle_applied",
            extra={"after_values": after_values},
        )


def _config_changes_from_values(
    after_values: dict[str, Any],
    *,
    fallback_policy: Any | None = None,
) -> dict[str, Any]:
    """Translate policy values into config keys without applying them."""
    return {
        "improvement_learning_auto_intake_min_quality": after_values.get(
            "auto_intake_min_quality",
            getattr(fallback_policy, "auto_intake_min_quality", None),
        ),
        "improvement_learning_retention_days": after_values.get(
            "retention_days",
            getattr(fallback_policy, "retention_days", None),
        ),
        "improvement_learning_auto_intake_min_severity": after_values.get(
            "auto_intake_min_severity",
            getattr(getattr(fallback_policy, "auto_intake_min_severity", None), "value", None),
        ),
        "improvement_learning_auto_intake_max_items": after_values.get(
            "auto_intake_max_items",
            getattr(fallback_policy, "auto_intake_max_items", None),
        ),
    }


# ---------------------------------------------------------------------------
# TuningLoopScheduler
# ---------------------------------------------------------------------------


class TuningLoopScheduler:
    """Periodic background scheduler for tuning cycles.

    Follows the same start/stop pattern as ``TrainingScheduler``.
    """

    def __init__(
        self,
        tuning_service: TuningLoopService,
        interval_hours: float = 24.0,
    ) -> None:
        self._service = tuning_service
        self._interval_seconds = interval_hours * 3600.0
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the background loop."""
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "tuning_loop_scheduler_started",
            extra={
                "interval_hours": self._interval_seconds / 3600.0,
            },
        )

    async def stop(self) -> None:
        """Cancel the background loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("tuning_loop_scheduler_stopped")

    async def _loop(self) -> None:
        """Sleep then run cycles indefinitely."""
        while self._running:
            await asyncio.sleep(self._interval_seconds)
            if not self._running:
                break
            try:
                record = self._service.run_cycle()
                logger.info(
                    "tuning_loop_cycle_completed",
                    extra={
                        "cycle_id": record.cycle_id,
                        "outcome": record.outcome.value,
                    },
                )
            except Exception:
                logger.warning("tuning_loop_cycle_failed", exc_info=True)
