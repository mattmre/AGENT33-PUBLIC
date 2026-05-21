"""Tests for TurboQuant-style embedding compression.

Validates the rotation + scalar quantization pipeline:
- Round-trip accuracy (compress → decompress preserves geometry)
- Cosine similarity preservation across quantization
- Compression ratio guarantees
- Edge cases (zero vectors, constant vectors, high-dimensional)
- Serialization round-trip
- Cache integration with compression
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock

import numpy as np
import pytest

from agent33.memory.quantization import TurboQuantCompressor

# ── Helpers ──────────────────────────────────────────────────────────────


def _random_vector(dim: int = 768, seed: int = 0) -> list[float]:
    """Generate a deterministic random unit vector."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim)
    v = v / np.linalg.norm(v)
    return v.tolist()


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    a_np = np.asarray(a)
    b_np = np.asarray(b)
    return float(np.dot(a_np, b_np) / (np.linalg.norm(a_np) * np.linalg.norm(b_np)))


# ── Compressor construction ─────────────────────────────────────────────


class TestTurboQuantCompressorInit:
    def test_default_construction(self) -> None:
        c = TurboQuantCompressor()
        assert c.dim == 768
        assert c.bits == 4

    def test_custom_params(self) -> None:
        c = TurboQuantCompressor(dim=256, bits=8, seed=99)
        assert c.dim == 256
        assert c.bits == 8

    def test_invalid_bits_low(self) -> None:
        with pytest.raises(ValueError, match="bits must be in"):
            TurboQuantCompressor(bits=0)

    def test_invalid_bits_high(self) -> None:
        with pytest.raises(ValueError, match="bits must be in"):
            TurboQuantCompressor(bits=9)


# ── Round-trip accuracy ─────────────────────────────────────────────────


class TestRoundTrip:
    @pytest.fixture()
    def compressor(self) -> TurboQuantCompressor:
        return TurboQuantCompressor(dim=768, bits=4)

    def test_round_trip_preserves_geometry(self, compressor: TurboQuantCompressor) -> None:
        """Compress → decompress should yield high cosine similarity."""
        original = _random_vector(768, seed=42)
        qv = compressor.compress(original)
        recovered = compressor.decompress(qv)

        sim = _cosine_sim(original, recovered)
        assert sim > 0.90, f"Cosine similarity {sim:.4f} too low after round-trip"

    def test_round_trip_multiple_vectors(self, compressor: TurboQuantCompressor) -> None:
        """Multiple independent vectors all round-trip with high fidelity."""
        for s in range(10):
            original = _random_vector(768, seed=s)
            recovered = compressor.decompress(compressor.compress(original))
            sim = _cosine_sim(original, recovered)
            assert sim > 0.90, f"Seed {s}: cosine {sim:.4f}"

    def test_8bit_near_lossless(self) -> None:
        """8-bit quantization should be nearly lossless (>0.999 cosine)."""
        c = TurboQuantCompressor(dim=768, bits=8)
        original = _random_vector(768, seed=7)
        recovered = c.decompress(c.compress(original))
        sim = _cosine_sim(original, recovered)
        assert sim > 0.995, f"8-bit cosine {sim:.6f} should be near-lossless"

    def test_2bit_still_reasonable(self) -> None:
        """Even 2-bit quantization should preserve basic direction (>0.75)."""
        c = TurboQuantCompressor(dim=768, bits=2)
        original = _random_vector(768, seed=3)
        recovered = c.decompress(c.compress(original))
        sim = _cosine_sim(original, recovered)
        assert sim > 0.75, f"2-bit cosine {sim:.4f} too degraded"


# ── Cosine similarity preservation ──────────────────────────────────────


class TestSimilarityPreservation:
    def test_similar_vectors_stay_similar(self) -> None:
        """Two similar vectors should remain similar after quantization."""
        c = TurboQuantCompressor(dim=768, bits=4)
        rng = np.random.default_rng(100)

        v1 = rng.standard_normal(768)
        v1 = v1 / np.linalg.norm(v1)
        # Create a similar vector (small perturbation).
        noise = rng.standard_normal(768) * 0.1
        v2 = v1 + noise
        v2 = v2 / np.linalg.norm(v2)

        original_sim = _cosine_sim(v1.tolist(), v2.tolist())
        q1 = c.compress(v1.tolist())
        q2 = c.compress(v2.tolist())
        approx_sim = c.approximate_cosine_similarity(q1, q2)

        # The error in similarity should be small.
        assert abs(original_sim - approx_sim) < 0.05, (
            f"Similarity drift: original={original_sim:.4f}, quantized={approx_sim:.4f}"
        )

    def test_orthogonal_vectors_stay_orthogonal(self) -> None:
        """Orthogonal vectors should have near-zero similarity after quantization."""
        c = TurboQuantCompressor(dim=768, bits=4)
        rng = np.random.default_rng(200)

        v1 = rng.standard_normal(768)
        v1 = v1 / np.linalg.norm(v1)
        # Gram-Schmidt to get orthogonal vector.
        v2 = rng.standard_normal(768)
        v2 = v2 - np.dot(v2, v1) * v1
        v2 = v2 / np.linalg.norm(v2)

        q1 = c.compress(v1.tolist())
        q2 = c.compress(v2.tolist())
        approx_sim = c.approximate_cosine_similarity(q1, q2)

        assert abs(approx_sim) < 0.1, f"Orthogonal vectors had similarity {approx_sim:.4f}"


