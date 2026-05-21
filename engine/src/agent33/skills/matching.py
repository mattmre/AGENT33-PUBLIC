"""4-stage hybrid skill matching with LLM-based refinement.

Implements a graduated skill matching pipeline inspired by SkillsBench
(benchflow-ai/skillsbench) to prevent irrelevant or answer-leaking
skills from being injected into agent prompts.

Stages
------
1. **Text retrieval** — BM25-scored keyword match across skill metadata
   (name, description, tags).  Returns top-K candidates.
2. **LLM lenient filter** — An LLM decides which candidates *could* be
   useful.  Intentionally permissive to avoid false negatives.
3. **Full content loading** — Full instructions are loaded for surviving
   candidates (expensive, so done only after filtering).
4. **LLM strict filter** — An LLM removes skills that leak answers or
   are truly irrelevant after seeing full content.
"""

from __future__ import annotations

import json
import logging
import math
import re
from typing import TYPE_CHECKING, Any

from agent33.llm.base import ChatMessage
from agent33.skills.definition import SkillStatus

if TYPE_CHECKING:
    from agent33.llm.router import ModelRouter
    from agent33.skills.definition import SkillDefinition
    from agent33.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# BM25 scoring (lightweight, in-memory, skill-specific)
# ---------------------------------------------------------------------------

_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "shall",
        "should",
        "may",
        "might",
        "can",
        "could",
        "of",
        "in",
        "to",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "and",
        "or",
        "but",
        "not",
        "no",
        "nor",
        "so",
        "yet",
        "both",
        "either",
        "neither",
        "each",
        "every",
        "all",
        "any",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
    }
)


