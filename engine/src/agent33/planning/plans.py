"""Lightweight plan and replanning contracts."""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent33.services.orchestration_state import OrchestrationStateStore

logger = logging.getLogger(__name__)

_NAMESPACE = "planner"


class PlanRisk(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class PlanAction(BaseModel):
    action_id: str
    title: str
    preconditions: list[str] = Field(default_factory=list)
    cost: int = 1
    risk: PlanRisk = PlanRisk.NORMAL


class Plan(BaseModel):
    plan_id: str
    objective: str
    actions: list[PlanAction] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)


class ReplanTrigger(StrEnum):
    BLOCKER_ADDED = "blocker_added"
    COST_EXCEEDED = "cost_exceeded"
    RISK_ESCALATED = "risk_escalated"
    ACTION_FAILED = "action_failed"


class ReplanEvent(BaseModel):
    trigger: ReplanTrigger
    reason: str
    action_id: str = ""
    severity: PlanRisk = PlanRisk.NORMAL


class PlanAssessment(BaseModel):
    total_cost: int
    highest_risk: PlanRisk
    blockers: list[str] = Field(default_factory=list)
    ready_action_ids: list[str] = Field(default_factory=list)


class PlanSummary(BaseModel):
    plan: Plan
    assessment: PlanAssessment
    next_actions: list[PlanAction] = Field(default_factory=list)


class ReplanDecision(BaseModel):
    should_replan: bool
    triggers: list[ReplanTrigger] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    action_ids: list[str] = Field(default_factory=list)


def ready_actions(plan: Plan) -> list[PlanAction]:
    return [action for action in plan.actions if not action.preconditions]


def should_replan(events: list[ReplanEvent]) -> bool:
    return evaluate_replan(events).should_replan


def evaluate_replan(events: list[ReplanEvent]) -> ReplanDecision:
    triggering_events = [
        event
        for event in events
        if event.trigger
        in {
            ReplanTrigger.BLOCKER_ADDED,
            ReplanTrigger.COST_EXCEEDED,
            ReplanTrigger.RISK_ESCALATED,
            ReplanTrigger.ACTION_FAILED,
        }
    ]
    return ReplanDecision(
        should_replan=bool(triggering_events),
        triggers=[event.trigger for event in triggering_events],
        reasons=[event.reason for event in triggering_events],
        action_ids=[event.action_id for event in triggering_events if event.action_id],
    )


def assess_plan(plan: Plan) -> PlanAssessment:
    risk_order = {
        PlanRisk.LOW: 0,
        PlanRisk.NORMAL: 1,
        PlanRisk.HIGH: 2,
        PlanRisk.CRITICAL: 3,
    }
    highest_risk = max(
        (action.risk for action in plan.actions),
        key=lambda risk: risk_order[risk],
        default=PlanRisk.LOW,
    )
    return PlanAssessment(
        total_cost=sum(action.cost for action in plan.actions),
        highest_risk=highest_risk,
        blockers=list(plan.blockers),
        ready_action_ids=[action.action_id for action in ready_actions(plan)],
    )


class PlannerService:
    def __init__(
        self,
        *,
        state_store: OrchestrationStateStore | None = None,
    ) -> None:
        self._state_store = state_store
        self._plans: dict[str, Plan] = {}
        if state_store is not None:
            self._load_state()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _persist_state(self) -> None:
        if self._state_store is None:
            return
        self._state_store.write_namespace(
            _NAMESPACE,
            {"plans": [p.model_dump(mode="json") for p in self._plans.values()]},
        )

    def _load_state(self) -> None:
        if self._state_store is None:
            return
        data = self._state_store.read_namespace(_NAMESPACE)
        if not data:
            return
        for raw in data.get("plans", []):
            try:
                plan = Plan.model_validate(raw)
                self._plans[plan.plan_id] = plan
            except Exception:
                logger.exception("planner_load_state_parse_error", extra={"raw": raw})
        logger.debug("planner_state_loaded count=%s", len(self._plans))

    # ------------------------------------------------------------------
    # Plan CRUD
    # ------------------------------------------------------------------

    def create_plan(
        self,
        *,
        plan_id: str,
        objective: str,
        actions: list[PlanAction],
        blockers: list[str] | None = None,
    ) -> PlanSummary:
        plan = Plan(
            plan_id=plan_id,
            objective=objective,
            actions=actions,
            blockers=blockers or [],
        )
        self._plans[plan_id] = plan
        self._persist_state()
        return self.summarize(plan)

    def get_plan(self, plan_id: str) -> Plan | None:
        return self._plans.get(plan_id)

    def list_plans(self) -> list[Plan]:
        return list(self._plans.values())

    def delete_plan(self, plan_id: str) -> bool:
        if plan_id not in self._plans:
            return False
        del self._plans[plan_id]
        self._persist_state()
        return True

    def summarize(self, plan: Plan) -> PlanSummary:
        return PlanSummary(
            plan=plan,
            assessment=assess_plan(plan),
            next_actions=ready_actions(plan),
        )

    def evaluate_replan(self, events: list[ReplanEvent]) -> ReplanDecision:
        return evaluate_replan(events)
