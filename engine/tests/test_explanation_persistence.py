"""Persistence tests for ExplanationStore.

These tests prove that explanations written to a SQLite store are retrievable
after the store object is discarded and a new instance is opened against the
same database file — simulating a server restart.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from agent33.explanation.models import (
    ClaimType,
    ExplanationClaim,
    ExplanationMetadata,
    ExplanationMode,
    FactCheckStatus,
)
from agent33.explanation.store import ExplanationStore

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_explanation(
    explanation_id: str = "expl-test001",
    entity_type: str = "workflow",
    entity_id: str = "hello-flow",
    mode: ExplanationMode = ExplanationMode.DIFF_REVIEW,
    content: str = "<html>test</html>",
    fact_check_status: FactCheckStatus = FactCheckStatus.VERIFIED,
    claims: list[ExplanationClaim] | None = None,
    metadata: dict | None = None,
) -> ExplanationMetadata:
    return ExplanationMetadata(
        id=explanation_id,
        entity_type=entity_type,
        entity_id=entity_id,
        mode=mode,
        content=content,
        fact_check_status=fact_check_status,
        claims=claims or [],
        metadata=metadata or {},
        created_at=datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# Core persistence test — the acceptance criterion
# ---------------------------------------------------------------------------


class TestExplanationPersistenceAcrossRestarts:
    """Verify that stored explanations survive a simulated process restart."""

    def test_explanation_survives_store_restart(self, tmp_path: Path) -> None:
        """Store instance A writes; store instance B reads the same row."""
        db_file = tmp_path / "explanations.db"

        # --- First "process" ---
        store_a = ExplanationStore(db_path=str(db_file))
        meta = _make_explanation()
        store_a.save(meta)

        # Discard store_a; simulate server restart by creating store_b
        del store_a

        # --- Second "process" ---
        store_b = ExplanationStore(db_path=str(db_file))
        retrieved = store_b.get(meta.id)

        assert retrieved is not None, "Explanation must be retrievable after store restart"
        assert retrieved.id == meta.id
        assert retrieved.entity_type == meta.entity_type
        assert retrieved.entity_id == meta.entity_id
        assert retrieved.mode == meta.mode
        assert retrieved.content == meta.content
        assert retrieved.fact_check_status == meta.fact_check_status

    def test_claims_survive_restart(self, tmp_path: Path) -> None:
        """Claims stored on an explanation are fully round-tripped through SQLite."""
        db_file = tmp_path / "explanations.db"
        claim = ExplanationClaim(
            claim_type=ClaimType.METADATA_EQUALS,
            target="model",
            expected="llama3.1",
            actual="llama3.1",
            status=FactCheckStatus.VERIFIED,
            message="Metadata value matches expected value",
        )
        meta = _make_explanation(claims=[claim])

        store_a = ExplanationStore(db_path=str(db_file))
        store_a.save(meta)
        del store_a

        store_b = ExplanationStore(db_path=str(db_file))
        retrieved = store_b.get(meta.id)

        assert retrieved is not None
        assert len(retrieved.claims) == 1
        c = retrieved.claims[0]
        assert c.claim_type == ClaimType.METADATA_EQUALS
        assert c.target == "model"
        assert c.expected == "llama3.1"
        assert c.status == FactCheckStatus.VERIFIED

    def test_metadata_dict_survives_restart(self, tmp_path: Path) -> None:
        """Arbitrary metadata dict is round-tripped faithfully."""
        db_file = tmp_path / "explanations.db"
        meta = _make_explanation(metadata={"branch": "feat/test", "pr": 42, "nested": {"k": "v"}})

        ExplanationStore(db_path=str(db_file)).save(meta)

        store_b = ExplanationStore(db_path=str(db_file))
        retrieved = store_b.get(meta.id)

        assert retrieved is not None
        assert retrieved.metadata["branch"] == "feat/test"
        assert retrieved.metadata["pr"] == 42
        assert retrieved.metadata["nested"] == {"k": "v"}

    def test_multiple_explanations_survive_restart(self, tmp_path: Path) -> None:
        """Multiple explanations are all present after a restart."""
        db_file = tmp_path / "explanations.db"

        store_a = ExplanationStore(db_path=str(db_file))
        ids = []
        for i in range(5):
            m = _make_explanation(
                explanation_id=f"expl-{i:04d}",
                entity_id=f"flow-{i}",
            )
            store_a.save(m)
            ids.append(m.id)
        del store_a

        store_b = ExplanationStore(db_path=str(db_file))
        listed = store_b.list()
        assert len(listed) == 5

        for eid in ids:
            assert store_b.get(eid) is not None


# ---------------------------------------------------------------------------
# Additional store CRUD tests (unit coverage of store methods)
# ---------------------------------------------------------------------------


class TestExplanationStoreUnit:
    """Unit tests for CRUD operations on ExplanationStore."""

    @pytest.fixture
    def store(self) -> ExplanationStore:
        """In-memory SQLite store for fast isolated tests."""
        return ExplanationStore(db_path=":memory:")

    def test_save_and_get_roundtrip(self, store: ExplanationStore) -> None:
        meta = _make_explanation()
        store.save(meta)
        result = store.get(meta.id)
        assert result is not None
        assert result.id == meta.id

    def test_get_nonexistent_returns_none(self, store: ExplanationStore) -> None:
        assert store.get("nonexistent-id") is None

    def test_list_empty_store(self, store: ExplanationStore) -> None:
        assert store.list() == []

    def test_list_filter_by_entity_type(self, store: ExplanationStore) -> None:
        store.save(_make_explanation("expl-w1", entity_type="workflow", entity_id="f1"))
        store.save(_make_explanation("expl-a1", entity_type="agent", entity_id="a1"))

        workflows = store.list(entity_type="workflow")
        assert len(workflows) == 1
        assert workflows[0].entity_type == "workflow"

    def test_list_filter_by_entity_id(self, store: ExplanationStore) -> None:
        store.save(_make_explanation("expl-w1", entity_type="workflow", entity_id="flow-1"))
        store.save(_make_explanation("expl-w2", entity_type="workflow", entity_id="flow-2"))

        results = store.list(entity_id="flow-1")
        assert len(results) == 1
        assert results[0].entity_id == "flow-1"

    def test_list_combined_filter(self, store: ExplanationStore) -> None:
        store.save(_make_explanation("expl-w1", entity_type="workflow", entity_id="flow-1"))
        store.save(_make_explanation("expl-a1", entity_type="agent", entity_id="flow-1"))
        store.save(_make_explanation("expl-w2", entity_type="workflow", entity_id="flow-2"))

        results = store.list(entity_type="workflow", entity_id="flow-1")
        assert len(results) == 1
        assert results[0].id == "expl-w1"

    def test_delete_existing_returns_true(self, store: ExplanationStore) -> None:
        meta = _make_explanation()
        store.save(meta)
        assert store.delete(meta.id) is True
        assert store.get(meta.id) is None

    def test_delete_nonexistent_returns_false(self, store: ExplanationStore) -> None:
        assert store.delete("does-not-exist") is False

    def test_save_replaces_on_duplicate_id(self, store: ExplanationStore) -> None:
        """INSERT OR REPLACE semantics: second save updates the row."""
        meta = _make_explanation(content="original")
        store.save(meta)

        updated = meta.model_copy(update={"content": "updated"})
        store.save(updated)

        result = store.get(meta.id)
        assert result is not None
        assert result.content == "updated"

    def test_list_respects_limit(self, store: ExplanationStore) -> None:
        for i in range(10):
            store.save(_make_explanation(f"expl-{i:04d}", entity_id=f"flow-{i}"))

        results = store.list(limit=3)
        assert len(results) == 3
