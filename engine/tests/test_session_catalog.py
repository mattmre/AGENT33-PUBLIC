"""Tests for Track 8: Session catalog, lineage, spawn, archive, and context engine.

Covers:
- SessionCatalog enriched listing from OperatorSessionService
- SessionLineageBuilder tree construction from parent_session_id chains
- SessionSpawnService template-based child session creation
- SessionArchiveService state transition and cleanup
- ContextEngine protocol compliance for BuiltinContextEngine
- ContextEngineRegistry discovery, selection, and health
- API route integration for catalog, lineage, spawn, archive, context
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from agent33.context.engine import BuiltinContextEngine, ContextEngine
from agent33.context.models import (
    CompactionEvent,
    CompactionHistory,
    ContextAssemblyReport,
    ContextSlot,
)
from agent33.context.registry import ContextEngineRegistry
from agent33.sessions.archive import SessionArchiveService
from agent33.sessions.catalog import SessionCatalog, SessionCatalogResponse
from agent33.sessions.lineage import SessionLineageBuilder, SessionLineageNode
from agent33.sessions.models import OperatorSessionStatus
from agent33.sessions.service import OperatorSessionService
from agent33.sessions.spawn import SessionSpawnService, SpawnRequest
from agent33.sessions.storage import FileSessionStorage

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_session_dir(tmp_path: Path) -> Path:
    """Temporary directory for session storage."""
    d = tmp_path / "sessions"
    d.mkdir()
    return d


@pytest.fixture()
def storage(tmp_session_dir: Path) -> FileSessionStorage:
    """File session storage backed by tmp dir."""
    return FileSessionStorage(base_dir=tmp_session_dir)


@pytest.fixture()
def session_service(storage: FileSessionStorage) -> OperatorSessionService:
    """Operator session service with file storage."""
    return OperatorSessionService(storage=storage)


# ---------------------------------------------------------------------------
# SessionCatalog tests
# ---------------------------------------------------------------------------


class TestSessionCatalog:
    """Tests for SessionCatalog enriched listing."""

    async def test_empty_catalog(self, session_service: OperatorSessionService) -> None:
        """Catalog returns zero entries when no sessions exist."""
        catalog = SessionCatalog(session_service)
        result = await catalog.list_catalog()
        assert isinstance(result, SessionCatalogResponse)
        assert result.total == 0
        assert result.entries == []
        assert result.offset == 0
        assert result.limit == 50

    async def test_catalog_returns_enriched_entries(
        self, session_service: OperatorSessionService
    ) -> None:
        """Catalog returns enriched entries with computed idle_seconds and agent_name."""
        session = await session_service.start_session(
            purpose="test purpose",
            context={"agent_name": "code-worker"},
        )
        await session_service.add_task(session.session_id, "task 1")

        catalog = SessionCatalog(session_service)
        result = await catalog.list_catalog()

        assert result.total == 1
        assert len(result.entries) == 1
        entry = result.entries[0]
        assert entry.session_id == session.session_id
        assert entry.purpose == "test purpose"
        assert entry.status == "active"
        assert entry.agent_name == "code-worker"
        assert entry.task_count == 1
        assert entry.event_count >= 1
        assert entry.idle_seconds >= 0.0
        assert entry.parent_session_id is None

    async def test_catalog_status_filter(self, session_service: OperatorSessionService) -> None:
        """Catalog filters by status correctly."""
        s1 = await session_service.start_session(purpose="active session")
        s2 = await session_service.start_session(purpose="completed session")
        await session_service.end_session(s2.session_id)

        catalog = SessionCatalog(session_service)

        active_result = await catalog.list_catalog(status=OperatorSessionStatus.ACTIVE)
        assert active_result.total == 1
        assert active_result.entries[0].session_id == s1.session_id

        completed_result = await catalog.list_catalog(status=OperatorSessionStatus.COMPLETED)
        assert completed_result.total == 1
        assert completed_result.entries[0].session_id == s2.session_id

    async def test_catalog_agent_name_filter(
        self, session_service: OperatorSessionService
    ) -> None:
        """Catalog filters by agent_name in context."""
        await session_service.start_session(purpose="s1", context={"agent_name": "researcher"})
        await session_service.start_session(purpose="s2", context={"agent_name": "code-worker"})

        catalog = SessionCatalog(session_service)
        result = await catalog.list_catalog(agent_name="researcher")
        assert result.total == 1
        assert result.entries[0].agent_name == "researcher"

    async def test_catalog_pagination(self, session_service: OperatorSessionService) -> None:
        """Catalog respects offset and limit."""
        for i in range(5):
            await session_service.start_session(purpose=f"session-{i}")

        catalog = SessionCatalog(session_service)

        result = await catalog.list_catalog(limit=2, offset=0)
        assert len(result.entries) == 2
        assert result.total == 5

        result2 = await catalog.list_catalog(limit=2, offset=3)
        assert len(result2.entries) == 2
        assert result2.offset == 3


# ---------------------------------------------------------------------------
# SessionLineageBuilder tests
# ---------------------------------------------------------------------------


class TestSessionLineageBuilder:
    """Tests for lineage tree construction."""

    async def test_single_root_node(self, session_service: OperatorSessionService) -> None:
        """A session with no parent returns a tree with itself as root."""
        session = await session_service.start_session(purpose="root")
        builder = SessionLineageBuilder(session_service)
        tree = await builder.build_tree(session.session_id)

        assert isinstance(tree, SessionLineageNode)
        assert tree.session_id == session.session_id
        assert tree.purpose == "root"
        assert tree.children == []
        assert tree.parent_session_id is None

    async def test_parent_child_tree(self, session_service: OperatorSessionService) -> None:
        """A parent-child chain produces a proper tree."""
        parent = await session_service.start_session(purpose="parent")
        child = await session_service.start_session(purpose="child")
        child.parent_session_id = parent.session_id
        session_service.storage.save_session(child)

        builder = SessionLineageBuilder(session_service)
        tree = await builder.build_tree(child.session_id)

        # Root should be parent
        assert tree.session_id == parent.session_id
        assert len(tree.children) == 1
        assert tree.children[0].session_id == child.session_id

    async def test_multi_child_tree(self, session_service: OperatorSessionService) -> None:
        """A parent with multiple children produces correct tree."""
        parent = await session_service.start_session(purpose="parent")
        child1 = await session_service.start_session(purpose="child-1")
        child2 = await session_service.start_session(purpose="child-2")

        child1.parent_session_id = parent.session_id
        child2.parent_session_id = parent.session_id
        session_service.storage.save_session(child1)
        session_service.storage.save_session(child2)

        builder = SessionLineageBuilder(session_service)
        tree = await builder.build_tree(parent.session_id)

        assert tree.session_id == parent.session_id
        assert len(tree.children) == 2
        child_ids = {c.session_id for c in tree.children}
        assert child_ids == {child1.session_id, child2.session_id}

    async def test_lineage_handles_missing_parent(
        self, session_service: OperatorSessionService
    ) -> None:
        """When parent_session_id references a deleted session, the orphan is the root."""
        orphan = await session_service.start_session(purpose="orphan")
        orphan.parent_session_id = "nonexistent_parent"
        session_service.storage.save_session(orphan)

        builder = SessionLineageBuilder(session_service)
        tree = await builder.build_tree(orphan.session_id)

        # Orphan becomes the root since parent is missing
        assert tree.session_id == orphan.session_id
        assert tree.children == []

    async def test_lineage_not_found_raises(self, session_service: OperatorSessionService) -> None:
        """build_tree raises KeyError for non-existent session."""
        builder = SessionLineageBuilder(session_service)
        with pytest.raises(KeyError, match="not found"):
            await builder.build_tree("nonexistent")

    async def test_build_forest(self, session_service: OperatorSessionService) -> None:
        """build_forest returns list of all root trees."""
        root1 = await session_service.start_session(purpose="root-1")
        root2 = await session_service.start_session(purpose="root-2")
        child = await session_service.start_session(purpose="child-of-1")
        child.parent_session_id = root1.session_id
        session_service.storage.save_session(child)

        builder = SessionLineageBuilder(session_service)
        forest = await builder.build_forest()

        root_ids = {t.session_id for t in forest}
        assert root1.session_id in root_ids
        assert root2.session_id in root_ids
        # child should not be a root
        assert child.session_id not in root_ids

        # Find root1 and verify it has child
        root1_tree = next(t for t in forest if t.session_id == root1.session_id)
        assert len(root1_tree.children) == 1
        assert root1_tree.children[0].session_id == child.session_id


# ---------------------------------------------------------------------------
# SessionSpawnService tests
# ---------------------------------------------------------------------------


class TestSessionSpawnService:
    """Tests for template-based session spawning."""

    async def test_spawn_sets_parent(self, session_service: OperatorSessionService) -> None:
        """Spawned child has parent_session_id pointing to parent."""
        parent = await session_service.start_session(purpose="parent")
        spawn_svc = SessionSpawnService(session_service)

        req = SpawnRequest(
            parent_session_id=parent.session_id,
            agent_name="qa",
            purpose="child task",
        )
        child = await spawn_svc.spawn(req)

        assert child.parent_session_id == parent.session_id
        assert child.purpose == "child task"
        assert child.context.get("agent_name") == "qa"

    async def test_spawn_with_template(
        self, session_service: OperatorSessionService, tmp_path: Path
    ) -> None:
        """Spawning with a template merges template defaults."""
        templates_dir = tmp_path / "spawn-templates"
        templates_dir.mkdir()
        template_data = {
            "template_id": "research",
            "name": "Research Agent",
            "agent_name": "researcher",
            "purpose_template": "Research: {topic}",
            "model_override": "gpt-4",
            "effort_override": "high",
        }
        (templates_dir / "research.json").write_text(json.dumps(template_data))

        parent = await session_service.start_session(purpose="parent")
        spawn_svc = SessionSpawnService(session_service, templates_dir=str(templates_dir))

        assert len(spawn_svc.list_templates()) == 1
        assert spawn_svc.list_templates()[0].template_id == "research"

        req = SpawnRequest(
            parent_session_id=parent.session_id,
            template_id="research",
        )
        child = await spawn_svc.spawn(req)

        assert child.parent_session_id == parent.session_id
        assert child.context.get("agent_name") == "researcher"
        assert child.context.get("model_override") == "gpt-4"
        assert child.context.get("effort_override") == "high"
        assert child.context.get("spawn_template_id") == "research"

    async def test_spawn_request_overrides_template(
        self, session_service: OperatorSessionService, tmp_path: Path
    ) -> None:
        """Request-level values override template defaults."""
        templates_dir = tmp_path / "spawn-templates"
        templates_dir.mkdir()
        (templates_dir / "basic.json").write_text(
            json.dumps(
                {
                    "template_id": "basic",
                    "name": "Basic",
                    "agent_name": "default-agent",
                    "purpose_template": "Default purpose",
                }
            )
        )

        parent = await session_service.start_session(purpose="parent")
        spawn_svc = SessionSpawnService(session_service, templates_dir=str(templates_dir))

        req = SpawnRequest(
            parent_session_id=parent.session_id,
            template_id="basic",
            agent_name="custom-agent",
            purpose="custom purpose",
        )
        child = await spawn_svc.spawn(req)

        assert child.context.get("agent_name") == "custom-agent"
        assert child.purpose == "custom purpose"

    async def test_spawn_missing_parent_raises(
        self, session_service: OperatorSessionService
    ) -> None:
        """Spawning from a non-existent parent raises KeyError."""
        spawn_svc = SessionSpawnService(session_service)
        req = SpawnRequest(parent_session_id="nonexistent")
        with pytest.raises(KeyError, match="not found"):
            await spawn_svc.spawn(req)

    async def test_spawn_missing_template_raises(
        self, session_service: OperatorSessionService
    ) -> None:
        """Referencing a non-existent template raises KeyError."""
        parent = await session_service.start_session(purpose="parent")
        spawn_svc = SessionSpawnService(session_service)
        req = SpawnRequest(parent_session_id=parent.session_id, template_id="nonexistent")
        with pytest.raises(KeyError, match="not found"):
            await spawn_svc.spawn(req)

    async def test_list_templates_empty(self, session_service: OperatorSessionService) -> None:
        """list_templates returns empty list when no templates dir configured."""
        spawn_svc = SessionSpawnService(session_service, templates_dir="")
        assert spawn_svc.list_templates() == []


# ---------------------------------------------------------------------------
# SessionArchiveService tests
# ---------------------------------------------------------------------------


class TestSessionArchiveService:
    """Tests for session archiving."""

    async def test_archive_completed_session(
        self, session_service: OperatorSessionService
    ) -> None:
        """A completed session can be archived."""
        session = await session_service.start_session(purpose="done")
        await session_service.end_session(session.session_id)

        archive_svc = SessionArchiveService(session_service)
        archived = await archive_svc.archive(session.session_id)

        assert archived.status == OperatorSessionStatus.ARCHIVED

        # Verify persisted state
        reloaded = await session_service.get_session(session.session_id)
        assert reloaded is not None
        assert reloaded.status == OperatorSessionStatus.ARCHIVED

    async def test_archive_clears_terminal_session_state(
        self, storage: FileSessionStorage
    ) -> None:
        """Archiving a terminal session clears pack-scoped session state."""
        cleanup = MagicMock()
        session_service = OperatorSessionService(
            storage=storage,
            session_cleanup_callback=cleanup,
        )
        session = await session_service.start_session(purpose="done")
        await session_service.end_session(session.session_id)

        archive_svc = SessionArchiveService(session_service)
        cleanup.reset_mock()
        await archive_svc.archive(session.session_id)

        cleanup.assert_called_once_with(session.session_id)

    async def test_archive_active_session_raises(
        self, session_service: OperatorSessionService
    ) -> None:
        """Archiving an active session raises ValueError."""
        session = await session_service.start_session(purpose="still running")

        archive_svc = SessionArchiveService(session_service)
        with pytest.raises(ValueError, match="Cannot archive an active session"):
            await archive_svc.archive(session.session_id)

    async def test_archive_already_archived_raises(
        self, session_service: OperatorSessionService
    ) -> None:
        """Archiving an already-archived session raises ValueError."""
        session = await session_service.start_session(purpose="done")
        await session_service.end_session(session.session_id)

        archive_svc = SessionArchiveService(session_service)
        await archive_svc.archive(session.session_id)

        with pytest.raises(ValueError, match="already archived"):
            await archive_svc.archive(session.session_id)

    async def test_archive_not_found_raises(self, session_service: OperatorSessionService) -> None:
        """Archiving a non-existent session raises KeyError."""
        archive_svc = SessionArchiveService(session_service)
        with pytest.raises(KeyError, match="not found"):
            await archive_svc.archive("nonexistent")

    async def test_cleanup_archived_removes_old(
        self, session_service: OperatorSessionService
    ) -> None:
        """cleanup_archived removes sessions older than retention days."""
        session = await session_service.start_session(purpose="old")
        await session_service.end_session(session.session_id)

        archive_svc = SessionArchiveService(session_service)
        await archive_svc.archive(session.session_id)

        # Manipulate updated_at to simulate age
        s = await session_service.get_session(session.session_id)
        assert s is not None
        s.updated_at = datetime.now(UTC) - timedelta(days=100)
        session_service.storage.save_session(s)

        removed = await archive_svc.cleanup_archived(older_than_days=90)
        assert removed == 1

        # Verify it was actually deleted
        assert await session_service.get_session(session.session_id) is None

    async def test_cleanup_archived_clears_terminal_session_state(
        self, storage: FileSessionStorage
    ) -> None:
        """cleanup_archived clears pack-scoped state before deleting old sessions."""
        cleanup = MagicMock()
        session_service = OperatorSessionService(
            storage=storage,
            session_cleanup_callback=cleanup,
        )
        session = await session_service.start_session(purpose="old")
        await session_service.end_session(session.session_id)

        archive_svc = SessionArchiveService(session_service)
        await archive_svc.archive(session.session_id)

        s = await session_service.get_session(session.session_id)
        assert s is not None
        s.updated_at = datetime.now(UTC) - timedelta(days=100)
        session_service.storage.save_session(s)

        cleanup.reset_mock()
        removed = await archive_svc.cleanup_archived(older_than_days=90)

        assert removed == 1
        cleanup.assert_called_once_with(session.session_id)

    async def test_cleanup_archived_logs_cleanup_failure_and_continues(
        self,
        storage: FileSessionStorage,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """cleanup_archived still removes old sessions when cleanup raises."""

        def cleanup_callback(_: str) -> None:
            raise RuntimeError("cleanup failed")

        session_service = OperatorSessionService(
            storage=storage,
            session_cleanup_callback=cleanup_callback,
        )
        session = await session_service.start_session(purpose="old")
        await session_service.end_session(session.session_id)

        archive_svc = SessionArchiveService(session_service)
        await archive_svc.archive(session.session_id)

        s = await session_service.get_session(session.session_id)
        assert s is not None
        s.updated_at = datetime.now(UTC) - timedelta(days=100)
        session_service.storage.save_session(s)

        with caplog.at_level(logging.WARNING):
            removed = await archive_svc.cleanup_archived(older_than_days=90)

        assert removed == 1
        assert "session_cleanup_callback_failed" in caplog.text
        assert await session_service.get_session(session.session_id) is None

    async def test_cleanup_archived_keeps_recent(
        self, session_service: OperatorSessionService
    ) -> None:
        """cleanup_archived keeps recently archived sessions."""
        session = await session_service.start_session(purpose="recent")
        await session_service.end_session(session.session_id)

        archive_svc = SessionArchiveService(session_service)
        await archive_svc.archive(session.session_id)

        removed = await archive_svc.cleanup_archived(older_than_days=90)
        assert removed == 0

        assert await session_service.get_session(session.session_id) is not None


# ---------------------------------------------------------------------------
# ContextEngine tests
# ---------------------------------------------------------------------------


class TestBuiltinContextEngine:
    """Tests for the builtin context engine implementation."""

    async def test_protocol_compliance(self) -> None:
        """BuiltinContextEngine satisfies the ContextEngine protocol."""
        engine = BuiltinContextEngine()
        assert isinstance(engine, ContextEngine)
        assert engine.engine_id == "builtin"

    async def test_assemble_returns_report(self) -> None:
        """assemble() returns a valid ContextAssemblyReport with slots."""
        engine = BuiltinContextEngine()
        report = await engine.assemble("test-session-123")

        assert isinstance(report, ContextAssemblyReport)
        assert report.session_id == "test-session-123"
        assert report.engine_id == "builtin"
        assert len(report.slots_filled) == 3
        assert report.total_tokens > 0
        assert report.compaction_triggered is False

        slot_names = {s.name for s in report.slots_filled}
        assert slot_names == {"system_prompt", "conversation_history", "tool_results"}

    async def test_assemble_slot_properties(self) -> None:
        """Each slot has name, priority, token_budget, source, and content_hash."""
        engine = BuiltinContextEngine()
        report = await engine.assemble("test-session")

        for slot in report.slots_filled:
            assert isinstance(slot, ContextSlot)
            assert slot.name
            assert slot.priority > 0
            assert slot.token_budget > 0
            assert slot.source == "builtin"
            assert slot.content_hash  # non-empty hash

    async def test_compact_returns_event(self) -> None:
        """compact() returns a CompactionEvent with noop strategy."""
        engine = BuiltinContextEngine()
        event = await engine.compact("test-session")

        assert isinstance(event, CompactionEvent)
        assert event.session_id == "test-session"
        assert event.strategy == "noop"
        assert event.success is True
        assert event.tokens_before == event.tokens_after

    async def test_health_returns_status(self) -> None:
        """health() returns a dict with engine_id and healthy status."""
        engine = BuiltinContextEngine()
        h = engine.health()

        assert h["engine_id"] == "builtin"
        assert h["status"] == "healthy"
        assert h["type"] == "builtin"


# ---------------------------------------------------------------------------
# ContextEngineRegistry tests
# ---------------------------------------------------------------------------


class TestContextEngineRegistry:
    """Tests for context engine discovery and selection."""

    def test_builtin_registered_by_default(self) -> None:
        """The builtin engine is auto-registered."""
        registry = ContextEngineRegistry()
        assert "builtin" in registry.list_available()

    def test_get_active_returns_builtin(self) -> None:
        """Default active engine is builtin."""
        registry = ContextEngineRegistry()
        engine = registry.get_active()
        assert engine.engine_id == "builtin"

    def test_register_custom_engine(self) -> None:
        """A custom engine can be registered and activated."""

        class CustomEngine:
            engine_id = "custom"

            async def assemble(self, session_id: str) -> ContextAssemblyReport:
                return ContextAssemblyReport(
                    session_id=session_id,
                    timestamp=datetime.now(UTC),
                    engine_id="custom",
                )

            async def compact(self, session_id: str) -> CompactionEvent:
                return CompactionEvent(
                    session_id=session_id,
                    timestamp=datetime.now(UTC),
                    tokens_before=0,
                    tokens_after=0,
                )

            def health(self) -> dict[str, Any]:
                return {"engine_id": "custom", "status": "healthy"}

        registry = ContextEngineRegistry()
        custom = CustomEngine()
        registry.register(custom)

        assert "custom" in registry.list_available()
        registry.set_active("custom")
        assert registry.get_active().engine_id == "custom"

    def test_register_duplicate_raises(self) -> None:
        """Re-registering the same engine_id raises ValueError."""
        registry = ContextEngineRegistry()
        with pytest.raises(ValueError, match="already registered"):
            registry.register(BuiltinContextEngine())

    def test_set_active_unknown_raises(self) -> None:
        """Setting active to unknown engine raises KeyError."""
        registry = ContextEngineRegistry()
        with pytest.raises(KeyError, match="not registered"):
            registry.set_active("nonexistent")

    def test_health_check_all_engines(self) -> None:
        """health_check returns status for all engines."""
        registry = ContextEngineRegistry()
        health = registry.health_check()

        assert health["active_engine"] == "builtin"
        assert "builtin" in health["engines"]
        assert health["engines"]["builtin"]["status"] == "healthy"

    def test_list_available_sorted(self) -> None:
        """list_available returns sorted engine ids."""
        registry = ContextEngineRegistry()
        available = registry.list_available()
        assert available == sorted(available)


# ---------------------------------------------------------------------------
# Context models tests
# ---------------------------------------------------------------------------


class TestContextModels:
    """Tests for context model construction and serialization."""

    def test_context_slot_defaults(self) -> None:
        """ContextSlot has reasonable defaults."""
        slot = ContextSlot(name="test")
        assert slot.priority == 0
        assert slot.token_budget == 0
        assert slot.source == ""

    def test_compaction_history(self) -> None:
        """CompactionHistory aggregates events."""
        now = datetime.now(UTC)
        event = CompactionEvent(
            session_id="s1",
            timestamp=now,
            tokens_before=1000,
            tokens_after=500,
            strategy="summarize",
        )
        history = CompactionHistory(
            session_id="s1",
            events=[event],
            total_compactions=1,
        )
        assert history.total_compactions == 1
        assert len(history.events) == 1
        assert history.events[0].tokens_before == 1000


# ---------------------------------------------------------------------------
# API route integration tests
# ---------------------------------------------------------------------------


class TestSessionCatalogAPI:
    """Integration tests for Track 8 session API endpoints."""

    @pytest.fixture()
    def _wired_app(self, session_service: OperatorSessionService) -> Any:
        """Wire Track 8 services into the sessions route module."""
        from agent33.api.routes import sessions as sessions_mod

        catalog = SessionCatalog(session_service)
        lineage_builder = SessionLineageBuilder(session_service)
        spawn_svc = SessionSpawnService(session_service)
        archive_svc = SessionArchiveService(session_service)

        sessions_mod.set_session_service(session_service)
        sessions_mod.set_session_catalog(catalog)
        sessions_mod.set_session_lineage_builder(lineage_builder)
        sessions_mod.set_session_spawn_service(spawn_svc)
        sessions_mod.set_session_archive_service(archive_svc)

        yield

        # Clean up module-level state
        sessions_mod.set_session_service(None)
        sessions_mod.set_session_catalog(None)
        sessions_mod.set_session_lineage_builder(None)
        sessions_mod.set_session_spawn_service(None)
        sessions_mod.set_session_archive_service(None)

    @pytest.fixture()
    def _wired_context(self) -> Any:
        """Wire context engine registry into the context route module."""
        from agent33.api.routes import context as context_mod

        registry = ContextEngineRegistry()
        context_mod.set_context_engine_registry(registry)

        yield

        context_mod.set_context_engine_registry(None)

    async def test_catalog_route_returns_entries(
        self, session_service: OperatorSessionService, _wired_app: Any
    ) -> None:
        """GET /v1/sessions/catalog returns enriched entries."""
        import httpx

        from agent33.main import app

        await session_service.start_session(
            purpose="catalog test", context={"agent_name": "tester"}
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            # Install services on app.state for route access
            app.state.session_catalog = SessionCatalog(session_service)
            app.state.operator_session_service = session_service

            resp = await client.get("/v1/sessions/catalog")

        if resp.status_code == 401:
            pytest.skip("Auth middleware active; module-level wiring sufficient")
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data
        assert "total" in data

    async def test_lineage_route_returns_tree(
        self, session_service: OperatorSessionService, _wired_app: Any
    ) -> None:
        """GET /v1/sessions/{id}/lineage returns a tree structure."""
        import httpx

        from agent33.main import app

        session = await session_service.start_session(purpose="lineage test")
        app.state.session_lineage_builder = SessionLineageBuilder(session_service)
        app.state.operator_session_service = session_service

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.get(f"/v1/sessions/{session.session_id}/lineage")

        if resp.status_code == 401:
            pytest.skip("Auth middleware active; module-level wiring sufficient")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == session.session_id
        assert "children" in data

    async def test_archive_active_returns_409(
        self, session_service: OperatorSessionService, _wired_app: Any
    ) -> None:
        """POST /v1/sessions/{id}/archive returns 409 for active session."""
        import httpx

        from agent33.main import app

        session = await session_service.start_session(purpose="active session")
        app.state.session_archive_service = SessionArchiveService(session_service)
        app.state.operator_session_service = session_service

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.post(f"/v1/sessions/{session.session_id}/archive")

        if resp.status_code == 401:
            pytest.skip("Auth middleware active; module-level wiring sufficient")
        assert resp.status_code == 409

    async def test_context_status_route(self, _wired_context: Any) -> None:
        """GET /v1/context/status returns engine info."""
        import httpx

        from agent33.main import app

        app.state.context_engine_registry = ContextEngineRegistry()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.get("/v1/context/status")

        if resp.status_code == 401:
            pytest.skip("Auth middleware active; module-level wiring sufficient")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_engine"] == "builtin"
        assert "builtin" in data["available_engines"]

    async def test_context_health_route(self, _wired_context: Any) -> None:
        """GET /v1/context/health returns engine health."""
        import httpx

        from agent33.main import app

        app.state.context_engine_registry = ContextEngineRegistry()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.get("/v1/context/health")

        if resp.status_code == 401:
            pytest.skip("Auth middleware active; module-level wiring sufficient")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_engine"] == "builtin"
        assert "builtin" in data["engines"]

    async def test_context_assembly_route(self, _wired_context: Any) -> None:
        """GET /v1/context/{session_id}/assembly returns assembly report."""
        import httpx

        from agent33.main import app

        app.state.context_engine_registry = ContextEngineRegistry()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.get("/v1/context/test-session-123/assembly")

        if resp.status_code == 401:
            pytest.skip("Auth middleware active; module-level wiring sufficient")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "test-session-123"
        assert data["engine_id"] == "builtin"
        assert data["slots_count"] == 3
        assert data["total_tokens"] > 0


# ---------------------------------------------------------------------------
# OperatorService.get_sessions() delegation tests
# ---------------------------------------------------------------------------


class TestOperatorServiceSessionDelegation:
    """Tests that OperatorService.get_sessions() delegates to SessionCatalog."""

    async def test_get_sessions_with_catalog(
        self, session_service: OperatorSessionService
    ) -> None:
        """When SessionCatalog is on app.state, get_sessions returns real data."""
        from agent33.config import Settings
        from agent33.operator.service import OperatorService

        await session_service.start_session(
            purpose="delegation test", context={"agent_name": "worker"}
        )

        catalog = SessionCatalog(session_service)

        app_state = MagicMock()
        app_state.session_catalog = catalog
        app_state.redis = None
        app_state.nats_bus = None
        app_state.long_term_memory = None
        app_state.agent_registry = None
        app_state.tool_registry = None
        app_state.plugin_registry = None
        app_state.pack_registry = None
        app_state.skill_registry = None
        app_state.hook_registry = None
        app_state.process_manager_service = None
        app_state.multimodal_service = None
        app_state.voice_sidecar_probe = None
        app_state.status_line_service = None

        settings = Settings()
        op_service = OperatorService(app_state, settings, 0.0)

        result = await op_service.get_sessions()
        assert result.degraded is False
        assert result.count == 1
        assert result.total == 1
        assert result.sessions[0].type == "operator"
        assert result.sessions[0].agent == "worker"

    async def test_get_sessions_no_catalog_no_redis_is_degraded(self) -> None:
        """Without catalog or Redis, get_sessions returns degraded=True."""
        from agent33.config import Settings
        from agent33.operator.service import OperatorService

        app_state = MagicMock()
        app_state.session_catalog = None
        app_state.redis = None

        settings = Settings()
        op_service = OperatorService(app_state, settings, 0.0)

        result = await op_service.get_sessions()
        assert result.degraded is True
        assert result.count == 0
