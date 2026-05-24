"""Tests for explanations API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent33.explanation.store import ExplanationStore
from agent33.main import app
from agent33.security.auth import create_access_token


@pytest.fixture(autouse=True)
def isolated_explanation_store():
    """Mount a fresh in-memory ExplanationStore on app.state for each test."""
    app.state.explanation_store = ExplanationStore(db_path=":memory:")
    yield
    # clean up the reference so we don't leak between suites
    if hasattr(app.state, "explanation_store"):
        del app.state.explanation_store


@pytest.fixture
def reader_client() -> TestClient:
    """Client with read scope."""
    token = create_access_token("reader-user", scopes=["workflows:read"])
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def writer_client() -> TestClient:
    """Client with write scope."""
    token = create_access_token(
        "writer-user",
        scopes=["workflows:read", "workflows:write"],
    )
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def no_scope_client() -> TestClient:
    """Client with no scopes."""
    token = create_access_token("no-scope-user", scopes=[])
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


# -- Happy path tests --------------------------------------------------------


class TestExplanationCreation:
    """Tests for creating explanations."""

    def test_create_explanation_success(self, writer_client: TestClient) -> None:
        """Should create explanation with fact-check hook invoked."""
        resp = writer_client.post(
            "/v1/explanations/",
            json={
                "entity_type": "workflow",
                "entity_id": "hello-flow",
                "mode": "plan_review",
                "metadata": {"model": "llama3.1"},
            },
        )
        assert resp.status_code == 201

        data = resp.json()
        assert data["entity_type"] == "workflow"
        assert data["entity_id"] == "hello-flow"
        assert "Plan Review explanation" in data["content"]
        assert data["fact_check_status"] == "skipped"  # Hook returns SKIPPED
        assert "expl-" in data["id"]
        assert data["mode"] == "plan_review"
        assert data["claims"] == []
        assert data["metadata"]["model"] == "llama3.1"

    def test_create_multiple_explanations(self, writer_client: TestClient) -> None:
        """Should create multiple explanations with unique IDs."""
        resp1 = writer_client.post(
            "/v1/explanations/",
            json={"entity_type": "workflow", "entity_id": "flow-1"},
        )
        resp2 = writer_client.post(
            "/v1/explanations/",
            json={"entity_type": "agent", "entity_id": "agent-1"},
        )

        assert resp1.status_code == 201
        assert resp2.status_code == 201

        data1 = resp1.json()
        data2 = resp2.json()

        # Should have different IDs
        assert data1["id"] != data2["id"]


class TestExplanationRetrieval:
    """Tests for retrieving explanations."""

    def test_get_explanation_by_id(
        self, writer_client: TestClient, reader_client: TestClient
    ) -> None:
        """Should retrieve explanation by ID."""
        # Create explanation
        create_resp = writer_client.post(
            "/v1/explanations/",
            json={"entity_type": "workflow", "entity_id": "test-flow"},
        )
        explanation_id = create_resp.json()["id"]

        # Retrieve with read scope
        get_resp = reader_client.get(f"/v1/explanations/{explanation_id}")
        assert get_resp.status_code == 200

        data = get_resp.json()
        assert data["id"] == explanation_id
        assert data["entity_type"] == "workflow"
        assert data["entity_id"] == "test-flow"

    def test_get_nonexistent_explanation_returns_404(self, reader_client: TestClient) -> None:
        """Should return 404 for nonexistent explanation."""
        resp = reader_client.get("/v1/explanations/expl-nonexistent")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_list_all_explanations(
        self, writer_client: TestClient, reader_client: TestClient
    ) -> None:
        """Should list all explanations."""
        # Create multiple explanations
        writer_client.post(
            "/v1/explanations/",
            json={"entity_type": "workflow", "entity_id": "flow-1"},
        )
        writer_client.post(
            "/v1/explanations/",
            json={"entity_type": "agent", "entity_id": "agent-1"},
        )

        # List all
        resp = reader_client.get("/v1/explanations/")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) == 2

    def test_list_explanations_filtered_by_entity_type(
        self, writer_client: TestClient, reader_client: TestClient
    ) -> None:
        """Should filter explanations by entity_type."""
        # Create explanations of different types
        writer_client.post(
            "/v1/explanations/",
            json={"entity_type": "workflow", "entity_id": "flow-1"},
        )
        writer_client.post(
            "/v1/explanations/",
            json={"entity_type": "agent", "entity_id": "agent-1"},
        )

        # Filter by workflow
        resp = reader_client.get("/v1/explanations/?entity_type=workflow")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) == 1
        assert data[0]["entity_type"] == "workflow"

    def test_list_explanations_filtered_by_entity_id(
        self, writer_client: TestClient, reader_client: TestClient
    ) -> None:
        """Should filter explanations by entity_id."""
        writer_client.post(
            "/v1/explanations/",
            json={"entity_type": "workflow", "entity_id": "flow-1"},
        )
        writer_client.post(
            "/v1/explanations/",
            json={"entity_type": "workflow", "entity_id": "flow-2"},
        )

        resp = reader_client.get("/v1/explanations/?entity_id=flow-1")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) == 1
        assert data[0]["entity_id"] == "flow-1"


class TestExplanationDeletion:
    """Tests for deleting explanations."""

    def test_delete_explanation_success(self, writer_client: TestClient) -> None:
        """Should delete explanation."""
        # Create
        create_resp = writer_client.post(
            "/v1/explanations/",
            json={"entity_type": "workflow", "entity_id": "test-flow"},
        )
        explanation_id = create_resp.json()["id"]

        # Delete
        delete_resp = writer_client.delete(f"/v1/explanations/{explanation_id}")
        assert delete_resp.status_code == 200
        assert "deleted" in delete_resp.json()["message"].lower()

        # Verify deleted
        get_resp = writer_client.get(f"/v1/explanations/{explanation_id}")
        assert get_resp.status_code == 404

    def test_delete_nonexistent_explanation_returns_404(self, writer_client: TestClient) -> None:
        """Should return 404 when deleting nonexistent explanation."""
        resp = writer_client.delete("/v1/explanations/expl-nonexistent")
        assert resp.status_code == 404


# -- Authorization tests -----------------------------------------------------


class TestExplanationAuthorization:
    """Tests for scope enforcement."""

    def test_create_requires_write_scope(self, no_scope_client: TestClient) -> None:
        """Should require workflows:write scope to create."""
        resp = no_scope_client.post(
            "/v1/explanations/",
            json={"entity_type": "workflow", "entity_id": "test-flow"},
        )
        assert resp.status_code == 403
        assert "workflows:write" in resp.json()["detail"]

    def test_get_requires_read_scope(
        self, writer_client: TestClient, no_scope_client: TestClient
    ) -> None:
        """Should require workflows:read scope to retrieve."""
        # Create explanation
        create_resp = writer_client.post(
            "/v1/explanations/",
            json={"entity_type": "workflow", "entity_id": "test-flow"},
        )
        explanation_id = create_resp.json()["id"]

        # Try to get without scope
        resp = no_scope_client.get(f"/v1/explanations/{explanation_id}")
        assert resp.status_code == 403
        assert "workflows:read" in resp.json()["detail"]

    def test_list_requires_read_scope(self, no_scope_client: TestClient) -> None:
        """Should require workflows:read scope to list."""
        resp = no_scope_client.get("/v1/explanations/")
        assert resp.status_code == 403

    def test_delete_requires_write_scope(
        self, writer_client: TestClient, reader_client: TestClient
    ) -> None:
        """Should require workflows:write scope to delete."""
        # Create explanation
        create_resp = writer_client.post(
            "/v1/explanations/",
            json={"entity_type": "workflow", "entity_id": "test-flow"},
        )
        explanation_id = create_resp.json()["id"]

        # Try to delete with only read scope
        resp = reader_client.delete(f"/v1/explanations/{explanation_id}")
        assert resp.status_code == 403

    def test_rerun_fact_check_requires_write_scope(
        self, writer_client: TestClient, reader_client: TestClient
    ) -> None:
        """Rerun endpoint should require workflows:write."""
        create_resp = writer_client.post(
            "/v1/explanations/",
            json={"entity_type": "workflow", "entity_id": "test-flow"},
        )
        explanation_id = create_resp.json()["id"]
        resp = reader_client.post(f"/v1/explanations/{explanation_id}/fact-check")
        assert resp.status_code == 403

    def test_get_claims_requires_read_scope(
        self, writer_client: TestClient, no_scope_client: TestClient
    ) -> None:
        """Claims endpoint should require workflows:read."""
        create_resp = writer_client.post(
            "/v1/explanations/",
            json={"entity_type": "workflow", "entity_id": "test-flow"},
        )
        explanation_id = create_resp.json()["id"]
        resp = no_scope_client.get(f"/v1/explanations/{explanation_id}/claims")
        assert resp.status_code == 403


# -- Fact-check hook tests ---------------------------------------------------


class TestFactCheckHook:
    """Tests for fact-check hook integration."""

    def test_fact_check_hook_invoked_on_creation(self, writer_client: TestClient) -> None:
        """Fact-check hook should be invoked and set status."""
        resp = writer_client.post(
            "/v1/explanations/",
            json={"entity_type": "workflow", "entity_id": "test-flow"},
        )
        assert resp.status_code == 201

        data = resp.json()
        # Hook currently returns SKIPPED
        assert data["fact_check_status"] == "skipped"

    def test_fact_check_status_persisted(
        self, writer_client: TestClient, reader_client: TestClient
    ) -> None:
        """Fact-check status should persist on retrieval."""
        create_resp = writer_client.post(
            "/v1/explanations/",
            json={"entity_type": "workflow", "entity_id": "test-flow"},
        )
        explanation_id = create_resp.json()["id"]

        # Retrieve and verify status persisted
        get_resp = reader_client.get(f"/v1/explanations/{explanation_id}")
        assert get_resp.json()["fact_check_status"] == "skipped"

    def test_fact_check_validates_file_exists_claim(
        self, writer_client: TestClient, tmp_path
    ) -> None:
        """Fact-check should verify deterministic file existence claim."""
        existing_file = tmp_path / "evidence.txt"
        existing_file.write_text("evidence")

        resp = writer_client.post(
            "/v1/explanations/",
            json={
                "entity_type": "workflow",
                "entity_id": "file-check",
                "claims": [
                    {
                        "claim_type": "file_exists",
                        "target": str(existing_file),
                        "description": "Evidence file should exist",
                    }
                ],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["fact_check_status"] == "verified"
        assert len(data["claims"]) == 1
        assert data["claims"][0]["status"] == "verified"
        assert "File exists" in data["claims"][0]["message"]

    def test_fact_check_flags_missing_file_claim(self, writer_client: TestClient) -> None:
        """Fact-check should flag missing files."""
        resp = writer_client.post(
            "/v1/explanations/",
            json={
                "entity_type": "workflow",
                "entity_id": "missing-file",
                "claims": [
                    {
                        "claim_type": "file_exists",
                        "target": "D:/missing/file.txt",
                    }
                ],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["fact_check_status"] == "flagged"
        assert data["claims"][0]["status"] == "flagged"


class TestFactCheckEndpoints:
    """Tests for dedicated Stage 2 fact-check endpoints."""

    def test_rerun_fact_check_updates_status(self, writer_client: TestClient, tmp_path) -> None:
        """Re-run endpoint should update claim status after external state changes."""
        changing_file = tmp_path / "changing.txt"
        explanation_resp = writer_client.post(
            "/v1/explanations/",
            json={
                "entity_type": "workflow",
                "entity_id": "rerun-check",
                "claims": [{"claim_type": "file_exists", "target": str(changing_file)}],
            },
        )
        explanation_id = explanation_resp.json()["id"]
        assert explanation_resp.json()["fact_check_status"] == "flagged"

        changing_file.write_text("now present")

        rerun_resp = writer_client.post(f"/v1/explanations/{explanation_id}/fact-check")
        assert rerun_resp.status_code == 200
        rerun_data = rerun_resp.json()
        assert rerun_data["fact_check_status"] == "verified"
        assert rerun_data["claims"][0]["status"] == "verified"

    def test_get_claims_returns_claim_list(
        self,
        writer_client: TestClient,
        reader_client: TestClient,
    ) -> None:
        """Claims endpoint should return stored claim details."""
        create_resp = writer_client.post(
            "/v1/explanations/",
            json={
                "entity_type": "workflow",
                "entity_id": "claims-check",
                "claims": [
                    {
                        "claim_type": "metadata_equals",
                        "target": "model",
                        "expected": "llama3.1",
                    }
                ],
                "metadata": {"model": "llama3.1"},
            },
        )
        explanation_id = create_resp.json()["id"]
        claims_resp = reader_client.get(f"/v1/explanations/{explanation_id}/claims")
        assert claims_resp.status_code == 200
        claims = claims_resp.json()
        assert len(claims) == 1
        assert claims[0]["claim_type"] == "metadata_equals"
        assert claims[0]["status"] == "verified"


# -- Phase 26 visual page generation tests ----------------------------------


class TestDiffReviewEndpoint:
    """Tests for diff review visual page generation."""

    def test_create_diff_review_success(self, writer_client: TestClient) -> None:
        """Should create diff review with visual HTML content."""
        diff_text = """diff --git a/file.py b/file.py
