"""Tests for improvement/quality.py — configurable quality scoring and enrichment.

Covers: empty/minimal signals, isolated dimensions, severity dominance,
boundary threshold values, enrichment metadata, custom configs, round-trip
stability, and all severity levels.
"""

from __future__ import annotations

import pytest

from agent33.improvement.models import (
    LearningSignal,
    LearningSignalSeverity,
    LearningSignalType,
)
from agent33.improvement.quality import QualityScoringConfig, enrich_learning_signal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(
    *,
    summary: str = "",
    details: str = "",
    source: str = "",
    context: dict[str, str] | None = None,
    severity: LearningSignalSeverity = LearningSignalSeverity.MEDIUM,
) -> LearningSignal:
    """Create a LearningSignal with controlled fields."""
    return LearningSignal(
        signal_type=LearningSignalType.FEEDBACK,
        severity=severity,
        summary=summary,
        details=details,
        source=source,
        context=context or {},
    )


# ---------------------------------------------------------------------------
# Default config produces identical behaviour to pre-refactor hardcoded values
# ---------------------------------------------------------------------------


class TestDefaultConfig:
    """QualityScoringConfig() must match the original hardcoded defaults."""

    def test_default_weights_match(self) -> None:
        cfg = QualityScoringConfig()
        assert cfg.weight_summary == 0.25
        assert cfg.weight_details == 0.20
        assert cfg.weight_source == 0.10
        assert cfg.weight_context == 0.10
        assert cfg.weight_severity == 0.35

    def test_default_thresholds(self) -> None:
        cfg = QualityScoringConfig()
        assert cfg.high_threshold == 0.70
        assert cfg.medium_threshold == 0.45

    def test_default_normalizers(self) -> None:
        cfg = QualityScoringConfig()
        assert cfg.summary_max_chars == 80
        assert cfg.details_max_chars == 160
        assert cfg.context_max_items == 5

    def test_default_severity_map(self) -> None:
        cfg = QualityScoringConfig()
        assert cfg.severity_map[LearningSignalSeverity.LOW] == 0.3
        assert cfg.severity_map[LearningSignalSeverity.MEDIUM] == 0.55
        assert cfg.severity_map[LearningSignalSeverity.HIGH] == 0.8
        assert cfg.severity_map[LearningSignalSeverity.CRITICAL] == 1.0

    def test_frozen(self) -> None:
        cfg = QualityScoringConfig()
        with pytest.raises(AttributeError):
            cfg.weight_summary = 0.5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Empty / minimal signal
# ---------------------------------------------------------------------------


class TestEmptyMinimalSignal:
    """Empty or near-empty signals should produce low quality scores."""

    def test_empty_signal_produces_low_score(self) -> None:
        signal = _make_signal(summary="x", severity=LearningSignalSeverity.LOW)
        enrich_learning_signal(signal)
        assert signal.quality_score < 0.45
        assert signal.quality_label == "low"

    def test_minimal_signal_has_reasons(self) -> None:
        signal = _make_signal(summary="tiny")
        enrich_learning_signal(signal)
        assert "summary_too_short" in signal.quality_reasons
        assert "details_missing" in signal.quality_reasons
        assert "source_missing" in signal.quality_reasons
        assert "context_missing" in signal.quality_reasons

    def test_empty_summary_still_enriched(self) -> None:
        """Even empty summary produces valid enrichment metadata."""
        signal = _make_signal(summary="")
        enrich_learning_signal(signal)
        assert "summary_length" in signal.enrichment
        assert signal.enrichment["summary_length"] == "0"


# ---------------------------------------------------------------------------
# Isolated dimension tests — each dimension in turn
# ---------------------------------------------------------------------------


