"""Signal enrichment and quality scoring for automated intake generation."""

from __future__ import annotations

from dataclasses import dataclass, field

from agent33.improvement.models import LearningSignal, LearningSignalSeverity

# ---------------------------------------------------------------------------
# Default severity-to-quality mapping
# ---------------------------------------------------------------------------

_DEFAULT_SEVERITY_MAP: dict[LearningSignalSeverity, float] = {
    LearningSignalSeverity.LOW: 0.3,
    LearningSignalSeverity.MEDIUM: 0.55,
    LearningSignalSeverity.HIGH: 0.8,
    LearningSignalSeverity.CRITICAL: 1.0,
}


# ---------------------------------------------------------------------------
# Configurable scoring parameters
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QualityScoringConfig:
    """All tuneable parameters for deterministic quality scoring.

    Defaults match the original hardcoded values so existing behaviour is
    preserved when no custom config is supplied.
    """

    # Dimension weights (should sum to 1.0 for intuitive scores)
    weight_summary: float = 0.25
    weight_details: float = 0.20
    weight_source: float = 0.10
    weight_context: float = 0.10
    weight_severity: float = 0.35

    # Label thresholds
    high_threshold: float = 0.70
    medium_threshold: float = 0.45

    # Normalizers
    summary_max_chars: int = 80
    details_max_chars: int = 160
    context_max_items: int = 5

    # Severity quality mapping
    severity_map: dict[LearningSignalSeverity, float] = field(
        default_factory=lambda: dict(_DEFAULT_SEVERITY_MAP)
    )


# Module-level default instance (singleton-safe, frozen)
_DEFAULT_CONFIG = QualityScoringConfig()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def enrich_learning_signal(
    signal: LearningSignal,
    config: QualityScoringConfig | None = None,
) -> LearningSignal:
    """Apply deterministic quality scoring and enrichment metadata."""
    cfg = config if config is not None else _DEFAULT_CONFIG

    summary_len = len(signal.summary.strip())
    details_len = len(signal.details.strip())
    source_present = bool(signal.source.strip())
    context_items = len(signal.context)

    dimensions: dict[str, float] = {
        "summary": min(1.0, summary_len / max(cfg.summary_max_chars, 1)),
        "details": min(1.0, details_len / max(cfg.details_max_chars, 1)),
        "source": 1.0 if source_present else 0.0,
        "context": min(1.0, context_items / max(cfg.context_max_items, 1)),
        "severity": _severity_quality(signal.severity, cfg),
    }
    weights = {
        "summary": cfg.weight_summary,
        "details": cfg.weight_details,
        "source": cfg.weight_source,
        "context": cfg.weight_context,
        "severity": cfg.weight_severity,
    }
    score = sum(dimensions[name] * weight for name, weight in weights.items())
    quality_score = round(min(1.0, max(0.0, score)), 3)

    quality_label = "low"
    if quality_score >= cfg.high_threshold:
        quality_label = "high"
    elif quality_score >= cfg.medium_threshold:
        quality_label = "medium"

    reasons: list[str] = []
    if summary_len < 20:
        reasons.append("summary_too_short")
    if details_len == 0:
        reasons.append("details_missing")
    if not source_present:
        reasons.append("source_missing")
    if context_items == 0:
        reasons.append("context_missing")
    if not reasons:
        reasons.append("well_formed_signal")

    signal.quality_score = quality_score
    signal.quality_label = quality_label
    signal.quality_reasons = reasons
    signal.enrichment = {
        "has_source": str(source_present).lower(),
        "context_items": str(context_items),
        "summary_length": str(summary_len),
        "details_length": str(details_len),
    }
    return signal


def _severity_quality(
    severity: LearningSignalSeverity,
    cfg: QualityScoringConfig,
) -> float:
    return cfg.severity_map.get(severity, 0.5)
