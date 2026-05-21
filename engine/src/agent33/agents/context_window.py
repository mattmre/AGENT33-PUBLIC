"""Per-component context window budgeting for agent invocations.

Provides fine-grained token budget allocation across prompt components
(system prompt, tool definitions, conversation history, injected skills)
so the runtime can detect and correct context window overruns *before*
sending a request to the LLM.

This module complements :mod:`agent33.agents.context_manager`, which
handles *reactive* context management (unwinding and summarization
during iterative tool loops).  ``ContextWindowManager`` adds a
*proactive* budgeting layer that is applied before every LLM call,
including single-shot :meth:`AgentRuntime.invoke`.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field, computed_field

from agent33.agents.tokenizer import EstimateTokenCounter, TokenCounter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ContextBudget(BaseModel):
    """Token budget breakdown for a single LLM invocation.

    Each field tracks how many tokens are consumed by a specific prompt
    component.  ``available_tokens`` and ``utilization`` are computed
    automatically from the other fields.
    """

    max_tokens: int = Field(
        default=128_000,
        description="Total context window limit for the target model.",
    )
    system_tokens: int = Field(
        default=0,
        description="Tokens consumed by the system prompt.",
    )
    tool_tokens: int = Field(
        default=0,
        description="Tokens consumed by tool/function definitions.",
    )
    history_tokens: int = Field(
        default=0,
        description="Tokens consumed by conversation history messages.",
    )
    skill_tokens: int = Field(
        default=0,
        description="Tokens consumed by injected skill instructions.",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def used_tokens(self) -> int:
        """Total tokens used across all components."""
        return self.system_tokens + self.tool_tokens + self.history_tokens + self.skill_tokens

    @computed_field  # type: ignore[prop-decorator]
    @property
    def available_tokens(self) -> int:
        """Tokens remaining for the LLM completion."""
        return max(0, self.max_tokens - self.used_tokens)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def utilization(self) -> float:
        """Percentage of the context window consumed (0.0 -- 100.0)."""
        if self.max_tokens == 0:
            return 100.0
        return (self.used_tokens / self.max_tokens) * 100.0


class ContextWindowPolicy(BaseModel):
    """Policy governing how the context budget is distributed.

    Ratios are fractions of ``max_tokens`` -- if any component exceeds
    its ratio the manager will apply truncation according to
    ``truncation_strategy``.
    """

    max_history_ratio: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Maximum fraction of budget for conversation history.",
    )
    max_skill_ratio: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Maximum fraction of budget for injected skills.",
    )
    max_tool_ratio: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description="Maximum fraction of budget for tool definitions.",
    )
    truncation_strategy: str = Field(
        default="smart",
        description=(
            "Strategy for truncation when over budget: "
            "'head' keeps the start, 'tail' keeps the end, "
            "'smart' keeps both start and end."
        ),
    )
    warn_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Utilization fraction (0-1) that triggers a warning log.",
    )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class ContextWindowManager:
    """Proactive context window budgeting for agent invocations.

    Unlike :class:`~agent33.agents.context_manager.ContextManager`, which
    reacts to context pressure during iterative loops, this class
    *pre-computes* a budget from all prompt components and applies
    truncation before the first LLM call.

    Parameters
    ----------
    default_max_tokens:
        Default context window size when no model-specific limit is known.
    token_counter:
        Pluggable token counting implementation.  Falls back to the
        character-based heuristic estimator.
    policy:
        Optional :class:`ContextWindowPolicy` governing component ratios.
    """

    def __init__(
        self,
        default_max_tokens: int = 128_000,
        token_counter: TokenCounter | None = None,
        policy: ContextWindowPolicy | None = None,
    ) -> None:
        self._default_max_tokens = default_max_tokens
        self._counter: TokenCounter = token_counter or EstimateTokenCounter()
        self._policy = policy or ContextWindowPolicy()

    @property
    def policy(self) -> ContextWindowPolicy:
        """The active context window policy."""
        return self._policy

    # ------------------------------------------------------------------
    # Token estimation
    # ------------------------------------------------------------------

    def estimate_tokens(self, text: str) -> int:
        """Estimate the token count for *text*.

        Uses the configured :class:`TokenCounter` (heuristic or tiktoken).
        """
        return self._counter.count(text)

    # ------------------------------------------------------------------
    # Budget creation
    # ------------------------------------------------------------------

    def create_budget(
        self,
        *,
        max_tokens: int | None = None,
        system_prompt: str = "",
        tools: list[str] | None = None,
        history: list[dict[str, str]] | None = None,
        skills: list[str] | None = None,
    ) -> ContextBudget:
        """Compute a token budget from the given prompt components.

        Parameters
        ----------
        max_tokens:
            Context window limit for the target model.  Falls back to
            ``default_max_tokens``.
        system_prompt:
            The full system prompt text.
        tools:
            JSON-serialised tool/function definitions (one string per tool).
        history:
            Conversation history as ``{"role": ..., "content": ...}`` dicts.
        skills:
            Injected skill instruction blocks (one string per skill).

        Returns
        -------
        ContextBudget
            Populated budget with per-component token counts.
        """
        effective_max = max_tokens if max_tokens is not None else self._default_max_tokens
        system_tokens = self._counter.count(system_prompt)
        tool_tokens = sum(self._counter.count(t) for t in (tools or []))
        history_tokens = self._counter.count_messages(history or [])
        skill_tokens = sum(self._counter.count(s) for s in (skills or []))
        return ContextBudget(
            max_tokens=effective_max,
            system_tokens=system_tokens,
            tool_tokens=tool_tokens,
            history_tokens=history_tokens,
            skill_tokens=skill_tokens,
        )

    # ------------------------------------------------------------------
    # Truncation helpers
    # ------------------------------------------------------------------

    def truncate_history(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> list[dict[str, str]]:
        """Truncate conversation history to fit within *max_tokens*.

        Keeps the system message (role ``"system"``) and the most recent
        non-system messages intact.  Removes the oldest middle messages
        first.

        Returns a new list; the original is not mutated.
        """
        if not messages:
            return []

        current = self._counter.count_messages(messages)
        if current <= max_tokens:
            return list(messages)

        system_msgs: list[dict[str, str]] = []
        non_system: list[dict[str, str]] = []
        for msg in messages:
            if msg.get("role") == "system":
                system_msgs.append(msg)
            else:
                non_system.append(msg)

        running = self._counter.count_messages(system_msgs + non_system)

        # Remove oldest non-system messages until under budget
        while non_system and running > max_tokens:
            removed = non_system.pop(0)
            removed_tokens = self._counter.count_messages([removed])
            running -= removed_tokens

        return system_msgs + non_system

    def truncate_context(
        self,
        text: str,
        max_tokens: int,
        strategy: str = "tail",
    ) -> str:
        """Truncate *text* to fit within *max_tokens*.

        Strategies:

        - ``"head"`` -- keep the beginning of the text.
        - ``"tail"`` -- keep the end of the text.
        - ``"smart"`` -- keep both start and end, drop the middle.

        Returns the (possibly shortened) text.
        """
        current = self._counter.count(text)
        if current <= max_tokens:
            return text

        # Approximate char limit from token budget
        # Use the inverse of the counter heuristic (chars_per_token ≈ 3.5)
        chars_per_token = 3.5
        if isinstance(self._counter, EstimateTokenCounter):
            chars_per_token = self._counter._cpt  # noqa: SLF001
        max_chars = int(max_tokens * chars_per_token)

        if max_chars >= len(text):
            return text

        if strategy == "head":
            return text[:max_chars]
        if strategy == "tail":
            return text[-max_chars:]

        # "smart": keep start + end, drop middle
        half = max_chars // 2
        if half == 0:
            return text[:max_chars]
        marker = "\n\n... [truncated] ...\n\n"
        return text[:half] + marker + text[-half:]

    # ------------------------------------------------------------------
    # Budget queries
    # ------------------------------------------------------------------

    def fits_budget(self, text: str, budget: ContextBudget) -> bool:
        """Return ``True`` if *text* fits within the budget's available tokens."""
        tokens = self._counter.count(text)
        return tokens <= budget.available_tokens

    def get_utilization_report(self, budget: ContextBudget) -> dict[str, object]:
        """Return a detailed utilization breakdown for observability."""
        return {
            "max_tokens": budget.max_tokens,
            "system_tokens": budget.system_tokens,
            "tool_tokens": budget.tool_tokens,
            "history_tokens": budget.history_tokens,
            "skill_tokens": budget.skill_tokens,
            "used_tokens": budget.used_tokens,
            "available_tokens": budget.available_tokens,
            "utilization_pct": round(budget.utilization, 2),
            "over_budget": budget.used_tokens > budget.max_tokens,
            "warn_threshold_pct": round(self._policy.warn_threshold * 100, 2),
            "above_warn_threshold": budget.utilization >= self._policy.warn_threshold * 100,
        }

    # ------------------------------------------------------------------
    # Policy enforcement
    # ------------------------------------------------------------------

    def enforce_policy(
        self,
        budget: ContextBudget,
    ) -> ContextBudget:
        """Apply the configured policy limits, truncating where necessary.

        Returns a new :class:`ContextBudget` with component token counts
        capped to their policy ratios.  Actual text truncation should be
        done by the caller using :meth:`truncate_context` or
        :meth:`truncate_history` based on the capped values.
        """
        max_history = int(budget.max_tokens * self._policy.max_history_ratio)
        max_skills = int(budget.max_tokens * self._policy.max_skill_ratio)
        max_tools = int(budget.max_tokens * self._policy.max_tool_ratio)

        capped_history = min(budget.history_tokens, max_history)
        capped_skills = min(budget.skill_tokens, max_skills)
        capped_tools = min(budget.tool_tokens, max_tools)

        new_budget = ContextBudget(
            max_tokens=budget.max_tokens,
            system_tokens=budget.system_tokens,
            tool_tokens=capped_tools,
            history_tokens=capped_history,
            skill_tokens=capped_skills,
        )

        if new_budget.used_tokens != budget.used_tokens:
            logger.info(
                "Context window policy enforced: original=%d, capped=%d tokens "
                "(history %d->%d, skills %d->%d, tools %d->%d)",
                budget.used_tokens,
                new_budget.used_tokens,
                budget.history_tokens,
                capped_history,
                budget.skill_tokens,
                capped_skills,
                budget.tool_tokens,
                capped_tools,
            )

        return new_budget

    def check_and_warn(self, budget: ContextBudget) -> None:
        """Log a warning if utilization exceeds the policy threshold."""
        threshold_pct = self._policy.warn_threshold * 100.0
        if budget.utilization >= threshold_pct:
            logger.warning(
                "Context window utilization %.1f%% exceeds warn threshold %.1f%% "
                "(used=%d, max=%d, available=%d)",
                budget.utilization,
                threshold_pct,
                budget.used_tokens,
                budget.max_tokens,
                budget.available_tokens,
            )