class TestIsolatedDimensions:
    """Test each scoring dimension in isolation by maximising one at a time."""

    def test_long_summary_only(self) -> None:
        """80+ char summary with nothing else and LOW severity."""
        signal = _make_signal(
            summary="a" * 100,
            severity=LearningSignalSeverity.LOW,
        )
        enrich_learning_signal(signal)
        # summary dimension = 1.0 * 0.25 + severity(LOW)=0.3*0.35 = 0.355
        assert signal.quality_score == pytest.approx(0.355, abs=0.001)

    def test_long_details_only(self) -> None:
        """160+ char details with nothing else and LOW severity."""
        signal = _make_signal(
            summary="x",
            details="b" * 200,
            severity=LearningSignalSeverity.LOW,
        )
        enrich_learning_signal(signal)
        # details dimension: 1.0 * 0.20, summary ~ 1/80 * 0.25, sev 0.3*0.35
        expected_approx = (1 / 80) * 0.25 + 1.0 * 0.20 + 0.3 * 0.35
        assert signal.quality_score == pytest.approx(expected_approx, abs=0.002)

    def test_source_only(self) -> None:
        """Source present with nothing else special."""
        signal = _make_signal(
            summary="x",
            source="unit-test",
            severity=LearningSignalSeverity.LOW,
        )
        enrich_learning_signal(signal)
        # source dimension: 1.0 * 0.10
        expected = (1 / 80) * 0.25 + 1.0 * 0.10 + 0.3 * 0.35
        assert signal.quality_score == pytest.approx(expected, abs=0.002)

    def test_context_only(self) -> None:
        """5+ context items with nothing else special."""
        signal = _make_signal(
            summary="x",
            context={f"k{i}": f"v{i}" for i in range(6)},
            severity=LearningSignalSeverity.LOW,
        )
        enrich_learning_signal(signal)
        # context dimension: 1.0 * 0.10
        expected = (1 / 80) * 0.25 + 1.0 * 0.10 + 0.3 * 0.35
        assert signal.quality_score == pytest.approx(expected, abs=0.002)


# ---------------------------------------------------------------------------
# Severity dominance
# ---------------------------------------------------------------------------


class TestSeverityDominance:
    """CRITICAL severity alone should dominate the score."""

    def test_critical_with_empty_fields(self) -> None:
        """CRITICAL + minimal fields should produce a moderate score."""
        signal = _make_signal(
            summary="x",
            severity=LearningSignalSeverity.CRITICAL,
        )
        enrich_learning_signal(signal)
        # severity contributes 1.0 * 0.35 = 0.35 alone
        assert signal.quality_score >= 0.35

    def test_critical_with_full_fields(self) -> None:
        """CRITICAL + all dimensions maxed should produce highest score."""
        signal = _make_signal(
            summary="a" * 100,
            details="b" * 200,
            source="test",
            context={f"k{i}": f"v{i}" for i in range(6)},
            severity=LearningSignalSeverity.CRITICAL,
        )
        enrich_learning_signal(signal)
        # All dimensions maxed: 0.25 + 0.20 + 0.10 + 0.10 + 0.35 = 1.0
        assert signal.quality_score == 1.0
        assert signal.quality_label == "high"


# ---------------------------------------------------------------------------
# Boundary threshold values
# ---------------------------------------------------------------------------


class TestBoundaryThresholds:
    """Test that the label thresholds work at exact boundaries."""

    def test_score_at_0_44_is_low(self) -> None:
        """A score just below 0.45 should be 'low'."""
        # We construct a config with known weights and feed known values
        cfg = QualityScoringConfig(
            weight_summary=1.0,
            weight_details=0.0,
            weight_source=0.0,
            weight_context=0.0,
            weight_severity=0.0,
            medium_threshold=0.45,
            high_threshold=0.70,
        )
        # summary_len / 80 = X, quality_score = X * 1.0
        # For score = 0.44: summary_len = 0.44 * 80 = 35.2 -> 35 chars
        signal = _make_signal(summary="a" * 35)
        enrich_learning_signal(signal, config=cfg)
        # 35/80 = 0.4375 -> rounds to 0.438
        assert signal.quality_score < 0.45
        assert signal.quality_label == "low"

    def test_score_at_0_45_is_medium(self) -> None:
        """A score exactly at 0.45 should be 'medium'."""
        cfg = QualityScoringConfig(
            weight_summary=1.0,
            weight_details=0.0,
            weight_source=0.0,
            weight_context=0.0,
            weight_severity=0.0,
            medium_threshold=0.45,
            high_threshold=0.70,
        )
        # 36/80 = 0.45
        signal = _make_signal(summary="a" * 36)
        enrich_learning_signal(signal, config=cfg)
        assert signal.quality_score >= 0.45
        assert signal.quality_label == "medium"

    def test_score_at_0_69_is_medium(self) -> None:
        """A score just below 0.70 should still be 'medium'."""
        cfg = QualityScoringConfig(
            weight_summary=1.0,
            weight_details=0.0,
            weight_source=0.0,
            weight_context=0.0,
            weight_severity=0.0,
            medium_threshold=0.45,
            high_threshold=0.70,
        )
        # 55/80 = 0.6875 -> rounds to 0.688
        signal = _make_signal(summary="a" * 55)
        enrich_learning_signal(signal, config=cfg)
        assert signal.quality_score < 0.70
        assert signal.quality_label == "medium"

    def test_score_at_0_70_is_high(self) -> None:
        """A score at exactly 0.70 should be 'high'."""
        cfg = QualityScoringConfig(
            weight_summary=1.0,
            weight_details=0.0,
            weight_source=0.0,
            weight_context=0.0,
            weight_severity=0.0,
            medium_threshold=0.45,
            high_threshold=0.70,
        )
        # 56/80 = 0.70
        signal = _make_signal(summary="a" * 56)
        enrich_learning_signal(signal, config=cfg)
        assert signal.quality_score >= 0.70
        assert signal.quality_label == "high"


