"""4-stage hybrid skill matching calibration pipeline.

Implements a graduated, non-LLM matching pipeline with four stages:
1. **Exact** -- query matches a skill name exactly.
2. **Fuzzy** -- SequenceMatcher similarity against skill names/descriptions.
3. **Semantic** -- tag/category overlap scoring.
4. **Contextual** -- score based on context dict (agent capabilities, task type).

Short-circuits on exact match.  Includes calibration and diagnostics APIs
for tuning thresholds.
"""

from __future__ import annotations

import logging
import time
from difflib import SequenceMatcher
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent33.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class MatchStage(StrEnum):
    """Matching pipeline stage identifier."""

    EXACT = "exact"
    FUZZY = "fuzzy"
    SEMANTIC = "semantic"
    CONTEXTUAL = "contextual"


class MatchCandidate(BaseModel):
    """A single skill candidate from the matching pipeline."""

    skill_name: str
    stage: MatchStage
    score: float = Field(ge=0.0, le=1.0)
    reason: str


class MatchResult(BaseModel):
    """Aggregated result of the 4-stage matching pipeline."""

    query: str
    candidates: list[MatchCandidate]
    best_match: MatchCandidate | None = None
    stages_searched: list[MatchStage]
    total_duration_ms: float


class MatchThresholds(BaseModel):
    """Configurable thresholds for each matching stage."""

    exact_threshold: float = Field(default=1.0, ge=0.0, le=1.0)
    fuzzy_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    semantic_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    contextual_threshold: float = Field(default=0.4, ge=0.0, le=1.0)
    max_candidates: int = Field(default=10, ge=1)


class MatchDiagnostics(BaseModel):
    """Per-stage diagnostic information from a match run."""

    stage: MatchStage
    candidates_found: int
    best_score: float
    duration_ms: float


# ---------------------------------------------------------------------------
# HybridSkillMatcher
# ---------------------------------------------------------------------------