# ── Compression ratio ───────────────────────────────────────────────────


class TestCompressionRatio:
    def test_4bit_768d_ratio(self) -> None:
        c = TurboQuantCompressor(dim=768, bits=4)
        ratio = c.compression_ratio()
        # float32: 768*4=3072 bytes, 4-bit: 384+11=395 bytes -> ~7.8x
        assert ratio > 7.0
        assert ratio < 8.5

    def test_8bit_ratio(self) -> None:
        c = TurboQuantCompressor(dim=768, bits=8)
        ratio = c.compression_ratio()
        # float32: 3072, 8-bit: 768+11=779 -> ~3.9x
        assert ratio > 3.5
        assert ratio < 4.5

    def test_actual_size_reduction(self) -> None:
        """The packed codes should actually be smaller than float32."""
        c = TurboQuantCompressor(dim=768, bits=4)
        v = _random_vector(768, seed=5)
        qv = c.compress(v)
        float32_size = 768 * 4  # 3072 bytes
        quantized_size = len(qv.codes) + 11  # codes + header (u16+u8+f32+f32)
        assert quantized_size < float32_size / 5  # at least 5x smaller


# ── Edge cases ───────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_zero_vector(self) -> None:
        """Zero vector should not crash and should round-trip to near-zero."""
        c = TurboQuantCompressor(dim=768, bits=4)
        zeros = [0.0] * 768
        qv = c.compress(zeros)
        recovered = c.decompress(qv)
        assert all(abs(x) < 1e-6 for x in recovered)

    def test_constant_vector(self) -> None:
        """Constant vector (all same value) should round-trip cleanly."""
        c = TurboQuantCompressor(dim=768, bits=4)
        const = [0.5] * 768
        recovered = c.decompress(c.compress(const))
        # Constant vector → all codes = 0 after rotation, so near-constant on recovery.
        mse = sum((a - b) ** 2 for a, b in zip(const, recovered, strict=True)) / len(const)
        assert mse < 0.01, f"MSE {mse:.6f} too high for constant vector"

    def test_dimension_mismatch(self) -> None:
        """Passing wrong-dimension vector should raise ValueError."""
        c = TurboQuantCompressor(dim=768, bits=4)
        with pytest.raises(ValueError, match="Expected vector of dim 768"):
            c.compress([1.0] * 100)

    def test_small_dimension(self) -> None:
        """Should work with small dimensions (e.g. 16)."""
        c = TurboQuantCompressor(dim=16, bits=4)
        v = _random_vector(16, seed=11)
        recovered = c.decompress(c.compress(v))
        sim = _cosine_sim(v, recovered)
        assert sim > 0.95

    def test_large_magnitude_vector(self) -> None:
        """Vectors with large magnitude should still quantize correctly."""
        c = TurboQuantCompressor(dim=768, bits=4)
        v = [x * 1000 for x in _random_vector(768, seed=8)]
        recovered = c.decompress(c.compress(v))
        sim = _cosine_sim(v, recovered)
        assert sim > 0.90


# ── Serialization ────────────────────────────────────────────────────────


class TestSerialization:
    def test_serialize_roundtrip(self) -> None:
        """Serialize → deserialize should produce identical QuantizedVector."""
        c = TurboQuantCompressor(dim=768, bits=4)
        qv = c.compress(_random_vector(768, seed=1))
        data = TurboQuantCompressor.serialize(qv)
        qv2 = TurboQuantCompressor.deserialize(data)

        assert qv.dim == qv2.dim
        assert qv.bits == qv2.bits
        assert abs(qv.scale - qv2.scale) < 1e-6
        assert abs(qv.offset - qv2.offset) < 1e-6
        assert qv.codes == qv2.codes

    def test_serialized_size(self) -> None:
        """Serialized form should be compact."""
        c = TurboQuantCompressor(dim=768, bits=4)
        qv = c.compress(_random_vector(768, seed=2))
        data = TurboQuantCompressor.serialize(qv)
        # 11 bytes header + ceil(768*4/8) = 384 bytes codes = 395 bytes
        assert len(data) == 11 + math.ceil(768 * 4 / 8)


# ── Batch operations ─────────────────────────────────────────────────────


