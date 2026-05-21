"""Pack signing, provenance verification, and trust policy enforcement.

Provides HMAC-SHA256 signing of pack manifests, signature verification,
and trust policy evaluation to ensure packs are from trusted sources.

HMAC-SHA256 is the primary on-disk signing mechanism.  Sigstore (keyless
cosign) verification is also supported via ``algorithm="sigstore"``; the
Python ``sigstore`` library is optional -- if absent, Sigstore verification
is skipped with a warning rather than hard-failing.  Install the library
with ``pip install sigstore`` to enable full Sigstore support.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime

import structlog

from agent33.packs.manifest import PackManifest, manifest_to_dict
from agent33.packs.provenance_models import (
    PackProvenance,
    PackTrustPolicy,
    SigstoreBundle,
    TrustDecision,
    TrustLevel,
)

logger = structlog.get_logger()

__all__ = [
    "PackProvenance",
    "PackTrustPolicy",
    "SigstoreBundle",
    "TrustDecision",
    "TrustLevel",
    "evaluate_trust",
    "sign_pack",
    "verify_pack",
    "verify_pack_sigstore",
]

# Ordered for comparison: higher index = more trusted
_TRUST_ORDER: list[TrustLevel] = [
    TrustLevel.UNTRUSTED,
    TrustLevel.COMMUNITY,
    TrustLevel.VERIFIED,
    TrustLevel.OFFICIAL,
]


def _trust_rank(level: TrustLevel) -> int:
    """Return numeric rank for a trust level (higher = more trusted)."""
    return _TRUST_ORDER.index(level)


def _canonical_manifest_bytes(manifest: PackManifest) -> bytes:
    """Serialize a manifest to canonical JSON bytes for signing.

    Uses sorted keys and no extra whitespace to ensure deterministic output
    regardless of field insertion order.
    """
    data = manifest_to_dict(manifest)
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_pack(
    manifest: PackManifest,
    signing_key: str,
    *,
    signer_id: str = "default",
    trust_level: TrustLevel = TrustLevel.COMMUNITY,
) -> PackProvenance:
    """Sign a pack manifest with HMAC-SHA256.

    Args:
        manifest: The pack manifest to sign.
        signing_key: Shared secret key for HMAC computation.
        signer_id: Identifier for the signing entity.
        trust_level: Trust classification to embed in provenance.

    Returns:
        A ``PackProvenance`` with ``algorithm="sha256"`` containing the
        hex signature and metadata.
    """
    payload = _canonical_manifest_bytes(manifest)
    sig = hmac.new(
        signing_key.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    provenance = PackProvenance(
        signer_id=signer_id,
        signature=sig,
        signed_at=datetime.now(UTC),
        algorithm="sha256",
        trust_level=trust_level,
    )

    logger.info(
        "pack_signed",
        pack=manifest.name,
        signer=signer_id,
        trust_level=trust_level,
    )
    return provenance


def verify_pack(
    manifest: PackManifest,
    provenance: PackProvenance,
    verification_key: str,
) -> bool:
    """Verify a pack manifest's signature against its provenance.

    Dispatches to the correct verifier based on ``provenance.algorithm``:

    * ``"sha256"`` — HMAC-SHA256 using *verification_key*.
    * ``"sigstore"`` — Sigstore keyless verification (key is ignored);
      requires the optional ``sigstore`` Python package.

    Args:
        manifest: The pack manifest to verify.
        provenance: The provenance metadata containing the signature.
        verification_key: Shared secret for HMAC verification (ignored for
            Sigstore).

    Returns:
        ``True`` if the signature is valid, ``False`` otherwise.
    """
    if provenance.algorithm == "sha256":
        return _verify_hmac(manifest, provenance, verification_key)
    if provenance.algorithm == "sigstore":
        return verify_pack_sigstore(manifest, provenance)

    logger.warning(
        "pack_verify_unsupported_algorithm",
        algorithm=provenance.algorithm,
    )
    return False


def _verify_hmac(
    manifest: PackManifest,
    provenance: PackProvenance,
    verification_key: str,
) -> bool:
    """Verify HMAC-SHA256 signature."""
    payload = _canonical_manifest_bytes(manifest)
    expected_sig = hmac.new(
        verification_key.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    valid = hmac.compare_digest(expected_sig, provenance.signature)

    logger.info(
        "pack_verified",
        pack=manifest.name,
        signer=provenance.signer_id,
        algorithm="sha256",
        valid=valid,
    )
    return valid


def verify_pack_sigstore(
    manifest: PackManifest,
    provenance: PackProvenance,
) -> bool:
    """Verify a pack manifest signature using Sigstore (keyless cosign).

    Requires the ``sigstore`` Python package (``pip install sigstore``).
    If the package is unavailable this function logs a warning and returns
    ``False`` so that callers can treat the result as unverified rather than
    crash.

    The ``provenance.signature`` field must contain the base64-encoded
    Sigstore bundle JSON.  The ``provenance.sigstore_bundle`` field carries
    the OIDC subject and Rekor log ID for human-readable audit; they are not
    re-verified here (Sigstore's own verifier covers the full chain).

    Args:
        manifest: The pack manifest to verify.
        provenance: Provenance with ``algorithm="sigstore"`` and a
            base64-encoded bundle in ``signature``.

    Returns:
        ``True`` if the Sigstore bundle verifies successfully.
        ``False`` if the library is unavailable, the bundle is malformed,
        or verification fails.
    """
    try:
        import base64

        from sigstore.models import Bundle  # type: ignore[import-not-found]
        from sigstore.verify import Verifier  # type: ignore[import-not-found]
    except ImportError:
        logger.warning(
            "pack_sigstore_unavailable",
            pack=manifest.name,
            detail=(
                "sigstore Python package not installed; "
                "install with 'pip install sigstore' to enable Sigstore verification"
            ),
        )
        return False

    try:
        bundle_bytes = base64.b64decode(provenance.signature)
        bundle = Bundle.from_json(bundle_bytes.decode("utf-8"))
    except Exception as exc:
        logger.warning(
            "pack_sigstore_bundle_parse_failed",
            pack=manifest.name,
            error=str(exc),
        )
        return False

    try:
        verifier = Verifier.production()
        payload = _canonical_manifest_bytes(manifest)
        verifier.verify_artifact(payload, bundle)  # raises on failure
    except Exception as exc:
        logger.warning(
            "pack_sigstore_verify_failed",
            pack=manifest.name,
            signer=provenance.signer_id,
            error=str(exc),
        )
        return False

    logger.info(
        "pack_verified",
        pack=manifest.name,
        signer=provenance.signer_id,
        algorithm="sigstore",
        valid=True,
    )
    return True


def evaluate_trust(provenance: PackProvenance | None, policy: PackTrustPolicy) -> TrustDecision:
    """Evaluate provenance metadata against a trust policy.

    Args:
        provenance: The provenance to evaluate (may be ``None`` for unsigned packs).
        policy: The trust policy to check against.

    Returns:
        A ``TrustDecision`` indicating whether the pack should be allowed.
    """
    # No provenance at all
    if provenance is None:
        if policy.require_signature:
            return TrustDecision(
                allowed=False,
                reason="Pack has no provenance metadata but policy requires a signature",
            )
        # No signature required, no provenance — allow by default
        return TrustDecision(
            allowed=True,
            reason="No provenance metadata; policy does not require signature",
        )

    # Check signer allowlist
    if policy.allowed_signers and provenance.signer_id not in policy.allowed_signers:
        return TrustDecision(
            allowed=False,
            reason=(
                f"Signer '{provenance.signer_id}' is not in the allowed signers list: "
                f"{policy.allowed_signers}"
            ),
        )

    # Check minimum trust level
    if _trust_rank(provenance.trust_level) < _trust_rank(policy.min_trust_level):
        return TrustDecision(
            allowed=False,
            reason=(
                f"Pack trust level '{provenance.trust_level}' is below the required "
                f"minimum '{policy.min_trust_level}'"
            ),
        )

    return TrustDecision(
        allowed=True,
        reason=(
            f"Pack signed by '{provenance.signer_id}' with trust level "
            f"'{provenance.trust_level}' meets policy requirements"
        ),
    )
