from __future__ import annotations

from agent33.benchmarks.leaderboard import (
    LeaderboardArtifact,
    LeaderboardEntry,
    build_leaderboard_artifact,
    ranked_entries,
)
from agent33.benchmarks.public_report import (
    BenchmarkReportItem,
    PublicBenchmarkReport,
    average_score,
    pass_rate,
)


def test_public_benchmark_report_pass_rate() -> None:
    report = PublicBenchmarkReport(
        report_id="r1",
        model="model-a",
        suite="smoke",
        items=[
            BenchmarkReportItem(task_id="a", score=1.0, passed=True),
            BenchmarkReportItem(task_id="b", score=0.0, passed=False),
        ],
    )

    assert pass_rate(report) == 0.5
    assert average_score(report) == 0.5


def test_leaderboard_artifact_ranks_highest_score_first() -> None:
    artifact = LeaderboardArtifact(
        artifact_id="lb1",
        entries=[
            LeaderboardEntry(
                model="model-b",
                suite="smoke",
                score=0.4,
                report_uri="reports/b.json",
            ),
            LeaderboardEntry(
                model="model-a",
                suite="smoke",
                score=0.9,
                report_uri="reports/a.json",
            ),
        ],
    )

    assert [entry.model for entry in ranked_entries(artifact)] == [
        "model-a",
        "model-b",
    ]


def test_build_leaderboard_artifact_from_public_reports() -> None:
    reports = [
        PublicBenchmarkReport(
            report_id="r-low",
            model="model-low",
            suite="smoke",
            items=[BenchmarkReportItem(task_id="a", score=0.25, passed=False)],
        ),
        PublicBenchmarkReport(
            report_id="r-high",
            model="model-high",
            suite="smoke",
            artifact_uri="artifact://reports/high",
            items=[
                BenchmarkReportItem(task_id="a", score=1.0, passed=True),
                BenchmarkReportItem(task_id="b", score=0.8, passed=True),
            ],
        ),
    ]

    artifact = build_leaderboard_artifact("lb-public", reports)

    assert artifact.entries[0].model == "model-high"
    assert artifact.entries[0].score == 0.9
    assert artifact.entries[0].pass_rate == 1.0
    assert artifact.entries[0].task_count == 2
    assert artifact.entries[0].report_uri == "artifact://reports/high"