# ---------------------------------------------------------------------------
# Enrichment metadata
# ---------------------------------------------------------------------------


class TestEnrichmentMetadata:
    """Enrichment dict and quality_reasons are populated correctly."""

    def test_enrichment_fields_present(self) -> None:
        signal = _make_signal(
            summary="hello world",
            details="some detail text",
            source="ci",
            context={"key": "val"},
        )
        enrich_learning_signal(signal)
        assert signal.enrichment["has_source"] == "true"
        assert signal.enrichment["context_items"] == "1"
        assert signal.enrichment["summary_length"] == "11"
        assert signal.enrichment["details_length"] == "16"

    def test_well_formed_signal_reason(self) -> None:
        """A signal with all fields present should only have 'well_formed_signal'."""
        signal = _make_signal(
            summary="a" * 25,
            details="some detail",
            source="test",
            context={"k": "v"},
        )
        enrich_learning_signal(signal)
        assert signal.quality_reasons == ["well_formed_signal"]

    def test_quality_score_and_label_set(self) -> None:
        signal = _make_signal(summary="test")
        enrich_learning_signal(signal)
        assert isinstance(signal.quality_score, float)
        assert signal.quality_label in {"low", "medium", "high"}


# ---------------------------------------------------------------------------
# Custom config changes scoring behaviour
# ---------------------------------------------------------------------------


