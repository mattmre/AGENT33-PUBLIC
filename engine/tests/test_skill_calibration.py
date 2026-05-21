"""Tests for hybrid skill matching calibration (S29).

Covers:
- Exact match (skill name matches query exactly)
- Fuzzy match (similar name)
- Semantic match (tag overlap)
- Contextual match (capability-based)
- Short-circuit on exact match (other stages not searched)
- Threshold filtering (scores below threshold excluded)
- Diagnostics output
- Calibration with test queries
- Threshold comparison
- Empty registry
- No match found
- API route tests (match, thresholds CRUD, diagnostics, calibrate)
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agent33.skills.calibration import (
    HybridSkillMatcher,
    MatchCandidate,
    MatchDiagnostics,
    MatchResult,
    MatchStage,
    MatchThresholds,
)
from agent33.skills.definition import SkillDefinition, SkillStatus
from agent33.skills.registry import SkillRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def registry() -> SkillRegistry:
    """Create a registry populated with test skills."""
    reg = SkillRegistry()
    reg.register(
        SkillDefinition(
            name="kubernetes-deploy",
            description="Deploy applications to Kubernetes clusters",
            tags=["devops", "k8s", "deployment"],
            category="infrastructure",
            allowed_tools=["shell", "file_ops"],
        )
    )
    reg.register(
        SkillDefinition(
            name="code-review",
            description="Automated code review and quality analysis",
            tags=["quality", "review", "P-01"],
            category="development",
            allowed_tools=["file_ops"],
        )
    )
    reg.register(
        SkillDefinition(
            name="data-analysis",
            description="Analyze datasets and produce reports",
            tags=["analytics", "data", "reporting"],
            category="research",
        )
    )
    reg.register(
        SkillDefinition(
            name="web-scraping",
            description="Extract data from web pages",
            tags=["web", "scraping", "extraction"],
            category="data",
            allowed_tools=["browser", "web_fetch"],
            status=SkillStatus.EXPERIMENTAL,
        )
    )
    return reg


@pytest.fixture()
def matcher(registry: SkillRegistry) -> HybridSkillMatcher:
    """Create a HybridSkillMatcher with default thresholds."""
    return HybridSkillMatcher(skill_registry=registry)


@pytest.fixture()
def empty_matcher() -> HybridSkillMatcher:
    """Create a HybridSkillMatcher with an empty registry."""
    return HybridSkillMatcher(skill_registry=SkillRegistry())


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestModels:
    """Test Pydantic model construction and validation."""

    def test_match_stage_values(self) -> None:
        assert MatchStage.EXACT == "exact"
        assert MatchStage.FUZZY == "fuzzy"
        assert MatchStage.SEMANTIC == "semantic"
        assert MatchStage.CONTEXTUAL == "contextual"

    def test_match_candidate_construction(self) -> None:
        c = MatchCandidate(
            skill_name="test-skill",
            stage=MatchStage.EXACT,
            score=1.0,
            reason="Exact match",
        )
        assert c.skill_name == "test-skill"
        assert c.score == 1.0

    def test_match_candidate_score_upper_bound(self) -> None:
        with pytest.raises(ValueError):
            MatchCandidate(
                skill_name="test",
                stage=MatchStage.FUZZY,
                score=1.5,
                reason="too high",
            )

    def test_match_candidate_score_lower_bound(self) -> None:
        with pytest.raises(ValueError):
            MatchCandidate(
                skill_name="test",
                stage=MatchStage.FUZZY,
                score=-0.1,
                reason="too low",
            )

    def test_match_thresholds_defaults(self) -> None:
        t = MatchThresholds()
        assert t.exact_threshold == 1.0
        assert t.fuzzy_threshold == 0.7
        assert t.semantic_threshold == 0.5
        assert t.contextual_threshold == 0.4
        assert t.max_candidates == 10

    def test_match_result_construction(self) -> None:
        r = MatchResult(
            query="test",
            candidates=[],
            best_match=None,
            stages_searched=[MatchStage.EXACT],
            total_duration_ms=0.5,
        )
        assert r.query == "test"
        assert r.candidates == []
        assert r.best_match is None

    def test_match_diagnostics_construction(self) -> None:
        d = MatchDiagnostics(
            stage=MatchStage.FUZZY,
            candidates_found=3,
            best_score=0.85,
            duration_ms=1.234,
        )
        assert d.stage == MatchStage.FUZZY
        assert d.candidates_found == 3


# ---------------------------------------------------------------------------
# Exact match tests
# ---------------------------------------------------------------------------


class TestExactMatch:
    """Test exact name matching (Stage 1)."""

    def test_exact_match_by_name(self, matcher: HybridSkillMatcher) -> None:
        result = matcher.match("kubernetes-deploy")
        assert result.best_match is not None
        assert result.best_match.skill_name == "kubernetes-deploy"
        assert result.best_match.stage == MatchStage.EXACT
        assert result.best_match.score == 1.0

    def test_exact_match_case_insensitive(self, matcher: HybridSkillMatcher) -> None:
        result = matcher.match("Kubernetes-Deploy")
        assert result.best_match is not None
        assert result.best_match.skill_name == "kubernetes-deploy"
        assert result.best_match.stage == MatchStage.EXACT

    def test_exact_match_short_circuits(self, matcher: HybridSkillMatcher) -> None:
        """When exact match is found, only EXACT stage is searched."""
        result = matcher.match("code-review")
        assert result.stages_searched == [MatchStage.EXACT]
        assert len(result.candidates) == 1
        assert result.candidates[0].stage == MatchStage.EXACT

    def test_exact_match_with_whitespace(self, matcher: HybridSkillMatcher) -> None:
        result = matcher.match("  kubernetes-deploy  ")
        assert result.best_match is not None
        assert result.best_match.skill_name == "kubernetes-deploy"


# ---------------------------------------------------------------------------
# Fuzzy match tests
# ---------------------------------------------------------------------------


class TestFuzzyMatch:
    """Test fuzzy string similarity matching (Stage 2)."""

    def test_fuzzy_match_similar_name(self, matcher: HybridSkillMatcher) -> None:
        result = matcher.match("kubernetes-deplo")
        fuzzy_candidates = [c for c in result.candidates if c.stage == MatchStage.FUZZY]
        found_names = {c.skill_name for c in fuzzy_candidates}
        assert "kubernetes-deploy" in found_names

    def test_fuzzy_match_below_threshold_excluded(self) -> None:
        """Candidates below the fuzzy threshold are excluded."""
        reg = SkillRegistry()
        reg.register(SkillDefinition(name="alpha-beta-gamma", description="Complex skill"))
        # Very strict threshold
        matcher = HybridSkillMatcher(
            skill_registry=reg,
            thresholds=MatchThresholds(fuzzy_threshold=0.99),
        )
        result = matcher.match("zzz-completely-different")
        fuzzy_candidates = [c for c in result.candidates if c.stage == MatchStage.FUZZY]
        assert len(fuzzy_candidates) == 0

    def test_fuzzy_match_on_description(self) -> None:
        """Fuzzy match works against descriptions too."""
        reg = SkillRegistry()
        reg.register(
            SkillDefinition(
                name="xyz",
                description="Deploy applications to Kubernetes clusters",
            )
        )
        matcher = HybridSkillMatcher(
            skill_registry=reg,
            thresholds=MatchThresholds(fuzzy_threshold=0.5),
        )
        result = matcher.match("Deploy applications to Kubernetes")
        fuzzy_candidates = [c for c in result.candidates if c.stage == MatchStage.FUZZY]
        assert len(fuzzy_candidates) >= 1
        assert fuzzy_candidates[0].skill_name == "xyz"
        assert "description" in fuzzy_candidates[0].reason


# ---------------------------------------------------------------------------
# Semantic match tests
# ---------------------------------------------------------------------------


class TestSemanticMatch:
    """Test tag/category overlap matching (Stage 3)."""

    def test_semantic_match_tag_overlap(self) -> None:
        reg = SkillRegistry()
        reg.register(
            SkillDefinition(
                name="k8s-skill",
                description="Kubernetes skill",
                tags=["devops", "k8s"],
            )
        )
        matcher = HybridSkillMatcher(
            skill_registry=reg,
            thresholds=MatchThresholds(semantic_threshold=0.2),
        )
        result = matcher.match("devops")
        semantic_candidates = [c for c in result.candidates if c.stage == MatchStage.SEMANTIC]
        assert len(semantic_candidates) >= 1
        assert semantic_candidates[0].skill_name == "k8s-skill"

    def test_semantic_match_category_overlap(self) -> None:
        """Category tokens contribute to semantic matching."""
        reg = SkillRegistry()
        reg.register(
            SkillDefinition(
                name="xyz-abc",
                description="A specialized tool",
                tags=[],
                category="infrastructure/cloud",
            )
        )
        matcher = HybridSkillMatcher(
            skill_registry=reg,
            thresholds=MatchThresholds(
                fuzzy_threshold=0.99,  # high fuzzy threshold to avoid fuzzy match
                semantic_threshold=0.2,
            ),
        )
        result = matcher.match("infrastructure")
        # The skill should appear via semantic match on category "infrastructure"
        assert len(result.candidates) >= 1
        found_names = {c.skill_name for c in result.candidates}
        assert "xyz-abc" in found_names

    def test_semantic_match_no_overlap(self, matcher: HybridSkillMatcher) -> None:
        result = matcher.match("xyznonexistenttag123")
        semantic_candidates = [c for c in result.candidates if c.stage == MatchStage.SEMANTIC]
        assert len(semantic_candidates) == 0

    def test_semantic_splits_hyphenated_tags(self) -> None:
        """Hyphenated tags are split into individual tokens for matching."""
        reg = SkillRegistry()
        reg.register(
            SkillDefinition(
                name="ci-cd-tool",
                description="CI/CD pipeline tool",
                tags=["continuous-integration"],
            )
        )
        matcher = HybridSkillMatcher(
            skill_registry=reg,
            thresholds=MatchThresholds(semantic_threshold=0.15),
        )
        result = matcher.match("continuous")
        semantic_candidates = [c for c in result.candidates if c.stage == MatchStage.SEMANTIC]
        assert len(semantic_candidates) >= 1


# ---------------------------------------------------------------------------
# Contextual match tests
# ---------------------------------------------------------------------------


class TestContextualMatch:
    """Test context-based matching (Stage 4)."""

    def test_contextual_match_by_capability(self, matcher: HybridSkillMatcher) -> None:
        result = matcher.match(
            "review code quality",
            context={"capabilities": ["P-01"]},
        )
        contextual_candidates = [c for c in result.candidates if c.stage == MatchStage.CONTEXTUAL]
        found_names = {c.skill_name for c in contextual_candidates}
        assert "code-review" in found_names

    def test_contextual_match_by_task_type(self, matcher: HybridSkillMatcher) -> None:
        result = matcher.match(
            "deploy something",
            context={"task_type": "deploy"},
        )
        contextual_candidates = [c for c in result.candidates if c.stage == MatchStage.CONTEXTUAL]
        found_names = {c.skill_name for c in contextual_candidates}
        assert "kubernetes-deploy" in found_names

    def test_contextual_match_by_tools(self, matcher: HybridSkillMatcher) -> None:
        result = matcher.match(
            "browser task",
            context={"tools": ["browser"]},
        )
        contextual_candidates = [c for c in result.candidates if c.stage == MatchStage.CONTEXTUAL]
        found_names = {c.skill_name for c in contextual_candidates}
        assert "web-scraping" in found_names

    def test_contextual_no_context_skips_stage(self, matcher: HybridSkillMatcher) -> None:
        result = matcher.match("anything")
        assert MatchStage.CONTEXTUAL not in result.stages_searched

    def test_contextual_empty_context_values(self, matcher: HybridSkillMatcher) -> None:
        """Context with empty values produces no contextual candidates."""
        result = matcher.match(
            "anything",
            context={"capabilities": [], "task_type": "", "tools": []},
        )
        contextual_candidates = [c for c in result.candidates if c.stage == MatchStage.CONTEXTUAL]
        assert len(contextual_candidates) == 0


# ---------------------------------------------------------------------------
# Pipeline behavior tests
# ---------------------------------------------------------------------------


class TestPipelineBehavior:
    """Test overall pipeline behavior."""

    def test_empty_registry_returns_empty(self, empty_matcher: HybridSkillMatcher) -> None:
        result = empty_matcher.match("anything")
        assert result.candidates == []
        assert result.best_match is None

    def test_no_match_found(self, matcher: HybridSkillMatcher) -> None:
        result = matcher.match("xyzabc123nothingmatches")
        # best_match should either be None or have a sub-exact score
        if result.best_match is not None:
            assert result.best_match.score < 1.0

    def test_deduplication_keeps_highest_score(self) -> None:
        """When a skill appears in multiple stages, keep the highest score."""
        reg = SkillRegistry()
        reg.register(
            SkillDefinition(
                name="deploy",
                description="deploy applications",
                tags=["deploy", "deployment"],
            )
        )
        matcher = HybridSkillMatcher(
            skill_registry=reg,
            thresholds=MatchThresholds(
                fuzzy_threshold=0.3,
                semantic_threshold=0.2,
            ),
        )
        result = matcher.match("deploy")
        # Exact match should win since it's score=1.0
        assert result.best_match is not None
        assert result.best_match.score == 1.0
        # Should be deduplicated -- only one entry per skill
        skill_names = [c.skill_name for c in result.candidates]
        assert skill_names.count("deploy") == 1

    def test_max_candidates_limit(self) -> None:
        """Result respects max_candidates limit."""
        reg = SkillRegistry()
        for i in range(20):
            reg.register(
                SkillDefinition(
                    name=f"skill-{i:03d}",
                    description=f"Skill number {i}",
                    tags=["common"],
                )
            )
        matcher = HybridSkillMatcher(
            skill_registry=reg,
            thresholds=MatchThresholds(
                fuzzy_threshold=0.1,
                semantic_threshold=0.1,
                max_candidates=5,
            ),
        )
        result = matcher.match("common skill")
        assert len(result.candidates) <= 5

    def test_timing_is_recorded(self, matcher: HybridSkillMatcher) -> None:
        result = matcher.match("kubernetes-deploy")
        assert result.total_duration_ms >= 0

    def test_stages_searched_without_context(self, matcher: HybridSkillMatcher) -> None:
        """Without context, only EXACT+FUZZY+SEMANTIC stages are searched."""
        result = matcher.match("xyznonexistent")
        assert MatchStage.EXACT in result.stages_searched
        assert MatchStage.FUZZY in result.stages_searched
        assert MatchStage.SEMANTIC in result.stages_searched
        assert MatchStage.CONTEXTUAL not in result.stages_searched


# ---------------------------------------------------------------------------
# Diagnostics tests
# ---------------------------------------------------------------------------


class TestDiagnostics:
    """Test the diagnostics API."""

    def test_diagnostics_returns_all_four_stages(self, matcher: HybridSkillMatcher) -> None:
        diags = matcher.get_diagnostics("kubernetes-deploy")
        assert len(diags) == 4
        stages = {d.stage for d in diags}
        assert stages == {
            MatchStage.EXACT,
            MatchStage.FUZZY,
            MatchStage.SEMANTIC,
            MatchStage.CONTEXTUAL,
        }

    def test_diagnostics_exact_match_shows_candidates(self, matcher: HybridSkillMatcher) -> None:
        diags = matcher.get_diagnostics("code-review")
        exact_diag = next(d for d in diags if d.stage == MatchStage.EXACT)
        assert exact_diag.candidates_found == 1
        assert exact_diag.best_score == 1.0

    def test_diagnostics_no_match_zero_candidates(self, empty_matcher: HybridSkillMatcher) -> None:
        diags = empty_matcher.get_diagnostics("anything")
        for d in diags:
            assert d.candidates_found == 0
            assert d.best_score == 0.0

    def test_diagnostics_timing_positive(self, matcher: HybridSkillMatcher) -> None:
        diags = matcher.get_diagnostics("test query")
        for d in diags:
            assert d.duration_ms >= 0


# ---------------------------------------------------------------------------
# Calibration tests
# ---------------------------------------------------------------------------


class TestCalibration:
    """Test the calibration API."""

    def test_calibrate_with_test_queries(self, matcher: HybridSkillMatcher) -> None:
        test_queries = [
            {"query": "kubernetes-deploy", "expected": "kubernetes-deploy"},
            {"query": "code-review", "expected": "code-review"},
            {"query": "nonexistent-skill", "expected": "some-other-skill"},
        ]
        report = matcher.calibrate(test_queries)
        assert report["total_queries"] == 3
        assert report["correct_matches"] == 2
        assert 0.0 <= report["accuracy"] <= 1.0
        assert "stage_hit_rates" in report
        assert "exact" in report["stage_hit_rates"]
        assert "fuzzy" in report["stage_hit_rates"]
        assert "semantic" in report["stage_hit_rates"]
        assert "contextual" in report["stage_hit_rates"]

    def test_calibrate_empty_queries(self, matcher: HybridSkillMatcher) -> None:
        report = matcher.calibrate([])
        assert report["total_queries"] == 0

    def test_calibrate_perfect_accuracy(self, matcher: HybridSkillMatcher) -> None:
        test_queries = [
            {"query": "kubernetes-deploy", "expected": "kubernetes-deploy"},
            {"query": "code-review", "expected": "code-review"},
        ]
        report = matcher.calibrate(test_queries)
        assert report["accuracy"] == 1.0
        assert report["correct_matches"] == 2

    def test_calibrate_reports_recommendations_on_low_accuracy(self) -> None:
        reg = SkillRegistry()
        reg.register(SkillDefinition(name="only-skill", description="The only skill"))
        matcher = HybridSkillMatcher(skill_registry=reg)
        test_queries = [
            {"query": "nothing-matches", "expected": "wrong-expected"},
            {"query": "also-nothing", "expected": "another-wrong"},
            {"query": "nope", "expected": "still-wrong"},
        ]
        report = matcher.calibrate(test_queries)
        assert report["accuracy"] < 0.5
        assert len(report["recommendations"]) > 0
        assert any("accuracy" in r.lower() for r in report["recommendations"])

    def test_calibrate_reports_stage_avg_best_scores(self, matcher: HybridSkillMatcher) -> None:
        test_queries = [
            {"query": "kubernetes-deploy", "expected": "kubernetes-deploy"},
        ]
        report = matcher.calibrate(test_queries)
        assert "stage_avg_best_scores" in report
        # Exact stage should have a best score of 1.0
        assert report["stage_avg_best_scores"]["exact"] == 1.0


# ---------------------------------------------------------------------------
# Threshold comparison tests
# ---------------------------------------------------------------------------


class TestThresholdComparison:
    """Test the threshold A/B comparison API."""

    def test_compare_returns_both_results(self, matcher: HybridSkillMatcher) -> None:
        queries = [
            {"query": "kubernetes-deploy", "expected": "kubernetes-deploy"},
            {"query": "code-review", "expected": "code-review"},
        ]
        threshold_a = MatchThresholds(fuzzy_threshold=0.7)
        threshold_b = MatchThresholds(fuzzy_threshold=0.3)
        report = matcher.compare_thresholds(queries, threshold_a, threshold_b)
        assert "threshold_a" in report
        assert "threshold_b" in report
        assert "result_a" in report
        assert "result_b" in report
        assert "winner" in report
        assert report["winner"] in ("a", "b")

    def test_compare_preserves_original_thresholds(self, matcher: HybridSkillMatcher) -> None:
        original = matcher.thresholds.model_dump()
        queries = [{"query": "test", "expected": "test"}]
        matcher.compare_thresholds(
            queries,
            MatchThresholds(fuzzy_threshold=0.1),
            MatchThresholds(fuzzy_threshold=0.9),
        )
        assert matcher.thresholds.model_dump() == original

    def test_compare_winner_matches_higher_accuracy(self) -> None:
        """The winner field should correspond to the config with higher accuracy."""
        reg = SkillRegistry()
        reg.register(
            SkillDefinition(name="deploy", description="deploy workloads", tags=["deploy"])
        )
        matcher = HybridSkillMatcher(skill_registry=reg)
        queries = [
            {"query": "deploy", "expected": "deploy"},
        ]
        # Both should get 100% since exact match works regardless of fuzzy threshold
        report = matcher.compare_thresholds(
            queries,
            MatchThresholds(fuzzy_threshold=0.9),
            MatchThresholds(fuzzy_threshold=0.1),
        )
        # Both 100%, winner defaults to "a" on tie
        assert report["result_a"]["accuracy"] == report["result_b"]["accuracy"]
        assert report["winner"] == "a"


# ---------------------------------------------------------------------------
# Threshold update tests
# ---------------------------------------------------------------------------


class TestThresholdUpdate:
    """Test threshold get/set."""

    def test_get_thresholds(self, matcher: HybridSkillMatcher) -> None:
        t = matcher.thresholds
        assert isinstance(t, MatchThresholds)
        assert t.fuzzy_threshold == 0.7

    def test_set_thresholds(self, matcher: HybridSkillMatcher) -> None:
        new_t = MatchThresholds(fuzzy_threshold=0.5, semantic_threshold=0.3)
        matcher.thresholds = new_t
        assert matcher.thresholds.fuzzy_threshold == 0.5
        assert matcher.thresholds.semantic_threshold == 0.3

    def test_custom_thresholds_affect_matching(self) -> None:
        """Lowering thresholds should produce more candidates."""
        reg = SkillRegistry()
        reg.register(
            SkillDefinition(
                name="test-skill",
                description="A test skill for testing",
                tags=["test"],
            )
        )

        strict = HybridSkillMatcher(
            skill_registry=reg,
            thresholds=MatchThresholds(fuzzy_threshold=0.95),
        )
        lenient = HybridSkillMatcher(
            skill_registry=reg,
            thresholds=MatchThresholds(fuzzy_threshold=0.3),
        )

        strict_result = strict.match("test-skil")
        lenient_result = lenient.match("test-skil")

        fuzzy_strict = [c for c in strict_result.candidates if c.stage == MatchStage.FUZZY]
        fuzzy_lenient = [c for c in lenient_result.candidates if c.stage == MatchStage.FUZZY]
        assert len(fuzzy_lenient) >= len(fuzzy_strict)


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestConfig:
    """Test that config settings are wired correctly."""

    def test_config_defaults(self) -> None:
        from agent33.config import Settings

        s = Settings()
        assert s.skill_match_fuzzy_threshold == 0.7
        assert s.skill_match_semantic_threshold == 0.5
        assert s.skill_match_contextual_threshold == 0.4
        assert s.skill_match_max_candidates == 10

    def test_config_to_thresholds(self) -> None:
        from agent33.config import Settings

        s = Settings()
        t = MatchThresholds(
            fuzzy_threshold=s.skill_match_fuzzy_threshold,
            semantic_threshold=s.skill_match_semantic_threshold,
            contextual_threshold=s.skill_match_contextual_threshold,
            max_candidates=s.skill_match_max_candidates,
        )
        assert t.fuzzy_threshold == 0.7


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


def _build_test_app(matcher: HybridSkillMatcher) -> FastAPI:
    """Build a minimal FastAPI app with skill matching routes."""
    from types import SimpleNamespace

    from agent33.api.routes.skill_matching import router, set_skill_matcher

    app = FastAPI()
    app.include_router(router)
    set_skill_matcher(matcher)

    # Patch auth: set request.state.user with scopes and tenant_id
    @app.middleware("http")
    async def fake_auth(request: Any, call_next: Any) -> Any:
        request.state.user = SimpleNamespace(
            sub="test-user",
            scopes=["admin", "agents:read", "agents:write"],
            tenant_id="test-tenant",
        )
        return await call_next(request)

    return app


@pytest.fixture()
def test_app(matcher: HybridSkillMatcher) -> FastAPI:
    """Build a test app with the matcher installed."""
    return _build_test_app(matcher)


@pytest.fixture()
async def client(test_app: FastAPI) -> Any:
    """Create an async test client."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestAPIRoutes:
    """Test the skill matching API endpoints."""

    async def test_match_endpoint(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/v1/skills/match",
            json={"query": "kubernetes-deploy"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "kubernetes-deploy"
        assert len(data["candidates"]) >= 1
        assert data["best_match"] is not None
        assert data["best_match"]["skill_name"] == "kubernetes-deploy"
        assert data["best_match"]["stage"] == "exact"

    async def test_match_with_context(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/v1/skills/match",
            json={
                "query": "review task",
                "context": {"capabilities": ["P-01"]},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "candidates" in data

    async def test_match_empty_query_rejected(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/v1/skills/match",
            json={"query": ""},
        )
        assert resp.status_code == 422

    async def test_get_thresholds_endpoint(self, client: AsyncClient) -> None:
        resp = await client.get("/v1/skills/match/thresholds")
        assert resp.status_code == 200
        data = resp.json()
        assert data["fuzzy_threshold"] == 0.7
        assert data["semantic_threshold"] == 0.5
        assert data["contextual_threshold"] == 0.4
        assert data["max_candidates"] == 10

    async def test_update_thresholds_endpoint(self, client: AsyncClient) -> None:
        resp = await client.put(
            "/v1/skills/match/thresholds",
            json={"fuzzy_threshold": 0.6, "semantic_threshold": 0.4},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["fuzzy_threshold"] == 0.6
        assert data["semantic_threshold"] == 0.4

        # Verify it persisted
        resp2 = await client.get("/v1/skills/match/thresholds")
        assert resp2.json()["fuzzy_threshold"] == 0.6

    async def test_diagnostics_endpoint(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/v1/skills/match/diagnostics",
            json={"query": "code-review"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 4
        stages = {d["stage"] for d in data}
        assert stages == {"exact", "fuzzy", "semantic", "contextual"}
        # code-review should have exact match
        exact = next(d for d in data if d["stage"] == "exact")
        assert exact["candidates_found"] == 1
        assert exact["best_score"] == 1.0

    async def test_calibrate_endpoint(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/v1/skills/match/calibrate",
            json={
                "test_queries": [
                    {"query": "kubernetes-deploy", "expected": "kubernetes-deploy"},
                    {"query": "code-review", "expected": "code-review"},
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_queries"] == 2
        assert data["correct_matches"] == 2
        assert data["accuracy"] == 1.0

    async def test_compare_endpoint(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/v1/skills/match/compare",
            json={
                "queries": [
                    {"query": "kubernetes-deploy", "expected": "kubernetes-deploy"},
                ],
                "threshold_a": {"fuzzy_threshold": 0.7},
                "threshold_b": {"fuzzy_threshold": 0.3},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "result_a" in data
        assert "result_b" in data
        assert data["winner"] in ("a", "b")

    async def test_matcher_not_initialized(self) -> None:
        """503 when matcher is not set."""
        from types import SimpleNamespace

        from agent33.api.routes.skill_matching import router, set_skill_matcher

        # Temporarily clear the module-level matcher
        set_skill_matcher(None)
        try:
            app = FastAPI()
            app.include_router(router)

            @app.middleware("http")
            async def fake_auth(request: Any, call_next: Any) -> Any:
                request.state.user = SimpleNamespace(
                    sub="test-user",
                    scopes=["admin", "agents:read"],
                    tenant_id="test-tenant",
                )
                return await call_next(request)

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                resp = await c.post(
                    "/v1/skills/match",
                    json={"query": "test"},
                )
                assert resp.status_code == 503
                assert "not initialized" in resp.json()["detail"]
        finally:
            pass


# ---------------------------------------------------------------------------
# Integration with deprecated skills
# ---------------------------------------------------------------------------


class TestDeprecatedSkills:
    """Verify deprecated skills are still matchable by the hybrid matcher."""

    def test_deprecated_skills_still_appear(self) -> None:
        reg = SkillRegistry()
        reg.register(
            SkillDefinition(
                name="old-skill",
                description="A deprecated skill",
                status=SkillStatus.DEPRECATED,
            )
        )
        matcher = HybridSkillMatcher(skill_registry=reg)
        result = matcher.match("old-skill")
        # Deprecated skills are in the registry and should match exactly
        assert result.best_match is not None
        assert result.best_match.skill_name == "old-skill"
