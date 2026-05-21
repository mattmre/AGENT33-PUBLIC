"""Scheduled evaluation gates -- cron/interval-driven regression gate enforcement.

Provides periodic evaluation runs that check gate thresholds and detect
regressions automatically, serving as an early-warning monitoring layer.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, Field

from agent33.evaluation.models import (
    GateResult,
    GateType,
    TaskResult,
    TaskRunResult,
)

if TYPE_CHECKING:
    from agent33.evaluation.service import EvaluationService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ScheduleType(StrEnum):
    """Type of schedule trigger."""

    CRON = "cron"
    INTERVAL = "interval"


class ScheduledGateConfig(BaseModel):
    """Configuration for a scheduled evaluation gate."""

    schedule_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    gate_type: GateType = GateType.G_MON
    schedule_type: ScheduleType = ScheduleType.CRON
    cron_expr: str | None = None
    interval_seconds: int | None = None
    task_filter: list[str] | None = None
    auto_baseline: bool = False
    enabled: bool = True


class ScheduledGateResult(BaseModel):
    """Result of a single scheduled gate execution."""

    schedule_id: str
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    gate_result: GateResult = GateResult.PASS
    metrics: dict[str, float] = Field(default_factory=dict)
    regressions_found: int = 0
    executed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None


class ScheduledGateHistory(BaseModel):
    """Bounded history of execution results for a schedule."""

    schedule_id: str
    results: list[ScheduledGateResult] = Field(default_factory=list)
    max_history: int = 100

    def add_result(self, result: ScheduledGateResult) -> None:
        """Append a result, evicting the oldest if at capacity."""
        self.results.append(result)
        if len(self.results) > self.max_history:
            self.results = self.results[-self.max_history :]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ScheduledGateService:
    """Manages scheduled evaluation gate runs via APScheduler.

    Each service instance owns its own ``AsyncIOScheduler`` to avoid coupling
    with the workflow scheduler lifecycle.
    """

    def __init__(
        self,
        evaluation_service: EvaluationService,
        max_schedules: int = 50,
        history_retention: int = 100,
    ) -> None:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        self._evaluation_service = evaluation_service
        self._scheduler = AsyncIOScheduler()
        self._max_schedules = max_schedules
        self._history_retention = history_retention
        self._schedules: dict[str, ScheduledGateConfig] = {}
        self._histories: dict[str, ScheduledGateHistory] = {}
        self._running = False

    # -- lifecycle ------------------------------------------------------------

    async def start(self) -> None:
        """Start the internal APScheduler."""
        if not self._running:
            self._scheduler.start()
            self._running = True
            logger.info("scheduled_gate_service_started")

    async def stop(self) -> None:
        """Shut down the internal APScheduler."""
        if self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            logger.info("scheduled_gate_service_stopped")

    @property
    def running(self) -> bool:
        return self._running

    # -- CRUD -----------------------------------------------------------------

    def create_schedule(self, config: ScheduledGateConfig) -> ScheduledGateConfig:
        """Register a new scheduled gate.

        Raises ``ValueError`` if the schedule parameters are invalid or if
        the maximum number of schedules has been reached.
        """
        if len(self._schedules) >= self._max_schedules:
            raise ValueError(f"Maximum number of schedules ({self._max_schedules}) reached")

        # Validate schedule type vs parameters
        if config.schedule_type == ScheduleType.CRON:
            if not config.cron_expr:
                raise ValueError("cron_expr is required for CRON schedule type")
            if config.interval_seconds is not None:
                raise ValueError("interval_seconds must not be set for CRON schedule type")
            try:
                self._build_cron_trigger(config.cron_expr)
            except ValueError as exc:
                raise ValueError(f"Invalid cron_expr: {config.cron_expr!r}") from exc
        elif config.schedule_type == ScheduleType.INTERVAL:
            if config.interval_seconds is None or config.interval_seconds <= 0:
                raise ValueError(
                    "interval_seconds must be a positive integer for INTERVAL schedule type"
                )
            if config.cron_expr is not None:
                raise ValueError("cron_expr must not be set for INTERVAL schedule type")

        self._schedules[config.schedule_id] = config
        self._histories[config.schedule_id] = ScheduledGateHistory(
            schedule_id=config.schedule_id,
            max_history=self._history_retention,
        )

        # Register with APScheduler if enabled and running
        if config.enabled and self._running:
            self._register_job(config)

        logger.info(
            "scheduled_gate_created id=%s type=%s gate=%s",
            config.schedule_id,
            config.schedule_type.value,
            config.gate_type.value,
        )
        return config

    def remove_schedule(self, schedule_id: str) -> bool:
        """Remove a schedule. Returns True if the schedule existed."""
        if schedule_id not in self._schedules:
            return False

        # Remove from APScheduler (job may not be registered, e.g. disabled schedule)
        with contextlib.suppress(Exception):
            self._scheduler.remove_job(schedule_id)

        del self._schedules[schedule_id]
        self._histories.pop(schedule_id, None)
        logger.info("scheduled_gate_removed id=%s", schedule_id)
        return True

    def list_schedules(self) -> list[ScheduledGateConfig]:
        """Return all registered schedule configurations."""
        return list(self._schedules.values())

    def get_schedule(self, schedule_id: str) -> ScheduledGateConfig | None:
        """Retrieve a schedule by ID."""
        return self._schedules.get(schedule_id)

    # -- execution ------------------------------------------------------------

    async def trigger_now(self, schedule_id: str) -> ScheduledGateResult:
        """Manually trigger a gate execution immediately.

        Raises ``ValueError`` if the schedule does not exist.
        """
        config = self._schedules.get(schedule_id)
        if config is None:
            raise ValueError(f"Schedule not found: {schedule_id}")
        return await self._execute_gate(schedule_id)

    def get_history(
        self,
        schedule_id: str,
        limit: int = 20,
    ) -> list[ScheduledGateResult]:
        """Return recent execution results for a schedule (newest first).

        Returns an empty list if the schedule does not exist.
        """
        history = self._histories.get(schedule_id)
        if history is None:
            return []
        # Return newest first
        return list(reversed(history.results))[:limit]

    # -- internal -------------------------------------------------------------

    def _register_job(self, config: ScheduledGateConfig) -> None:
        """Add an APScheduler job for the given config."""
        if config.schedule_type == ScheduleType.CRON:
            trigger = self._build_cron_trigger(config.cron_expr or "")
            self._scheduler.add_job(
                self._execute_gate,
                trigger=trigger,
                id=config.schedule_id,
                args=[config.schedule_id],
            )
        elif config.schedule_type == ScheduleType.INTERVAL:
            from apscheduler.triggers.interval import IntervalTrigger

            trigger = IntervalTrigger(seconds=config.interval_seconds or 60)
            self._scheduler.add_job(
                self._execute_gate,
                trigger=trigger,
                id=config.schedule_id,
                args=[config.schedule_id],
            )

    @staticmethod
    def _build_cron_trigger(cron_expr: str) -> CronTrigger:
        """Build and validate an APScheduler cron trigger from a 5-field expression."""
        return CronTrigger.from_crontab(cron_expr.strip())

    async def _execute_gate(self, schedule_id: str) -> ScheduledGateResult:
        """Internal callback: run an evaluation gate and record the result."""
        config = self._schedules.get(schedule_id)
        if config is None:
            result = ScheduledGateResult(
                schedule_id=schedule_id,
                gate_result=GateResult.FAIL,
                error="Schedule not found",
            )
            return result

        try:
            # 1. Create an evaluation run
            run = self._evaluation_service.create_run(gate=config.gate_type)

            # 2. Determine tasks for this gate
            task_ids = self._evaluation_service.get_tasks_for_gate(config.gate_type)

            # Apply task filter if specified
            if config.task_filter:
                task_ids = [tid for tid in task_ids if tid in config.task_filter]

            # If no golden tasks for this gate type, use all available tasks
            if not task_ids:
                all_tasks = self._evaluation_service.list_golden_tasks()
                task_ids = [str(t["task_id"]) for t in all_tasks]

            # 3. Generate synthetic results using the evaluation service's
            #    trial evaluator (DeterministicFallbackEvaluator by default)
            task_results: list[TaskRunResult] = []
            for tid in task_ids:
                outcome = await self._evaluation_service._trial_evaluator.evaluate(
                    task_id=tid,
                    agent="scheduled-gate",
                    model="default",
                    skills_enabled=True,
                )
                task_results.append(
                    TaskRunResult(
                        item_id=tid,
                        result=TaskResult.PASS if outcome.success else TaskResult.FAIL,
                        checks_passed=1 if outcome.success else 0,
                        checks_total=1,
                        duration_ms=0,
                    )
                )

            # 4. Submit results to the evaluation service
            completed_run = self._evaluation_service.submit_results(
                run_id=run.run_id,
                task_results=task_results,
            )

            if completed_run is None:
                result = ScheduledGateResult(
                    schedule_id=schedule_id,
                    gate_result=GateResult.FAIL,
                    error="Failed to submit results",
                )
                self._record_result(schedule_id, result)
                return result

            # 5. Extract metrics and gate result
            metrics_dict: dict[str, float] = {}
            for m in completed_run.metrics:
                metrics_dict[m.metric_id.value] = m.value

            gate_result = GateResult.PASS
            if completed_run.gate_report is not None:
                gate_result = completed_run.gate_report.overall

            regressions_found = len(completed_run.regressions)

            # 6. Optionally save as baseline
            if config.auto_baseline and gate_result == GateResult.PASS:
                self._evaluation_service.save_baseline(
                    metrics=completed_run.metrics,
                    task_results=completed_run.task_results,
                    commit_hash="scheduled-gate",
                    branch="",
                )

            result = ScheduledGateResult(
                schedule_id=schedule_id,
                run_id=completed_run.run_id,
                gate_result=gate_result,
                metrics=metrics_dict,
                regressions_found=regressions_found,
            )

            logger.info(
                "scheduled_gate_executed id=%s gate=%s result=%s regressions=%d",
                schedule_id,
                config.gate_type.value,
                gate_result.value,
                regressions_found,
            )

        except Exception as exc:
            result = ScheduledGateResult(
                schedule_id=schedule_id,
                gate_result=GateResult.FAIL,
                error=str(exc),
            )
            logger.error(
                "scheduled_gate_execution_failed id=%s error=%s",
                schedule_id,
                str(exc),
                exc_info=True,
            )

        self._record_result(schedule_id, result)
        return result

    def _record_result(self, schedule_id: str, result: ScheduledGateResult) -> None:
        """Append a result to the schedule's history."""
        history = self._histories.get(schedule_id)
        if history is not None:
            history.add_result(result)
