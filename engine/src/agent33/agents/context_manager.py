"""Context window management for agent conversations.

Prevents context overflow by tracking token usage and proactively
managing the conversation history via message unwinding and handoff
summaries.  Integrates with the iterative tool-use loop and
AgentRuntime to keep conversations within model limits.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING

from agent33.agents.tokenizer import EstimateTokenCounter, TokenCounter
from agent33.llm.base import ChatMessage

if TYPE_CHECKING:
    from agent33.llm.router import ModelRouter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

# Average characters per token varies by model.  GPT-family averages ~4 chars
# per token; for safety we use 3.5 (overestimate) so we truncate sooner
# rather than running into hard limits.
_DEFAULT_CHARS_PER_TOKEN = 3.5

# Constants for summary/fallback formatting
_MAX_MESSAGE_PREVIEW_CHARS = 500
_MAX_FALLBACK_PREVIEW_CHARS = 100
_MAX_FALLBACK_PREVIEW_MESSAGES = 10


def estimate_tokens(text: str, chars_per_token: float = _DEFAULT_CHARS_PER_TOKEN) -> int:
    """Estimate token count from character length.

    This is a fast heuristic; an exact count would require the model's
    tokenizer.  Using a conservative ratio ensures we truncate early
    rather than hitting hard context limits.
    """
    if not text:
        return 0
    return max(1, int(len(text) / chars_per_token))


def estimate_message_tokens(
    messages: list[ChatMessage],
    chars_per_token: float = _DEFAULT_CHARS_PER_TOKEN,
) -> int:
    """Estimate total tokens across a list of messages.

    Accounts for per-message overhead (role prefix, separators) using a
    flat 4-token estimate per message.
    """
    total = 0
    for msg in messages:
        total += estimate_tokens(msg.text_content, chars_per_token) + 4
    return total


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class ContextBudget:
    """Defines the token budget for a conversation.

    Attributes
    ----------
    max_context_tokens:
        Hard limit — total tokens the model can accept (prompt + completion).
    reserved_for_completion:
        Tokens reserved for the model's reply.
    summarize_threshold:
        Fraction (0..1) of effective budget at which to trigger summarization.
    """

    max_context_tokens: int = 128_000
    reserved_for_completion: int = 4_096
    summarize_threshold: float = 0.75

    @property
    def effective_limit(self) -> int:
        """Maximum tokens available for conversation history."""
        return self.max_context_tokens - self.reserved_for_completion

    @property
    def summarize_at(self) -> int:
        """Token count that triggers proactive summarization."""
        return int(self.effective_limit * self.summarize_threshold)


@dataclasses.dataclass(frozen=True, slots=True)
class ContextSnapshot:
    """Point-in-time view of context window usage."""

    total_tokens: int
    message_count: int
    budget: ContextBudget
    headroom: int  # tokens remaining before effective_limit
    needs_summarization: bool
    needs_unwinding: bool

    @property
    def utilization(self) -> float:
        """Fraction of effective budget used (0..1)."""
        if self.budget.effective_limit == 0:
            return 1.0
        return self.total_tokens / self.budget.effective_limit


# ---------------------------------------------------------------------------
# Summarization prompt
# ---------------------------------------------------------------------------

_SUMMARIZE_SYSTEM = """\
You are a context summarizer. Given a series of conversation messages, \
produce a concise summary that preserves:
1. The original task/goal
2. Key decisions made and reasoning
3. Important results from tool calls
4. Current state and next steps

The summary will replace the original messages in the conversation, so it \
must contain all information the agent needs to continue working.