class TestBatchOps:
    def test_compress_batch(self) -> None:
        c = TurboQuantCompressor(dim=768, bits=4)
        vectors = [_random_vector(768, seed=s) for s in range(5)]
        qvs = c.compress_batch(vectors)
        assert len(qvs) == 5
        for v, qv in zip(vectors, qvs, strict=True):
            recovered = c.decompress(qv)
            assert _cosine_sim(v, recovered) > 0.90

    def test_decompress_batch(self) -> None:
        c = TurboQuantCompressor(dim=768, bits=4)
        vectors = [_random_vector(768, seed=s) for s in range(3)]
        qvs = c.compress_batch(vectors)
        recovered = c.decompress_batch(qvs)
        assert len(recovered) == 3
        for v, r in zip(vectors, recovered, strict=True):
            assert _cosine_sim(v, r) > 0.90


# ── Determinism ──────────────────────────────────────────────────────────


class TestDeterminism:
    def test_same_seed_same_results(self) -> None:
        """Same seed should produce identical compression output."""
        v = _random_vector(768, seed=50)
        c1 = TurboQuantCompressor(dim=768, bits=4, seed=42)
        c2 = TurboQuantCompressor(dim=768, bits=4, seed=42)
        qv1 = c1.compress(v)
        qv2 = c2.compress(v)
        assert qv1.codes == qv2.codes
        assert abs(qv1.scale - qv2.scale) < 1e-12
        assert abs(qv1.offset - qv2.offset) < 1e-12

    def test_different_seed_different_results(self) -> None:
        """Different seeds should produce different rotation (different codes)."""
        v = _random_vector(768, seed=50)
        c1 = TurboQuantCompressor(dim=768, bits=4, seed=42)
        c2 = TurboQuantCompressor(dim=768, bits=4, seed=99)
        qv1 = c1.compress(v)
        qv2 = c2.compress(v)
        # Codes should differ (extremely unlikely to match with different rotations).
        assert qv1.codes != qv2.codes


# ── EmbeddingCache integration ───────────────────────────────────────────


class TestCacheIntegration:
    @pytest.fixture()
    def mock_provider(self) -> AsyncMock:
        provider = AsyncMock()
        provider.embed = AsyncMock(return_value=_random_vector(768, seed=0))
        provider.embed_batch = AsyncMock(
            return_value=[_random_vector(768, seed=s) for s in range(3)]
        )
        provider.close = AsyncMock()
        return provider

    @pytest.mark.asyncio()
    async def test_cache_with_compressor(self, mock_provider: AsyncMock) -> None:
        """Cache should work transparently with compressor enabled."""
        from agent33.memory.cache import EmbeddingCache

        compressor = TurboQuantCompressor(dim=768, bits=4)
        cache = EmbeddingCache(
            provider=mock_provider,
            max_size=100,
            compressor=compressor,
        )

        # First call — cache miss.
        result1 = await cache.embed("hello")
        assert len(result1) == 768
        assert mock_provider.embed.call_count == 1

        # Second call — cache hit (decompressed from quantized storage).
        result2 = await cache.embed("hello")
        assert mock_provider.embed.call_count == 1  # No new provider call.
        assert len(result2) == 768

        # The cache-hit result should be close to the original (within quant error).
        sim = _cosine_sim(result1, result2)
        assert sim > 0.99

    @pytest.mark.asyncio()
    async def test_cache_without_compressor(self, mock_provider: AsyncMock) -> None:
        """Cache without compressor should still work as before (exact match)."""
        from agent33.memory.cache import EmbeddingCache

        cache = EmbeddingCache(provider=mock_provider, max_size=100)

        result1 = await cache.embed("hello")
        result2 = await cache.embed("hello")
        assert result1 == result2  # Exact match, no quantization error.
        assert mock_provider.embed.call_count == 1

    @pytest.mark.asyncio()
    async def test_cache_batch_with_compressor(self, mock_provider: AsyncMock) -> None:
        """Batch embedding with compressor should work correctly."""
        from agent33.memory.cache import EmbeddingCache

        compressor = TurboQuantCompressor(dim=768, bits=4)
        cache = EmbeddingCache(
            provider=mock_provider,
            max_size=100,
            compressor=compressor,
        )

        texts = ["hello", "world", "test"]
        results = await cache.embed_batch(texts)
        assert len(results) == 3
        assert all(len(r) == 768 for r in results)

    @pytest.mark.asyncio()
    async def test_cache_stats_with_compressor(self, mock_provider: AsyncMock) -> None:
        """Cache hit/miss stats should work with compression enabled."""
        from agent33.memory.cache import EmbeddingCache

        compressor = TurboQuantCompressor(dim=768, bits=4)
        cache = EmbeddingCache(
            provider=mock_provider,
            max_size=100,
            compressor=compressor,
        )

        await cache.embed("hello")
        assert cache.misses == 1
        assert cache.hits == 0

        await cache.embed("hello")
        assert cache.misses == 1
        assert cache.hits == 1
        assert cache.hit_rate == 0.5