--- a/file.py
+++ b/file.py
@@ -1,3 +1,4 @@
+import structlog
 import sys
-# old comment
+# new comment
"""
        resp = writer_client.post(
            "/v1/explanations/diff-review",
            json={
                "entity_type": "workflow",
                "entity_id": "test-flow",
                "diff_text": diff_text,
                "metadata": {"branch": "feat/test"},
            },
        )
        assert resp.status_code == 201

        data = resp.json()
        assert data["entity_type"] == "workflow"
        assert data["entity_id"] == "test-flow"
        assert data["mode"] == "diff_review"
        assert "<!DOCTYPE html>" in data["content"]
        assert "Diff Review" in data["content"]
        assert data["fact_check_status"] == "skipped"
        assert data["metadata"]["branch"] == "feat/test"

    def test_diff_review_is_persisted_and_retrievable(
        self, writer_client: TestClient, reader_client: TestClient
    ) -> None:
        """Visual diff explanations should round-trip through the authenticated API."""
        create_resp = writer_client.post(
            "/v1/explanations/diff-review",
            json={
                "entity_type": "pull-request",
                "entity_id": "pr-26",
                "diff_text": "diff --git a/a.py b/a.py\n+print('phase 26')",
                "metadata": {"source_ref": "local-remediation"},
            },
        )
        assert create_resp.status_code == 201
        explanation_id = create_resp.json()["id"]

        get_resp = reader_client.get(f"/v1/explanations/{explanation_id}")
        assert get_resp.status_code == 200
        retrieved = get_resp.json()
        assert retrieved["id"] == explanation_id
        assert retrieved["mode"] == "diff_review"
        assert retrieved["metadata"]["source_ref"] == "local-remediation"
        assert "Diff Review" in retrieved["content"]

    def test_diff_review_requires_write_scope(self, no_scope_client: TestClient) -> None:
        """Should require workflows:write scope."""
        resp = no_scope_client.post(
            "/v1/explanations/diff-review",
            json={
                "entity_type": "workflow",
                "entity_id": "test-flow",
                "diff_text": "diff --git a/f b/f",
            },
        )
        assert resp.status_code == 403
        assert "workflows:write" in resp.json()["detail"]

    def test_diff_review_with_claims(self, writer_client: TestClient, tmp_path) -> None:
        """Should validate claims during diff review creation."""
        evidence = tmp_path / "evidence.txt"
        evidence.write_text("proof")

        resp = writer_client.post(
            "/v1/explanations/diff-review",
            json={
                "entity_type": "workflow",
                "entity_id": "test-flow",
                "diff_text": "diff --git a/f b/f\n+added line",
                "claims": [
                    {
                        "claim_type": "file_exists",
                        "target": str(evidence),
                        "description": "Evidence file",
                    }
                ],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["fact_check_status"] == "verified"
        assert len(data["claims"]) == 1
        assert data["claims"][0]["status"] == "verified"


class TestPlanReviewEndpoint:
    """Tests for plan review visual page generation."""

    def test_create_plan_review_success(self, writer_client: TestClient) -> None:
        """Should create plan review with visual HTML content."""
        plan_text = """# Project Plan

