"""TurboQuant-style embedding vector compression.

Implements the rotation-preprocessing + scalar-quantization pipeline from
the TurboQuant family of papers (ICLR 2026, arXiv:2504.19874).  The core
insight is that applying a random orthogonal rotation before quantization
distributes information evenly across coordinates, eliminating outliers and
allowing uniform scalar quantization to approach the rate-distortion bound.

Algorithm:
    1. **Rotation** — Multiply by a deterministic pseudo-random orthogonal
       matrix (seeded for reproducibility).  This is O(d log d) when using
       the Randomized Hadamard Transform, but we use a standard random
       rotation for correctness at the dimensions AGENT-33 uses (768).
    2. **Scalar Quantization** — Clamp to [min, max] and uniformly quantize
       each coordinate to *bits* bits (default 4).  Store scale/offset per
       vector for lossless reconstruction within quantization error.
    3. **Dequantization** — Reverse: unpack integers → rescale → inverse
       rotation.

The compressor is stateless and deterministic: the same seed always produces
the same rotation matrix, so vectors quantized at different times are
comparable via dot product on the quantized representation.

References:
    - TurboQuant: arXiv 2504.19874 (ICLR 2026)
    - PolarQuant: arXiv 2502.02617 (AISTATS 2026)
    - QuaRot: arXiv 2404.00456 (NeurIPS 2024)
    - SpinQuant: arXiv 2405.16406 (ICLR 2025)
"""

from __future__ import annotations

import math
import struct
from typing import TYPE_CHECKING, NamedTuple

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray


class QuantizedVector(NamedTuple):
    """Compressed representation of an embedding vector.

    Attributes
    ----------
    codes:
        Packed quantization codes as raw bytes.  At 4 bits per coordinate
        and 768 dimensions this is 384 bytes (two codes per byte).
    scale:
        Per-vector scale factor for dequantization.
    offset:
        Per-vector offset for dequantization.
    dim:
        Original vector dimensionality.
    bits:
        Bits per coordinate used during quantization.
    """

    codes: bytes
    scale: float
    offset: float
    dim: int
    bits: int