def _tokenize(text: str) -> list[str]:
    """Lowercase split, strip punctuation, remove stop words."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w for w in words if w not in _STOP_WORDS]


class _SkillBM25:
    """Minimal BM25 index over skill metadata for stage-1 retrieval."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b
        self._docs: list[tuple[str, list[str]]] = []  # (skill_name, tokens)
        self._avg_dl: float = 0.0
        self._df: dict[str, int] = {}
        self._n: int = 0

    def index(self, skills: list[SkillDefinition]) -> None:
        """Build the index from a list of skill definitions."""
        self._docs.clear()
        self._df.clear()

        for skill in skills:
            if skill.status == SkillStatus.DEPRECATED:
                continue
            text = f"{skill.name} {skill.description} {' '.join(skill.tags)}"
            tokens = _tokenize(text)
            self._docs.append((skill.name, tokens))

        self._n = len(self._docs)
        if self._n == 0:
            return

        total_len = 0
        # Compute document frequencies
        for _name, tokens in self._docs:
            total_len += len(tokens)
            seen: set[str] = set()
            for t in tokens:
                if t not in seen:
                    self._df[t] = self._df.get(t, 0) + 1
                    seen.add(t)
        self._avg_dl = total_len / self._n if self._n else 1.0

    def query(self, text: str, top_k: int = 20) -> list[tuple[str, float]]:
        """Return (skill_name, score) pairs ranked by BM25 relevance."""
        q_tokens = _tokenize(text)
        if not q_tokens or not self._docs:
            return []

        scores: list[tuple[str, float]] = []
        for name, doc_tokens in self._docs:
            score = 0.0
            dl = len(doc_tokens)
            # Build term frequency map for this document
            tf_map: dict[str, int] = {}
            for t in doc_tokens:
                tf_map[t] = tf_map.get(t, 0) + 1

            for qt in q_tokens:
                tf = tf_map.get(qt, 0)
                if tf == 0:
                    continue
                df = self._df.get(qt, 0)
                # IDF with smoothing
                idf = math.log((self._n - df + 0.5) / (df + 0.5) + 1.0)
                # BM25 term score
                numerator = tf * (self._k1 + 1)
                denominator = tf + self._k1 * (1 - self._b + self._b * dl / self._avg_dl)
                score += idf * numerator / denominator

            if score > 0:
                scores.append((name, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


# ---------------------------------------------------------------------------
# LLM prompt templates
# ---------------------------------------------------------------------------

_LENIENT_FILTER_SYSTEM = """\
You are a skill relevance classifier. Given a task description and a list \
of available skills (with short descriptions), determine which skills \
COULD be useful for completing the task.

Be LENIENT — include skills that are even tangentially related. Only \
exclude skills that are clearly irrelevant (e.g., a cooking skill for \
a math problem).

Return a JSON array of skill names to KEEP. Example: ["skill-a", "skill-b"]
Return ONLY the JSON array, no other text."""

_STRICT_FILTER_SYSTEM = """\
You are a skill safety and relevance auditor. Given a task description and \
full skill instructions, determine which skills should be injected into \
the agent's prompt.

REJECT a skill if:
1. It is NOT relevant to the task
2. It LEAKS the answer (contains the exact solution, test assertions, or \
expected output for the specific task)
3. It would CONFUSE the agent (contradicts the task or provides wrong guidance)

KEEP a skill if it provides useful domain knowledge, tool configurations, \
or methodology guidance WITHOUT giving away the answer.

Return a JSON object with this structure:
{
  "keep": ["skill-a"],
  "reject": [{"name": "skill-b", "reason": "leaks answer"}]
}
Return ONLY the JSON object, no other text."""

# ---------------------------------------------------------------------------
# SkillMatcher
# ---------------------------------------------------------------------------


class SkillMatchResult:
    """Result of the 4-stage skill matching pipeline."""

    __slots__ = ("skills", "stage1_count", "stage2_count", "stage4_count", "rejected")

    def __init__(
        self,
        skills: list[SkillDefinition],
        stage1_count: int = 0,
        stage2_count: int = 0,
        stage4_count: int = 0,
        rejected: list[dict[str, str]] | None = None,
    ) -> None:
        self.skills = skills
        self.stage1_count = stage1_count
        self.stage2_count = stage2_count
        self.stage4_count = stage4_count
        self.rejected = rejected or []

    @property
    def count(self) -> int:
        return len(self.skills)


class SkillMatcher:
    """4-stage hybrid skill matching pipeline.

    Parameters
    ----------
    registry:
        The skill registry to search.
    router:
        Model router for LLM-based filtering stages.
    model:
        Model name to use for LLM calls.
    top_k:
        Number of candidates to retrieve in stage 1.
    temperature:
        LLM sampling temperature (lower = more deterministic).
    skip_llm_below:
        If stage 1 returns this many or fewer candidates, skip LLM
        filtering (all candidates are relevant enough).
    """

    def __init__(
        self,
        registry: SkillRegistry,
        router: ModelRouter,
        model: str = "llama3.2",
        top_k: int = 20,
        temperature: float = 0.1,
        skip_llm_below: int = 3,
    ) -> None:
        self._registry = registry
        self._router = router
        self._model = model
        self._top_k = top_k
        self._temperature = temperature
        self._skip_llm_below = skip_llm_below
        self._bm25 = _SkillBM25()
        self._indexed = False

    def reindex(self) -> None:
        """Rebuild the BM25 index from the current registry contents."""
        self._bm25.index(self._registry.list_all())
        self._indexed = True

    async def match(self, query: str) -> SkillMatchResult:
        """Run the full 4-stage matching pipeline.

        Parameters
        ----------
        query:
            The task description or user request to match skills against.

        Returns
        -------
        SkillMatchResult
            Contains matched skills, per-stage counts, and rejection details.
        """
        if not self._indexed:
            self.reindex()

        # Stage 1: BM25 text retrieval
        candidates = self._stage1_retrieve(query)
        stage1_count = len(candidates)

        if not candidates:
            return SkillMatchResult(skills=[], stage1_count=0)

        # Short-circuit: if very few candidates, skip LLM filtering
        if len(candidates) <= self._skip_llm_below:
            return SkillMatchResult(
                skills=candidates,
                stage1_count=stage1_count,
                stage2_count=len(candidates),
                stage4_count=len(candidates),
            )

        # Stage 2: LLM lenient filter
        filtered = await self._stage2_lenient_filter(query, candidates)
        stage2_count = len(filtered)

        if not filtered:
            return SkillMatchResult(
                skills=[],
                stage1_count=stage1_count,
                stage2_count=0,
            )

        # Stage 3: Full content loading (implicit — we already have definitions,
        # but now we'll pass full instructions in stage 4)

        # Stage 4: LLM strict filter
        final, rejected = await self._stage4_strict_filter(query, filtered)

        return SkillMatchResult(
            skills=final,
            stage1_count=stage1_count,
            stage2_count=stage2_count,
            stage4_count=len(final),
            rejected=rejected,
        )

    # ------------------------------------------------------------------
    # Stage 1: BM25 text retrieval
    # ------------------------------------------------------------------

    def _stage1_retrieve(self, query: str) -> list[SkillDefinition]:
        """Retrieve initial candidates via BM25 keyword match."""
        results = self._bm25.query(query, top_k=self._top_k)
        candidates: list[SkillDefinition] = []
        for name, _score in results:
            skill = self._registry.get(name)
            if skill is not None:
                candidates.append(skill)
        return candidates

    # ------------------------------------------------------------------
    # Stage 2: LLM lenient filter
    # ------------------------------------------------------------------

    async def _stage2_lenient_filter(
        self,
        query: str,
        candidates: list[SkillDefinition],
    ) -> list[SkillDefinition]:
        """Use LLM to leniently filter candidates by relevance."""
        skill_list = "\n".join(f"- {s.name}: {s.description}" for s in candidates)
        user_msg = (
            f"Task: {query}\n\n"
            f"Available skills:\n{skill_list}\n\n"
            "Which skills should be KEPT? Return a JSON array of skill names."
        )

        messages = [
            ChatMessage(role="system", content=_LENIENT_FILTER_SYSTEM),
            ChatMessage(role="user", content=user_msg),
        ]

        try:
            response = await self._router.complete(
                messages,
                model=self._model,
                temperature=self._temperature,
                max_tokens=500,
            )
            keep_names = self._parse_json_array(response.content)
        except Exception:
            logger.warning(
                "Stage 2 LLM filter failed, keeping all candidates",
                exc_info=True,
            )
            return candidates

        if not keep_names:
            # LLM returned empty or unparseable — keep all as fallback
            return candidates

        keep_set = set(keep_names)
        return [s for s in candidates if s.name in keep_set]

    # ------------------------------------------------------------------
    # Stage 4: LLM strict filter
    # ------------------------------------------------------------------

    async def _stage4_strict_filter(
        self,
        query: str,
        candidates: list[SkillDefinition],
    ) -> tuple[list[SkillDefinition], list[dict[str, str]]]:
        """Use LLM to strictly filter and detect answer leakage."""
        skill_blocks: list[str] = []
        for s in candidates:
            block = f"## {s.name}\n{s.instructions or s.description}"
            skill_blocks.append(block)

        user_msg = (
            f"Task: {query}\n\n"
            f"Skills with full instructions:\n\n"
            + "\n\n".join(skill_blocks)
            + "\n\nWhich skills should be KEPT and which REJECTED? "
            "Return a JSON object with 'keep' and 'reject' arrays."
        )

        messages = [
            ChatMessage(role="system", content=_STRICT_FILTER_SYSTEM),
            ChatMessage(role="user", content=user_msg),
        ]

        try:
            response = await self._router.complete(
                messages,
                model=self._model,
                temperature=self._temperature,
                max_tokens=1000,
            )
            result = self._parse_strict_response(response.content)
        except Exception:
            logger.warning(
                "Stage 4 LLM filter failed, keeping all candidates",
                exc_info=True,
            )
            return candidates, []

        keep_names = set(result.get("keep", []))
        rejected = result.get("reject", [])

        if not keep_names:
            # LLM returned empty keep list — keep all as safety fallback
            return candidates, []

        final = [s for s in candidates if s.name in keep_names]
        return final, rejected

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json_array(text: str) -> list[str]:
        """Extract a JSON array of strings from LLM output."""
        text = text.strip()
        # Try direct parse
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except (json.JSONDecodeError, TypeError) as e:
            logger.debug("Failed to parse LLM JSON response: %s", e)

        # Try extracting from markdown code fence
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(1))
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
            except (json.JSONDecodeError, TypeError) as e:
                logger.debug("Failed to parse LLM JSON response: %s", e)

        # Try finding array pattern in text
        match = re.search(r"\[.*?\]", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
            except (json.JSONDecodeError, TypeError) as e:
                logger.debug("Failed to parse LLM JSON response: %s", e)

        return []

    @staticmethod
    def _parse_strict_response(text: str) -> dict[str, Any]:
        """Extract keep/reject JSON from LLM output."""
        text = text.strip()

        # Try direct parse
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "keep" in parsed:
                return parsed
        except (json.JSONDecodeError, TypeError) as e:
            logger.debug("Failed to parse LLM JSON response: %s", e)

        # Try extracting from code fence
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(1))
                if isinstance(parsed, dict) and "keep" in parsed:
                    return parsed
            except (json.JSONDecodeError, TypeError) as e:
                logger.debug("Failed to parse LLM JSON response: %s", e)

        # Try finding JSON object in text using balanced brace matching.
        # A non-greedy match would break on nested objects, so we find
        # each opening brace and try parsing from there.
        for i, ch in enumerate(text):
            if ch == "{":
                # Try progressively longer substrings starting from this brace
                depth = 0
                for j in range(i, len(text)):
                    if text[j] == "{":
                        depth += 1
                    elif text[j] == "}":
                        depth -= 1
                    if depth == 0:
                        candidate = text[i : j + 1]
                        try:
                            parsed = json.loads(candidate)
                            if isinstance(parsed, dict) and "keep" in parsed:
                                return parsed
                        except (json.JSONDecodeError, TypeError) as e:
                            logger.debug("Failed to parse LLM JSON response: %s", e)
                        break

        return {}
