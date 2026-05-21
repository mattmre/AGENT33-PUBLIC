"""Tests for SkillsBench benchmark API routes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from agent33.api.routes import benchmarks
from agent33.benchmarks.skillsbench.models import (
    BenchmarkRunResult,
    BenchmarkRunStatus,
    TrialOutcome,
    TrialRecord,
)
from agent33.benchmarks.skillsbench.storage import SkillsBenchArtifactStore

if TYPE_CHECKING:
    from pathlib import Path


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _fake_auth(request: Request, call_next):
        request.state.user = SimpleNamespace(scopes=["admin"], tenant_id="tenant-test")
        return await call_next(request)

    app.include_router(benchmarks.router)
    return app


def _create_task(root: Path, category: str, task_name: str) -> None:
    task_dir = root / "tasks" / category / task_name
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "instruction.md").write_text("Solve the task.", encoding="utf-8")
    tests_dir = task_dir / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "test_outputs.py").write_text(
        "def test_output():\n    assert True\n",
        encoding="utf-8",
    )


class TestSkillsBenchRoutes:
    def setup_method(self, method) -> None:
        del method
        benchmarks._runs.clear()
        benchmarks._run_order.clear()
        benchmarks._artifact_store = None

    def test_list_tasks_returns_summaries(self, tmp_path: Path) -> None:
        _create_task(tmp_path, "math", "addition")
        client = TestClient(_make_app())

        response = client.post(
            "/v1/benchmarks/skillsbench/tasks",
            json={"skillsbench_root": str(tmp_path)},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert payload["categories"] == ["math"]
        assert payload["tasks"][0]["task_id"] == "math/addition"

    def test_run_benchmark_stores_summary(self, tmp_path: Path, monkeypatch) -> None:
        client = TestClient(_make_app())
        _create_task(tmp_path, "math", "addition")
        benchmarks._artifact_store = SkillsBenchArtifactStore(tmp_path / "store")

        run_result = BenchmarkRunResult(
            run_id="sb-test-run",
            status=BenchmarkRunStatus.COMPLETED,
            total_tasks=1,
            total_trials=2,
            passed_trials=2,
            pass_rate=1.0,
            total_duration_ms=25.0,
        )
        adapter = MagicMock()
        adapter.run_benchmark = AsyncMock(return_value=run_result)
        monkeypatch.setattr(benchmarks, "_build_skillsbench_adapter", lambda *_args: adapter)

        response = client.post(
            "/v1/benchmarks/skillsbench/runs",
            json={"skillsbench_root": str(tmp_path), "trials_per_task": 2},
        )

        assert response.status_code == 201
        assert response.json()["run_id"] == "sb-test-run"
        assert benchmarks._runs["sb-test-run"].run_id == "sb-test-run"
        assert (tmp_path / "store" / "sb-test-run" / "run.json").is_file()

    def test_list_and_get_runs(self, tmp_path: Path) -> None:
        client = TestClient(_make_app())
        benchmarks._artifact_store = SkillsBenchArtifactStore(tmp_path / "store")
        run = BenchmarkRunResult(
            run_id="sb-existing",
            status=BenchmarkRunStatus.COMPLETED,
            total_tasks=1,
            total_trials=1,
            passed_trials=1,
            pass_rate=1.0,
            total_duration_ms=5.0,
        )
        benchmarks._store_run(run)

        list_response = client.get("/v1/benchmarks/skillsbench/runs")
        assert list_response.status_code == 200
        assert list_response.json()[0]["run_id"] == "sb-existing"

        detail_response = client.get("/v1/benchmarks/skillsbench/runs/sb-existing")
        assert detail_response.status_code == 200
        assert detail_response.json()["run_id"] == "sb-existing"

    def test_get_run_caches_disk_loaded_runs_with_bounded_retention(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        store = SkillsBenchArtifactStore(tmp_path / "store")
        benchmarks._artifact_store = store
        monkeypatch.setattr(benchmarks, "_MAX_STORED_RUNS", 2)

        benchmarks._store_run(BenchmarkRunResult(run_id="sb-1"))
        benchmarks._store_run(BenchmarkRunResult(run_id="sb-2"))
        store.persist_run(BenchmarkRunResult(run_id="sb-3"))

        loaded = benchmarks._get_run("sb-3")

        assert loaded is not None
        assert loaded.run_id == "sb-3"
        assert benchmarks._run_order == ["sb-2", "sb-3"]
        assert "sb-1" not in benchmarks._runs

    def test_store_run_skips_duplicate_persist_when_snapshot_exists(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        store = SkillsBenchArtifactStore(tmp_path / "store")
        benchmarks._artifact_store = store
        run = BenchmarkRunResult(run_id="sb-existing")
        store.persist_run(run)

        persist_spy = MagicMock(wraps=store.persist_run)
        monkeypatch.setattr(store, "persist_run", persist_spy)

        benchmarks._store_run(run)

        persist_spy.assert_not_called()

    def test_get_run_returns_404_for_missing_run(self) -> None:
        client = TestClient(_make_app())
        response = client.get("/v1/benchmarks/skillsbench/runs/missing")
        assert response.status_code == 404

    def test_ctrf_and_artifact_routes(self, tmp_path: Path) -> None:
        client = TestClient(_make_app())
        store = SkillsBenchArtifactStore(tmp_path / "store")
        benchmarks._artifact_store = store

        artifact = store.persist_text_artifact(
            run_id="sb-existing",
            task_id="math/addition",
            trial_number=1,
            kind="pytest_stdout",
            filename="pytest-stdout.txt",
            content="1 passed",
        )
        run = BenchmarkRunResult(
            run_id="sb-existing",
            status=BenchmarkRunStatus.COMPLETED,
            total_tasks=1,
            total_trials=1,
            passed_trials=1,
            pass_rate=1.0,
        )
        run.trials.append(
            TrialRecord(
                task_id="math/addition",
                trial_number=1,
                outcome=TrialOutcome.PASSED,
                artifacts=[artifact],
            )
        )
        run.compute_aggregates()
        benchmarks._store_run(run)

        ctrf_response = client.get("/v1/benchmarks/skillsbench/runs/sb-existing/ctrf")
        assert ctrf_response.status_code == 200
        assert ctrf_response.json()["results"]["summary"]["tests"] == 1

        artifact_response = client.get(
            f"/v1/benchmarks/skillsbench/runs/sb-existing/artifacts/{artifact.relative_path}"
        )
        assert artifact_response.status_code == 200
        assert artifact_response.text == "1 passed"
