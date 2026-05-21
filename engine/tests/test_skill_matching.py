"""Tests for the 4-stage hybrid skill matching pipeline.

Tests cover: _tokenize helper, _SkillBM25 index, _parse_json_array and
_parse_strict_response parsers, SkillMatchResult model, and SkillMatcher
pipeline (stages 1-4, fallbacks, skip logic).
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent33.llm.base import LLMResponse
from agent33.skills.definition import SkillDefinition, SkillStatus
from agent33.skills.matching import (
    SkillMatcher,
    SkillMatchResult,
    _SkillBM25,
    _tokenize,
)
from agent33.skills.registry import SkillRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_skill(
    name: str,
    description: str = "",
    tags: list[str] | None = None,
    instructions: str = "",
    status: SkillStatus = SkillStatus.ACTIVE,
) -> SkillDefinition:
    return SkillDefinition(
        name=name,
        description=description or f"A skill for {name}",
        tags=tags or [],
        instructions=instructions,
        status=status,
    )


def _llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="test-model",
        prompt_tokens=10,
        completion_tokens=5,
    )


def _make_registry(*skills: SkillDefinition) -> SkillRegistry:
    registry = SkillRegistry()
    for s in skills:
        registry.register(s)
    return registry


def _make_router(**kwargs: Any) -> MagicMock:
    router = MagicMock()
    router.complete = AsyncMock(**kwargs)
    return router


# ===================================================================
# _tokenize tests
# ===================================================================


class TestTokenize:
    """Test the _tokenize helper function."""

    def test_lowercases_and_splits_on_word_boundaries(self) -> None:
        tokens = _tokenize("Deploy Kubernetes Apps")
        assert tokens == ["deploy", "kubernetes", "apps"]

    def test_removes_stop_words(self) -> None:
        tokens = _tokenize("a skill for the deployment of apps")
        # "a", "for", "the", "of" are stop words
        assert "a" not in tokens
        assert "for" not in tokens
        assert "the" not in tokens
        assert "of" not in tokens
        assert "skill" in tokens
        assert "deployment" in tokens
        assert "apps" in tokens

    def test_handles_empty_string(self) -> None:
        assert _tokenize("") == []

    def test_handles_punctuation(self) -> None:
        tokens = _tokenize("hello-world, this is (great)!")
        # re.findall(r"[a-z0-9]+", ...) splits on hyphens/punctuation
        assert "hello" in tokens
        assert "world" in tokens
        assert "great" in tokens
        # stop words removed
        assert "this" not in tokens
        assert "is" not in tokens

    def test_preserves_numbers(self) -> None:
        tokens = _tokenize("Python 3 version 11")
        assert "python" in tokens
        assert "3" in tokens
        assert "11" in tokens


# ===================================================================
# _SkillBM25 tests
# ===================================================================


class TestSkillBM25:
    """Test the internal BM25 index for stage-1 retrieval."""

    def test_empty_index_returns_no_results(self) -> None:
        bm25 = _SkillBM25()
        bm25.index([])
        results = bm25.query("deploy kubernetes")
        assert results == []

    def test_query_on_unindexed_returns_empty(self) -> None:
        bm25 = _SkillBM25()
        # No index() called at all
        results = bm25.query("anything")
        assert results == []

    def test_indexing_and_querying_returns_relevant_results(self) -> None:
        bm25 = _SkillBM25()
        skills = [
            _make_skill("kubernetes-deploy", "Deploy apps to Kubernetes", ["devops", "k8s"]),
            _make_skill("data-analysis", "Analyze datasets with pandas", ["data", "python"]),
            _make_skill("web-scraping", "Scrape web pages", ["web", "scraping"]),
        ]
        bm25.index(skills)

        results = bm25.query("deploy kubernetes")
        assert len(results) > 0
        # kubernetes-deploy should be the top result
        assert results[0][0] == "kubernetes-deploy"
        # Score should be positive
        assert results[0][1] > 0

    def test_deprecated_skills_excluded_from_index(self) -> None:
        bm25 = _SkillBM25()
        skills = [
            _make_skill("active-skill", "Deploy apps", status=SkillStatus.ACTIVE),
            _make_skill("old-skill", "Deploy legacy apps", status=SkillStatus.DEPRECATED),
        ]
        bm25.index(skills)

        results = bm25.query("deploy apps")
        result_names = [name for name, _score in results]
        assert "active-skill" in result_names
        assert "old-skill" not in result_names

    def test_multiple_query_terms_combine_scores(self) -> None:
        bm25 = _SkillBM25()
        skills = [
            _make_skill("kubernetes-deploy", "Deploy apps to Kubernetes", ["devops", "k8s"]),
            _make_skill("kubernetes-monitor", "Monitor Kubernetes clusters", ["devops", "k8s"]),
            _make_skill("data-analysis", "Analyze datasets with pandas", ["data"]),
        ]
        bm25.index(skills)

        # Query "deploy kubernetes" should rank kubernetes-deploy higher than
        # kubernetes-monitor because it matches both "deploy" and "kubernetes"
        # while kubernetes-monitor only matches "kubernetes".
        results = bm25.query("deploy kubernetes")
        assert len(results) >= 2
        names = [name for name, _ in results]
        assert names[0] == "kubernetes-deploy"

    def test_top_k_limit_is_respected(self) -> None:
        bm25 = _SkillBM25()
        skills = [_make_skill(f"skill-{i}", f"deploy variant {i}", ["deploy"]) for i in range(10)]
        bm25.index(skills)

        results = bm25.query("deploy", top_k=3)
        assert len(results) <= 3

    def test_experimental_skills_are_indexed(self) -> None:
        bm25 = _SkillBM25()
        skills = [
            _make_skill("experimental-tool", "New tool", status=SkillStatus.EXPERIMENTAL),
        ]
        bm25.index(skills)
        results = bm25.query("new tool")
        assert len(results) == 1
        assert results[0][0] == "experimental-tool"


# ===================================================================
# _parse_json_array tests
# ===================================================================


class TestParseJsonArray:
    """Test LLM output parsing for JSON arrays."""

    def test_direct_json_array(self) -> None:
        result = SkillMatcher._parse_json_array('["skill-a", "skill-b"]')
        assert result == ["skill-a", "skill-b"]

    def test_array_in_markdown_code_fence(self) -> None:
        text = 'Here are the results:\n```json\n["skill-a", "skill-b"]\n```'
        result = SkillMatcher._parse_json_array(text)
        assert result == ["skill-a", "skill-b"]

    def test_array_embedded_in_text(self) -> None:
        text = 'The relevant skills are: ["alpha", "beta"] as listed above.'
        result = SkillMatcher._parse_json_array(text)
        assert result == ["alpha", "beta"]

    def test_unparseable_returns_empty(self) -> None:
        result = SkillMatcher._parse_json_array("I cannot decide which skills to keep.")
        assert result == []

    def test_empty_string_returns_empty(self) -> None:
        result = SkillMatcher._parse_json_array("")
        assert result == []

    def test_empty_array_returns_empty_list(self) -> None:
        result = SkillMatcher._parse_json_array("[]")
        assert result == []

    def test_numeric_elements_coerced_to_strings(self) -> None:
        result = SkillMatcher._parse_json_array("[1, 2, 3]")
        assert result == ["1", "2", "3"]

    def test_code_fence_without_json_label(self) -> None:
        text = '```\n["foo", "bar"]\n```'
        result = SkillMatcher._parse_json_array(text)
        assert result == ["foo", "bar"]


# ===================================================================
# _parse_strict_response tests
# ===================================================================


class TestParseStrictResponse:
    """Test LLM output parsing for strict keep/reject JSON."""

    def test_direct_json_object(self) -> None:
        text = '{"keep": ["skill-a"], "reject": [{"name": "skill-b", "reason": "leaks answer"}]}'
        result = SkillMatcher._parse_strict_response(text)
        assert result["keep"] == ["skill-a"]
        assert len(result["reject"]) == 1
        assert result["reject"][0]["name"] == "skill-b"

    def test_object_in_code_fence(self) -> None:
        text = '```json\n{"keep": ["alpha"], "reject": []}\n```'
        result = SkillMatcher._parse_strict_response(text)
        assert result["keep"] == ["alpha"]
        assert result["reject"] == []

    def test_missing_keep_key_returns_empty_dict(self) -> None:
        text = '{"reject": [{"name": "x", "reason": "bad"}]}'
        result = SkillMatcher._parse_strict_response(text)
        assert result == {}

    def test_unparseable_returns_empty_dict(self) -> None:
        result = SkillMatcher._parse_strict_response("I think all skills are fine.")
        assert result == {}

    def test_object_embedded_in_text(self) -> None:
        text = (
            "After analysis, here is my assessment:\n"
            '{"keep": ["deploy"], "reject": [{"name": "test", "reason": "irrelevant"}]}\n'
            "That's my recommendation."
        )
        result = SkillMatcher._parse_strict_response(text)
        assert result["keep"] == ["deploy"]
        assert result["reject"][0]["name"] == "test"

    def test_empty_string_returns_empty_dict(self) -> None:
        result = SkillMatcher._parse_strict_response("")
        assert result == {}

    def test_keep_only_object_valid(self) -> None:
        text = '{"keep": ["a", "b"]}'
        result = SkillMatcher._parse_strict_response(text)
        assert result["keep"] == ["a", "b"]


# ===================================================================
# SkillMatchResult tests
# ===================================================================


class TestSkillMatchResult:
    """Test SkillMatchResult data class."""

    def test_count_reflects_skills_length(self) -> None:
        skills = [_make_skill("a"), _make_skill("b")]
        result = SkillMatchResult(skills=skills, stage1_count=5, stage2_count=3, stage4_count=2)
        assert result.count == 2

    def test_default_rejected_is_empty(self) -> None:
        result = SkillMatchResult(skills=[])
        assert result.rejected == []

    def test_rejected_populated(self) -> None:
        rejected = [{"name": "bad", "reason": "leaks answer"}]
        result = SkillMatchResult(skills=[], rejected=rejected)
        assert result.rejected == rejected
        assert result.rejected[0]["reason"] == "leaks answer"

    def test_stage_counts_stored(self) -> None:
        result = SkillMatchResult(skills=[], stage1_count=10, stage2_count=6, stage4_count=3)
        assert result.stage1_count == 10
        assert result.stage2_count == 6
        assert result.stage4_count == 3


# ===================================================================
# SkillMatcher tests
# ===================================================================


class TestSkillMatcher:
    """Test the full 4-stage skill matching pipeline."""

    @pytest.mark.asyncio
    async def test_no_skills_registered_returns_empty(self) -> None:
        registry = _make_registry()
        router = _make_router()
        matcher = SkillMatcher(registry, router)

        result = await matcher.match("deploy kubernetes app")
        assert result.count == 0
        assert result.stage1_count == 0
        assert result.skills == []
        # LLM should not have been called
        router.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_matching_skills_returns_empty(self) -> None:
        """Skills exist but none match the query."""
        registry = _make_registry(
            _make_skill("cooking-recipes", "How to cook Italian food", ["cooking"]),
        )
        router = _make_router()
        matcher = SkillMatcher(registry, router)

        result = await matcher.match("deploy kubernetes cluster")
        assert result.count == 0
        assert result.stage1_count == 0

    @pytest.mark.asyncio
    async def test_single_relevant_skill_skips_llm(self) -> None:
        """When stage 1 returns <= skip_llm_below candidates, LLM is skipped."""
        registry = _make_registry(
            _make_skill("kubernetes-deploy", "Deploy apps to Kubernetes", ["devops", "k8s"]),
        )
        router = _make_router()
        matcher = SkillMatcher(registry, router, skip_llm_below=3)

        result = await matcher.match("deploy kubernetes")
        assert result.count == 1
        assert result.skills[0].name == "kubernetes-deploy"
        assert result.stage1_count == 1
        # stage2 and stage4 counts equal stage1 when LLM is skipped
        assert result.stage2_count == 1
        assert result.stage4_count == 1
        # LLM should not have been called
        router.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_llm_below_threshold_exact(self) -> None:
        """Exactly skip_llm_below candidates still skips LLM."""
        skills = [
            _make_skill("deploy-v1", "Deploy version 1", ["deploy"]),
            _make_skill("deploy-v2", "Deploy version 2", ["deploy"]),
            _make_skill("deploy-v3", "Deploy version 3", ["deploy"]),
        ]
        registry = _make_registry(*skills)
        router = _make_router()
        matcher = SkillMatcher(registry, router, skip_llm_below=3)

        result = await matcher.match("deploy")
        assert result.count == 3
        router.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_above_threshold_calls_llm(self) -> None:
        """When candidates > skip_llm_below, LLM stages are invoked."""
        skills = [
            _make_skill("deploy-a", "Deploy alpha", ["deploy"]),
            _make_skill("deploy-b", "Deploy beta", ["deploy"]),
            _make_skill("deploy-c", "Deploy gamma", ["deploy"]),
            _make_skill("deploy-d", "Deploy delta", ["deploy"]),
        ]
        registry = _make_registry(*skills)
        # Stage 2 returns two, stage 4 keeps one
        router = _make_router(
            side_effect=[
                _llm_response('["deploy-a", "deploy-b"]'),
                _llm_response(
                    '{"keep": ["deploy-a"], "reject":'
                    ' [{"name": "deploy-b", "reason": "irrelevant"}]}'
                ),
            ]
        )
        matcher = SkillMatcher(registry, router, skip_llm_below=3)

        result = await matcher.match("deploy")
        assert result.stage1_count == 4
        assert result.stage2_count == 2
        assert result.stage4_count == 1
        assert result.count == 1
        assert result.skills[0].name == "deploy-a"
        assert len(result.rejected) == 1
        assert result.rejected[0]["name"] == "deploy-b"
        # Two LLM calls: stage 2 and stage 4
        assert router.complete.call_count == 2

    @pytest.mark.asyncio
    async def test_stage2_lenient_filter(self) -> None:
        """Stage 2 filters candidates based on LLM response."""
        skills = [
            _make_skill("kubernetes-deploy", "Deploy apps to K8s", ["devops", "k8s"]),
            _make_skill("kubernetes-monitor", "Monitor K8s clusters", ["devops", "k8s"]),
            _make_skill("kubernetes-scale", "Scale K8s workloads", ["devops", "k8s"]),
            _make_skill("kubernetes-debug", "Debug K8s pods", ["devops", "k8s"]),
        ]
        registry = _make_registry(*skills)
        # Stage 2: keep deploy and scale
        # Stage 4: keep both
        router = _make_router(
            side_effect=[
                _llm_response('["kubernetes-deploy", "kubernetes-scale"]'),
                _llm_response('{"keep": ["kubernetes-deploy", "kubernetes-scale"], "reject": []}'),
            ]
        )
        matcher = SkillMatcher(registry, router, skip_llm_below=3)

        result = await matcher.match("deploy kubernetes")
        assert result.stage2_count == 2
        assert {s.name for s in result.skills} == {"kubernetes-deploy", "kubernetes-scale"}

    @pytest.mark.asyncio
    async def test_stage2_fallback_on_llm_failure(self) -> None:
        """If stage 2 LLM call raises, all candidates are kept."""
        skills = [
            _make_skill("deploy-a", "Deploy alpha version", ["deploy"]),
            _make_skill("deploy-b", "Deploy beta version", ["deploy"]),
            _make_skill("deploy-c", "Deploy gamma version", ["deploy"]),
            _make_skill("deploy-d", "Deploy delta version", ["deploy"]),
        ]
        registry = _make_registry(*skills)
        # Stage 2 fails, stage 4 succeeds
        router = _make_router(
            side_effect=[
                RuntimeError("LLM service unavailable"),
                _llm_response(
                    '{"keep": ["deploy-a", "deploy-b", "deploy-c", "deploy-d"], "reject": []}'
                ),
            ]
        )
        matcher = SkillMatcher(registry, router, skip_llm_below=3)

        result = await matcher.match("deploy")
        # All 4 should survive stage 2 fallback
        assert result.stage2_count == 4
        assert result.count == 4

    @pytest.mark.asyncio
    async def test_stage2_fallback_on_empty_response(self) -> None:
        """If stage 2 LLM returns empty array, all candidates are kept."""
        skills = [
            _make_skill("deploy-a", "Deploy alpha version", ["deploy"]),
            _make_skill("deploy-b", "Deploy beta version", ["deploy"]),
            _make_skill("deploy-c", "Deploy gamma version", ["deploy"]),
            _make_skill("deploy-d", "Deploy delta version", ["deploy"]),
        ]
        registry = _make_registry(*skills)
        # Stage 2 returns empty array -> fallback keeps all
        # Stage 4 keeps all
        router = _make_router(
            side_effect=[
                _llm_response("[]"),
                _llm_response(
                    '{"keep": ["deploy-a", "deploy-b", "deploy-c", "deploy-d"], "reject": []}'
                ),
            ]
        )
        matcher = SkillMatcher(registry, router, skip_llm_below=3)

        result = await matcher.match("deploy")
        assert result.stage2_count == 4

    @pytest.mark.asyncio
    async def test_stage4_strict_filter(self) -> None:
        """Stage 4 removes skills and populates rejected list."""
        # All skills must contain "deploy" so BM25 stage 1 retrieves them all
        skills = [
            _make_skill(
                "kubernetes-deploy",
                "Deploy apps to kubernetes clusters",
                ["devops", "deploy"],
                instructions="Use kubectl apply -f deployment.yaml",
            ),
            _make_skill(
                "answer-leaker",
                "Deploy solutions with leaked answers",
                ["devops", "deploy"],
                instructions="The answer is 42, just print it",
            ),
            _make_skill(
                "helpful-guide",
                "Deploy best practices guide",
                ["devops", "deploy"],
                instructions="Follow 12-factor app methodology",
            ),
            _make_skill(
                "irrelevant-cooking",
                "Deploy cooking recipes automatically",
                ["devops", "deploy"],
                instructions="Make pasta while deploying",
            ),
        ]
        registry = _make_registry(*skills)
        # Stage 2: keep all four
        # Stage 4: keep deploy and guide, reject leaker and cooking
        router = _make_router(
            side_effect=[
                _llm_response(
                    '["kubernetes-deploy", "answer-leaker", "helpful-guide", "irrelevant-cooking"]'
                ),
                _llm_response(
                    '{"keep": ["kubernetes-deploy", "helpful-guide"], '
                    '"reject": ['
                    '{"name": "answer-leaker", "reason": "leaks answer"}, '
                    '{"name": "irrelevant-cooking", "reason": "not relevant"}'
                    "]}"
                ),
            ]
        )
        matcher = SkillMatcher(registry, router, skip_llm_below=3)

        result = await matcher.match("deploy")
        assert result.stage4_count == 2
        assert {s.name for s in result.skills} == {"kubernetes-deploy", "helpful-guide"}
        assert len(result.rejected) == 2
        reject_names = {r["name"] for r in result.rejected}
        assert "answer-leaker" in reject_names
        assert "irrelevant-cooking" in reject_names

    @pytest.mark.asyncio
    async def test_stage4_answer_leakage_reason_captured(self) -> None:
        """Rejection reasons (including leakage) are captured in result."""
        skills = [
            _make_skill("leaker", "Solution provider", ["test"], instructions="answer=42"),
            _make_skill("helper", "Helpful guide", ["test"], instructions="general guidance"),
            _make_skill("filler-a", "Filler skill A", ["test"]),
            _make_skill("filler-b", "Filler skill B", ["test"]),
        ]
        registry = _make_registry(*skills)
        router = _make_router(
            side_effect=[
                _llm_response('["leaker", "helper", "filler-a", "filler-b"]'),
                _llm_response(
                    '{"keep": ["helper"], "reject": ['
                    '{"name": "leaker", "reason": "leaks the expected answer"},'
                    '{"name": "filler-a", "reason": "irrelevant"},'
                    '{"name": "filler-b", "reason": "irrelevant"}'
                    "]}"
                ),
            ]
        )
        matcher = SkillMatcher(registry, router, skip_llm_below=3)

        result = await matcher.match("test problem")
        leaker_reject = next(r for r in result.rejected if r["name"] == "leaker")
        assert "leaks" in leaker_reject["reason"]

    @pytest.mark.asyncio
    async def test_stage4_fallback_on_llm_failure(self) -> None:
        """If stage 4 LLM call raises, all stage-2 candidates are kept."""
        skills = [
            _make_skill("deploy-a", "Deploy alpha version", ["deploy"]),
            _make_skill("deploy-b", "Deploy beta version", ["deploy"]),
            _make_skill("deploy-c", "Deploy gamma version", ["deploy"]),
            _make_skill("deploy-d", "Deploy delta version", ["deploy"]),
        ]
        registry = _make_registry(*skills)
        # Stage 2 succeeds, stage 4 fails
        router = _make_router(
            side_effect=[
                _llm_response('["deploy-a", "deploy-b"]'),
                RuntimeError("LLM timeout"),
            ]
        )
        matcher = SkillMatcher(registry, router, skip_llm_below=3)

        result = await matcher.match("deploy")
        assert result.stage2_count == 2
        # Stage 4 failure means all stage-2 candidates kept
        assert result.count == 2
        assert result.rejected == []

    @pytest.mark.asyncio
    async def test_stage4_empty_keep_keeps_all(self) -> None:
        """If stage 4 returns empty keep list, all candidates are kept as fallback."""
        skills = [
            _make_skill("deploy-a", "Deploy alpha version", ["deploy"]),
            _make_skill("deploy-b", "Deploy beta version", ["deploy"]),
            _make_skill("deploy-c", "Deploy gamma version", ["deploy"]),
            _make_skill("deploy-d", "Deploy delta version", ["deploy"]),
        ]
        registry = _make_registry(*skills)
        router = _make_router(
            side_effect=[
                _llm_response('["deploy-a", "deploy-b"]'),
                _llm_response('{"keep": [], "reject": []}'),
            ]
        )
        matcher = SkillMatcher(registry, router, skip_llm_below=3)

        result = await matcher.match("deploy")
        # Empty keep -> safety fallback keeps all stage-2 survivors
        assert result.count == 2
        assert result.rejected == []

    @pytest.mark.asyncio
    async def test_stage2_filters_to_empty_returns_early(self) -> None:
        """If stage 2 filters all candidates, return empty without stage 4."""
        skills = [
            _make_skill("deploy-a", "Deploy alpha version", ["deploy"]),
            _make_skill("deploy-b", "Deploy beta version", ["deploy"]),
            _make_skill("deploy-c", "Deploy gamma version", ["deploy"]),
            _make_skill("deploy-d", "Deploy delta version", ["deploy"]),
        ]
        registry = _make_registry(*skills)
        # Stage 2 returns names that do not match any candidate
        router = _make_router(return_value=_llm_response('["nonexistent-skill"]'))
        matcher = SkillMatcher(registry, router, skip_llm_below=3)

        result = await matcher.match("deploy")
        assert result.stage2_count == 0
        assert result.count == 0
        # Only one LLM call (stage 2); stage 4 never reached
        assert router.complete.call_count == 1

    @pytest.mark.asyncio
    async def test_reindex_called_automatically_on_first_match(self) -> None:
        """The BM25 index is built lazily on the first match call."""
        skill = _make_skill("auto-index", "Auto indexed skill", ["auto"])
        registry = _make_registry(skill)
        router = _make_router()
        matcher = SkillMatcher(registry, router)

        # Before match, _indexed is False
        assert matcher._indexed is False

        result = await matcher.match("auto indexed")
        assert result.count >= 1
        assert matcher._indexed is True

    @pytest.mark.asyncio
    async def test_reindex_explicit_updates_index(self) -> None:
        """Calling reindex() explicitly rebuilds the index with new skills."""
        skill_a = _make_skill("original", "Original skill", ["original"])
        registry = _make_registry(skill_a)
        router = _make_router()
        matcher = SkillMatcher(registry, router)

        result = await matcher.match("original")
        assert result.count == 1

        # Add a new skill after initial index
        registry.register(_make_skill("added-later", "Added later skill", ["added"]))
        # Without reindex, the new skill won't be found
        result_before = await matcher.match("added later")
        assert all(s.name != "added-later" for s in result_before.skills)

        # After explicit reindex, new skill is found
        matcher.reindex()
        result_after = await matcher.match("added later")
        found = any(s.name == "added-later" for s in result_after.skills)
        assert found is True

    @pytest.mark.asyncio
    async def test_full_pipeline_end_to_end(self) -> None:
        """Exercise the full pipeline with multiple skills filtered at each stage."""
        skills = [
            _make_skill(
                "data-analysis",
                "Analyze datasets with pandas",
                ["data", "python"],
                instructions="Use pandas DataFrame for analysis",
            ),
            _make_skill(
                "data-viz",
                "Visualize data with matplotlib",
                ["data", "python"],
                instructions="Use matplotlib.pyplot for charts",
            ),
            _make_skill(
                "data-cleaning",
                "Clean and preprocess data",
                ["data", "python"],
                instructions="Handle missing values and outliers",
            ),
            _make_skill(
                "web-scraping",
                "Scrape websites for data",
                ["web", "scraping"],
                instructions="Use requests and BeautifulSoup",
            ),
            _make_skill(
                "kubernetes-deploy",
                "Deploy to K8s",
                ["devops"],
                instructions="kubectl apply workflow",
            ),
            _make_skill(
                "data-export",
                "Export data to various formats",
                ["data", "export"],
                instructions="The expected output is exactly [1,2,3,4,5]",
            ),
        ]
        registry = _make_registry(*skills)

        # Stage 2: keep data-related skills (drop k8s, web)
        # Stage 4: keep analysis and viz, reject cleaning (irrelevant for task)
        #          and export (leaks answer)
        router = _make_router(
            side_effect=[
                _llm_response('["data-analysis", "data-viz", "data-cleaning", "data-export"]'),
                _llm_response(
                    '{"keep": ["data-analysis", "data-viz"], "reject": ['
                    '{"name": "data-cleaning", "reason": "not needed for visualization task"}, '
                    '{"name": "data-export", "reason": "leaks expected output"}'
                    "]}"
                ),
            ]
        )
        matcher = SkillMatcher(registry, router, skip_llm_below=3, top_k=10)

        result = await matcher.match("analyze data and create visualization")

        # Stage 1: should find data-related skills (at least 4)
        assert result.stage1_count >= 4
        # Stage 2: LLM kept 4
        assert result.stage2_count == 4
        # Stage 4: LLM kept 2
        assert result.stage4_count == 2
        assert result.count == 2
        assert {s.name for s in result.skills} == {"data-analysis", "data-viz"}
        # Rejections captured
        assert len(result.rejected) == 2
        reject_map = {r["name"]: r["reason"] for r in result.rejected}
        assert "data-export" in reject_map
        assert "leaks" in reject_map["data-export"]

    @pytest.mark.asyncio
    async def test_custom_model_and_temperature(self) -> None:
        """Custom model and temperature are forwarded to LLM calls."""
        skills = [
            _make_skill("skill-a", "Skill alpha", ["test"]),
            _make_skill("skill-b", "Skill beta", ["test"]),
            _make_skill("skill-c", "Skill gamma", ["test"]),
            _make_skill("skill-d", "Skill delta", ["test"]),
        ]
        registry = _make_registry(*skills)
        router = _make_router(
            side_effect=[
                _llm_response('["skill-a"]'),
                _llm_response('{"keep": ["skill-a"], "reject": []}'),
            ]
        )
        matcher = SkillMatcher(registry, router, model="gpt-4o", temperature=0.3, skip_llm_below=3)

        await matcher.match("test skill")

        # Verify model and temperature were passed to the router
        for call in router.complete.call_args_list:
            assert call.kwargs["model"] == "gpt-4o"
            assert call.kwargs["temperature"] == 0.3

    @pytest.mark.asyncio
    async def test_stage2_sends_correct_prompt_content(self) -> None:
        """Verify that stage 2 prompt includes skill names and descriptions."""
        # All skills share "deploy" keyword so BM25 returns all 4
        skills = [
            _make_skill("deploy-alpha", "Deploy alpha service", ["deploy"]),
            _make_skill("deploy-beta", "Deploy beta service", ["deploy"]),
            _make_skill("deploy-gamma", "Deploy gamma service", ["deploy"]),
            _make_skill("deploy-delta", "Deploy delta service", ["deploy"]),
        ]
        registry = _make_registry(*skills)
        router = _make_router(
            side_effect=[
                _llm_response('["deploy-alpha"]'),
                _llm_response('{"keep": ["deploy-alpha"], "reject": []}'),
            ]
        )
        matcher = SkillMatcher(registry, router, skip_llm_below=3)

        await matcher.match("deploy service")

        # Inspect the first LLM call (stage 2)
        stage2_call = router.complete.call_args_list[0]
        messages = stage2_call.args[0]
        # System message should be the lenient filter prompt
        assert "LENIENT" in messages[0].content
        # User message should include the query and skill names
        user_msg = messages[1].content
        assert "deploy service" in user_msg.lower()
        assert "deploy-alpha" in user_msg
        assert "deploy-beta" in user_msg

    @pytest.mark.asyncio
    async def test_deprecated_skills_not_matched(self) -> None:
        """Deprecated skills are excluded by BM25 and never reach LLM stages."""
        skills = [
            _make_skill("active-deploy", "Deploy apps", ["deploy"]),
            _make_skill("old-deploy", "Legacy deploy", ["deploy"], status=SkillStatus.DEPRECATED),
        ]
        registry = _make_registry(*skills)
        router = _make_router()
        matcher = SkillMatcher(registry, router)

        result = await matcher.match("deploy apps")
        result_names = [s.name for s in result.skills]
        assert "active-deploy" in result_names
        assert "old-deploy" not in result_names

    @pytest.mark.asyncio
    async def test_stage2_unparseable_response_keeps_all(self) -> None:
        """If stage 2 LLM returns unparseable text, all candidates are kept."""
        skills = [
            _make_skill("skill-a", "Skill alpha version", ["test"]),
            _make_skill("skill-b", "Skill beta version", ["test"]),
            _make_skill("skill-c", "Skill gamma version", ["test"]),
            _make_skill("skill-d", "Skill delta version", ["test"]),
        ]
        registry = _make_registry(*skills)
        router = _make_router(
            side_effect=[
                _llm_response("I'm not sure which skills to keep, let me think..."),
                _llm_response(
                    '{"keep": ["skill-a", "skill-b", "skill-c", "skill-d"], "reject": []}'
                ),
            ]
        )
        matcher = SkillMatcher(registry, router, skip_llm_below=3)

        result = await matcher.match("test skill")
        # Unparseable -> empty list -> fallback keeps all
        assert result.stage2_count == 4
