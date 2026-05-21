from __future__ import annotations

from agent33.planning.deferred_surfaces import (
    DeferredSurface,
    DeferredSurfaceDecision,
    active_deferred_surfaces,
    deferred_surface_actions,
)
from agent33.planning.plans import (
    Plan,
    PlanAction,
    PlannerService,
    PlanRisk,
    ReplanEvent,
    ReplanTrigger,
    assess_plan,
    evaluate_replan,
    ready_actions,
    should_replan,
)


def test_lightweight_planner_returns_ready_actions() -> None:
    plan = Plan(
        plan_id="p1",
        objective="ship slice",
        actions=[
            PlanAction(action_id="ready", title="Ready action"),
            PlanAction(
                action_id="blocked",
                title="Blocked action",
                preconditions=["ready"],
            ),
        ],
    )

    assert [action.action_id for action in ready_actions(plan)] == ["ready"]


def test_replanner_triggers_on_events() -> None:
    event = ReplanEvent(
        trigger=ReplanTrigger.ACTION_FAILED,
        reason="local validation failed",
        action_id="ready",
    )

    assert should_replan([event]) is True
    assert should_replan([]) is False


def test_replanner_decision_reports_triggers_and_reasons() -> None:
    events = [
        ReplanEvent(
            trigger=ReplanTrigger.BLOCKER_ADDED,
            reason="approval needed",
        ),
        ReplanEvent(
            trigger=ReplanTrigger.ACTION_FAILED,
            reason="pytest failed",
            action_id="validate",
            severity=PlanRisk.HIGH,
        ),
    ]

    decision = evaluate_replan(events)

    assert decision.should_replan is True
    assert decision.triggers == [
        ReplanTrigger.BLOCKER_ADDED,
        ReplanTrigger.ACTION_FAILED,
    ]
    assert decision.reasons == ["approval needed", "pytest failed"]
    assert decision.action_ids == ["validate"]


def test_plan_assessment_tracks_cost_risk_and_blockers() -> None:
    plan = Plan(
        plan_id="p2",
        objective="release",
        blockers=["missing approval"],
        actions=[
            PlanAction(action_id="a", title="A", cost=2, risk=PlanRisk.LOW),
            PlanAction(action_id="b", title="B", cost=5, risk=PlanRisk.HIGH),
        ],
    )

    assessment = assess_plan(plan)

    assert assessment.total_cost == 7
    assert assessment.highest_risk == PlanRisk.HIGH
    assert assessment.blockers == ["missing approval"]
    assert assessment.ready_action_ids == ["a", "b"]


def test_planner_service_creates_plan_summary() -> None:
    service = PlannerService()

    summary = service.create_plan(
        plan_id="p3",
        objective="ship planner API",
        blockers=["needs review"],
        actions=[
            PlanAction(action_id="inspect", title="Inspect"),
            PlanAction(
                action_id="patch",
                title="Patch",
                preconditions=["inspect"],
                cost=3,
                risk=PlanRisk.HIGH,
            ),
        ],
    )

    assert summary.plan.plan_id == "p3"
    assert summary.assessment.total_cost == 4
    assert summary.assessment.highest_risk == PlanRisk.HIGH
    assert summary.assessment.ready_action_ids == ["inspect"]
    assert [action.action_id for action in summary.next_actions] == ["inspect"]


def test_planner_service_evaluates_replan_events() -> None:
    service = PlannerService()

    decision = service.evaluate_replan(
        [
            ReplanEvent(
                trigger=ReplanTrigger.COST_EXCEEDED,
                reason="token budget exceeded",
            )
        ]
    )

    assert decision.should_replan is True
    assert decision.triggers == [ReplanTrigger.COST_EXCEEDED]


def test_deferred_surface_decision_filters_active_deferrals() -> None:
    decisions = [
        DeferredSurfaceDecision(
            surface=DeferredSurface.I18N,
            reason="needs product sequencing",
        ),
        DeferredSurfaceDecision(
            surface=DeferredSurface.THEMES,
            decision="ship",
            reason="already scoped",
        ),
    ]

    assert active_deferred_surfaces(decisions) == [DeferredSurface.I18N]
    assert deferred_surface_actions(decisions) == ["i18n: needs product sequencing"]
