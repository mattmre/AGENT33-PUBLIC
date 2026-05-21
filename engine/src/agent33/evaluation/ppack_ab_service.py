"""P-PACK v3 deterministic A/B assignment and reporting service."""

from __future__ import annotations

import hashlib
import importlib
import math
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from statistics import NormalDist
from typing import TYPE_CHECKING, Any

import httpx

from agent33.evaluation.ppack_ab_models import (
    GitHubIssuePublishResult,
    PPackABAssignment,
    PPackABMetricComparison,
    PPackABReport,
    PPackABVariant,
)
from agent33.outcomes.models import OutcomeEvent, OutcomeMetricType

if TYPE_CHECKING:
    from agent33.evaluation.ppack_ab_persistence import PPackABPersistence
    from agent33.outcomes.service import OutcomesService


@lru_cache(maxsize=1)
def _load_scipy_stats() -> Any | None:
    try:
        return importlib.import_module("scipy.stats")
    except (ModuleNotFoundError, ImportError):
        return None


@dataclass(slots=True)
class GitHubIssueAlertConfig:
    enabled: bool = False
    owner: str = ""
    repo: str = ""
    token: str = ""


class PPackABService:
    """Manage deterministic assignment and weekly-style outcome comparisons."""

    def __init__(
        self,
        *,
        outcomes_service: OutcomesService,
        persistence: PPackABPersistence,
        enabled: bool = True,
        experiment_key: str = "ppack_v3",
        confidence_level: float = 0.95,
        minimum_sample_size: int = 30,
        regression_threshold: float = -0.05,
        weekly_window_days: int = 7,
        alert_config: GitHubIssueAlertConfig | None = None,
    ) -> None:
        self._outcomes_service = outcomes_service
        self._persistence = persistence
        self._enabled = enabled
        self._experiment_key = experiment_key
        self._confidence_level = confidence_level
        self._minimum_sample_size = minimum_sample_size
        self._regression_threshold = regression_threshold
        self._weekly_window_days = weekly_window_days
        self._alert_config = alert_config or GitHubIssueAlertConfig()

    def close(self) -> None:
        self._persistence.close()

    def assign_variant(self, *, tenant_id: str, session_id: str) -> PPackABAssignment:
        if not self._enabled:
            raise RuntimeError("P-PACK v3 A/B harness is disabled")
        normalized_tenant = tenant_id.strip()
        normalized_session = session_id.strip()
        if not normalized_session:
            raise ValueError("session_id is required for P-PACK v3 assignment")
        existing = self._persistence.get_assignment(
            tenant_id=normalized_tenant,
            session_id=normalized_session,
            experiment_key=self._experiment_key,
        )
        if existing is not None:
            return existing
        assignment_hash = hashlib.sha256(
            f"{self._experiment_key}:{normalized_tenant}:{normalized_session}".encode()
        ).hexdigest()
        variant = (
            PPackABVariant.CONTROL
            if int(assignment_hash[:8], 16) % 2 == 0
            else PPackABVariant.TREATMENT
        )
        assignment = PPackABAssignment(
            experiment_key=self._experiment_key,
            tenant_id=normalized_tenant,
            session_id=normalized_session,
            variant=variant,
            assignment_hash=assignment_hash,
        )
        return self._persistence.save_assignment(assignment)

    def get_assignment(self, *, tenant_id: str, session_id: str) -> PPackABAssignment | None:
        return self._persistence.get_assignment(
            tenant_id=tenant_id.strip(),
            session_id=session_id.strip(),
            experiment_key=self._experiment_key,
        )

    def get_report(self, report_id: str) -> PPackABReport | None:
        return self._persistence.get_report(report_id)

    def generate_weekly_report(
        self,
        *,
        tenant_id: str,
        domain: str | None = None,
        metric_types: list[OutcomeMetricType] | None = None,
    ) -> PPackABReport:
        until = datetime.now(UTC)
        since = until - timedelta(days=self._weekly_window_days)
        return self.generate_report(
            tenant_id=tenant_id,
            domain=domain,
            since=since,
            until=until,
            metric_types=metric_types,
        )

    def generate_report(
        self,
        *,
        tenant_id: str,
        domain: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        metric_types: list[OutcomeMetricType] | None = None,
    ) -> PPackABReport:
        if not self._enabled:
            raise RuntimeError("P-PACK v3 A/B harness is disabled")
        normalized_tenant = tenant_id.strip()
        normalized_domain = (domain or "").strip()
        selected_metrics = metric_types or [
            OutcomeMetricType.SUCCESS_RATE,
            OutcomeMetricType.QUALITY_SCORE,
            OutcomeMetricType.LATENCY_MS,
            OutcomeMetricType.COST_USD,
        ]
        selected_metrics = list(dict.fromkeys(selected_metrics))
        assignments = self._persistence.list_assignments(
            tenant_id=normalized_tenant,
            experiment_key=self._experiment_key,
        )
        assignments_by_session = {item.session_id: item for item in assignments}
        assignment_counts = {
            PPackABVariant.CONTROL.value: sum(
                1 for item in assignments if item.variant == PPackABVariant.CONTROL
            ),
            PPackABVariant.TREATMENT.value: sum(
                1 for item in assignments if item.variant == PPackABVariant.TREATMENT
            ),
        }
        historical = self._outcomes_service.load_historical(
            normalized_tenant,
            since=since,
            until=until,
            domain=normalized_domain or None,
            metric_types=selected_metrics,
            limit=None,
        )
        metric_buckets: dict[OutcomeMetricType, dict[PPackABVariant, list[float]]] = {
            metric: {PPackABVariant.CONTROL: [], PPackABVariant.TREATMENT: []}
            for metric in selected_metrics
        }
        events_considered = 0
        for event in historical:
            if event.metric_type not in metric_buckets:
                continue
            variant = self._resolve_event_variant(event, assignments_by_session)
            if variant is None:
                continue
            metric_buckets[event.metric_type][variant].append(event.value)
            events_considered += 1
        tested_metrics = sum(
            1
            for metric in selected_metrics
            if metric_buckets[metric][PPackABVariant.CONTROL]
            and metric_buckets[metric][PPackABVariant.TREATMENT]
        )
        alpha = (1.0 - self._confidence_level) / max(tested_metrics, 1)
        comparisons = [
            self._build_metric_comparison(
                metric_type=metric,
                control_values=metric_buckets[metric][PPackABVariant.CONTROL],
                treatment_values=metric_buckets[metric][PPackABVariant.TREATMENT],
                alpha=alpha,
            )
            for metric in selected_metrics
        ]
        report = PPackABReport(
            experiment_key=self._experiment_key,
            tenant_id=normalized_tenant,
            domain=normalized_domain or "all",
            since=since,
            until=until,
            assignment_counts=assignment_counts,
            total_assignments=sum(assignment_counts.values()),
            total_events_considered=events_considered,
            comparisons=comparisons,
            overall_regression=any(item.regression_detected for item in comparisons),
        )
        report.markdown = self.render_markdown(report)
        return self._persistence.save_report(report)

    async def publish_github_issue(self, report: PPackABReport) -> GitHubIssuePublishResult:
        if not report.overall_regression:
            return GitHubIssuePublishResult(
                reason="No statistically significant regression detected"
            )
        if not self._alert_config.enabled:
            return GitHubIssuePublishResult(reason="GitHub issue alerting is disabled")
        if not (
            self._alert_config.owner.strip()
            and self._alert_config.repo.strip()
            and self._alert_config.token.strip()
        ):
            return GitHubIssuePublishResult(reason="GitHub issue alerting is not configured")
        title = f"P-PACK v3 regression detected for tenant {report.tenant_id}"
        body = (
            "Automated weekly regression alert for the P-PACK v3 A/B harness.\n\n"
            f"{report.markdown}\n"
        )
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"https://api.github.com/repos/{self._alert_config.owner}/{self._alert_config.repo}/issues",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {self._alert_config.token}",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    json={"title": title, "body": body},
                )
        except httpx.HTTPError as exc:
            return GitHubIssuePublishResult(
                attempted=True,
                reason=f"GitHub issue creation failed due to HTTP error: {exc}",
            )
        if response.status_code >= 300:
            return GitHubIssuePublishResult(
                attempted=True,
                reason=f"GitHub issue creation failed: {response.status_code}",
            )
        try:
            payload = response.json()
        except ValueError as exc:
            return GitHubIssuePublishResult(
                attempted=True,
                reason=f"GitHub issue creation failed due to invalid JSON response: {exc}",
            )
        return GitHubIssuePublishResult(
            attempted=True,
            created=True,
            issue_number=payload.get("number"),
            issue_url=payload.get("html_url", ""),
            reason="Created GitHub issue for regression alert",
        )

    def render_markdown(self, report: PPackABReport) -> str:
        lines = [
            "# P-PACK v3 A/B Report",
            "",
            f"- Tenant: `{report.tenant_id}`",
            f"- Experiment: `{report.experiment_key}`",
            f"- Domain: `{report.domain}`",
            f"- Window start: `{report.since.isoformat() if report.since else 'all time'}`",
            (
                f"- Window end: `"
                f"{report.until.isoformat() if report.until else report.generated_at.isoformat()}`"
            ),
            (
                f"- Assignments: control={report.assignment_counts.get('control', 0)}, "
                f"treatment={report.assignment_counts.get('treatment', 0)}"
            ),
            f"- Events considered: {report.total_events_considered}",
            f"- Overall regression: {'yes' if report.overall_regression else 'no'}",
            "",
            (
                "| Metric | Control mean | Treatment mean | Directional delta % | "
                "p-value | Significant | Regression |"
            ),
            "| --- | ---: | ---: | ---: | ---: | :---: | :---: |",
        ]
        for item in report.comparisons:
            lines.append(
                "| "
                f"{item.metric_type.value} | "
                f"{item.control_mean:.4f} ({item.control_count}) | "
                f"{item.treatment_mean:.4f} ({item.treatment_count}) | "
                f"{item.directional_delta_pct * 100:.2f}% | "
                f"{item.p_value:.4f} | "
                f"{'yes' if item.statistically_significant else 'no'} | "
                f"{'yes' if item.regression_detected else 'no'} |"
            )
        return "\n".join(lines)

    def _resolve_event_variant(
        self,
        event: OutcomeEvent,
        assignments_by_session: dict[str, PPackABAssignment],
    ) -> PPackABVariant | None:
        session_id = event.metadata.get("session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            return None
        assignment = assignments_by_session.get(session_id.strip())
        return assignment.variant if assignment is not None else None

    def _build_metric_comparison(
        self,
        *,
        metric_type: OutcomeMetricType,
        control_values: list[float],
        treatment_values: list[float],
        alpha: float,
    ) -> PPackABMetricComparison:
        control_mean = statistics.fmean(control_values) if control_values else 0.0
        treatment_mean = statistics.fmean(treatment_values) if treatment_values else 0.0
        delta = treatment_mean - control_mean
        lower_is_better = metric_type in {
            OutcomeMetricType.LATENCY_MS,
            OutcomeMetricType.COST_USD,
        }
        baseline = abs(control_mean) if abs(control_mean) > 1e-9 else 1.0
        directional_delta_pct = (
            (control_mean - treatment_mean) / baseline if lower_is_better else delta / baseline
        )
        sample_size_ready = (
            len(control_values) >= self._minimum_sample_size
            and len(treatment_values) >= self._minimum_sample_size
        )
        p_value = self._welch_ttest(control_values, treatment_values)
        statistically_significant = sample_size_ready and p_value <= alpha
        regression_detected = (
            statistically_significant and directional_delta_pct <= self._regression_threshold
        )
        return PPackABMetricComparison(
            metric_type=metric_type,
            lower_is_better=lower_is_better,
            control_mean=control_mean,
            control_count=len(control_values),
            treatment_mean=treatment_mean,
            treatment_count=len(treatment_values),
            delta=delta,
            directional_delta_pct=directional_delta_pct,
            p_value=p_value,
            alpha=alpha,
            minimum_sample_size=self._minimum_sample_size,
            sample_size_ready=sample_size_ready,
            statistically_significant=statistically_significant,
            regression_detected=regression_detected,
        )

    def _welch_ttest(self, control_values: list[float], treatment_values: list[float]) -> float:
        if len(control_values) < 2 or len(treatment_values) < 2:
            return 1.0
        scipy_stats = _load_scipy_stats()
        if scipy_stats is not None:
            result = scipy_stats.ttest_ind(control_values, treatment_values, equal_var=False)
            p_value = float(result.pvalue)
            return p_value if math.isfinite(p_value) else 1.0
        control_variance = statistics.variance(control_values)
        treatment_variance = statistics.variance(treatment_values)
        control_n = len(control_values)
        treatment_n = len(treatment_values)
        standard_error_sq = (control_variance / control_n) + (treatment_variance / treatment_n)
        if standard_error_sq <= 0:
            return (
                0.0
                if not math.isclose(
                    statistics.fmean(control_values),
                    statistics.fmean(treatment_values),
                )
                else 1.0
            )
        t_stat = abs(
            statistics.fmean(control_values) - statistics.fmean(treatment_values)
        ) / math.sqrt(standard_error_sq)
        return 2 * (1 - NormalDist().cdf(t_stat))