class TestCustomConfig:
    """Non-default weights/thresholds should change scores and labels."""

    def test_severity_only_weights(self) -> None:
        """Config that weights only severity produces score = severity_quality."""
        cfg = QualityScoringConfig(
            weight_summary=0.0,
            weight_details=0.0,
            weight_source=0.0,
            weight_context=0.0,
            weight_severity=1.0,
        )
        signal = _make_signal(
            summary="a" * 100,
            details="b" * 200,
            source="test",
            context={"k": "v"},
            severity=LearningSignalSeverity.HIGH,
        )
        enrich_learning_signal(signal, config=cfg)
        assert signal.quality_score == 0.8

    def test_custom_thresholds(self) -> None:
        """Custom thresholds change the labelling boundaries."""
        cfg = QualityScoringConfig(
            high_threshold=0.90,
            medium_threshold=0.80,
        )
        # A normally-high signal (full fields + CRITICAL) = 1.0 score
        signal = _make_signal(
            summary="a" * 100,
            details="b" * 200,
            source="test",
            context={f"k{i}": f"v{i}" for i in range(6)},
            severity=LearningSignalSeverity.CRITICAL,
        )
        enrich_learning_signal(signal, config=cfg)
        assert signal.quality_label == "high"

        # Same fields with HIGH severity (0.8*0.35=0.28 for severity dim)
        # total = 0.25 + 0.20 + 0.10 + 0.10 + 0.28 = 0.93
        signal2 = _make_signal(
            summary="a" * 100,
            details="b" * 200,
            source="test",
            context={f"k{i}": f"v{i}" for i in range(6)},
            severity=LearningSignalSeverity.HIGH,
        )
        enrich_learning_signal(signal2, config=cfg)
        assert signal2.quality_score == pytest.approx(0.93, abs=0.01)
        assert signal2.quality_label == "high"

    def test_custom_normalizers(self) -> None:
        """Changing normalizers affects dimension computation."""
        cfg = QualityScoringConfig(
            summary_max_chars=10,  # 10 chars = full score
            details_max_chars=20,
            context_max_items=2,
        )
        signal = _make_signal(
            summary="a" * 10,  # exactly max
            details="b" * 20,  # exactly max
            context={"k1": "v1", "k2": "v2"},  # exactly max
            source="test",
            severity=LearningSignalSeverity.CRITICAL,
        )
        enrich_learning_signal(signal, config=cfg)
        # All dimensions at 1.0 with default weights = 1.0
        assert signal.quality_score == 1.0

    def test_custom_severity_map(self) -> None:
        """Custom severity map changes severity dimension output."""
        cfg = QualityScoringConfig(
            severity_map={
                LearningSignalSeverity.LOW: 0.0,
                LearningSignalSeverity.MEDIUM: 0.0,
                LearningSignalSeverity.HIGH: 0.0,
                LearningSignalSeverity.CRITICAL: 0.0,
            },
            weight_severity=1.0,
            weight_summary=0.0,
            weight_details=0.0,
            weight_source=0.0,
            weight_context=0.0,
        )
        signal = _make_signal(
            summary="a" * 100,
            severity=LearningSignalSeverity.CRITICAL,
        )
        enrich_learning_signal(signal, config=cfg)
        assert signal.quality_score == 0.0

    def test_none_config_uses_defaults(self) -> None:
        """Passing config=None should behave identically to no arg."""
        signal_a = _make_signal(summary="same input", severity=LearningSignalSeverity.HIGH)
        signal_b = _make_signal(summary="same input", severity=LearningSignalSeverity.HIGH)
        enrich_learning_signal(signal_a)
        enrich_learning_signal(signal_b, config=None)
        assert signal_a.quality_score == signal_b.quality_score
        assert signal_a.quality_label == signal_b.quality_label


# ---------------------------------------------------------------------------
# Round-trip stability
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """Enriching the same signal twice produces identical results."""

    def test_enrich_then_reenrich_is_stable(self) -> None:
        signal = _make_signal(
            summary="some summary text here",
            details="some detail text here",
            source="test",
            context={"k": "v"},
            severity=LearningSignalSeverity.HIGH,
        )
        enrich_learning_signal(signal)
        first_score = signal.quality_score
        first_label = signal.quality_label
        first_reasons = list(signal.quality_reasons)

        enrich_learning_signal(signal)
        assert signal.quality_score == first_score
        assert signal.quality_label == first_label
        assert signal.quality_reasons == first_reasons


# ---------------------------------------------------------------------------
# All severity levels produce expected quality mappings
# ---------------------------------------------------------------------------


class TestAllSeverityLevels:
    """Each severity level maps to a specific quality contribution."""

    @pytest.mark.parametrize(
        ("severity", "expected_severity_quality"),
        [
            (LearningSignalSeverity.LOW, 0.3),
            (LearningSignalSeverity.MEDIUM, 0.55),
            (LearningSignalSeverity.HIGH, 0.8),
            (LearningSignalSeverity.CRITICAL, 1.0),
        ],
    )
    def test_severity_quality_mapping(
        self,
        severity: LearningSignalSeverity,
        expected_severity_quality: float,
    ) -> None:
        """Severity-only config isolates the severity dimension."""
        cfg = QualityScoringConfig(
            weight_summary=0.0,
            weight_details=0.0,
            weight_source=0.0,
            weight_context=0.0,
            weight_severity=1.0,
        )
        signal = _make_signal(summary="x", severity=severity)
        enrich_learning_signal(signal, config=cfg)
        assert signal.quality_score == expected_severity_quality

    def test_severity_ordering(self) -> None:
        """LOW < MEDIUM < HIGH < CRITICAL in quality score."""
        scores: list[float] = []
        for sev in [
            LearningSignalSeverity.LOW,
            LearningSignalSeverity.MEDIUM,
            LearningSignalSeverity.HIGH,
            LearningSignalSeverity.CRITICAL,
        ]:
            signal = _make_signal(summary="same text for all", severity=sev)
            enrich_learning_signal(signal)
            scores.append(signal.quality_score)
        assert scores == sorted(scores)
        assert len(set(scores)) == 4  # all distinct
