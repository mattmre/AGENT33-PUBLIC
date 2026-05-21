"""Public benchmark report contracts."""

from __future__ import annotations

from pydantic import BaseModel, Field


class BenchmarkReportItem(BaseModel):
    task_id: str
    score: float
    passed: bool


class PublicBenchmarkReport(BaseModel):
    report_id: str
    model: str
    suite: str
    items: list[BenchmarkReportItem] = Field(default_factory=list)
    artifact_uri: str = ""


def pass_rate(report: PublicBenchmarkReport) -> float:
    if not report.items:
        return 0.0
    passed = sum(1 for item in report.items if item.passed)
    return passed / len(report.items)


def average_score(report: PublicBenchmarkReport) -> float:
    if not report.items:
        return 0.0
    return sum(item.score for item in report.items) / len(report.items)