## Phase 1: Setup
Set up the environment.

## Phase 2: Implementation
Implement features.

## Phase 3: Testing
Test everything.
"""
        resp = writer_client.post(
            "/v1/explanations/plan-review",
            json={
                "entity_type": "workflow",
                "entity_id": "project-plan",
                "plan_text": plan_text,
            },
        )
        assert resp.status_code == 201

        data = resp.json()
        assert data["entity_type"] == "workflow"
        assert data["entity_id"] == "project-plan"
        assert data["mode"] == "plan_review"
        assert "<!DOCTYPE html>" in data["content"]
        assert "Plan Review" in data["content"]
        assert "3 sections identified" in data["content"]  # 3 h2 sections

    def test_plan_review_requires_write_scope(self, no_scope_client: TestClient) -> None:
        """Should require workflows:write scope."""
        resp = no_scope_client.post(
            "/v1/explanations/plan-review",
            json={
                "entity_type": "workflow",
                "entity_id": "test",
                "plan_text": "## Section 1",
            },
        )
        assert resp.status_code == 403


class TestProjectRecapEndpoint:
    """Tests for project recap visual page generation."""

    def test_create_project_recap_success(self, writer_client: TestClient) -> None:
        """Should create project recap with highlights."""
        resp = writer_client.post(
            "/v1/explanations/project-recap",
            json={
                "entity_type": "workflow",
                "entity_id": "q4-recap",
                "recap_text": "Completed all Phase 26 objectives.",
                "highlights": [
                    "Added visual page generation",
                    "Implemented diff stats computation",
                    "Created template system",
                ],
            },
        )
        assert resp.status_code == 201

        data = resp.json()
        assert data["entity_type"] == "workflow"
        assert data["entity_id"] == "q4-recap"
        assert data["mode"] == "project_recap"
        assert "<!DOCTYPE html>" in data["content"]
        assert "Project Recap" in data["content"]
        assert "Added visual page generation" in data["content"]

    def test_project_recap_requires_write_scope(self, no_scope_client: TestClient) -> None:
        """Should require workflows:write scope."""
        resp = no_scope_client.post(
            "/v1/explanations/project-recap",
            json={
                "entity_type": "workflow",
                "entity_id": "recap",
                "recap_text": "Summary",
            },
        )
        assert resp.status_code == 403


class TestVisualPageSecurity:
    """Security-focused tests for visual page rendering endpoints."""

    def test_diff_review_escapes_html_content(self, writer_client: TestClient) -> None:
        """Diff payload HTML should be escaped in rendered output."""
        resp = writer_client.post(
            "/v1/explanations/diff-review",
            json={
                "entity_type": "workflow",
                "entity_id": "xss-diff",
                "diff_text": "<script>alert('xss')</script>\n+safe line",
            },
        )
        assert resp.status_code == 201
        content = resp.json()["content"]
        assert "<script>alert('xss')</script>" not in content
        assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in content

    def test_plan_review_escapes_plan_text(self, writer_client: TestClient) -> None:
        """Plan review payload HTML should be escaped in rendered output."""
        resp = writer_client.post(
            "/v1/explanations/plan-review",
            json={
                "entity_type": "workflow",
                "entity_id": "xss-plan",
                "plan_text": "## Safe section\n<script>alert('plan')</script>",
            },
        )
        assert resp.status_code == 201
        content = resp.json()["content"]
        assert "<script>alert('plan')</script>" not in content
        assert "&lt;script&gt;alert(&#x27;plan&#x27;)&lt;/script&gt;" in content

    def test_project_recap_escapes_highlight_items(self, writer_client: TestClient) -> None:
        """Highlight list entries should be escaped before HTML interpolation."""
        resp = writer_client.post(
            "/v1/explanations/project-recap",
            json={
                "entity_type": "workflow",
                "entity_id": "xss-recap",
                "recap_text": "Recap content",
                "highlights": ["</li><script>alert('x')</script><li>"],
            },
        )
        assert resp.status_code == 201
        content = resp.json()["content"]
        assert "<script>alert('x')</script>" not in content
        assert "&lt;/li&gt;&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;&lt;li&gt;" in content