Be concise but complete. Use bullet points. Maximum 500 words."""


# ---------------------------------------------------------------------------
# ContextManager
# ---------------------------------------------------------------------------


class ContextManager:
    """Manages the context window for agent conversations.

    Provides three mechanisms to keep conversations within model limits:

    1. **Token tracking** — Estimates token usage per message and warns
       when approaching limits.
    2. **Message unwinding** — Removes the oldest non-system messages
       when the conversation exceeds the effective limit.
    3. **Handoff summaries** — Uses an LLM to compress older messages
       into a summary, preserving key information.
    """

    def __init__(
        self,
        budget: ContextBudget | None = None,
        router: ModelRouter | None = None,
        summarize_model: str = "llama3.2",
        chars_per_token: float = _DEFAULT_CHARS_PER_TOKEN,
        token_counter: TokenCounter | None = None,
        skip_summarization: bool = False,
    ) -> None:
        self._budget = budget or ContextBudget()
        self._router = router
        self._summarize_model = summarize_model
        self._chars_per_token = chars_per_token
        self._token_counter: TokenCounter = token_counter or EstimateTokenCounter(
            chars_per_token=chars_per_token,
        )
        self._skip_summarization = skip_summarization

    @property
    def budget(self) -> ContextBudget:
        return self._budget

    @property
    def token_counter(self) -> TokenCounter:
        """The token counter used by this manager."""
        return self._token_counter

    def _estimate_messages(self, messages: list[ChatMessage]) -> int:
        """Estimate total tokens for *messages* using the configured counter."""
        msg_dicts = [{"role": m.role, "content": m.text_content} for m in messages]
        return self._token_counter.count_messages(msg_dicts)

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def snapshot(self, messages: list[ChatMessage]) -> ContextSnapshot:
        """Take a snapshot of current context window usage."""
        total = self._estimate_messages(messages)
        headroom = max(0, self._budget.effective_limit - total)
        return ContextSnapshot(
            total_tokens=total,
            message_count=len(messages),
            budget=self._budget,
            headroom=headroom,
            needs_summarization=total >= self._budget.summarize_at,
            needs_unwinding=total >= self._budget.effective_limit,
        )

    # ------------------------------------------------------------------
    # Message unwinding
    # ------------------------------------------------------------------

    def unwind(
        self,
        messages: list[ChatMessage],
        target_tokens: int | None = None,
    ) -> list[ChatMessage]:
        """Remove oldest non-system messages until under *target_tokens*.

        System messages (role="system") are always preserved.  Messages
        are removed from the front of the conversation (oldest first).
        The most recent messages are kept.

        Parameters
        ----------
        messages:
            The full conversation history (mutated in place is avoided;
            a new list is returned).
        target_tokens:
            Desired token ceiling.  Defaults to the effective limit.

        Returns
        -------
        list[ChatMessage]
            A trimmed copy of *messages*.
        """
        target = target_tokens or self._budget.effective_limit
        current = self._estimate_messages(messages)

        if current <= target:
            return list(messages)

        # Partition into system and non-system messages
        system_msgs: list[ChatMessage] = []
        non_system: list[ChatMessage] = []
        for msg in messages:
            if msg.role == "system":
                system_msgs.append(msg)
            else:
                non_system.append(msg)

        # Track running token count to avoid O(n^2) re-estimation
        running_tokens = self._estimate_messages(system_msgs + non_system)

        # Remove oldest non-system messages until under target
        while non_system and running_tokens > target:
            removed = non_system.pop(0)
            removed_tokens = self._estimate_messages([removed])
            running_tokens -= removed_tokens
            logger.debug(
                "Unwinding message: role=%s, tokens~%d",
                removed.role,
                self._token_counter.count(removed.text_content),
            )

        final_messages = system_msgs + non_system

        if running_tokens > target:
            system_tokens = self._estimate_messages(system_msgs)
            logger.warning(
                "Unwind could not meet target tokens: system messages alone "
                "use ≈%d tokens (target=%d). Consider reducing system prompt size.",
                system_tokens,
                target,
            )

        return final_messages

    # ------------------------------------------------------------------
    # Handoff summaries
    # ------------------------------------------------------------------

    async def summarize_and_compact(
        self,
        messages: list[ChatMessage],
        keep_recent: int = 4,
    ) -> list[ChatMessage]:
        """Compress older messages into a summary via LLM.

        Keeps the system prompt and the most recent *keep_recent*
        non-system messages.  Everything in between is summarized into
        a single message injected after the system prompt.

        Parameters
        ----------
        messages:
            Full conversation.
        keep_recent:
            Number of recent non-system messages to preserve verbatim.

        Returns
        -------
        list[ChatMessage]
            Compacted conversation: system + summary + recent.
            Falls back to a simple text summary when no model router
            is configured.
        """
        # Partition
        system_msgs: list[ChatMessage] = []
        non_system: list[ChatMessage] = []
        for msg in messages:
            if msg.role == "system":
                system_msgs.append(msg)
            else:
                non_system.append(msg)

        if len(non_system) <= keep_recent:
            # Nothing to summarize
            return list(messages)

        # Split into "to summarize" and "to keep"
        to_summarize = non_system[:-keep_recent]
        to_keep = non_system[-keep_recent:]

        if not to_summarize:
            return list(messages)

        # Build the summary
        summary_text = await self._generate_summary(to_summarize)

        # Role is intentionally "user" — not "system" — so that the
        # summary message remains eligible for unwinding if context
        # pressure continues to build.  The "[Context Summary]" prefix
        # signals its origin to the LLM.
        summary_msg = ChatMessage(
            role="user",
            content=f"[Context Summary]\n{summary_text}",
        )

        return system_msgs + [summary_msg] + to_keep

    async def _generate_summary(self, messages: list[ChatMessage]) -> str:
        """Generate a summary of the given messages via LLM."""
        if self._router is None:
            # Fallback: simple truncation-based summary
            return self._fallback_summary(messages)

        conversation_text = "\n".join(
            f"[{msg.role}]: {msg.text_content[:_MAX_MESSAGE_PREVIEW_CHARS]}" for msg in messages
        )

        try:
            response = await self._router.complete(
                [
                    ChatMessage(role="system", content=_SUMMARIZE_SYSTEM),
                    ChatMessage(
                        role="user",
                        content=f"Summarize this conversation:\n\n{conversation_text}",
                    ),
                ],
                model=self._summarize_model,
                temperature=0.2,
                max_tokens=1000,
            )
            return response.content
        except Exception:
            logger.warning("LLM summarization failed, using fallback", exc_info=True)
            return self._fallback_summary(messages)

    @staticmethod
    def _fallback_summary(messages: list[ChatMessage]) -> str:
        """Create a basic summary without LLM when router is unavailable."""
        lines = [f"Prior conversation ({len(messages)} messages):"]
        for msg in messages[:_MAX_FALLBACK_PREVIEW_MESSAGES]:
            preview = msg.text_content[:_MAX_FALLBACK_PREVIEW_CHARS].replace("\n", " ")
            lines.append(f"- [{msg.role}] {preview}...")
        if len(messages) > _MAX_FALLBACK_PREVIEW_MESSAGES:
            lines.append(
                f"  ... and {len(messages) - _MAX_FALLBACK_PREVIEW_MESSAGES} more messages"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Proactive management
    # ------------------------------------------------------------------

    async def manage(
        self,
        messages: list[ChatMessage],
        keep_recent: int = 4,
    ) -> list[ChatMessage]:
        """Proactively manage context: summarize if needed, unwind if critical.

        This is the primary entry point for automatic context management.
        Call it before each LLM invocation in the tool loop.

        Strategy:
        1. If under summarization threshold — do nothing
        2. If over threshold but under limit — summarize older messages
        3. If over limit — unwind (drop oldest non-system messages)

        When ``skip_summarization`` is True (e.g. because the Phase 50
        ContextCompressor is handling compression), summarization is
        skipped but hard-limit unwinding is still performed as a safety
        net.
        """
        snap = self.snapshot(messages)

        if not snap.needs_summarization:
            return list(messages)

        if self._skip_summarization:
            # Compressor handles summarization; only unwind if over hard limit.
            if snap.needs_unwinding:
                return self.unwind(messages)
            return list(messages)

        if snap.needs_unwinding:
            # Critical: over the limit.  First try to summarize, then unwind
            # as a safety net.
            if self._router is not None:
                messages = await self.summarize_and_compact(messages, keep_recent)
                # Check if summarization was enough
                snap = self.snapshot(messages)
                if not snap.needs_unwinding:
                    return messages

            # Still over limit — hard unwind
            return self.unwind(messages)

        # Over threshold but not over limit — summarize proactively
        if self._router is not None:
            return await self.summarize_and_compact(messages, keep_recent)

        # No router available — unwind instead
        return self.unwind(messages, target_tokens=self._budget.summarize_at)


# ---------------------------------------------------------------------------
# Model context limits (known models)
# ---------------------------------------------------------------------------

MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    "claude-3-opus": 200_000,
    "claude-3-sonnet": 200_000,
    "claude-3-haiku": 200_000,
    "claude-3.5-sonnet": 200_000,
    "claude-4-opus": 200_000,
    "claude-4-sonnet": 200_000,
    "llama3.2": 128_000,
    "llama3.1": 128_000,
    "llama3": 8_192,
    "mistral": 32_768,
    "mixtral": 32_768,
    "gemma2": 8_192,
    "deepseek-v2": 128_000,
    "qwen3-coder:32b": 32_768,
    "qwen3-coder:30b": 32_768,
    "qwen3-coder:14b": 32_768,
}


def truncate_tool_output(output: str, max_chars: int = 15000) -> str:
    """Truncate massive tool outputs before they hit the LLM.

    If the string length exceeds max_chars, it will be sliced and appended with a
    truncation warning so the model knows there's more data it didn't see.
    """
    if not isinstance(output, str):
        output = str(output)
    if len(output) <= max_chars:
        return output

    half = max_chars // 2
    return (
        output[:half]
        + f"\n\n... [TRUNCATED: {len(output) - max_chars} chars omitted] ...\n\n"
        + output[-half:]
    )


def budget_for_model(model: str, reserved_for_completion: int = 4_096) -> ContextBudget:
    """Create a ContextBudget using the known context limit for *model*.

    Falls back to 128K if the model is not in the lookup table.
    """
    limit = MODEL_CONTEXT_LIMITS.get(model, 128_000)
    return ContextBudget(
        max_context_tokens=limit,
        reserved_for_completion=reserved_for_completion,
    )