class HybridSkillMatcher:
    """4-stage hybrid skill matching pipeline with calibration.

    Stages run in order: Exact -> Fuzzy -> Semantic -> Contextual.
    Short-circuits when an exact match is found.

    Parameters
    ----------
    skill_registry:
        The skill registry to search against.
    thresholds:
        Configurable per-stage score thresholds and max candidates.
    """

    def __init__(
        self,
        skill_registry: SkillRegistry,
        thresholds: MatchThresholds | None = None,
    ) -> None:
        self._registry = skill_registry
        self._thresholds = thresholds or MatchThresholds()

    @property
    def thresholds(self) -> MatchThresholds:
        """Return current thresholds."""
        return self._thresholds

    @thresholds.setter
    def thresholds(self, value: MatchThresholds) -> None:
        """Update thresholds."""
        self._thresholds = value

    # ------------------------------------------------------------------
    # Main match pipeline
    # ------------------------------------------------------------------

    def match(
        self,
        query: str,
        context: dict[str, Any] | None = None,
    ) -> MatchResult:
        """Run the 4-stage matching pipeline.

        Parameters
        ----------
        query:
            The search query (skill name, description fragment, etc.).
        context:
            Optional context dict for contextual matching (e.g.
            ``{"capabilities": ["P-01"], "task_type": "deploy"}``).

        Returns
        -------
        MatchResult
            Contains all candidates above threshold, best match,
            stages searched, and timing.
        """
        t0 = time.perf_counter()
        all_candidates: list[MatchCandidate] = []
        stages_searched: list[MatchStage] = []

        # Stage 1: Exact match
        exact_candidates = self._stage_exact(query)
        stages_searched.append(MatchStage.EXACT)
        all_candidates.extend(exact_candidates)

        # Short-circuit if exact match found
        if exact_candidates:
            duration_ms = (time.perf_counter() - t0) * 1000
            exact_best = max(all_candidates, key=lambda c: c.score)
            return MatchResult(
                query=query,
                candidates=all_candidates[: self._thresholds.max_candidates],
                best_match=exact_best,
                stages_searched=stages_searched,
                total_duration_ms=round(duration_ms, 3),
            )

        # Stage 2: Fuzzy match
        fuzzy_candidates = self._stage_fuzzy(query)
        stages_searched.append(MatchStage.FUZZY)
        all_candidates.extend(fuzzy_candidates)

        # Stage 3: Semantic match (tag/category overlap)
        semantic_candidates = self._stage_semantic(query)
        stages_searched.append(MatchStage.SEMANTIC)
        all_candidates.extend(semantic_candidates)

        # Stage 4: Contextual match
        if context:
            contextual_candidates = self._stage_contextual(query, context)
            stages_searched.append(MatchStage.CONTEXTUAL)
            all_candidates.extend(contextual_candidates)

        # Deduplicate: keep highest-scoring entry per skill
        all_candidates = self._deduplicate(all_candidates)

        # Sort by score descending and limit
        all_candidates.sort(key=lambda c: c.score, reverse=True)
        all_candidates = all_candidates[: self._thresholds.max_candidates]

        duration_ms = (time.perf_counter() - t0) * 1000
        best: MatchCandidate | None = (
            max(all_candidates, key=lambda c: c.score) if all_candidates else None
        )

        return MatchResult(
            query=query,
            candidates=all_candidates,
            best_match=best,
            stages_searched=stages_searched,
            total_duration_ms=round(duration_ms, 3),
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_diagnostics(self, query: str) -> list[MatchDiagnostics]:
        """Run all stages and return per-stage diagnostic information.

        Unlike ``match()``, this always runs every stage (no short-circuit)
        and provides timing and candidate counts for each.
        """
        diagnostics: list[MatchDiagnostics] = []

        # Exact
        t0 = time.perf_counter()
        exact = self._stage_exact(query)
        d_exact = (time.perf_counter() - t0) * 1000
        diagnostics.append(
            MatchDiagnostics(
                stage=MatchStage.EXACT,
                candidates_found=len(exact),
                best_score=max((c.score for c in exact), default=0.0),
                duration_ms=round(d_exact, 3),
            )
        )

        # Fuzzy
        t0 = time.perf_counter()
        fuzzy = self._stage_fuzzy(query)
        d_fuzzy = (time.perf_counter() - t0) * 1000
        diagnostics.append(
            MatchDiagnostics(
                stage=MatchStage.FUZZY,
                candidates_found=len(fuzzy),
                best_score=max((c.score for c in fuzzy), default=0.0),
                duration_ms=round(d_fuzzy, 3),
            )
        )

        # Semantic
        t0 = time.perf_counter()
        semantic = self._stage_semantic(query)
        d_semantic = (time.perf_counter() - t0) * 1000
        diagnostics.append(
            MatchDiagnostics(
                stage=MatchStage.SEMANTIC,
                candidates_found=len(semantic),
                best_score=max((c.score for c in semantic), default=0.0),
                duration_ms=round(d_semantic, 3),
            )
        )

        # Contextual (with empty context)
        t0 = time.perf_counter()
        contextual = self._stage_contextual(query, {})
        d_contextual = (time.perf_counter() - t0) * 1000
        diagnostics.append(
            MatchDiagnostics(
                stage=MatchStage.CONTEXTUAL,
                candidates_found=len(contextual),
                best_score=max((c.score for c in contextual), default=0.0),
                duration_ms=round(d_contextual, 3),
            )
        )

        return diagnostics

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def calibrate(self, test_queries: list[dict[str, Any]]) -> dict[str, Any]:
        """Run test queries against the catalog and compute per-stage hit rates.

        Each test query dict should have:
        - ``query`` (str): the search query.
        - ``expected`` (str): the expected skill name to match.
        - ``context`` (dict, optional): context for contextual matching.

        Returns a calibration report with per-stage hit rates and
        recommended threshold adjustments.
        """
        if not test_queries:
            return {
                "total_queries": 0,
                "stage_hit_rates": {},
                "recommendations": [],
            }

        stage_hits: dict[str, int] = {s.value: 0 for s in MatchStage}
        stage_best_scores: dict[str, list[float]] = {s.value: [] for s in MatchStage}
        correct_matches = 0
        total = len(test_queries)

        for tq in test_queries:
            query = str(tq.get("query", ""))
            expected = str(tq.get("expected", ""))
            ctx = tq.get("context")

            result = self.match(query, context=ctx if isinstance(ctx, dict) else None)

            # Check if best match is the expected skill
            if result.best_match and result.best_match.skill_name == expected:
                correct_matches += 1

            # Track per-stage hit rates via diagnostics
            diags = self.get_diagnostics(query)
            for diag in diags:
                if diag.candidates_found > 0:
                    stage_hits[diag.stage.value] += 1
                    stage_best_scores[diag.stage.value].append(diag.best_score)

        stage_hit_rates: dict[str, float] = {}
        for stage_name, hits in stage_hits.items():
            stage_hit_rates[stage_name] = round(hits / total, 4) if total > 0 else 0.0

        # Generate recommendations
        recommendations: list[str] = []
        accuracy = correct_matches / total if total > 0 else 0.0

        if accuracy < 0.5:
            recommendations.append(
                f"Overall accuracy is low ({accuracy:.1%}). "
                "Consider lowering fuzzy_threshold or semantic_threshold."
            )

        for stage_name, scores in stage_best_scores.items():
            if scores:
                avg_score = sum(scores) / len(scores)
                current_threshold = getattr(self._thresholds, f"{stage_name}_threshold", None)
                if current_threshold is not None and avg_score < current_threshold * 0.8:
                    recommendations.append(
                        f"Stage '{stage_name}' average best score ({avg_score:.3f}) is "
                        f"well below threshold ({current_threshold:.3f}). "
                        "Consider lowering the threshold."
                    )

        return {
            "total_queries": total,
            "correct_matches": correct_matches,
            "accuracy": round(accuracy, 4),
            "stage_hit_rates": stage_hit_rates,
            "stage_avg_best_scores": {
                k: round(sum(v) / len(v), 4) if v else 0.0 for k, v in stage_best_scores.items()
            },
            "recommendations": recommendations,
        }

    # ------------------------------------------------------------------
    # Threshold comparison
    # ------------------------------------------------------------------

    def compare_thresholds(
        self,
        queries: list[dict[str, Any]],
        threshold_a: MatchThresholds,
        threshold_b: MatchThresholds,
    ) -> dict[str, Any]:
        """A/B compare two threshold configurations on the same queries.

        Each query dict follows the same format as ``calibrate()``.

        Returns a comparison report with accuracy and match counts for each.
        """
        original = self._thresholds

        # Run A
        self._thresholds = threshold_a
        report_a = self.calibrate(queries)

        # Run B
        self._thresholds = threshold_b
        report_b = self.calibrate(queries)

        # Restore
        self._thresholds = original

        return {
            "threshold_a": threshold_a.model_dump(),
            "threshold_b": threshold_b.model_dump(),
            "result_a": report_a,
            "result_b": report_b,
            "winner": ("a" if report_a.get("accuracy", 0) >= report_b.get("accuracy", 0) else "b"),
        }

    # ------------------------------------------------------------------
    # Stage implementations
    # ------------------------------------------------------------------

    def _stage_exact(self, query: str) -> list[MatchCandidate]:
        """Stage 1: exact skill name match (case-insensitive)."""
        query_lower = query.strip().lower()
        candidates: list[MatchCandidate] = []
        for skill in self._registry.list_all():
            if skill.name.lower() == query_lower:
                candidates.append(
                    MatchCandidate(
                        skill_name=skill.name,
                        stage=MatchStage.EXACT,
                        score=1.0,
                        reason="Exact name match",
                    )
                )
        return candidates

    def _stage_fuzzy(self, query: str) -> list[MatchCandidate]:
        """Stage 2: fuzzy string similarity against names and descriptions."""
        query_lower = query.strip().lower()
        candidates: list[MatchCandidate] = []
        threshold = self._thresholds.fuzzy_threshold

        for skill in self._registry.list_all():
            # Score against name
            name_score = SequenceMatcher(None, query_lower, skill.name.lower()).ratio()

            # Score against description
            desc_score = 0.0
            if skill.description:
                desc_score = SequenceMatcher(None, query_lower, skill.description.lower()).ratio()

            best_score = max(name_score, desc_score)
            if best_score >= threshold:
                reason_part = "name" if name_score >= desc_score else "description"
                candidates.append(
                    MatchCandidate(
                        skill_name=skill.name,
                        stage=MatchStage.FUZZY,
                        score=round(best_score, 4),
                        reason=f"Fuzzy match on {reason_part} (score={best_score:.3f})",
                    )
                )

        return candidates

    def _stage_semantic(self, query: str) -> list[MatchCandidate]:
        """Stage 3: tag/category overlap scoring.

        Tokenizes the query and computes Jaccard-like overlap with each
        skill's tags and category tokens.
        """
        query_tokens = set(query.strip().lower().split())
        if not query_tokens:
            return []

        candidates: list[MatchCandidate] = []
        threshold = self._thresholds.semantic_threshold

        for skill in self._registry.list_all():
            # Build skill token set from tags + category
            skill_tokens: set[str] = set()
            for tag in skill.tags:
                skill_tokens.update(tag.lower().split("-"))
                skill_tokens.add(tag.lower())
            if skill.category:
                skill_tokens.update(skill.category.lower().replace("/", " ").split())

            if not skill_tokens:
                continue

            # Jaccard overlap
            intersection = query_tokens & skill_tokens
            union = query_tokens | skill_tokens
            score = len(intersection) / len(union) if union else 0.0

            if score >= threshold:
                matched_tokens = ", ".join(sorted(intersection))
                candidates.append(
                    MatchCandidate(
                        skill_name=skill.name,
                        stage=MatchStage.SEMANTIC,
                        score=round(score, 4),
                        reason=f"Tag/category overlap: {matched_tokens}",
                    )
                )

        return candidates

    def _stage_contextual(
        self,
        query: str,
        context: dict[str, Any],
    ) -> list[MatchCandidate]:
        """Stage 4: contextual matching based on agent capabilities and task type.

        Scores skills based on how well they match the provided context
        (capabilities, task_type, allowed_tools, etc.).
        """
        candidates: list[MatchCandidate] = []
        threshold = self._thresholds.contextual_threshold

        ctx_capabilities = set(context.get("capabilities", []))
        ctx_task_type = str(context.get("task_type", "")).lower()
        ctx_tools = set(context.get("tools", []))

        if not ctx_capabilities and not ctx_task_type and not ctx_tools:
            return []

        for skill in self._registry.list_all():
            score_components: list[float] = []
            reasons: list[str] = []

            # Capability match: check if any of the skill's tags match
            # capability IDs
            if ctx_capabilities:
                skill_tag_set = {t.upper() for t in skill.tags}
                cap_overlap = ctx_capabilities & skill_tag_set
                if cap_overlap:
                    cap_score = len(cap_overlap) / len(ctx_capabilities)
                    score_components.append(cap_score)
                    reasons.append(f"capabilities={','.join(sorted(cap_overlap))}")

            # Task type match: check description/category for task type
            if ctx_task_type:
                task_match = 0.0
                if ctx_task_type in skill.description.lower():
                    task_match = 0.8
                elif ctx_task_type in skill.category.lower():
                    task_match = 0.6
                elif any(ctx_task_type in tag.lower() for tag in skill.tags):
                    task_match = 0.5
                if task_match > 0:
                    score_components.append(task_match)
                    reasons.append(f"task_type={ctx_task_type}")

            # Tool overlap: check if the skill's allowed_tools match context
            if ctx_tools and skill.allowed_tools:
                tool_overlap = ctx_tools & set(skill.allowed_tools)
                if tool_overlap:
                    tool_score = len(tool_overlap) / len(ctx_tools)
                    score_components.append(tool_score)
                    reasons.append(f"tools={','.join(sorted(tool_overlap))}")

            if not score_components:
                continue

            avg_score = sum(score_components) / len(score_components)

            if avg_score >= threshold:
                candidates.append(
                    MatchCandidate(
                        skill_name=skill.name,
                        stage=MatchStage.CONTEXTUAL,
                        score=round(avg_score, 4),
                        reason=f"Context match: {'; '.join(reasons)}",
                    )
                )

        return candidates

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _deduplicate(candidates: list[MatchCandidate]) -> list[MatchCandidate]:
        """Keep only the highest-scoring entry per skill name."""
        best: dict[str, MatchCandidate] = {}
        for c in candidates:
            existing = best.get(c.skill_name)
            if existing is None or c.score > existing.score:
                best[c.skill_name] = c
        return list(best.values())