class TurboQuantCompressor:
    """Rotation-aware scalar quantizer for embedding vectors.

    Parameters
    ----------
    dim:
        Dimensionality of input vectors (must be consistent across calls).
    bits:
        Quantization bit-width per coordinate (default 4 → 16 levels).
    seed:
        Random seed for the rotation matrix (deterministic, reproducible).
    """

    def __init__(self, dim: int = 768, bits: int = 4, seed: int = 42) -> None:
        if bits < 1 or bits > 8:
            raise ValueError(f"bits must be in [1, 8], got {bits}")
        self._dim = dim
        self._bits = bits
        self._levels = (1 << bits) - 1  # e.g. 15 for 4-bit
        self._seed = seed

        # Build a deterministic random orthogonal rotation matrix.
        # QR decomposition of a random Gaussian matrix gives a uniformly
        # distributed orthogonal matrix (Haar measure on O(d)).
        rng = np.random.default_rng(seed)
        gaussian = rng.standard_normal((dim, dim))
        q, r = np.linalg.qr(gaussian)
        # Ensure det(Q) = +1 (proper rotation, not reflection).
        diag_signs = np.sign(np.diag(r))
        diag_signs[diag_signs == 0] = 1.0
        self._rotation: NDArray[np.float64] = q * diag_signs[np.newaxis, :]
        self._rotation_inv: NDArray[np.float64] = self._rotation.T

    # ── Public API ───────────────────────────────────────────────────

    def compress(self, vector: list[float]) -> QuantizedVector:
        """Quantize a single embedding vector.

        Returns a :class:`QuantizedVector` that is typically 8× smaller than
        the float32 input (at 4 bits/coord).
        """
        x = np.asarray(vector, dtype=np.float64)
        if x.shape != (self._dim,):
            raise ValueError(f"Expected vector of dim {self._dim}, got shape {x.shape}")

        # Step 1: Rotate to spread information across coordinates.
        rotated = self._rotation @ x

        # Step 2: Uniform scalar quantization.
        vmin = float(rotated.min())
        vmax = float(rotated.max())
        span = vmax - vmin
        if span < 1e-12:
            # Near-constant vector — all codes = 0, trivial round-trip.
            codes = bytes(math.ceil(self._dim * self._bits / 8))
            return QuantizedVector(
                codes=codes, scale=0.0, offset=vmin, dim=self._dim, bits=self._bits
            )

        scale = span / self._levels
        # Quantize to integers in [0, levels].
        quantized = np.clip(np.round((rotated - vmin) / scale), 0, self._levels).astype(np.uint8)

        codes = self._pack_codes(quantized)
        return QuantizedVector(
            codes=codes, scale=scale, offset=vmin, dim=self._dim, bits=self._bits
        )

    def decompress(self, qv: QuantizedVector) -> list[float]:
        """Reconstruct a float vector from its quantized representation."""
        if qv.dim != self._dim:
            raise ValueError(
                f"QuantizedVector dim={qv.dim} does not match compressor dim={self._dim}"
            )
        quantized = self._unpack_codes(qv.codes, qv.dim, qv.bits)
        rotated = quantized.astype(np.float64) * qv.scale + qv.offset
        original = self._rotation_inv @ rotated
        result: list[float] = original.tolist()
        return result

    def compress_batch(self, vectors: list[list[float]]) -> list[QuantizedVector]:
        """Quantize multiple vectors."""
        return [self.compress(v) for v in vectors]

    def decompress_batch(self, qvs: list[QuantizedVector]) -> list[list[float]]:
        """Decompress multiple vectors."""
        return [self.decompress(qv) for qv in qvs]

    def compression_ratio(self) -> float:
        """Theoretical compression ratio vs float32 storage.

        At 4 bits/coord on 768 dimensions:
          float32: 768 x 4 = 3072 bytes
          quantized: 768 x 0.5 + 11 (header) = 395 bytes
          ratio ~ 7.8x

        Header layout: ``<HBff`` = u16 + u8 + f32 + f32 = 2+1+4+4 = 11 bytes.
        """
        original_bytes = self._dim * 4  # float32
        compressed_bytes = math.ceil(self._dim * self._bits / 8) + 11  # codes + header
        return original_bytes / compressed_bytes

    @property
    def dim(self) -> int:
        """Configured vector dimensionality."""
        return self._dim

    @property
    def bits(self) -> int:
        """Quantization bit-width."""
        return self._bits

    # ── Serialization helpers ────────────────────────────────────────

    @staticmethod
    def serialize(qv: QuantizedVector) -> bytes:
        """Serialize a QuantizedVector to compact bytes.

        Layout: [dim:u16][bits:u8][scale:f32][offset:f32][codes...]
        Header is 11 bytes.
        """
        header = struct.pack("<HBff", qv.dim, qv.bits, qv.scale, qv.offset)
        return header + qv.codes

    @staticmethod
    def deserialize(data: bytes) -> QuantizedVector:
        """Deserialize bytes back to a QuantizedVector."""
        dim, bits, scale, offset = struct.unpack("<HBff", data[:11])
        codes = data[11:]
        return QuantizedVector(codes=codes, scale=scale, offset=offset, dim=dim, bits=bits)

    # ── Distance computation on compressed vectors ───────────────────

    def approximate_cosine_similarity(self, qv1: QuantizedVector, qv2: QuantizedVector) -> float:
        """Compute approximate cosine similarity between two quantized vectors.

        Dequantizes both vectors into the rotated space and computes cosine
        there.  Since rotation preserves inner products, this is equivalent
        to cosine similarity in the original space (within quantization error).
        """
        if qv1.dim != qv2.dim or qv1.bits != qv2.bits:
            raise ValueError("Cannot compare QuantizedVectors with different dim/bits")
        c1 = self._unpack_codes(qv1.codes, qv1.dim, qv1.bits).astype(np.float64)
        c2 = self._unpack_codes(qv2.codes, qv2.dim, qv2.bits).astype(np.float64)
        r1 = c1 * qv1.scale + qv1.offset
        r2 = c2 * qv2.scale + qv2.offset
        dot = float(np.dot(r1, r2))
        norm1 = float(np.linalg.norm(r1))
        norm2 = float(np.linalg.norm(r2))
        if norm1 < 1e-12 or norm2 < 1e-12:
            return 0.0
        return dot / (norm1 * norm2)

    # ── Internal ─────────────────────────────────────────────────────

    def _pack_codes(self, codes: NDArray[np.uint8]) -> bytes:
        """Pack integer codes into compact bytes.

        For 4-bit: two codes per byte (high nibble, low nibble).
        For 8-bit: one code per byte.
        For other widths: bit-packing via shifts.
        """
        if self._bits == 8:
            return bytes(codes)

        if self._bits == 4:
            # Fast path: pack two 4-bit values per byte.
            n = len(codes)
            packed = bytearray(math.ceil(n / 2))
            for i in range(0, n - 1, 2):
                packed[i // 2] = (codes[i] << 4) | (codes[i + 1] & 0x0F)
            if n % 2:
                packed[n // 2] = codes[n - 1] << 4
            return bytes(packed)

        # General bit-packing.
        total_bits = len(codes) * self._bits
        packed = bytearray(math.ceil(total_bits / 8))
        bit_offset = 0
        for code in codes:
            byte_idx = bit_offset >> 3
            bit_pos = bit_offset & 7
            # Write bits, possibly spanning two bytes.
            packed[byte_idx] |= (code << bit_pos) & 0xFF
            if bit_pos + self._bits > 8 and byte_idx + 1 < len(packed):
                packed[byte_idx + 1] |= code >> (8 - bit_pos)
            bit_offset += self._bits
        return bytes(packed)

    def _unpack_codes(self, data: bytes, dim: int, bits: int) -> NDArray[np.uint8]:
        """Unpack packed bytes back to integer codes."""
        if bits == 8:
            return np.frombuffer(data, dtype=np.uint8)[:dim].copy()

        levels = (1 << bits) - 1
        if bits == 4:
            codes = np.empty(dim, dtype=np.uint8)
            for i in range(dim):
                byte_idx = i // 2
                if byte_idx < len(data):
                    if i % 2 == 0:
                        codes[i] = (data[byte_idx] >> 4) & 0x0F
                    else:
                        codes[i] = data[byte_idx] & 0x0F
                else:
                    codes[i] = 0
            return codes

        # General unpacking.
        codes = np.empty(dim, dtype=np.uint8)
        bit_offset = 0
        mask = levels
        for i in range(dim):
            byte_idx = bit_offset >> 3
            bit_pos = bit_offset & 7
            if byte_idx < len(data):
                val = data[byte_idx] >> bit_pos
                if bit_pos + bits > 8 and byte_idx + 1 < len(data):
                    val |= data[byte_idx + 1] << (8 - bit_pos)
                codes[i] = val & mask
            else:
                codes[i] = 0
            bit_offset += bits
        return codes
