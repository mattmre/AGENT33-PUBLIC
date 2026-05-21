"""Tests for POST /v1/rag/query endpoint."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from agent33.main import app
from agent33.security.auth import create_access_token


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    token = create_access_token("test-user", scopes=["admin"])
    return {"Authorization": f"Bearer {token}"}


class TestRagRouteNoAuth:
    def test_returns_401_without_auth(self, client: TestClient) -> None:
        response = client.post("/v1/rag/query", json={"query": "hello"})
        assert response.status_code == 401


class TestRagRouteNoPipeline:
    def test_returns_503_when_pipeline_missing(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Route must return HTTP 503 with a typed body when rag_pipeline is absent."""
        if hasattr(app.state, "rag_pipeline"):
            del app.state.rag_pipeline

        response = client.post(
            "/v1/rag/query",
            json={"query": "what is agent33"},
            headers=auth_headers,
        )
        assert response.status_code == 503
        body = response.json()
        # FastAPI wraps HTTPException detail under the "detail" key
        detail = body["detail"]
        assert detail["error"] == "rag_unavailable"
        assert "not initialized" in detail["detail"]

    def test_503_body_has_correct_error_key(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """503 response must carry error='rag_unavailable' so the frontend can identify it."""
        if hasattr(app.state, "rag_pipeline"):
            del app.state.rag_pipeline

        response = client.post(
            "/v1/rag/query",
            json={"query": "test"},
            headers=auth_headers,
        )
        assert response.status_code == 503
        body = response.json()
        assert body["detail"]["error"] == "rag_unavailable"


class TestRagRouteWithPipeline:
    def test_calls_pipeline_and_maps_sources(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """When a rag_pipeline is present its query() result is returned."""
        src = MagicMock()
        src.text = "hello world"
        src.score = 0.9
        src.metadata = {"doc_id": "d1"}
        src.retrieval_method = "vector"

        result = MagicMock()
        result.augmented_prompt = "Context: hello"
        result.sources = [src]
        result.citations = []

        mock_pipeline = MagicMock()
        mock_pipeline.query = AsyncMock(return_value=result)
        app.state.rag_pipeline = mock_pipeline

        response = client.post(
            "/v1/rag/query",
            json={"query": "hello"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["augmented_prompt"] == "Context: hello"
        assert len(body["sources"]) == 1
        assert body["sources"][0]["score"] == pytest.approx(0.9)
        assert body["citations"] == []
        mock_pipeline.query.assert_awaited_once_with("hello")

    def test_citations_field_always_present(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Response must include a citations list even when the pipeline returns None."""
        result = MagicMock()
        result.augmented_prompt = "answer"
        result.sources = []
        result.citations = None  # pipeline doesn't populate citations

        mock_pipeline = MagicMock()
        mock_pipeline.query = AsyncMock(return_value=result)
        app.state.rag_pipeline = mock_pipeline

        response = client.post(
            "/v1/rag/query",
            json={"query": "citations test"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert "citations" in body
        assert body["citations"] == []

    def test_pipeline_connection_error_returns_503(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """A ConnectionError from the pipeline must yield HTTP 503, not swallow silently."""
        mock_pipeline = MagicMock()
        mock_pipeline.query = AsyncMock(side_effect=ConnectionError("db unreachable"))
        app.state.rag_pipeline = mock_pipeline

        response = client.post(
            "/v1/rag/query",
            json={"query": "connection fail"},
            headers=auth_headers,
        )
        assert response.status_code == 503
        body = response.json()
        assert body["detail"]["error"] == "rag_unavailable"
        assert "db unreachable" in body["detail"]["detail"]

    def test_pipeline_timeout_error_returns_503(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """A TimeoutError from the pipeline must yield HTTP 503."""
        mock_pipeline = MagicMock()
        mock_pipeline.query = AsyncMock(side_effect=TimeoutError("timed out"))
        app.state.rag_pipeline = mock_pipeline

        response = client.post(
            "/v1/rag/query",
            json={"query": "timeout test"},
            headers=auth_headers,
        )
        assert response.status_code == 503
        body = response.json()
        assert body["detail"]["error"] == "rag_unavailable"

    def test_pipeline_unexpected_error_returns_500(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """An unexpected exception from the pipeline must yield HTTP 500 with typed body.

        Previously the broad except swallowed this silently (L11 violation).
        The route must now propagate the error visibly.
        """
        mock_pipeline = MagicMock()
        mock_pipeline.query = AsyncMock(side_effect=RuntimeError("unexpected internal error"))
        app.state.rag_pipeline = mock_pipeline

        response = client.post(
            "/v1/rag/query",
            json={"query": "crash"},
            headers=auth_headers,
        )
        assert response.status_code == 500
        body = response.json()
        assert body["detail"]["error"] == "rag_error"
        assert "unexpected internal error" in body["detail"]["detail"]

    def teardown_method(self) -> None:
        if hasattr(app.state, "rag_pipeline"):
            del app.state.rag_pipeline
