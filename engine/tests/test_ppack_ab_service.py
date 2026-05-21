from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent33.evaluation.ppack_ab_models import PPackABAssignment, PPackABVariant
from agent33.evaluation.ppack_ab_persistence import PPackABPersistence
from agent33.evaluation.ppack_ab_service import GitHubIssueAlertConfig, PPackABService
from agent33.outcomes.models import OutcomeEventCreate, OutcomeMetricType
from agent33.outcomes.persistence import OutcomePersistence
from agent33.outcomes.service import OutcomesService


def test_assign_variant_is_deterministic() -> None:
    service = PPackABService(
        outcomes_service=OutcomesService(),
        persistence=PPackABPersistence(":memory:"),
    )
    first = service.assign_variant(tenant_id="tenant-a", session_id="session-123")
    second = service.assign_variant(tenant_id="tenant-a", session_id="session-123")
    assert first.variant == second.variant
    assert first.assignment_hash == second.assignment_hash


def test_generate_report_detects_significant_regression() -> None:
    outcomes = OutcomesService()
    service = PPackABService(
        outcomes_service=outcomes,
        persistence=PPackABPersistence(":memory:"),
        minimum_sample_size=4,
        regression_threshold=-0.05,
    )
    base = datetime.now(UTC)
    assignments = []
    candidate = 0
    while len([item for item in assignments if item.variant.value == "control"]) < 4:
        assignment = service.assign_variant(
            tenant_id="tenant-a",
            session_id=f"session-candidate-{candidate}",
        )
        if assignment.variant.value == "control":
            assignments.append(assignment)
        candidate += 1
    while len([item for item in assignments if item.variant.value == "treatment"]) < 4:
        assignment = service.assign_variant(
            tenant_id="tenant-a",
            session_id=f"session-candidate-{candidate}",
        )
        if assignment.variant.value == "treatment":
            assignments.append(assignment)
        candidate += 1
    for assignment in assignments:
        value = 1.0 if assignment.variant.value == "control" else 0.0
        for offset in range(4):
            outcomes.record_event(
                tenant_id="tenant-a",
                event=OutcomeEventCreate(
                    domain="support",
                    event_type="invoke",
                    metric_type=OutcomeMetricType.SUCCESS_RATE,
                    value=value,
                    occurred_at=base + timedelta(minutes=offset),
                    metadata={
                        "session_id": assignment.session_id,
                        "ppack_variant": assignment.variant.value,
                    },
                ),
            )
    report = service.generate_report(
        tenant_id="tenant-a",
        domain="support",
        since=base - timedelta(minutes=1),
        until=base + timedelta(hours=1),
        metric_types=[OutcomeMetricType.SUCCESS_RATE],
    )
    assert report.total_assignments >= 8
    assert report.total_events_considered == 32
    assert report.overall_regression is True
    comparison = report.comparisons[0]
    assert comparison.metric_type == OutcomeMetricType.SUCCESS_RATE
    assert comparison.regression_detected is True
    assert comparison.statistically_significant is True
    assert comparison.directional_delta_pct <= -0.05


@pytest.mark.asyncio
async def test_publish_github_issue_returns_reason_on_http_error() -> None:
    service = PPackABService(
        outcomes_service=OutcomesService(),
        persistence=PPackABPersistence(":memory:"),
        alert_config=GitHubIssueAlertConfig(
            enabled=True,
            owner="mattmre",
            repo="AGENT33",
            token="test-token",
        ),
    )
    report = service.generate_weekly_report(
        tenant_id="tenant-a",
        metric_types=[OutcomeMetricType.SUCCESS_RATE],
    )
    report.overall_regression = True
    with patch(
        "httpx.AsyncClient.post",
        new=AsyncMock(side_effect=httpx.ConnectError("boom")),
    ):
        result = await service.publish_github_issue(report)
    assert result.attempted is True
    assert result.created is False
    assert "HTTP error" in result.reason


def test_generate_report_pushes_filters_down_to_historical_load() -> None:
    outcomes = MagicMock()
    outcomes.load_historical.return_value = []
    service = PPackABService(
        outcomes_service=outcomes,
        persistence=PPackABPersistence(":memory:"),
    )
    since = datetime.now(UTC) - timedelta(days=2)
    until = datetime.now(UTC)

    service.generate_report(
        tenant_id="tenant-a",
        domain="support",
        since=since,
        until=until,
        metric_types=[OutcomeMetricType.SUCCESS_RATE],
    )

    outcomes.load_historical.assert_called_once_with(
        "tenant-a",
        since=since,
        until=until,
        domain="support",
        metric_types=[OutcomeMetricType.SUCCESS_RATE],
        limit=None,
    )


