from __future__ import annotations

from fastapi.testclient import TestClient

from agent33.api.routes.resources import router
from agent33.main import app
from agent33.resources.manifest import ResourceKind, ResourceManifest
from agent33.resources.service import ResourceService, set_resource_service
from agent33.security.auth import create_access_token


def _client() -> TestClient:
    token = create_access_token(
        "resource-user",
        scopes=["workflows:read", "tools:execute"],
        tenant_id="tenant-a",
    )
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def setup_function() -> None:
    set_resource_service(
        ResourceService(
            [
                ResourceManifest(
                    id="pack.safe-ops",
                    name="Safe Ops",
                    version="1.0.0",
                    kind=ResourceKind.PACK,
                    description="Operational safety pack.",
                    tags=["ops", "safety"],
                ),
                ResourceManifest(
                    id="skill.research",
                    name="Research Skill",
                    version="0.1.0",
                    kind=ResourceKind.SKILL,
                    description="Evidence gathering skill.",
                    tags=["research"],
                ),
            ]
        )
    )


def test_resource_routes_registered() -> None:
    paths = {route.path for route in router.routes}

    assert "/v1/resources/search" in paths or "/search" in paths
    assert "/v1/resources/{resource_id}" in paths or "/{resource_id}" in paths
    assert "/v1/resources/validate" in paths or "/validate" in paths
    assert "/v1/resources/submit" in paths or "/submit" in paths


def test_resource_search_endpoint_filters_by_query_and_kind() -> None:
    client = _client()

    response = client.get("/v1/resources/search", params={"query": "ops", "kind": "pack"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == "pack.safe-ops"


def test_resource_detail_endpoint_returns_manifest() -> None:
    client = _client()

    response = client.get("/v1/resources/skill.research")

    assert response.status_code == 200
    assert response.json()["name"] == "Research Skill"


def test_resource_detail_endpoint_404s_for_unknown_resource() -> None:
    client = _client()

    response = client.get("/v1/resources/missing")

    assert response.status_code == 404


def test_resource_validate_endpoint_returns_valid_manifest() -> None:
    client = _client()

    response = client.post(
        "/v1/resources/validate",
        json={
            "id": "workflow.example",
            "name": "Example Workflow",
            "version": "0.1.0",
            "kind": "workflow",
            "tags": ["Example", "example"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "workflow"
    assert body["tags"] == ["example"]


def test_resource_submission_endpoint_registers_pending_manifest() -> None:
    client = _client()

    response = client.post(
        "/v1/resources/submit",
        json={
            "id": "prompt.review",
            "name": "Review Prompt",
            "version": "0.1.0",
            "kind": "prompt",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["resource_id"] == "prompt.review"
    assert client.get("/v1/resources/prompt.review").status_code == 200


def test_resource_quarantine_endpoint_marks_submission() -> None:
    client = _client()
    client.post(
        "/v1/resources/submit",
        json={
            "id": "policy.filesystem",
            "name": "Filesystem Policy",
            "version": "1.0.0",
            "kind": "policy",
        },
    )

    response = client.post(
        "/v1/resources/policy.filesystem/quarantine",
        json={"note": "Needs rollback instructions."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "quarantined"
    assert body["reviewer_notes"] == ["Needs rollback instructions."]


def test_resource_feedback_endpoint_records_review_notes() -> None:
    client = _client()
    client.post(
        "/v1/resources/submit",
        json={
            "id": "eval.smoke",
            "name": "Smoke Eval",
            "version": "0.1.0",
            "kind": "eval",
        },
    )

    response = client.post("/v1/resources/eval.smoke/feedback", json={"note": "Add examples."})

    assert response.status_code == 200
    assert response.json()["reviewer_notes"] == ["Add examples."]
