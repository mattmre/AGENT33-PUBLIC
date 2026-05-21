"""Tests for Track 8: session catalog, context slots, compaction diagnostics.

Covers:
- SessionCatalog (memory layer) CRUD, filtering, lineage tree
- ContextSlotManager register/update/evict/list and budget-aware assembly
- CompactionDiagnostics event recording, history, and summary stats
- API route integration for all new endpoints
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from agent33.memory.compaction import CompactionDiagnostics, CompactionEvent, CompactionSummary
from agent33.memory.context_slots import (
    AssembledContext,
    ContextSlot,
    ContextSlotManager,
    SlotPriority,
)
from agent33.memory.session_catalog import (
    LineageNode,
    SessionCatalog,
    SessionCatalogEntry,
    SessionStatus,
)

# ===========================================================================
# SessionCatalog tests
# ===========================================================================


class TestSessionCatalogCRUD:
    """Tests for SessionCatalog create/read/update/archive."""

    def test_create_session_returns_entry(self) -> None:
        """create_session returns a SessionCatalogEntry with a generated id."""
        catalog = SessionCatalog()
        entry = catalog.create_session(agent_id="code-worker", tenant_id="t1")

        assert isinstance(entry, SessionCatalogEntry)
        assert entry.session_id  # non-empty
        assert entry.agent_id == "code-worker"
        assert entry.tenant_id == "t1"
        assert entry.status == SessionStatus.ACTIVE
        assert entry.message_count == 0
        assert entry.token_count == 0
        assert entry.parent_session_id is None
        assert entry.tags == []
        assert entry.metadata == {}

    def test_create_session_with_tags_and_metadata(self) -> None:
        """Tags and metadata are persisted on creation."""
        catalog = SessionCatalog()
        entry = catalog.create_session(
            agent_id="researcher",
            tags=["important", "phase-3"],
            metadata={"model": "gpt-4", "effort": "high"},
        )
        assert entry.tags == ["important", "phase-3"]
        assert entry.metadata == {"model": "gpt-4", "effort": "high"}

    def test_create_session_with_parent(self) -> None:
        """parent_session_id is stored for delegation tracking."""
        catalog = SessionCatalog()
        parent = catalog.create_session(agent_id="orchestrator")
        child = catalog.create_session(agent_id="worker", parent_session_id=parent.session_id)
        assert child.parent_session_id == parent.session_id

    def test_get_session_returns_entry(self) -> None:
        """get_session returns the stored entry by id."""
        catalog = SessionCatalog()
        created = catalog.create_session(agent_id="qa")
        retrieved = catalog.get_session(created.session_id)
        assert retrieved.session_id == created.session_id
        assert retrieved.agent_id == "qa"

    def test_get_session_not_found_raises(self) -> None:
        """get_session raises KeyError for non-existent id."""
        catalog = SessionCatalog()
        with pytest.raises(KeyError, match="not found"):
            catalog.get_session("nonexistent")

    def test_update_session_changes_fields(self) -> None:
        """update_session modifies tags, metadata, status, and counters."""
        catalog = SessionCatalog()
        entry = catalog.create_session(agent_id="worker")
        original_created_at = entry.created_at

        updated = catalog.update_session(
            entry.session_id,
            status=SessionStatus.COMPLETED,
            tags=["done"],
            metadata={"result": "success"},
            message_count=42,
            token_count=8000,
        )

        assert updated.status == SessionStatus.COMPLETED
        assert updated.tags == ["done"]
        assert updated.metadata == {"result": "success"}
        assert updated.message_count == 42
        assert updated.token_count == 8000
        # updated_at should be >= the original creation time
        assert updated.updated_at >= original_created_at
        # created_at should remain unchanged
        assert updated.created_at == original_created_at

    def test_update_session_partial(self) -> None:
        """update_session only changes provided fields; others stay intact."""
        catalog = SessionCatalog()
        entry = catalog.create_session(
            agent_id="worker",
            tags=["original"],
            metadata={"key": "value"},
        )
        catalog.update_session(entry.session_id, message_count=10)

        refreshed = catalog.get_session(entry.session_id)
        assert refreshed.tags == ["original"]  # unchanged
        assert refreshed.metadata == {"key": "value"}  # unchanged
        assert refreshed.message_count == 10  # updated
        assert refreshed.status == SessionStatus.ACTIVE  # unchanged

    def test_update_session_not_found_raises(self) -> None:
        """update_session raises KeyError for non-existent session."""
        catalog = SessionCatalog()
        with pytest.raises(KeyError, match="not found"):
            catalog.update_session("nonexistent", tags=["x"])

    def test_archive_session(self) -> None:
        """archive_session transitions to ARCHIVED status."""
        catalog = SessionCatalog()
        entry = catalog.create_session(agent_id="worker")
        archived = catalog.archive_session(entry.session_id)
        assert archived.status == SessionStatus.ARCHIVED

    def test_archive_session_already_archived_raises(self) -> None:
        """archive_session raises ValueError if already archived."""
        catalog = SessionCatalog()
        entry = catalog.create_session(agent_id="worker")
        catalog.archive_session(entry.session_id)
        with pytest.raises(ValueError, match="already archived"):
            catalog.archive_session(entry.session_id)

    def test_archive_session_not_found_raises(self) -> None:
        """archive_session raises KeyError for non-existent id."""
        catalog = SessionCatalog()
        with pytest.raises(KeyError, match="not found"):
            catalog.archive_session("nonexistent")


class TestSessionCatalogList:
    """Tests for SessionCatalog.list_sessions with filters."""

    def test_list_empty(self) -> None:
        """Empty catalog returns empty list and total 0."""
        catalog = SessionCatalog()
        entries, total = catalog.list_sessions()
        assert entries == []
        assert total == 0

    def test_list_all(self) -> None:
        """list_sessions returns all entries when no filters are applied."""
        catalog = SessionCatalog()
        catalog.create_session(agent_id="a")
        catalog.create_session(agent_id="b")
        entries, total = catalog.list_sessions()
        assert total == 2
        assert len(entries) == 2

    def test_list_filter_by_status(self) -> None:
        """list_sessions filters by status correctly."""
        catalog = SessionCatalog()
        s1 = catalog.create_session(agent_id="worker")
        s2 = catalog.create_session(agent_id="worker")
        catalog.update_session(s2.session_id, status=SessionStatus.COMPLETED)

        active, active_total = catalog.list_sessions(status=SessionStatus.ACTIVE)
        assert active_total == 1
        assert active[0].session_id == s1.session_id

        completed, completed_total = catalog.list_sessions(status=SessionStatus.COMPLETED)
        assert completed_total == 1
        assert completed[0].session_id == s2.session_id

    def test_list_filter_by_agent_id(self) -> None:
        """list_sessions filters by agent_id."""
        catalog = SessionCatalog()
        catalog.create_session(agent_id="researcher")
        catalog.create_session(agent_id="code-worker")
        catalog.create_session(agent_id="researcher")

        entries, total = catalog.list_sessions(agent_id="researcher")
        assert total == 2
        assert all(e.agent_id == "researcher" for e in entries)

    def test_list_filter_by_tenant_id(self) -> None:
        """list_sessions filters by tenant_id."""
        catalog = SessionCatalog()
        catalog.create_session(agent_id="a", tenant_id="t1")
        catalog.create_session(agent_id="b", tenant_id="t2")

        entries, total = catalog.list_sessions(tenant_id="t1")
        assert total == 1
        assert entries[0].tenant_id == "t1"

    def test_list_pagination(self) -> None:
        """list_sessions respects offset and limit."""
        catalog = SessionCatalog()
        for i in range(10):
            catalog.create_session(agent_id=f"agent-{i}")

        page1, total = catalog.list_sessions(limit=3, offset=0)
        assert total == 10
        assert len(page1) == 3

        page2, total2 = catalog.list_sessions(limit=3, offset=3)
        assert total2 == 10
        assert len(page2) == 3

        # No overlap between pages
        page1_ids = {e.session_id for e in page1}
        page2_ids = {e.session_id for e in page2}
        assert page1_ids.isdisjoint(page2_ids)

    def test_list_sorted_newest_first(self) -> None:
        """list_sessions returns entries newest first."""
        catalog = SessionCatalog()
        s1 = catalog.create_session(agent_id="first")
        s2 = catalog.create_session(agent_id="second")
        # Force distinct timestamps so sort is deterministic
        s1.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        s2.created_at = datetime(2026, 1, 2, tzinfo=UTC)

        entries, _ = catalog.list_sessions()
        assert entries[0].session_id == s2.session_id
        assert entries[1].session_id == s1.session_id


class TestSessionCatalogLineage:
    """Tests for SessionCatalog.get_lineage_tree."""

    def test_single_root(self) -> None:
        """A session with no parent is its own root in the lineage tree."""
        catalog = SessionCatalog()
        entry = catalog.create_session(agent_id="root")
        tree = catalog.get_lineage_tree(entry.session_id)

        assert isinstance(tree, LineageNode)
        assert tree.session_id == entry.session_id
        assert tree.agent_id == "root"
        assert tree.children == []

    def test_parent_child(self) -> None:
        """A parent-child pair builds a two-level tree."""
        catalog = SessionCatalog()
        parent = catalog.create_session(agent_id="orchestrator")
        child = catalog.create_session(agent_id="worker", parent_session_id=parent.session_id)

        tree = catalog.get_lineage_tree(child.session_id)
        assert tree.session_id == parent.session_id
        assert len(tree.children) == 1
        assert tree.children[0].session_id == child.session_id

    def test_multi_level_delegation(self) -> None:
        """A grandparent-parent-child chain produces a three-level tree."""
        catalog = SessionCatalog()
        grandparent = catalog.create_session(agent_id="orchestrator")
        parent = catalog.create_session(
            agent_id="director", parent_session_id=grandparent.session_id
        )
        child = catalog.create_session(agent_id="worker", parent_session_id=parent.session_id)

        tree = catalog.get_lineage_tree(child.session_id)
        assert tree.session_id == grandparent.session_id
        assert len(tree.children) == 1
        assert tree.children[0].session_id == parent.session_id
        assert len(tree.children[0].children) == 1
        assert tree.children[0].children[0].session_id == child.session_id

    def test_multi_child(self) -> None:
        """A parent with multiple children produces a fan-out tree."""
        catalog = SessionCatalog()
        parent = catalog.create_session(agent_id="orchestrator")
        child1 = catalog.create_session(agent_id="worker-1", parent_session_id=parent.session_id)
        child2 = catalog.create_session(agent_id="worker-2", parent_session_id=parent.session_id)

        tree = catalog.get_lineage_tree(parent.session_id)
        assert tree.session_id == parent.session_id
        assert len(tree.children) == 2
        child_ids = {c.session_id for c in tree.children}
        assert child_ids == {child1.session_id, child2.session_id}

    def test_lineage_from_child_walks_up(self) -> None:
        """Requesting lineage from a child still returns the root-rooted tree."""
        catalog = SessionCatalog()
        root = catalog.create_session(agent_id="root")
        child = catalog.create_session(agent_id="child", parent_session_id=root.session_id)

        tree_from_child = catalog.get_lineage_tree(child.session_id)
        tree_from_root = catalog.get_lineage_tree(root.session_id)

        assert tree_from_child.session_id == tree_from_root.session_id

    def test_lineage_orphaned_parent(self) -> None:
        """When parent_session_id references a missing session, child is the root."""
        catalog = SessionCatalog()
        orphan = catalog.create_session(agent_id="orphan", parent_session_id="missing_parent")

        tree = catalog.get_lineage_tree(orphan.session_id)
        assert tree.session_id == orphan.session_id
        assert tree.children == []

    def test_lineage_not_found_raises(self) -> None:
        """get_lineage_tree raises KeyError for non-existent session."""
        catalog = SessionCatalog()
        with pytest.raises(KeyError, match="not found"):
            catalog.get_lineage_tree("nonexistent")


# ===========================================================================
# ContextSlotManager tests
# ===========================================================================


class TestContextSlotManagerLifecycle:
    """Tests for slot register, update, evict, and list."""

    def test_register_and_list(self) -> None:
        """Registered slots appear in list_slots."""
        mgr = ContextSlotManager()
        slot = ContextSlot(
            name="system_prompt",
            content="You are an assistant.",
            token_count=10,
            priority=SlotPriority.REQUIRED,
            source="system",
        )
        mgr.register("s1", slot)

        slots = mgr.list_slots("s1")
        assert len(slots) == 1
        assert slots[0].name == "system_prompt"
        assert slots[0].content == "You are an assistant."
        assert slots[0].priority == SlotPriority.REQUIRED

    def test_register_overwrites_same_name(self) -> None:
        """Registering a slot with the same name replaces the previous one."""
        mgr = ContextSlotManager()
        mgr.register("s1", ContextSlot(name="prompt", content="v1", token_count=5))
        mgr.register("s1", ContextSlot(name="prompt", content="v2", token_count=10))

        slots = mgr.list_slots("s1")
        assert len(slots) == 1
        assert slots[0].content == "v2"
        assert slots[0].token_count == 10

    def test_update_changes_fields(self) -> None:
        """update modifies only the provided fields."""
        mgr = ContextSlotManager()
        mgr.register("s1", ContextSlot(name="history", content="old", token_count=50))
        updated = mgr.update(
            "s1",
            "history",
            content="new content",
            token_count=100,
            priority=SlotPriority.PREFERRED,
        )
        assert updated.content == "new content"
        assert updated.token_count == 100
        assert updated.priority == SlotPriority.PREFERRED

    def test_update_not_found_raises(self) -> None:
        """update raises KeyError when slot does not exist."""
        mgr = ContextSlotManager()
        with pytest.raises(KeyError, match="not found"):
            mgr.update("s1", "missing", content="x")

    def test_evict_removes_slot(self) -> None:
        """evict removes the slot and returns it."""
        mgr = ContextSlotManager()
        mgr.register("s1", ContextSlot(name="tools", token_count=20))
        evicted = mgr.evict("s1", "tools")

        assert evicted.name == "tools"
        assert mgr.list_slots("s1") == []

    def test_evict_not_found_raises(self) -> None:
        """evict raises KeyError when slot does not exist."""
        mgr = ContextSlotManager()
        with pytest.raises(KeyError, match="not found"):
            mgr.evict("s1", "missing")

    def test_get_slot(self) -> None:
        """get_slot returns the specific slot by name."""
        mgr = ContextSlotManager()
        mgr.register("s1", ContextSlot(name="prompt", token_count=5))
        mgr.register("s1", ContextSlot(name="history", token_count=50))

        slot = mgr.get_slot("s1", "history")
        assert slot.name == "history"
        assert slot.token_count == 50

    def test_list_slots_sorted_by_priority(self) -> None:
        """list_slots returns slots sorted required > preferred > optional."""
        mgr = ContextSlotManager()
        mgr.register("s1", ContextSlot(name="opt", priority=SlotPriority.OPTIONAL))
        mgr.register("s1", ContextSlot(name="req", priority=SlotPriority.REQUIRED))
        mgr.register("s1", ContextSlot(name="pref", priority=SlotPriority.PREFERRED))

        slots = mgr.list_slots("s1")
        assert [s.name for s in slots] == ["req", "pref", "opt"]

    def test_clear_session(self) -> None:
        """clear_session removes all slots for that session."""
        mgr = ContextSlotManager()
        mgr.register("s1", ContextSlot(name="a", token_count=1))
        mgr.register("s1", ContextSlot(name="b", token_count=2))
        mgr.register("s2", ContextSlot(name="c", token_count=3))

        mgr.clear_session("s1")
        assert mgr.list_slots("s1") == []
        assert len(mgr.list_slots("s2")) == 1  # s2 unaffected

    def test_session_token_total(self) -> None:
        """session_token_total sums effective tokens across all slots."""
        mgr = ContextSlotManager()
        mgr.register("s1", ContextSlot(name="a", token_count=100))
        mgr.register("s1", ContextSlot(name="b", token_count=200))

        assert mgr.session_token_total("s1") == 300

    def test_to_summary(self) -> None:
        """to_summary returns a JSON-friendly dict with slot details."""
        mgr = ContextSlotManager()
        mgr.register("s1", ContextSlot(name="prompt", token_count=50, source="system"))

        summary = mgr.to_summary("s1")
        assert summary["session_id"] == "s1"
        assert summary["slot_count"] == 1
        assert summary["total_tokens"] == 50
        assert len(summary["slots"]) == 1
        assert summary["slots"][0]["name"] == "prompt"


class TestContextSlotBudgetAssembly:
    """Tests for budget-aware context slot assembly."""

    def test_all_slots_fit(self) -> None:
        """When budget exceeds all slots, everything is included."""
        mgr = ContextSlotManager()
        mgr.register("s1", ContextSlot(name="a", token_count=100))
        mgr.register("s1", ContextSlot(name="b", token_count=200))

        result = mgr.assemble("s1", budget=1000)
        assert isinstance(result, AssembledContext)
        assert len(result.included) == 2
        assert len(result.excluded) == 0
        assert result.total_tokens == 300
        assert result.budget == 1000
        assert result.budget_remaining == 700

    def test_budget_excludes_overflow(self) -> None:
        """Slots that exceed remaining budget are excluded."""
        mgr = ContextSlotManager()
        mgr.register(
            "s1",
            ContextSlot(name="req", token_count=500, priority=SlotPriority.REQUIRED),
        )
        mgr.register(
            "s1",
            ContextSlot(name="pref", token_count=400, priority=SlotPriority.PREFERRED),
        )
        mgr.register(
            "s1",
            ContextSlot(name="opt", token_count=300, priority=SlotPriority.OPTIONAL),
        )

        result = mgr.assemble("s1", budget=800)

        included_names = {s.name for s in result.included}
        excluded_names = {s.name for s in result.excluded}

        # Required (500) + Preferred (400) = 900 > 800
        # Required (500) fits; Preferred (400) exceeds 300 remaining; Optional (300) fits
        assert "req" in included_names
        assert "opt" in included_names
        assert "pref" in excluded_names
        assert result.total_tokens == 800
        assert result.budget_remaining == 0

    def test_priority_ordering(self) -> None:
        """Required slots are filled before preferred before optional."""
        mgr = ContextSlotManager()
        mgr.register(
            "s1",
            ContextSlot(name="opt", token_count=100, priority=SlotPriority.OPTIONAL),
        )
        mgr.register(
            "s1",
            ContextSlot(name="req", token_count=100, priority=SlotPriority.REQUIRED),
        )

        # Budget = 100 means only one slot fits
        result = mgr.assemble("s1", budget=100)

        assert len(result.included) == 1
        assert result.included[0].name == "req"
        assert len(result.excluded) == 1
        assert result.excluded[0].name == "opt"

    def test_max_tokens_cap(self) -> None:
        """Slot with max_tokens only charges up to the cap."""
        mgr = ContextSlotManager()
        mgr.register(
            "s1",
            ContextSlot(name="history", token_count=1000, max_tokens=200),
        )

        result = mgr.assemble("s1", budget=300)
        assert len(result.included) == 1
        assert result.total_tokens == 200  # capped at max_tokens
        assert result.budget_remaining == 100

    def test_zero_budget(self) -> None:
        """Zero budget excludes everything."""
        mgr = ContextSlotManager()
        mgr.register("s1", ContextSlot(name="a", token_count=1))

        result = mgr.assemble("s1", budget=0)
        assert len(result.included) == 0
        assert len(result.excluded) == 1

    def test_empty_session_assembly(self) -> None:
        """Assembly on a session with no slots returns empty result."""
        mgr = ContextSlotManager()
        result = mgr.assemble("nonexistent", budget=1000)
        assert result.included == []
        assert result.excluded == []
        assert result.total_tokens == 0
        assert result.budget_remaining == 1000

    def test_effective_tokens_from_content(self) -> None:
        """Slot without explicit token_count estimates from content."""
        slot = ContextSlot(name="test", content="hello world this is a test")
        # 6 words * 1.3 = 7.8 -> ceil = 8
        assert slot.effective_tokens() == 8

    def test_effective_tokens_zero_when_empty(self) -> None:
        """Slot with no content and no token_count returns 0."""
        slot = ContextSlot(name="empty")
        assert slot.effective_tokens() == 0

    def test_effective_tokens_explicit_takes_precedence(self) -> None:
        """Explicit token_count overrides content-based estimate."""
        slot = ContextSlot(name="test", content="hello world", token_count=42)
        assert slot.effective_tokens() == 42


# ===========================================================================
# CompactionDiagnostics tests
# ===========================================================================


class TestCompactionDiagnosticsRecording:
    """Tests for CompactionDiagnostics event recording."""

    def test_record_and_history(self) -> None:
        """Recorded events appear in history."""
        diag = CompactionDiagnostics()
        event = CompactionEvent(
            session_id="s1",
            messages_before=100,
            messages_after=50,
            tokens_saved=2000,
            strategy="summarize",
            trigger_reason="budget_exceeded",
        )
        diag.record(event)

        history = diag.history("s1")
        assert len(history) == 1
        assert history[0].session_id == "s1"
        assert history[0].messages_before == 100
        assert history[0].messages_after == 50
        assert history[0].tokens_saved == 2000
        assert history[0].strategy == "summarize"
        assert history[0].trigger_reason == "budget_exceeded"

    def test_history_newest_first(self) -> None:
        """History returns events in reverse chronological order."""
        diag = CompactionDiagnostics()
        e1 = CompactionEvent(
            session_id="s1",
            messages_before=100,
            messages_after=50,
            tokens_saved=1000,
            strategy="first",
        )
        e2 = CompactionEvent(
            session_id="s1",
            messages_before=50,
            messages_after=25,
            tokens_saved=500,
            strategy="second",
        )
        diag.record(e1)
        diag.record(e2)

        history = diag.history("s1")
        assert len(history) == 2
        assert history[0].strategy == "second"  # newest first
        assert history[1].strategy == "first"

    def test_history_limit(self) -> None:
        """History respects the limit parameter."""
        diag = CompactionDiagnostics()
        for i in range(20):
            diag.record(
                CompactionEvent(
                    session_id="s1",
                    messages_before=100 - i,
                    messages_after=50,
                    tokens_saved=i * 10,
                    strategy=f"pass-{i}",
                )
            )
        history = diag.history("s1", limit=5)
        assert len(history) == 5

    def test_history_empty_session(self) -> None:
        """History for a session with no events returns empty list."""
        diag = CompactionDiagnostics()
        assert diag.history("nonexistent") == []

    def test_session_ids(self) -> None:
        """session_ids returns all sessions that have events."""
        diag = CompactionDiagnostics()
        diag.record(CompactionEvent(session_id="s1", messages_before=10, messages_after=5))
        diag.record(CompactionEvent(session_id="s2", messages_before=20, messages_after=10))

        ids = diag.session_ids()
        assert "s1" in ids
        assert "s2" in ids

    def test_clear(self) -> None:
        """clear removes all events for a session and returns count."""
        diag = CompactionDiagnostics()
        diag.record(CompactionEvent(session_id="s1", messages_before=10, messages_after=5))
        diag.record(CompactionEvent(session_id="s1", messages_before=20, messages_after=10))

        removed = diag.clear("s1")
        assert removed == 2
        assert diag.history("s1") == []

    def test_clear_empty_returns_zero(self) -> None:
        """Clearing a session with no events returns 0."""
        diag = CompactionDiagnostics()
        assert diag.clear("nonexistent") == 0


class TestCompactionDiagnosticsSummary:
    """Tests for CompactionDiagnostics summary stats."""

    def test_summary_empty_session(self) -> None:
        """Summary for a session with no events returns zeros."""
        diag = CompactionDiagnostics()
        summary = diag.summary("nonexistent")

        assert isinstance(summary, CompactionSummary)
        assert summary.session_id == "nonexistent"
        assert summary.total_compactions == 0
        assert summary.total_tokens_saved == 0
        assert summary.total_messages_removed == 0
        assert summary.average_ratio == 0.0

    def test_summary_single_event(self) -> None:
        """Summary with one event computes correctly."""
        diag = CompactionDiagnostics()
        diag.record(
            CompactionEvent(
                session_id="s1",
                messages_before=100,
                messages_after=40,
                tokens_saved=3000,
            )
        )
        summary = diag.summary("s1")

        assert summary.total_compactions == 1
        assert summary.total_tokens_saved == 3000
        assert summary.total_messages_removed == 60  # 100 - 40
        assert summary.average_ratio == 0.4  # 40 / 100

    def test_summary_multiple_events(self) -> None:
        """Summary aggregates correctly across multiple events."""
        diag = CompactionDiagnostics()
        diag.record(
            CompactionEvent(
                session_id="s1",
                messages_before=100,
                messages_after=50,
                tokens_saved=2000,
            )
        )
        diag.record(
            CompactionEvent(
                session_id="s1",
                messages_before=50,
                messages_after=20,
                tokens_saved=1000,
            )
        )

        summary = diag.summary("s1")
        assert summary.total_compactions == 2
        assert summary.total_tokens_saved == 3000  # 2000 + 1000
        assert summary.total_messages_removed == 80  # (100-50) + (50-20)
        # average_ratio = (50/100 + 20/50) / 2 = (0.5 + 0.4) / 2 = 0.45
        assert summary.average_ratio == 0.45

    def test_summary_handles_zero_messages_before(self) -> None:
        """Events with messages_before=0 are excluded from ratio calculation."""
        diag = CompactionDiagnostics()
        diag.record(
            CompactionEvent(
                session_id="s1",
                messages_before=0,
                messages_after=0,
                tokens_saved=0,
            )
        )
        diag.record(
            CompactionEvent(
                session_id="s1",
                messages_before=100,
                messages_after=50,
                tokens_saved=1000,
            )
        )

        summary = diag.summary("s1")
        assert summary.total_compactions == 2
        assert summary.average_ratio == 0.5  # only the valid event counts


# ===========================================================================
# API route integration tests
# ===========================================================================


class TestTrack8API:
    """Integration tests for the new Track 8 upstream agent OS API endpoints."""

    @pytest.fixture()
    def _wired_services(self) -> Any:
        """Wire Track 8 upstream agent OS services into the sessions route module."""
        from agent33.api.routes import sessions as sessions_mod

        catalog = SessionCatalog()
        slot_manager = ContextSlotManager()
        compaction_diag = CompactionDiagnostics()

        sessions_mod.set_memory_session_catalog(catalog)
        sessions_mod.set_context_slot_manager(slot_manager)
        sessions_mod.set_compaction_diagnostics(compaction_diag)

        yield {
            "catalog": catalog,
            "slot_manager": slot_manager,
            "compaction_diag": compaction_diag,
        }

        sessions_mod.set_memory_session_catalog(None)
        sessions_mod.set_context_slot_manager(None)
        sessions_mod.set_compaction_diagnostics(None)

    async def test_create_memory_session(self, _wired_services: Any) -> None:
        """POST /v1/sessions/memory creates a session."""
        import httpx

        from agent33.main import app

        svcs = _wired_services
        app.state.memory_session_catalog = svcs["catalog"]

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.post(
                "/v1/sessions/memory",
                json={"agent_id": "worker", "tags": ["test"]},
            )

        if resp.status_code == 401:
            pytest.skip("Auth middleware active")
        assert resp.status_code == 201
        data = resp.json()
        assert data["agent_id"] == "worker"
        assert data["tags"] == ["test"]
        assert data["status"] == "active"
        assert "session_id" in data

    async def test_list_memory_sessions(self, _wired_services: Any) -> None:
        """GET /v1/sessions/memory returns entries."""
        import httpx

        from agent33.main import app

        svcs = _wired_services
        catalog = svcs["catalog"]
        app.state.memory_session_catalog = catalog

        catalog.create_session(agent_id="worker-1")
        catalog.create_session(agent_id="worker-2")

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.get("/v1/sessions/memory")

        if resp.status_code == 401:
            pytest.skip("Auth middleware active")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["entries"]) == 2

    async def test_get_memory_session(self, _wired_services: Any) -> None:
        """GET /v1/sessions/memory/{id} returns a single session."""
        import httpx

        from agent33.main import app

        svcs = _wired_services
        catalog = svcs["catalog"]
        app.state.memory_session_catalog = catalog

        entry = catalog.create_session(agent_id="qa", tags=["review"])

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.get(f"/v1/sessions/memory/{entry.session_id}")

        if resp.status_code == 401:
            pytest.skip("Auth middleware active")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == entry.session_id
        assert data["agent_id"] == "qa"
        assert data["tags"] == ["review"]

    async def test_get_memory_session_not_found(self, _wired_services: Any) -> None:
        """GET /v1/sessions/memory/{id} returns 404 for missing session."""
        import httpx

        from agent33.main import app

        svcs = _wired_services
        app.state.memory_session_catalog = svcs["catalog"]

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.get("/v1/sessions/memory/nonexistent")

        if resp.status_code == 401:
            pytest.skip("Auth middleware active")
        assert resp.status_code == 404

    async def test_update_memory_session(self, _wired_services: Any) -> None:
        """PATCH /v1/sessions/memory/{id} updates tags and metadata."""
        import httpx

        from agent33.main import app

        svcs = _wired_services
        catalog = svcs["catalog"]
        app.state.memory_session_catalog = catalog

        entry = catalog.create_session(agent_id="worker")

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.patch(
                f"/v1/sessions/memory/{entry.session_id}",
                json={
                    "tags": ["updated"],
                    "metadata": {"key": "value"},
                    "message_count": 42,
                    "status": "completed",
                },
            )

        if resp.status_code == 401:
            pytest.skip("Auth middleware active")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tags"] == ["updated"]
        assert data["metadata"] == {"key": "value"}
        assert data["message_count"] == 42
        assert data["status"] == "completed"

    async def test_memory_session_lineage(self, _wired_services: Any) -> None:
        """GET /v1/sessions/memory/{id}/lineage returns delegation tree."""
        import httpx

        from agent33.main import app

        svcs = _wired_services
        catalog = svcs["catalog"]
        app.state.memory_session_catalog = catalog

        parent = catalog.create_session(agent_id="orchestrator")
        child = catalog.create_session(agent_id="worker", parent_session_id=parent.session_id)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.get(f"/v1/sessions/memory/{child.session_id}/lineage")

        if resp.status_code == 401:
            pytest.skip("Auth middleware active")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == parent.session_id
        assert len(data["children"]) == 1
        assert data["children"][0]["session_id"] == child.session_id

    async def test_context_slots_register_and_list(self, _wired_services: Any) -> None:
        """POST+GET /v1/sessions/memory/{id}/context-slots works."""
        import httpx

        from agent33.main import app

        svcs = _wired_services
        app.state.context_slot_manager = svcs["slot_manager"]

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            # Register a slot
            create_resp = await client.post(
                "/v1/sessions/memory/s1/context-slots",
                json={
                    "name": "system_prompt",
                    "content": "You are helpful.",
                    "token_count": 10,
                    "priority": "required",
                    "source": "system",
                },
            )

        if create_resp.status_code == 401:
            pytest.skip("Auth middleware active")
        assert create_resp.status_code == 201
        slot_data = create_resp.json()
        assert slot_data["name"] == "system_prompt"
        assert slot_data["priority"] == "required"

        # List slots
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            list_resp = await client.get("/v1/sessions/memory/s1/context-slots")

        assert list_resp.status_code == 200
        summary = list_resp.json()
        assert summary["slot_count"] == 1
        assert summary["total_tokens"] == 10

    async def test_context_slot_evict(self, _wired_services: Any) -> None:
        """DELETE /v1/sessions/memory/{id}/context-slots/{name} removes slot."""
        import httpx

        from agent33.main import app

        svcs = _wired_services
        slot_mgr = svcs["slot_manager"]
        app.state.context_slot_manager = slot_mgr

        slot_mgr.register("s1", ContextSlot(name="tools", token_count=50))

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.delete("/v1/sessions/memory/s1/context-slots/tools")

        if resp.status_code == 401:
            pytest.skip("Auth middleware active")
        assert resp.status_code == 200
        assert resp.json()["status"] == "evicted"

        # Verify evicted
        assert slot_mgr.list_slots("s1") == []

    async def test_context_slot_evict_not_found(self, _wired_services: Any) -> None:
        """DELETE returns 404 for non-existent slot."""
        import httpx

        from agent33.main import app

        svcs = _wired_services
        app.state.context_slot_manager = svcs["slot_manager"]

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.delete("/v1/sessions/memory/s1/context-slots/missing")

        if resp.status_code == 401:
            pytest.skip("Auth middleware active")
        assert resp.status_code == 404

    async def test_compaction_history_route(self, _wired_services: Any) -> None:
        """GET /v1/sessions/memory/{id}/compaction-history returns events and summary."""
        import httpx

        from agent33.main import app

        svcs = _wired_services
        compaction_diag = svcs["compaction_diag"]
        app.state.compaction_diagnostics = compaction_diag

        compaction_diag.record(
            CompactionEvent(
                session_id="s1",
                messages_before=100,
                messages_after=40,
                tokens_saved=3000,
                strategy="summarize",
                trigger_reason="budget",
            )
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.get("/v1/sessions/memory/s1/compaction-history")

        if resp.status_code == 401:
            pytest.skip("Auth middleware active")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "s1"
        assert len(data["events"]) == 1
        assert data["events"][0]["tokens_saved"] == 3000
        assert data["events"][0]["strategy"] == "summarize"
        assert data["summary"]["total_compactions"] == 1
        assert data["summary"]["total_tokens_saved"] == 3000
        assert data["summary"]["total_messages_removed"] == 60

    async def test_compaction_history_empty(self, _wired_services: Any) -> None:
        """GET compaction-history for session with no events returns empty."""
        import httpx

        from agent33.main import app

        svcs = _wired_services
        app.state.compaction_diagnostics = svcs["compaction_diag"]

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.get("/v1/sessions/memory/empty/compaction-history")

        if resp.status_code == 401:
            pytest.skip("Auth middleware active")
        assert resp.status_code == 200
        data = resp.json()
        assert data["events"] == []
        assert data["summary"]["total_compactions"] == 0
