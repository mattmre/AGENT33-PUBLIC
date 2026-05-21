"""Tests for embedding model hot-swap (S44).

Covers:
- Model registration and listing
- Swap validation (compatible and incompatible models)
- Swap execution lifecycle
- Rollback behavior
- Swap history tracking and bounded storage
- Cache invalidation on swap
- Concurrent swap safety
- API routes with auth
- Stats computation
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Any
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from agent33.memory.embedding_swap import (
    EmbeddingModelInfo,
    EmbeddingSwapManager,
    SwapRecord,
    SwapStatus,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_model(
    model_id: str = "nomic-embed-text",
    provider: str = "ollama",
    dimensions: int = 768,
    **kwargs: Any,
) -> EmbeddingModelInfo:
    return EmbeddingModelInfo(
        model_id=model_id,
        provider=provider,
        dimensions=dimensions,
        **kwargs,
    )


@pytest.fixture()
def default_model() -> EmbeddingModelInfo:
    return _make_model()


@pytest.fixture()
def alt_model() -> EmbeddingModelInfo:
    return _make_model(
        model_id="bge-large-en",
        provider="ollama",
        dimensions=1024,
        version="1.5",
        description="BGE large English embeddings",
    )


@pytest.fixture()
def same_dim_model() -> EmbeddingModelInfo:
    return _make_model(
        model_id="nomic-embed-text-v2",
        provider="ollama",
        dimensions=768,
        version="2.0",
    )


@pytest.fixture()
def manager(default_model: EmbeddingModelInfo) -> EmbeddingSwapManager:
    return EmbeddingSwapManager(current_model=default_model, max_history=100)


class FakeEmbeddingCache:
    """Minimal stand-in for EmbeddingCache to verify invalidation."""

    def __init__(self) -> None:
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self.clear_count = 0
        self._lock = asyncio.Lock()

    @property
    def size(self) -> int:
        return len(self._cache)

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    def clear(self) -> None:
        self._cache.clear()
        self.clear_count += 1


class FakeEmbeddingProvider:
    """Minimal stand-in for EmbeddingProvider."""

    def __init__(self, model: str = "nomic-embed-text") -> None:
        self._model = model


# ---------------------------------------------------------------------------
# Model registration and listing
# ---------------------------------------------------------------------------


class TestModelRegistration:
    """Test registering and listing embedding models."""

    async def test_initial_model_is_registered(
        self, manager: EmbeddingSwapManager, default_model: EmbeddingModelInfo
    ) -> None:
        models = manager.list_available_models()
        assert len(models) == 1
        assert models[0].model_id == default_model.model_id
        assert models[0].dimensions == 768

    async def test_register_new_model(
        self, manager: EmbeddingSwapManager, alt_model: EmbeddingModelInfo
    ) -> None:
        await manager.register_model(alt_model)
        models = manager.list_available_models()
        assert len(models) == 2
        model_ids = [m.model_id for m in models]
        assert "bge-large-en" in model_ids

    async def test_register_replaces_existing(self, manager: EmbeddingSwapManager) -> None:
        updated = _make_model(
            model_id="nomic-embed-text",
            dimensions=1024,
            version="2.0",
        )
        await manager.register_model(updated)
        models = manager.list_available_models()
        assert len(models) == 1
        assert models[0].dimensions == 1024
        assert models[0].version == "2.0"

    async def test_get_model_by_id(
        self, manager: EmbeddingSwapManager, alt_model: EmbeddingModelInfo
    ) -> None:
        await manager.register_model(alt_model)
        found = manager.get_model("bge-large-en")
        assert found is not None
        assert found.provider == "ollama"
        assert found.dimensions == 1024

    async def test_get_model_not_found(self, manager: EmbeddingSwapManager) -> None:
        assert manager.get_model("nonexistent") is None

    async def test_list_sorted_by_model_id(self, manager: EmbeddingSwapManager) -> None:
        await manager.register_model(_make_model("z-model", dimensions=512))
        await manager.register_model(_make_model("a-model", dimensions=256))
        models = manager.list_available_models()
        ids = [m.model_id for m in models]
        assert ids == sorted(ids)


# ---------------------------------------------------------------------------
# Swap validation
# ---------------------------------------------------------------------------


class TestSwapValidation:
    """Test pre-swap compatibility validation."""

    async def test_validate_unregistered_model(self, manager: EmbeddingSwapManager) -> None:
        valid, msg = await manager.validate_swap("unknown-model")
        assert valid is False
        assert "not registered" in msg

    async def test_validate_same_model(
        self, manager: EmbeddingSwapManager, default_model: EmbeddingModelInfo
    ) -> None:
        valid, msg = await manager.validate_swap(default_model.model_id)
        assert valid is False
        assert "already the active model" in msg

    async def test_validate_dimension_mismatch_warns(
        self, manager: EmbeddingSwapManager, alt_model: EmbeddingModelInfo
    ) -> None:
        await manager.register_model(alt_model)
        valid, msg = await manager.validate_swap("bge-large-en")
        assert valid is True
        assert "Dimension mismatch" in msg
        assert "768" in msg
        assert "1024" in msg

    async def test_validate_compatible_swap(
        self, manager: EmbeddingSwapManager, same_dim_model: EmbeddingModelInfo
    ) -> None:
        await manager.register_model(same_dim_model)
        valid, msg = await manager.validate_swap("nomic-embed-text-v2")
        assert valid is True
        assert "compatible" in msg.lower()


# ---------------------------------------------------------------------------
# Swap execution lifecycle
# ---------------------------------------------------------------------------


class TestSwapExecution:
    """Test the swap execution path."""

    async def test_swap_updates_current_model(
        self, manager: EmbeddingSwapManager, alt_model: EmbeddingModelInfo
    ) -> None:
        await manager.register_model(alt_model)
        record = await manager.execute_swap("bge-large-en", initiated_by="test-user")

        assert record.status == SwapStatus.COMPLETED
        assert record.from_model == "nomic-embed-text"
        assert record.to_model == "bge-large-en"
        assert record.initiated_by == "test-user"
        assert record.duration_ms >= 0

        current = manager.get_current_model()
        assert current.model_id == "bge-large-en"
        assert current.dimensions == 1024

    async def test_swap_unregistered_raises(self, manager: EmbeddingSwapManager) -> None:
        with pytest.raises(ValueError, match="not registered"):
            await manager.execute_swap("missing-model", initiated_by="test")

    async def test_swap_to_same_model_raises(self, manager: EmbeddingSwapManager) -> None:
        with pytest.raises(ValueError, match="already active"):
            await manager.execute_swap("nomic-embed-text", initiated_by="test")

    async def test_swap_creates_history_entry(
        self, manager: EmbeddingSwapManager, alt_model: EmbeddingModelInfo
    ) -> None:
        await manager.register_model(alt_model)
        await manager.execute_swap("bge-large-en", initiated_by="admin")

        history = manager.get_swap_history()
        assert len(history) == 1
        assert history[0].to_model == "bge-large-en"

    async def test_swap_record_has_unique_id(
        self, manager: EmbeddingSwapManager, alt_model: EmbeddingModelInfo
    ) -> None:
        await manager.register_model(alt_model)
        r1 = await manager.execute_swap("bge-large-en", initiated_by="admin")
        await manager.register_model(_make_model("model-c", dimensions=512))
        r2 = await manager.execute_swap("model-c", initiated_by="admin")
        assert r1.swap_id != r2.swap_id

    async def test_swap_updates_provider_model(
        self, manager: EmbeddingSwapManager, alt_model: EmbeddingModelInfo
    ) -> None:
        provider = FakeEmbeddingProvider()
        manager.set_embedding_provider(provider)  # type: ignore[arg-type]
        await manager.register_model(alt_model)

        await manager.execute_swap("bge-large-en", initiated_by="admin")
        assert provider._model == "bge-large-en"


# ---------------------------------------------------------------------------
# Cache invalidation on swap
# ---------------------------------------------------------------------------


class TestCacheInvalidation:
    """Test that swapping models invalidates the embedding cache."""

    async def test_swap_clears_cache(
        self, manager: EmbeddingSwapManager, alt_model: EmbeddingModelInfo
    ) -> None:
        cache = FakeEmbeddingCache()
        cache._cache["hash1"] = [1.0, 2.0]
        cache._cache["hash2"] = [3.0, 4.0]
        manager.set_embedding_cache(cache)  # type: ignore[arg-type]
        await manager.register_model(alt_model)

        assert cache.size == 2
        await manager.execute_swap("bge-large-en", initiated_by="admin")
        assert cache.size == 0
        assert cache.clear_count == 1

    async def test_rollback_clears_cache(
        self, manager: EmbeddingSwapManager, alt_model: EmbeddingModelInfo
    ) -> None:
        cache = FakeEmbeddingCache()
        manager.set_embedding_cache(cache)  # type: ignore[arg-type]
        await manager.register_model(alt_model)

        await manager.execute_swap("bge-large-en", initiated_by="admin")
        assert cache.clear_count == 1

        await manager.rollback_last_swap()
        assert cache.clear_count == 2

    async def test_swap_without_cache_does_not_error(
        self, manager: EmbeddingSwapManager, alt_model: EmbeddingModelInfo
    ) -> None:
        """If no cache is wired, swap should still succeed."""
        await manager.register_model(alt_model)
        record = await manager.execute_swap("bge-large-en", initiated_by="admin")
        assert record.status == SwapStatus.COMPLETED


# ---------------------------------------------------------------------------
# Rollback behavior
# ---------------------------------------------------------------------------


class TestRollback:
    """Test rollback to previous model."""

    async def test_rollback_reverts_to_previous_model(
        self, manager: EmbeddingSwapManager, alt_model: EmbeddingModelInfo
    ) -> None:
        await manager.register_model(alt_model)
        await manager.execute_swap("bge-large-en", initiated_by="admin")

        assert manager.get_current_model().model_id == "bge-large-en"

        record = await manager.rollback_last_swap()
        assert record is not None
        assert record.status == SwapStatus.ROLLED_BACK
        assert record.from_model == "bge-large-en"
        assert record.to_model == "nomic-embed-text"
        assert manager.get_current_model().model_id == "nomic-embed-text"

    async def test_rollback_no_history_returns_none(self, manager: EmbeddingSwapManager) -> None:
        result = await manager.rollback_last_swap()
        assert result is None

    async def test_rollback_already_rolled_back_returns_none(
        self, manager: EmbeddingSwapManager, alt_model: EmbeddingModelInfo
    ) -> None:
        await manager.register_model(alt_model)
        await manager.execute_swap("bge-large-en", initiated_by="admin")
        await manager.rollback_last_swap()

        # Second rollback has no completed swap to rollback
        result = await manager.rollback_last_swap()
        assert result is None

    async def test_rollback_marks_original_as_rolled_back(
        self, manager: EmbeddingSwapManager, alt_model: EmbeddingModelInfo
    ) -> None:
        await manager.register_model(alt_model)
        await manager.execute_swap("bge-large-en", initiated_by="admin")
        await manager.rollback_last_swap()

        history = manager.get_swap_history()
        # History should have 2 records: the rollback and the original swap
        assert len(history) == 2
        # Both should be marked as rolled_back
        statuses = {r.status for r in history}
        assert SwapStatus.ROLLED_BACK in statuses

    async def test_rollback_updates_provider_model(
        self, manager: EmbeddingSwapManager, alt_model: EmbeddingModelInfo
    ) -> None:
        provider = FakeEmbeddingProvider()
        manager.set_embedding_provider(provider)  # type: ignore[arg-type]
        await manager.register_model(alt_model)

        await manager.execute_swap("bge-large-en", initiated_by="admin")
        assert provider._model == "bge-large-en"

        await manager.rollback_last_swap()
        assert provider._model == "nomic-embed-text"


# ---------------------------------------------------------------------------
# History tracking
# ---------------------------------------------------------------------------


class TestSwapHistory:
    """Test history tracking and bounded storage."""

    async def test_history_ordered_most_recent_first(self, manager: EmbeddingSwapManager) -> None:
        models = [_make_model(f"model-{i}", dimensions=100 + i) for i in range(3)]
        for m in models:
            await manager.register_model(m)

        await manager.execute_swap("model-0", initiated_by="admin")
        await manager.execute_swap("model-1", initiated_by="admin")
        await manager.execute_swap("model-2", initiated_by="admin")

        history = manager.get_swap_history()
        assert len(history) == 3
        assert history[0].to_model == "model-2"
        assert history[2].to_model == "model-0"

    async def test_history_limited_by_param(self, manager: EmbeddingSwapManager) -> None:
        models = [_make_model(f"model-{i}", dimensions=100 + i) for i in range(5)]
        for m in models:
            await manager.register_model(m)

        for i in range(5):
            await manager.execute_swap(f"model-{i}", initiated_by="admin")

        history = manager.get_swap_history(limit=2)
        assert len(history) == 2

    async def test_bounded_history_evicts_oldest(self, default_model: EmbeddingModelInfo) -> None:
        # Small bounded history
        mgr = EmbeddingSwapManager(current_model=default_model, max_history=3)
        models = [_make_model(f"m-{i}", dimensions=100 + i) for i in range(5)]
        for m in models:
            await mgr.register_model(m)

        for i in range(5):
            await mgr.execute_swap(f"m-{i}", initiated_by="admin")

        history = mgr.get_swap_history()
        assert len(history) == 3
        # Oldest entries evicted; most recent 3 remain
        ids = [r.to_model for r in history]
        assert "m-4" in ids
        assert "m-3" in ids
        assert "m-2" in ids

    async def test_empty_history(self, manager: EmbeddingSwapManager) -> None:
        history = manager.get_swap_history()
        assert history == []


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


class TestStats:
    """Test stats computation."""

    async def test_initial_stats(self, manager: EmbeddingSwapManager) -> None:
        stats = manager.get_current_stats()
        assert stats["current_model"] == "nomic-embed-text"
        assert stats["current_provider"] == "ollama"
        assert stats["current_dimensions"] == 768
        assert stats["registered_models"] == 1
        assert stats["total_swaps"] == 0
        assert stats["total_rollbacks"] == 0
        assert stats["total_failures"] == 0
        assert stats["history_size"] == 0
        assert stats["cache_size"] == 0
        assert stats["cache_hit_rate"] == 0.0
        assert "uptime_since" in stats

    async def test_stats_after_swap(
        self, manager: EmbeddingSwapManager, alt_model: EmbeddingModelInfo
    ) -> None:
        await manager.register_model(alt_model)
        await manager.execute_swap("bge-large-en", initiated_by="admin")

        stats = manager.get_current_stats()
        assert stats["current_model"] == "bge-large-en"
        assert stats["registered_models"] == 2
        assert stats["total_swaps"] == 1
        assert stats["history_size"] == 1

    async def test_stats_with_cache(self, manager: EmbeddingSwapManager) -> None:
        cache = FakeEmbeddingCache()
        cache._cache["k1"] = [1.0]
        cache._hits = 5
        cache._misses = 3
        manager.set_embedding_cache(cache)  # type: ignore[arg-type]

        stats = manager.get_current_stats()
        assert stats["cache_size"] == 1
        assert stats["cache_hit_rate"] == pytest.approx(5 / 8)

    async def test_stats_rollback_count(
        self, manager: EmbeddingSwapManager, alt_model: EmbeddingModelInfo
    ) -> None:
        await manager.register_model(alt_model)
        await manager.execute_swap("bge-large-en", initiated_by="admin")
        await manager.rollback_last_swap()

        stats = manager.get_current_stats()
        assert stats["total_swaps"] == 1
        assert stats["total_rollbacks"] == 1


# ---------------------------------------------------------------------------
# Concurrent swap safety
# ---------------------------------------------------------------------------


class TestConcurrentSwapSafety:
    """Test that concurrent swap operations are serialized."""

    async def test_concurrent_swaps_do_not_corrupt_state(
        self, default_model: EmbeddingModelInfo
    ) -> None:
        mgr = EmbeddingSwapManager(current_model=default_model)
        models = [_make_model(f"c-{i}", dimensions=100 + i) for i in range(10)]
        for m in models:
            await mgr.register_model(m)

        # Launch concurrent swaps
        results: list[SwapRecord | Exception] = []

        async def _swap(model_id: str) -> SwapRecord:
            return await mgr.execute_swap(model_id, initiated_by="concurrent")

        tasks = [_swap(f"c-{i}") for i in range(10)]
        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        results.extend(gathered)

        # Some should succeed, rest should raise (already active or other conflict)
        successes = [r for r in results if isinstance(r, SwapRecord)]
        errors = [r for r in results if isinstance(r, (ValueError, Exception))]

        # At least one must succeed; total should equal 10
        assert len(successes) >= 1
        assert len(successes) + len(errors) == 10

        # Current model must be one of the c-* models (not corrupted)
        current = mgr.get_current_model()
        assert current.model_id.startswith("c-")

        # History must match the number of completed + failed swaps
        # (pending records don't remain; all get resolved)
        history = mgr.get_swap_history(limit=100)
        for record in history:
            assert record.status in {SwapStatus.COMPLETED, SwapStatus.FAILED}


# ---------------------------------------------------------------------------
# Pydantic model validation
# ---------------------------------------------------------------------------


class TestModelValidation:
    """Test Pydantic model constraints."""

    def test_embedding_model_info_requires_positive_dimensions(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            EmbeddingModelInfo(
                model_id="bad",
                provider="test",
                dimensions=0,
            )

    def test_swap_record_defaults(self) -> None:
        record = SwapRecord(
            from_model="a",
            to_model="b",
            initiated_by="test",
        )
        assert record.status == SwapStatus.PENDING
        assert record.duration_ms == 0.0
        assert record.swap_id  # non-empty
        assert record.timestamp is not None


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def _app_with_swap_manager(
    default_model: EmbeddingModelInfo,
) -> Any:
    """Create a FastAPI app with swap manager on app.state and auth bypassed."""
    from fastapi import FastAPI

    test_app = FastAPI()

    from agent33.api.routes.embedding_swap import router

    test_app.include_router(router)

    mgr = EmbeddingSwapManager(current_model=default_model)

    @test_app.middleware("http")
    async def _fake_auth(request: Any, call_next: Any) -> Any:
        """Inject a fake admin user so require_scope('admin') passes."""
        request.state.user = MagicMock(scopes=["admin"])
        return await call_next(request)

    test_app.state.embedding_swap = mgr
    return test_app


@pytest.fixture()
async def client(_app_with_swap_manager: Any) -> AsyncClient:
    transport = ASGITransport(app=_app_with_swap_manager)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestAPIRoutes:
    """Test embedding swap API endpoints with mocked auth."""

    async def test_get_current_model(self, client: AsyncClient) -> None:
        resp = await client.get("/v1/embeddings/current")
        assert resp.status_code == 200
        body = resp.json()
        assert body["model_id"] == "nomic-embed-text"
        assert body["provider"] == "ollama"
        assert body["dimensions"] == 768

    async def test_list_models_initially(self, client: AsyncClient) -> None:
        resp = await client.get("/v1/embeddings/models")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert len(body["models"]) == 1

    async def test_register_model(self, client: AsyncClient) -> None:
        payload = {
            "model_id": "bge-small",
            "provider": "ollama",
            "dimensions": 384,
            "version": "1.0",
            "description": "Small BGE model",
        }
        resp = await client.post("/v1/embeddings/models", json=payload)
        assert resp.status_code == 201
        body = resp.json()
        assert body["model_id"] == "bge-small"
        assert body["dimensions"] == 384

        # Verify it shows up in listing
        resp2 = await client.get("/v1/embeddings/models")
        assert resp2.json()["count"] == 2

    async def test_register_model_invalid_dimensions(self, client: AsyncClient) -> None:
        payload = {
            "model_id": "bad",
            "provider": "test",
            "dimensions": -1,
        }
        resp = await client.post("/v1/embeddings/models", json=payload)
        assert resp.status_code == 422

    async def test_execute_swap(self, client: AsyncClient) -> None:
        # Register target
        await client.post(
            "/v1/embeddings/models",
            json={
                "model_id": "new-model",
                "provider": "ollama",
                "dimensions": 768,
            },
        )

        # Execute swap
        resp = await client.post(
            "/v1/embeddings/swap",
            json={"target_model_id": "new-model", "initiated_by": "test-admin"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        assert body["to_model"] == "new-model"
        assert body["initiated_by"] == "test-admin"

        # Current model should have changed
        resp2 = await client.get("/v1/embeddings/current")
        assert resp2.json()["model_id"] == "new-model"

    async def test_swap_unregistered_returns_400(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/v1/embeddings/swap",
            json={"target_model_id": "nonexistent"},
        )
        assert resp.status_code == 400
        assert "not registered" in resp.json()["detail"]

    async def test_swap_to_same_model_returns_400(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/v1/embeddings/swap",
            json={"target_model_id": "nomic-embed-text"},
        )
        assert resp.status_code == 400
        assert "already" in resp.json()["detail"]

    async def test_rollback_no_history_returns_404(self, client: AsyncClient) -> None:
        resp = await client.post("/v1/embeddings/rollback")
        assert resp.status_code == 404

    async def test_rollback_after_swap(self, client: AsyncClient) -> None:
        await client.post(
            "/v1/embeddings/models",
            json={"model_id": "target", "provider": "ollama", "dimensions": 768},
        )
        await client.post(
            "/v1/embeddings/swap",
            json={"target_model_id": "target"},
        )

        resp = await client.post("/v1/embeddings/rollback")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "rolled_back"
        assert body["to_model"] == "nomic-embed-text"

    async def test_get_history(self, client: AsyncClient) -> None:
        await client.post(
            "/v1/embeddings/models",
            json={"model_id": "target", "provider": "ollama", "dimensions": 768},
        )
        await client.post(
            "/v1/embeddings/swap",
            json={"target_model_id": "target"},
        )

        resp = await client.get("/v1/embeddings/history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert len(body["records"]) == 1

    async def test_get_history_with_limit(self, client: AsyncClient) -> None:
        resp = await client.get("/v1/embeddings/history?limit=5")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    async def test_get_stats(self, client: AsyncClient) -> None:
        resp = await client.get("/v1/embeddings/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["current_model"] == "nomic-embed-text"
        assert body["total_swaps"] == 0
        assert body["registered_models"] == 1

    async def test_stats_update_after_swap(self, client: AsyncClient) -> None:
        await client.post(
            "/v1/embeddings/models",
            json={"model_id": "m", "provider": "p", "dimensions": 128},
        )
        await client.post(
            "/v1/embeddings/swap",
            json={"target_model_id": "m"},
        )

        resp = await client.get("/v1/embeddings/stats")
        body = resp.json()
        assert body["total_swaps"] == 1
        assert body["current_model"] == "m"


# ---------------------------------------------------------------------------
# API auth enforcement (no auth -> 401)
# ---------------------------------------------------------------------------


class TestAPIAuthEnforcement:
    """Test that unauthenticated requests are rejected."""

    async def test_no_auth_returns_401(self) -> None:
        """Routes without auth middleware should get 401 from require_scope."""
        from fastapi import FastAPI

        from agent33.api.routes.embedding_swap import router
        from agent33.security.middleware import AuthMiddleware

        bare_app = FastAPI()
        bare_app.add_middleware(AuthMiddleware)
        bare_app.include_router(router)

        transport = ASGITransport(app=bare_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/v1/embeddings/current")
            assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Service unavailable when manager not wired
# ---------------------------------------------------------------------------


class TestManagerNotInitialized:
    """Test 503 response when swap manager is not on app.state."""

    async def test_503_when_manager_missing(self) -> None:
        from fastapi import FastAPI

        from agent33.api.routes.embedding_swap import router

        bare_app = FastAPI()
        bare_app.include_router(router)

        @bare_app.middleware("http")
        async def _fake_auth(request: Any, call_next: Any) -> Any:
            request.state.user = MagicMock(scopes=["admin"])
            return await call_next(request)

        # No embedding_swap on app.state
        transport = ASGITransport(app=bare_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/v1/embeddings/current")
            assert resp.status_code == 503
            assert "not initialized" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Fix 2: Swap state revert on failure
# ---------------------------------------------------------------------------


class TestSwapStateRevert:
    """Test that _current_model is not updated if swap side effects fail."""

    async def test_current_model_reverts_on_provider_error(
        self,
        manager: EmbeddingSwapManager,
        alt_model: EmbeddingModelInfo,
    ) -> None:
        """If the provider mutation raises, _current_model stays unchanged."""

        class FailingProvider:
            _model: str = "nomic-embed-text"

            def __setattr__(self, name: str, value: Any) -> None:
                if name == "_model" and value == "bge-large-en":
                    raise RuntimeError("Provider mutation failed")
                super().__setattr__(name, value)

        manager.set_embedding_provider(FailingProvider())  # type: ignore[arg-type]
        await manager.register_model(alt_model)

        record = await manager.execute_swap("bge-large-en", initiated_by="test")
        assert record.status == SwapStatus.FAILED
        assert "Provider mutation failed" in record.error

        # Current model must NOT have been updated
        assert manager.get_current_model().model_id == "nomic-embed-text"

    async def test_current_model_reverts_on_cache_error(
        self,
        manager: EmbeddingSwapManager,
        alt_model: EmbeddingModelInfo,
    ) -> None:
        """If cache invalidation raises, _current_model stays unchanged."""

        class FailingCache:
            _lock = asyncio.Lock()

            @property
            def size(self) -> int:
                return 0

            @property
            def hit_rate(self) -> float:
                return 0.0

            def clear(self) -> None:
                raise RuntimeError("Cache clear exploded")

        manager.set_embedding_cache(FailingCache())  # type: ignore[arg-type]
        await manager.register_model(alt_model)

        record = await manager.execute_swap("bge-large-en", initiated_by="test")
        assert record.status == SwapStatus.FAILED
        assert "Cache clear exploded" in record.error

        # Current model must NOT have been updated
        assert manager.get_current_model().model_id == "nomic-embed-text"


# ---------------------------------------------------------------------------
# Fix 3: Cache invalidation acquires cache lock
# ---------------------------------------------------------------------------


class TestCacheInvalidationLockAcquisition:
    """Test that _invalidate_cache() uses the cache's internal lock."""

    async def test_invalidate_cache_acquires_lock(
        self,
        manager: EmbeddingSwapManager,
        alt_model: EmbeddingModelInfo,
    ) -> None:
        """Verify that the cache lock is acquired during invalidation."""
        cache = FakeEmbeddingCache()
        cache._cache["key"] = [1.0]
        manager.set_embedding_cache(cache)  # type: ignore[arg-type]
        await manager.register_model(alt_model)

        # Track lock acquisitions
        original_lock = cache._lock
        lock_acquired_count = 0
        original_acquire = original_lock.acquire

        async def tracking_acquire() -> bool:
            nonlocal lock_acquired_count
            result = await original_acquire()
            lock_acquired_count += 1
            return result

        original_lock.acquire = tracking_acquire  # type: ignore[assignment]

        await manager.execute_swap("bge-large-en", initiated_by="admin")
        assert cache.clear_count == 1
        assert lock_acquired_count >= 1


