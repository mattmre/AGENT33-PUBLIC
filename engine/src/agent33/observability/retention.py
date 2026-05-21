"""Artifact retention rules from ``core/orchestrator/TRACE_SCHEMA.md``.

Provides retention policy models and classification logic for
managing artifact lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent33.observability.trace_models import ArtifactType

# ---------------------------------------------------------------------------
# Storage tiers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetentionPolicy:
    """Retention policy for a single artifact type."""

    artifact_type: ArtifactType
    retention_days: int  # 0 = permanent
    initial_tier: str  # hot | warm | cold
    hot_to_warm_days: int = 0  # 0 = stays in tier
    warm_to_cold_days: int = 0


# ---------------------------------------------------------------------------
# Default retention policies (from TRACE_SCHEMA.md § Retention Periods)
# ---------------------------------------------------------------------------

RETENTION_POLICIES: dict[ArtifactType, RetentionPolicy] = {
    ArtifactType.TMP: RetentionPolicy(ArtifactType.TMP, retention_days=7, initial_tier="hot"),
    ArtifactType.LOG: RetentionPolicy(
        ArtifactType.LOG,
        retention_days=30,
        initial_tier="hot",
        hot_to_warm_days=30,
    ),
    ArtifactType.OUT: RetentionPolicy(
        ArtifactType.OUT,
        retention_days=30,
        initial_tier="hot",
        hot_to_warm_days=30,
    ),
    ArtifactType.DIF: RetentionPolicy(
        ArtifactType.DIF,
        retention_days=90,
        initial_tier="warm",
        warm_to_cold_days=90,
    ),
    ArtifactType.TST: RetentionPolicy(
        ArtifactType.TST,
        retention_days=90,
        initial_tier="warm",
        warm_to_cold_days=90,
    ),
    ArtifactType.SES: RetentionPolicy(
        ArtifactType.SES,
        retention_days=90,
        initial_tier="warm",
        warm_to_cold_days=90,
    ),
    ArtifactType.CFG: RetentionPolicy(
        ArtifactType.CFG,
        retention_days=90,
        initial_tier="warm",
        warm_to_cold_days=90,
    ),
    ArtifactType.REV: RetentionPolicy(
        ArtifactType.REV,
        retention_days=0,
        initial_tier="cold",  # permanent
    ),
    ArtifactType.EVD: RetentionPolicy(
        ArtifactType.EVD,
        retention_days=0,
        initial_tier="cold",  # permanent
    ),
}


def get_retention_policy(artifact_type: ArtifactType) -> RetentionPolicy:
    """Return the retention policy for *artifact_type*."""
    return RETENTION_POLICIES[artifact_type]


def is_permanent(artifact_type: ArtifactType) -> bool:
    """Return ``True`` if the artifact type has permanent retention."""
    return RETENTION_POLICIES[artifact_type].retention_days == 0


def get_storage_path(
    artifact_type: ArtifactType,
    year: int,
    month: int,
    day: int,
    session_id: str = "",
    run_id: str = "",
    task_id: str = "",
) -> str:
    """Build a standardized storage path following TRACE_SCHEMA.md conventions.

    Returns a relative path under ``artifacts/``.
    """
    base = "artifacts"

    if artifact_type == ArtifactType.SES:
        return f"{base}/sessions/{year:04d}/{month:02d}/{day:02d}/{session_id}"
    if artifact_type in (ArtifactType.EVD,):
        return f"{base}/evidence/{year:04d}/{month:02d}/{task_id}"
    if artifact_type == ArtifactType.REV:
        return f"{base}/reviews/{year:04d}/{month:02d}/{task_id}"
    if artifact_type == ArtifactType.LOG:
        path = f"{base}/sessions/{year:04d}/{month:02d}/{day:02d}"
        if session_id:
            path += f"/{session_id}"
        if run_id:
            path += f"/runs/{run_id}/logs"
        return path
    # Default
    path = f"{base}/sessions/{year:04d}/{month:02d}/{day:02d}"
    if session_id:
        path += f"/{session_id}"
    if run_id:
        path += f"/runs/{run_id}/{artifact_type.value.lower()}"
    return path
