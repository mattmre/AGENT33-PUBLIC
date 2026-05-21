"""Tests for comparative evaluation API routes."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from agent33.api.routes import synthetic_envs
from agent33.api.routes.comparative import set_comparative_service
from agent33.evaluation.comparative.models import AgentScore
from agent33.evaluation.comparative.service import ComparativeEvaluationService
from agent33.evaluation.synthetic_envs.service import SyntheticEnvironmentService

if TYPE_CHECKING:
    from starlette.testclient import TestClient


def _init_service_with_data() -> ComparativeEvaluationService:
    """Create and populate a test service."""
    svc = ComparativeEvaluationService()
    svc.record_scores(
        [
            AgentScore(agent_name="alpha", metric_name="M-01", value=90.0),
            AgentScore(agent_name="beta", metric_name="M-01", value=70.0),
            AgentScore(agent_name="gamma", metric_name="M-01", value=50.0),
        ]
    )
    set_comparative_service(svc)
    return svc


def _init_bundle_services(tmp_path) -> tuple[ComparativeEvaluationService, str, str, str]:
    root = Path(__file__).resolve().parents[1]
    synthetic_service = SyntheticEnvironmentService(
        workflow_dir=root / "workflow-definitions",
        tool_dir=root / "tool-definitions",
        persistence_path=tmp_path / "synthetic-bundles.json",
    )
    bundle = synthetic_service.generate_bundle(
        workflow_names=["incident-triage-loop"],
        variations_per_workflow=1,
    )
    synthetic_envs.set_synthetic_environment_service(synthetic_service)

    task = bundle.environments[0].tasks[0]
    comparative = ComparativeEvaluationService()
    set_comparative_service(comparative)
    return comparative, bundle.bundle_id, bundle.environments[0].environment_id, task.task_id


class TestLeaderboardRoute:
    @pytest.fixture(autouse=True)
    def _setup(self, client: TestClient) -> None:
        self.client = client
        _init_service_with_data()

    def test_get_leaderboard(self) -> None:
        resp = self.client.get("/v1/evaluation/comparative/leaderboard")
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data
        assert "population_size" in data


class TestAgentProfileRoute:
    @pytest.fixture(autouse=True)
    def _setup(self, client: TestClient) -> None:
        self.client = client
        _init_service_with_data()

    def test_get_profile(self) -> None:
        resp = self.client.get("/v1/evaluation/comparative/agents/alpha/profile")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_name"] == "alpha"
        assert "metric_percentiles" in data

    def test_profile_not_found(self) -> None:
        resp = self.client.get("/v1/evaluation/comparative/agents/nonexistent/profile")
        assert resp.status_code == 404


class TestEvaluateRoute:
    @pytest.fixture(autouse=True)
    def _setup(self, client: TestClient) -> None:
        self.client = client
        _init_service_with_data()

    def test_trigger_evaluation(self) -> None:
        resp = self.client.post(
            "/v1/evaluation/comparative/evaluate",
            json={"metric_name": "M-01"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["comparisons"] == 3  # 3 agents -> 3 pairs
        assert data["population_size"] == 3


class TestRecordScoresRoute:
    @pytest.fixture(autouse=True)
    def _setup(self, client: TestClient) -> None:
        self.client = client
        svc = ComparativeEvaluationService()
        set_comparative_service(svc)

    def test_record_scores(self) -> None:
        resp = self.client.post(
            "/v1/evaluation/comparative/scores",
            json={
                "scores": [
                    {"agent_name": "x", "metric_name": "M-01", "value": 80.0},
                    {"agent_name": "y", "metric_name": "M-01", "value": 60.0},
                ]
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["recorded"] == 2
        assert data["population_size"] == 2

    def test_empty_scores_rejected(self) -> None:
        resp = self.client.post(
            "/v1/evaluation/comparative/scores",
            json={"scores": []},
        )
        assert resp.status_code == 422  # Validation error


class TestPairwiseCompareRoute:
    @pytest.fixture(autouse=True)
    def _setup(self, client: TestClient) -> None:
        self.client = client
        _init_service_with_data()

    def test_compare_success(self) -> None:
        resp = self.client.post(
            "/v1/evaluation/comparative/compare",
            json={"agent_a": "alpha", "agent_b": "beta", "metric_name": "M-01"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["outcome"] == "win"
        assert data["agent_a"] == "alpha"

    def test_compare_missing_data(self) -> None:
        resp = self.client.post(
            "/v1/evaluation/comparative/compare",
            json={"agent_a": "alpha", "agent_b": "nobody", "metric_name": "M-01"},
        )
        assert resp.status_code == 404


class TestHistoryRoute:
    @pytest.fixture(autouse=True)
    def _setup(self, client: TestClient) -> None:
        self.client = client
        svc = _init_service_with_data()
        # Run a round-robin to generate history
        svc.run_round_robin("M-01")

    def test_history_for_agent(self) -> None:
        resp = self.client.get(
            "/v1/evaluation/comparative/history",
            params={"agent_name": "alpha"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_name"] == "alpha"
        assert len(data["history"]) > 1

    def test_history_all_snapshots(self) -> None:
        resp = self.client.get("/v1/evaluation/comparative/history")
        assert resp.status_code == 200
        data = resp.json()
        assert "snapshots" in data

    def test_history_unknown_agent(self) -> None:
        resp = self.client.get(
            "/v1/evaluation/comparative/history",
            params={"agent_name": "ghost"},
        )
        assert resp.status_code == 404


class TestBundleEvaluationRoutes:
    @pytest.fixture(autouse=True)
    def _setup(self, client: TestClient, tmp_path) -> None:
        self.client = client
        self.svc, self.bundle_id, self.environment_id, self.task_id = _init_bundle_services(
            tmp_path
        )

    def test_record_bundle_scores(self) -> None:
        resp = self.client.post(
            f"/v1/evaluation/comparative/bundles/{self.bundle_id}/scores",
            json={
                "scores": [
                    {
                        "agent_name": "alpha",
                        "metric_name": "M-01",
                        "environment_id": self.environment_id,
                        "task_id": self.task_id,
                        "value": 0.91,
                    },
                    {
                        "agent_name": "beta",
                        "metric_name": "M-01",
                        "environment_id": self.environment_id,
                        "task_id": self.task_id,
                        "value": 0.61,
                    },
                ]
            },
        )

        assert resp.status_code == 201
        payload = resp.json()
        assert payload["recorded"] == 2
        assert payload["bundle_id"] == self.bundle_id

    def test_record_bundle_scores_rejects_environment_task_mismatch(self) -> None:
        resp = self.client.post(
            f"/v1/evaluation/comparative/bundles/{self.bundle_id}/scores",
            json={
                "scores": [
                    {
                        "agent_name": "alpha",
                        "metric_name": "M-01",
                        "environment_id": self.environment_id,
                        "task_id": "TASK-missing",
                        "value": 0.91,
                    }
                ]
            },
        )

        assert resp.status_code == 400
        assert "does not belong to environment" in resp.json()["detail"]

    def test_record_bundle_scores_rejects_unknown_environment(self) -> None:
        resp = self.client.post(
            f"/v1/evaluation/comparative/bundles/{self.bundle_id}/scores",
            json={
                "scores": [
                    {
                        "agent_name": "alpha",
                        "metric_name": "M-01",
                        "environment_id": "SENV-missing",
                        "task_id": "TASK-missing",
                        "value": 0.91,
                    }
                ]
            },
        )

        assert resp.status_code == 400
        assert resp.json()["detail"] == (
            f"Environment 'SENV-missing' is not part of bundle '{self.bundle_id}'"
        )

    def test_evaluate_bundle_returns_task_aligned_leaderboard(self) -> None:
        record_resp = self.client.post(
            f"/v1/evaluation/comparative/bundles/{self.bundle_id}/scores",
            json={
                "scores": [
                    {
                        "agent_name": "alpha",
                        "metric_name": "M-01",
                        "environment_id": self.environment_id,
                        "task_id": self.task_id,
                        "value": 0.91,
                    },
                    {
                        "agent_name": "beta",
                        "metric_name": "M-01",
                        "environment_id": self.environment_id,
                        "task_id": self.task_id,
                        "value": 0.61,
                    },
                ]
            },
        )
        assert record_resp.status_code == 201

        evaluate_resp = self.client.post(
            f"/v1/evaluation/comparative/bundles/{self.bundle_id}/evaluate",
            json={"metric_name": "M-01"},
        )

        assert evaluate_resp.status_code == 200
        payload = evaluate_resp.json()
        assert payload["bundle_id"] == self.bundle_id
        assert payload["common_task_count"] == 1
        assert payload["leaderboard"]["entries"][0]["agent_name"] == "alpha"
