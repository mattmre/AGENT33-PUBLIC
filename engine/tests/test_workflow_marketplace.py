"""Tests for the workflow template marketplace (S41).

Covers:
- Template CRUD (register, get, list, search, delete)
- Category and tag filtering
- Install flow with tenant tracking
- Rating system with per-tenant deduplication
- Statistics computation
- Template-from-workflow creation
- API route tests with auth mocking
- Duplicate/edge-case handling
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from agent33.workflows.marketplace import (
    TemplateCategory,
    TemplateRating,
    TemplateSearchQuery,
    TemplateSortField,
    WorkflowMarketplace,
    WorkflowTemplate,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def marketplace() -> WorkflowMarketplace:
    """Create a fresh in-memory marketplace (no directory)."""
    return WorkflowMarketplace()


def _make_template(
    *,
    name: str = "test-template",
    description: str = "A test template",
    category: TemplateCategory = TemplateCategory.AUTOMATION,
    tags: list[str] | None = None,
    version: str = "1.0.0",
    author: str = "tester",
) -> WorkflowTemplate:
    """Factory for creating test templates."""
    return WorkflowTemplate(
        name=name,
        description=description,
        category=category,
        tags=tags or ["test"],
        version=version,
        author=author,
        template_definition={
            "name": name,
            "version": version,
            "steps": [{"id": "step-a", "action": "invoke-agent", "agent": "test"}],
        },
    )


# ===========================================================================
# Unit tests: WorkflowMarketplace service
# ===========================================================================


class TestTemplateCRUD:
    """Register, get, list, and delete templates."""

    def test_register_and_get(self, marketplace: WorkflowMarketplace) -> None:
        template = _make_template(name="my-workflow")
        tid = marketplace.register_template(template)

        assert tid == template.id
        retrieved = marketplace.get_template(tid)
        assert retrieved is not None
        assert retrieved.name == "my-workflow"
        assert retrieved.category == TemplateCategory.AUTOMATION
        assert retrieved.author == "tester"

    def test_get_nonexistent_returns_none(self, marketplace: WorkflowMarketplace) -> None:
        assert marketplace.get_template("nonexistent-id") is None

    def test_list_returns_sorted_by_name(self, marketplace: WorkflowMarketplace) -> None:
        marketplace.register_template(_make_template(name="zulu-wf"))
        marketplace.register_template(_make_template(name="alpha-wf"))
        marketplace.register_template(_make_template(name="mike-wf"))

        listed = marketplace.list_templates()
        names = [t.name for t in listed]
        assert names == ["alpha-wf", "mike-wf", "zulu-wf"]

    def test_list_with_pagination(self, marketplace: WorkflowMarketplace) -> None:
        for i in range(5):
            marketplace.register_template(_make_template(name=f"wf-{i:02d}"))

        page = marketplace.list_templates(limit=2, offset=1)
        assert len(page) == 2
        assert page[0].name == "wf-01"
        assert page[1].name == "wf-02"

    def test_list_with_category_filter(self, marketplace: WorkflowMarketplace) -> None:
        marketplace.register_template(
            _make_template(name="auto-wf", category=TemplateCategory.AUTOMATION)
        )
        marketplace.register_template(
            _make_template(name="research-wf", category=TemplateCategory.RESEARCH)
        )
        marketplace.register_template(
            _make_template(name="deploy-wf", category=TemplateCategory.DEPLOYMENT)
        )

        auto_only = marketplace.list_templates(category=TemplateCategory.AUTOMATION)
        assert len(auto_only) == 1
        assert auto_only[0].name == "auto-wf"

    def test_delete_existing_template(self, marketplace: WorkflowMarketplace) -> None:
        template = _make_template(name="to-delete")
        tid = marketplace.register_template(template)

        assert marketplace.count == 1
        assert marketplace.remove_template(tid) is True
        assert marketplace.count == 0
        assert marketplace.get_template(tid) is None

    def test_delete_nonexistent_returns_false(self, marketplace: WorkflowMarketplace) -> None:
        assert marketplace.remove_template("no-such-id") is False

    def test_delete_also_removes_ratings_and_installs(
        self, marketplace: WorkflowMarketplace
    ) -> None:
        template = _make_template()
        tid = marketplace.register_template(template)

        # Add rating and install
        marketplace.rate_template(tid, TemplateRating(template_id=tid, stars=4, tenant_id="t1"))
        marketplace.install_template(tid, "t1")

        marketplace.remove_template(tid)
        # Verify internal state is cleaned up
        assert marketplace.get_ratings(tid) == []

    def test_count_property(self, marketplace: WorkflowMarketplace) -> None:
        assert marketplace.count == 0
        marketplace.register_template(_make_template(name="one"))
        assert marketplace.count == 1
        marketplace.register_template(_make_template(name="two"))
        assert marketplace.count == 2


class TestTemplateSearch:
    """Search templates by query string, category, and tags."""

    def test_search_by_name(self, marketplace: WorkflowMarketplace) -> None:
        marketplace.register_template(_make_template(name="data-pipeline"))
        marketplace.register_template(_make_template(name="code-review"))
        marketplace.register_template(_make_template(name="pipeline-deploy"))

        query = TemplateSearchQuery(query="pipeline")
        results = marketplace.search_templates(query)
        names = {t.name for t in results}
        assert names == {"data-pipeline", "pipeline-deploy"}

    def test_search_by_description(self, marketplace: WorkflowMarketplace) -> None:
        marketplace.register_template(
            _make_template(name="wf-a", description="handles data transformation")
        )
        marketplace.register_template(
            _make_template(name="wf-b", description="code generation workflow")
        )

        results = marketplace.search_templates(TemplateSearchQuery(query="data"))
        assert len(results) == 1
        assert results[0].name == "wf-a"

    def test_search_by_tags(self, marketplace: WorkflowMarketplace) -> None:
        marketplace.register_template(_make_template(name="wf-tagged", tags=["ml", "python"]))
        marketplace.register_template(_make_template(name="wf-other", tags=["go"]))

        results = marketplace.search_templates(TemplateSearchQuery(query="ml"))
        assert len(results) == 1
        assert results[0].name == "wf-tagged"

    def test_search_filter_by_category(self, marketplace: WorkflowMarketplace) -> None:
        marketplace.register_template(
            _make_template(name="auto-wf", category=TemplateCategory.AUTOMATION)
        )
        marketplace.register_template(
            _make_template(name="auto-research", category=TemplateCategory.RESEARCH)
        )

        results = marketplace.search_templates(
            TemplateSearchQuery(query="auto", category=TemplateCategory.AUTOMATION)
        )
        assert len(results) == 1
        assert results[0].name == "auto-wf"

    def test_search_filter_by_tag_set(self, marketplace: WorkflowMarketplace) -> None:
        marketplace.register_template(_make_template(name="full", tags=["ml", "python", "gpu"]))
        marketplace.register_template(_make_template(name="partial", tags=["ml", "go"]))

        # Require both ml AND python
        results = marketplace.search_templates(TemplateSearchQuery(tags=["ml", "python"]))
        assert len(results) == 1
        assert results[0].name == "full"

    def test_search_sort_by_rating(self, marketplace: WorkflowMarketplace) -> None:
        t1 = _make_template(name="low-rated")
        t2 = _make_template(name="high-rated")
        tid1 = marketplace.register_template(t1)
        tid2 = marketplace.register_template(t2)

        marketplace.rate_template(tid1, TemplateRating(template_id=tid1, stars=2, tenant_id="t1"))
        marketplace.rate_template(tid2, TemplateRating(template_id=tid2, stars=5, tenant_id="t1"))

        results = marketplace.search_templates(
            TemplateSearchQuery(sort_by=TemplateSortField.RATING)
        )
        # Descending order for rating
        assert results[0].name == "high-rated"
        assert results[1].name == "low-rated"

    def test_search_pagination(self, marketplace: WorkflowMarketplace) -> None:
        for i in range(10):
            marketplace.register_template(_make_template(name=f"wf-{i:02d}"))

        results = marketplace.search_templates(TemplateSearchQuery(limit=3, offset=2))
        assert len(results) == 3

    def test_search_empty_query_returns_all(self, marketplace: WorkflowMarketplace) -> None:
        marketplace.register_template(_make_template(name="a"))
        marketplace.register_template(_make_template(name="b"))

        results = marketplace.search_templates(TemplateSearchQuery())
        assert len(results) == 2


class TestTemplateInstall:
    """Template installation flow."""

    def test_install_returns_definition(self, marketplace: WorkflowMarketplace) -> None:
        template = _make_template(name="install-me")
        tid = marketplace.register_template(template)

        result = marketplace.install_template(tid, "tenant-abc")
        assert result.installed is True
        assert result.template_id == tid
        assert result.workflow_name == "install-me"
        assert result.tenant_id == "tenant-abc"
        assert result.definition["name"] == "install-me"
        assert result.definition["steps"] is not None

    def test_install_increments_count(self, marketplace: WorkflowMarketplace) -> None:
        template = _make_template(name="popular")
        tid = marketplace.register_template(template)

        marketplace.install_template(tid, "tenant-1")
        marketplace.install_template(tid, "tenant-2")
        marketplace.install_template(tid, "tenant-3")

        updated = marketplace.get_template(tid)
        assert updated is not None
        assert updated.install_count == 3

    def test_install_same_tenant_counted_once(self, marketplace: WorkflowMarketplace) -> None:
        template = _make_template()
        tid = marketplace.register_template(template)

        marketplace.install_template(tid, "tenant-1")
        marketplace.install_template(tid, "tenant-1")

        updated = marketplace.get_template(tid)
        assert updated is not None
        assert updated.install_count == 1

    def test_install_nonexistent_raises(self, marketplace: WorkflowMarketplace) -> None:
        with pytest.raises(ValueError, match="not found"):
            marketplace.install_template("does-not-exist", "tenant-1")


class TestTemplateRating:
    """Star rating system."""

    def test_rate_template(self, marketplace: WorkflowMarketplace) -> None:
        template = _make_template()
        tid = marketplace.register_template(template)

        marketplace.rate_template(tid, TemplateRating(template_id=tid, stars=4, tenant_id="t1"))

        updated = marketplace.get_template(tid)
        assert updated is not None
        assert updated.rating == 4.0
        assert updated.rating_count == 1

    def test_multiple_ratings_average(self, marketplace: WorkflowMarketplace) -> None:
        template = _make_template()
        tid = marketplace.register_template(template)

        marketplace.rate_template(tid, TemplateRating(template_id=tid, stars=5, tenant_id="t1"))
        marketplace.rate_template(tid, TemplateRating(template_id=tid, stars=3, tenant_id="t2"))

        updated = marketplace.get_template(tid)
        assert updated is not None
        assert updated.rating == 4.0  # (5+3)/2
        assert updated.rating_count == 2

    def test_same_tenant_replaces_rating(self, marketplace: WorkflowMarketplace) -> None:
        template = _make_template()
        tid = marketplace.register_template(template)

        marketplace.rate_template(tid, TemplateRating(template_id=tid, stars=1, tenant_id="t1"))
        marketplace.rate_template(tid, TemplateRating(template_id=tid, stars=5, tenant_id="t1"))

        updated = marketplace.get_template(tid)
        assert updated is not None
        assert updated.rating == 5.0
        assert updated.rating_count == 1

    def test_rate_nonexistent_raises(self, marketplace: WorkflowMarketplace) -> None:
        with pytest.raises(ValueError, match="not found"):
            marketplace.rate_template(
                "nope", TemplateRating(template_id="nope", stars=3, tenant_id="t1")
            )

    def test_get_ratings(self, marketplace: WorkflowMarketplace) -> None:
        template = _make_template()
        tid = marketplace.register_template(template)

        marketplace.rate_template(
            tid, TemplateRating(template_id=tid, stars=4, tenant_id="t1", comment="good")
        )
        marketplace.rate_template(
            tid, TemplateRating(template_id=tid, stars=2, tenant_id="t2", comment="ok")
        )

        ratings = marketplace.get_ratings(tid)
        assert len(ratings) == 2
        comments = {r.comment for r in ratings}
        assert comments == {"good", "ok"}

    def test_rating_validation_bounds(self) -> None:
        with pytest.raises(ValueError):
            TemplateRating(template_id="x", stars=0, tenant_id="t1")
        with pytest.raises(ValueError):
            TemplateRating(template_id="x", stars=6, tenant_id="t1")


class TestTemplateStats:
    """Marketplace statistics."""

    def test_empty_stats(self, marketplace: WorkflowMarketplace) -> None:
        stats = marketplace.get_template_stats()
        assert stats["total_templates"] == 0
        assert stats["by_category"] == {}
        assert stats["total_installs"] == 0
        assert stats["total_ratings"] == 0
        assert stats["average_rating"] == 0.0

    def test_stats_with_data(self, marketplace: WorkflowMarketplace) -> None:
        t1 = _make_template(name="a", category=TemplateCategory.AUTOMATION)
        t2 = _make_template(name="b", category=TemplateCategory.AUTOMATION)
        t3 = _make_template(name="c", category=TemplateCategory.RESEARCH)
        tid1 = marketplace.register_template(t1)
        tid2 = marketplace.register_template(t2)
        marketplace.register_template(t3)

        marketplace.install_template(tid1, "t1")
        marketplace.install_template(tid2, "t1")
        marketplace.install_template(tid2, "t2")

        marketplace.rate_template(tid1, TemplateRating(template_id=tid1, stars=4, tenant_id="t1"))
        marketplace.rate_template(tid2, TemplateRating(template_id=tid2, stars=2, tenant_id="t1"))

        stats = marketplace.get_template_stats()
        assert stats["total_templates"] == 3
        assert stats["by_category"]["automation"] == 2
        assert stats["by_category"]["research"] == 1
        assert stats["total_installs"] == 3  # 1 + 2
        assert stats["total_ratings"] == 2
        assert stats["average_rating"] == 3.0  # (4+2)/2


class TestCreateFromWorkflow:
    """Create marketplace template from an existing WorkflowDefinition."""

    def test_create_from_workflow(self, marketplace: WorkflowMarketplace) -> None:
        from agent33.workflows.definition import WorkflowDefinition

        wf = WorkflowDefinition(
            name="source-wf",
            version="2.0.0",
            description="A real workflow",
            steps=[{"id": "s1", "action": "invoke-agent", "agent": "test"}],
        )

        tid = marketplace.create_template_from_workflow(
            wf,
            name="marketplace-version",
            description="Template from existing workflow",
            category=TemplateCategory.DATA_PIPELINE,
            tags=["etl", "batch"],
            author="builder",
        )

        template = marketplace.get_template(tid)
        assert template is not None
        assert template.name == "marketplace-version"
        assert template.description == "Template from existing workflow"
        assert template.category == TemplateCategory.DATA_PIPELINE
        assert template.tags == ["etl", "batch"]
        assert template.version == "2.0.0"
        assert template.author == "builder"
        # The embedded definition should have the workflow name
        assert template.template_definition["name"] == "source-wf"

    def test_create_from_workflow_defaults(self, marketplace: WorkflowMarketplace) -> None:
        from agent33.workflows.definition import (
            WorkflowDefinition,
            WorkflowMetadata,
        )

        wf = WorkflowDefinition(
            name="auto-named",
            version="1.0.0",
            description="auto desc",
            steps=[{"id": "s1", "action": "validate"}],
            metadata=WorkflowMetadata(author="original-author", tags=["infra"]),
        )

        tid = marketplace.create_template_from_workflow(wf)
        template = marketplace.get_template(tid)
        assert template is not None
        assert template.name == "auto-named"
        assert template.description == "auto desc"
        assert template.author == "original-author"
        assert template.tags == ["infra"]


# ===========================================================================
# API route tests
# ===========================================================================


def _build_test_app() -> Any:
    """Build a minimal FastAPI app with workflow marketplace routes and mock auth."""
    from fastapi import FastAPI

    from agent33.api.routes.workflow_marketplace import router, set_workflow_marketplace

    app = FastAPI()
    app.include_router(router)

    mp = WorkflowMarketplace()
    app.state.workflow_marketplace = mp
    set_workflow_marketplace(mp)

    # Install mock auth middleware that injects a user with required scopes
    from starlette.middleware.base import BaseHTTPMiddleware

    class FakeAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Any, call_next: Any) -> Any:
            user = MagicMock()
            user.tenant_id = "test-tenant"
            user.scopes = [
                "workflows:read",
                "workflows:write",
                "workflows:execute",
                "admin",
            ]
            user.sub = "test-user"
            request.state.user = user
            return await call_next(request)

    app.add_middleware(FakeAuthMiddleware)
    return app, mp


@pytest.fixture()
def test_app() -> tuple[Any, WorkflowMarketplace]:
    return _build_test_app()


class TestMarketplaceAPI:
    """API route tests with proper auth mocking."""

    async def test_list_templates_empty(self, test_app: tuple[Any, WorkflowMarketplace]) -> None:
        app, _ = test_app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/workflow-marketplace/templates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["templates"] == []
        assert data["count"] == 0
        assert data["total"] == 0

    async def test_publish_and_get_template(
        self, test_app: tuple[Any, WorkflowMarketplace]
    ) -> None:
        app, _ = test_app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Publish
            resp = await client.post(
                "/v1/workflow-marketplace/templates",
                json={
                    "name": "api-template",
                    "description": "Created via API",
                    "category": "automation",
                    "tags": ["ci", "deploy"],
                    "version": "1.2.0",
                    "author": "api-user",
                    "template_definition": {
                        "name": "api-template",
                        "version": "1.2.0",
                        "steps": [{"id": "s1", "action": "validate"}],
                    },
                },
            )
            assert resp.status_code == 201
            body = resp.json()
            assert body["created"] is True
            assert body["name"] == "api-template"
            template_id = body["template_id"]

            # Get
            resp = await client.get(f"/v1/workflow-marketplace/templates/{template_id}")
            assert resp.status_code == 200
            detail = resp.json()
            assert detail["name"] == "api-template"
            assert detail["description"] == "Created via API"
            assert detail["category"] == "automation"
            assert detail["tags"] == ["ci", "deploy"]
            assert detail["author"] == "api-user"
            assert detail["version"] == "1.2.0"

    async def test_get_nonexistent_template(
        self, test_app: tuple[Any, WorkflowMarketplace]
    ) -> None:
        app, _ = test_app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/workflow-marketplace/templates/no-such-id")
        assert resp.status_code == 404

    async def test_install_template(self, test_app: tuple[Any, WorkflowMarketplace]) -> None:
        app, mp = test_app
        template = _make_template(name="installable")
        tid = mp.register_template(template)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(f"/v1/workflow-marketplace/templates/{tid}/install")
        assert resp.status_code == 200
        data = resp.json()
        assert data["installed"] is True
        assert data["template_id"] == tid
        assert data["workflow_name"] == "installable"
        assert data["tenant_id"] == "test-tenant"

    async def test_install_nonexistent_template(
        self, test_app: tuple[Any, WorkflowMarketplace]
    ) -> None:
        app, _ = test_app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/v1/workflow-marketplace/templates/missing/install")
        assert resp.status_code == 404

    async def test_rate_template(self, test_app: tuple[Any, WorkflowMarketplace]) -> None:
        app, mp = test_app
        template = _make_template(name="rateable")
        tid = mp.register_template(template)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/v1/workflow-marketplace/templates/{tid}/rate",
                json={"stars": 4, "comment": "Great template"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["template_id"] == tid
        assert data["stars"] == 4
        assert data["current_rating"] == 4.0
        assert data["rating_count"] == 1

    async def test_rate_nonexistent_template(
        self, test_app: tuple[Any, WorkflowMarketplace]
    ) -> None:
        app, _ = test_app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/workflow-marketplace/templates/nope/rate",
                json={"stars": 3},
            )
        assert resp.status_code == 404

    async def test_rate_invalid_stars(self, test_app: tuple[Any, WorkflowMarketplace]) -> None:
        app, mp = test_app
        template = _make_template(name="to-rate-bad")
        tid = mp.register_template(template)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/v1/workflow-marketplace/templates/{tid}/rate",
                json={"stars": 0},
            )
        assert resp.status_code == 422  # Pydantic validation error

    async def test_stats_endpoint(self, test_app: tuple[Any, WorkflowMarketplace]) -> None:
        app, mp = test_app
        t1 = _make_template(name="stat-a", category=TemplateCategory.AUTOMATION)
        t2 = _make_template(name="stat-b", category=TemplateCategory.RESEARCH)
        mp.register_template(t1)
        mp.register_template(t2)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/workflow-marketplace/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_templates"] == 2
        assert data["by_category"]["automation"] == 1
        assert data["by_category"]["research"] == 1

    async def test_delete_template(self, test_app: tuple[Any, WorkflowMarketplace]) -> None:
        app, mp = test_app
        template = _make_template(name="deleteable")
        tid = mp.register_template(template)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete(f"/v1/workflow-marketplace/templates/{tid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] is True
        assert data["template_id"] == tid

        # Verify it's gone
        assert mp.get_template(tid) is None

    async def test_delete_nonexistent_template(
        self, test_app: tuple[Any, WorkflowMarketplace]
    ) -> None:
        app, _ = test_app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/v1/workflow-marketplace/templates/ghost")
        assert resp.status_code == 404

    async def test_search_via_query_param(self, test_app: tuple[Any, WorkflowMarketplace]) -> None:
        app, mp = test_app
        mp.register_template(_make_template(name="data-etl"))
        mp.register_template(_make_template(name="code-review"))
        mp.register_template(_make_template(name="data-sync"))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/workflow-marketplace/templates", params={"q": "data"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        names = {t["name"] for t in data["templates"]}
        assert names == {"data-etl", "data-sync"}

    async def test_search_via_category_param(
        self, test_app: tuple[Any, WorkflowMarketplace]
    ) -> None:
        app, mp = test_app
        mp.register_template(_make_template(name="a", category=TemplateCategory.DEPLOYMENT))
        mp.register_template(_make_template(name="b", category=TemplateCategory.REVIEW))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/v1/workflow-marketplace/templates",
                params={"category": "deployment"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["templates"][0]["name"] == "a"

    async def test_search_via_tags_param(self, test_app: tuple[Any, WorkflowMarketplace]) -> None:
        app, mp = test_app
        mp.register_template(_make_template(name="full", tags=["ml", "python"]))
        mp.register_template(_make_template(name="partial", tags=["ml"]))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/v1/workflow-marketplace/templates",
                params={"tags": "ml,python"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["templates"][0]["name"] == "full"


class TestMarketplaceAPIUninitialised:
    """API errors when marketplace is not initialized."""

    async def test_503_when_marketplace_not_set(self) -> None:
        from fastapi import FastAPI

        from agent33.api.routes.workflow_marketplace import router

        app = FastAPI()
        app.include_router(router)

        # No marketplace set on app.state, no module-level fallback

        from starlette.middleware.base import BaseHTTPMiddleware

        class FakeAuthMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Any, call_next: Any) -> Any:
                user = MagicMock()
                user.scopes = ["admin"]
                user.tenant_id = "t1"
                request.state.user = user
                return await call_next(request)

        app.add_middleware(FakeAuthMiddleware)

        # Temporarily clear module-level marketplace
        import agent33.api.routes.workflow_marketplace as wm_mod

        old = wm_mod._marketplace
        wm_mod._marketplace = None
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/v1/workflow-marketplace/templates")
            assert resp.status_code == 503
            assert "not initialized" in resp.json()["detail"]
        finally:
            wm_mod._marketplace = old