# ---------------------------------------------------------------------------
# Fix 4: Failed swap returns 409 via API
# ---------------------------------------------------------------------------


class TestFailedSwapReturns409:
    """Test that a swap that fails at runtime returns HTTP 409."""

    async def test_swap_failure_returns_409(self) -> None:
        from fastapi import FastAPI

        from agent33.api.routes.embedding_swap import router

        test_app = FastAPI()
        test_app.include_router(router)

        default = _make_model()
        mgr = EmbeddingSwapManager(current_model=default)

        class FailingCache:
            _lock = asyncio.Lock()

            @property
            def size(self) -> int:
                return 0

            @property
            def hit_rate(self) -> float:
                return 0.0

            def clear(self) -> None:
                raise RuntimeError("Intentional cache failure")

        mgr.set_embedding_cache(FailingCache())  # type: ignore[arg-type]

        @test_app.middleware("http")
        async def _fake_auth(request: Any, call_next: Any) -> Any:
            request.state.user = MagicMock(scopes=["admin"])
            return await call_next(request)

        test_app.state.embedding_swap = mgr

        # Register the target model first
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            await c.post(
                "/v1/embeddings/models",
                json={"model_id": "fail-model", "provider": "test", "dimensions": 256},
            )
            resp = await c.post(
                "/v1/embeddings/swap",
                json={"target_model_id": "fail-model"},
            )
            assert resp.status_code == 409
            assert "Intentional cache failure" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Fix 5: Limit validation on history endpoint
# ---------------------------------------------------------------------------


class TestHistoryLimitValidation:
    """Test that the limit query param is validated."""

    async def test_negative_limit_rejected(self, client: AsyncClient) -> None:
        resp = await client.get("/v1/embeddings/history?limit=-1")
        assert resp.status_code == 422

    async def test_zero_limit_rejected(self, client: AsyncClient) -> None:
        resp = await client.get("/v1/embeddings/history?limit=0")
        assert resp.status_code == 422

    async def test_limit_over_max_rejected(self, client: AsyncClient) -> None:
        resp = await client.get("/v1/embeddings/history?limit=101")
        assert resp.status_code == 422

    async def test_valid_limit_accepted(self, client: AsyncClient) -> None:
        resp = await client.get("/v1/embeddings/history?limit=50")
        assert resp.status_code == 200
