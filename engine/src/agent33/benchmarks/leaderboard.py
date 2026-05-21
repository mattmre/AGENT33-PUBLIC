"""Leaderboard artifact contracts."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent33.benchmarks.public_report import PublicBenchmarkReport, average_score, pass_rate


class LeaderboardEntry(BaseModel):
    model: str
    suite: str
    score: float
    report_uri: str
    pass_rate: float = 0.0
    task_count: int = 0


class LeaderboardArtifact(BaseModel):
    artifact_id: str
    entries: list[LeaderboardEntry] = Field(default_factory=list)


def ranked_entries(artifact: LeaderboardArtifact) -> list[LeaderboardEntry]:
    return sorted(artifact.entries, key=lambda entry: entry.score, reverse=True)


def build_leaderboard_artifact(
    artifact_id: str,
    reports: list[PublicBenchmarkReport],
) -> LeaderboardArtifact:
    return LeaderboardArtifact(
        artifact_id=artifact_id,
        entries=ranked_entries(
            LeaderboardArtifact(
                artifact_id=artifact_id,
                entries=[
                    LeaderboardEntry(
                        model=report.model,
                        suite=report.suite,
                        score=average_score(report),
                        report_uri=report.artifact_uri or f"reports/{report.report_id}.json",
                        pass_rate=pass_rate(report),
                        task_count=len(report.items),
                    )
                    for report in reports
                ],
            )
        ),
    )