def test_generate_report_keeps_older_assignments_for_in_window_events() -> None:
    outcomes = OutcomesService()
    persistence = PPackABPersistence(":memory:")
    service = PPackABService(
        outcomes_service=outcomes,
        persistence=persistence,
        minimum_sample_size=1,
    )
    now = datetime.now(UTC)
    old_assignment = PPackABAssignment(
        tenant_id="tenant-a",
        session_id="old-session",
        variant=PPackABVariant.CONTROL,
        assignment_hash="old-hash",
        assigned_at=now - timedelta(days=10),
    )
    current_assignment = PPackABAssignment(
        tenant_id="tenant-a",
        session_id="current-session",
        variant=PPackABVariant.TREATMENT,
        assignment_hash="current-hash",
        assigned_at=now - timedelta(days=1),
    )
    persistence.save_assignment(old_assignment)
    persistence.save_assignment(current_assignment)
    outcomes.record_event(
        tenant_id="tenant-a",
        event=OutcomeEventCreate(
            domain="support",
            event_type="invoke",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=1.0,
            occurred_at=now - timedelta(hours=12),
            metadata={"session_id": current_assignment.session_id},
        ),
    )
    outcomes.record_event(
        tenant_id="tenant-a",
        event=OutcomeEventCreate(
            domain="support",
            event_type="invoke",
            metric_type=OutcomeMetricType.SUCCESS_RATE,
            value=1.0,
            occurred_at=now - timedelta(hours=6),
            metadata={"session_id": old_assignment.session_id},
        ),
    )

    report = service.generate_report(
        tenant_id="tenant-a",
        domain="support",
        since=now - timedelta(days=7),
        until=now,
        metric_types=[OutcomeMetricType.SUCCESS_RATE],
    )

    assert report.total_assignments == 2
    assert report.assignment_counts == {"control": 1, "treatment": 1}
    assert report.total_events_considered == 2


def test_assign_variant_is_thread_safe_under_concurrent_load(tmp_path) -> None:
    persistence = PPackABPersistence(tmp_path / "ppack-ab.db")
    service = PPackABService(
        outcomes_service=OutcomesService(),
        persistence=persistence,
    )

    def assign(session_id: str) -> str:
        return service.assign_variant(tenant_id="tenant-a", session_id=session_id).variant.value

    session_ids = [f"session-{index % 12}" for index in range(60)]
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(assign, session_ids))

    assert len(results) == len(session_ids)
    persisted = persistence.list_assignments(
        tenant_id="tenant-a",
        experiment_key="ppack_v3",
    )
    assert len({assignment.session_id for assignment in persisted}) == 12


def test_generate_report_reads_persisted_history_inside_worker_thread(tmp_path) -> None:
    outcome_persistence = OutcomePersistence(tmp_path / "outcomes.db")
    assignment_persistence = PPackABPersistence(tmp_path / "ppack-ab.db")
    writer_outcomes = OutcomesService(persistence=outcome_persistence)
    writer_service = PPackABService(
        outcomes_service=writer_outcomes,
        persistence=assignment_persistence,
        minimum_sample_size=1,
    )
    base = datetime.now(UTC)

    assignments: list[PPackABAssignment] = []
    candidate = 0
    while len({assignment.variant for assignment in assignments}) < 2:
        assignment = writer_service.assign_variant(
            tenant_id="tenant-a",
            session_id=f"worker-session-{candidate}",
        )
        assignments.append(assignment)
        candidate += 1

    for assignment in assignments:
        writer_outcomes.record_event(
            tenant_id="tenant-a",
            event=OutcomeEventCreate(
                domain="support",
                event_type="invoke",
                metric_type=OutcomeMetricType.SUCCESS_RATE,
                value=1.0 if assignment.variant == PPackABVariant.CONTROL else 0.0,
                occurred_at=base,
                metadata={"session_id": assignment.session_id},
            ),
        )

    reporter_service = PPackABService(
        outcomes_service=OutcomesService(persistence=outcome_persistence),
        persistence=assignment_persistence,
        minimum_sample_size=1,
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        report = executor.submit(
            reporter_service.generate_report,
            tenant_id="tenant-a",
            domain="support",
            since=base - timedelta(minutes=1),
            until=base + timedelta(minutes=1),
            metric_types=[OutcomeMetricType.SUCCESS_RATE],
        ).result()

    assert report.total_assignments == 2
    assert report.total_events_considered == 2
