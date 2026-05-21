"""Compatibility reports from real model/resource/workflow runs."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class CompatibilityOutcome(StrEnum):
    SUCCESS = "success"
    DEGRADED = "degraded"
    FAILED = "failed"


class CompatibilityReport(BaseModel):
    report_id: str
    run_id: str = ""
    model: str = ""
    provider: str = ""
    resource_id: str = ""
    workflow_id: str = ""
    environment: str = ""
    outcome: CompatibilityOutcome
    failure_mode: str = ""
    degraded_mode: str = ""
    required_hints: list[str] = Field(default_factory=list)
    token_count: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    feedback: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CompatibilityReportStore:
    def __init__(self) -> None:
        self._reports: list[CompatibilityReport] = []

    def record(self, report: CompatibilityReport) -> CompatibilityReport:
        self._reports.append(report)
        return report

    def list_reports(
        self,
        *,
        model: str = "",
        provider: str = "",
        resource_id: str = "",
        limit: int = 100,
    ) -> list[CompatibilityReport]:
        reports = list(self._reports)
        if model:
            reports = [report for report in reports if report.model == model]
        if provider:
            reports = [report for report in reports if report.provider == provider]
        if resource_id:
            reports = [report for report in reports if report.resource_id == resource_id]
        reports.sort(key=lambda report: report.created_at, reverse=True)
        return reports[: max(1, limit)]


_store = CompatibilityReportStore()


def set_compatibility_report_store(store: CompatibilityReportStore) -> None:
    global _store  # noqa: PLW0603
    _store = store


def get_compatibility_report_store() -> CompatibilityReportStore:
    return _store
