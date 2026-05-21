"""Context compression engine for long conversations (Phase 50).

Provides structured context compression that preserves essential information
while reducing token usage.  Operates on a *copy* of the message list and
returns a replacement list atomically.  Uses a separate, non-tool-capable
LLM call to generate summaries (no recursion risk).

Design constraints (from the Hermes Adoption Roadmap):
- Compression happens in the tool loop, NOT in get_context() (read-only)
- Operate on a COPY of messages; swap atomically
- Use separate non-tool-capable call path for LLM (no recursion)
- protect_first_n accounts for tool-call message pairs
"""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING

from agent33.agents.context_manager import estimate_message_tokens
from agent33.llm.base import ChatMessage

if TYPE_CHECKING:
    from agent33.llm.router import ModelRouter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured summary prompt
# ---------------------------------------------------------------------------

_SUMMARY_SYSTEM_PROMPT = """\
You are a context compressor.  Given a block of conversation messages, \
produce a structured summary using EXACTLY this format:

## Goal
What the user/agent is trying to accomplish.

## Progress
What has been completed so far (bullet points).

## Key Decisions
Important choices made and their reasoning (bullet points).

## Files Modified
List of files or resources that were created/modified (bullet points, \
or "None" if not applicable).

## Next Steps
What still needs to be done (bullet points).

Be concise but preserve all information needed to continue the task.  \
Do not omit tool outputs that contain error messages or critical results.  \
Target length: {target_tokens} tokens."""

_ITERATIVE_UPDATE_PROMPT = """\
You are updating an existing context summary with new conversation data.  \
The existing summary and the new messages are provided below.

Update the summary to incorporate the new information while keeping the \
same structure:

## Goal
## Progress
## Key Decisions
## Files Modified
## Next Steps

Merge new progress into the existing sections.  Remove items from \
"Next Steps" that are now completed.  Add new decisions and file changes.  \
Keep the summary concise.  Target length: {target_tokens} tokens.

EXISTING SUMMARY:
{existing_summary}

NEW MESSAGES TO INCORPORATE:
{new_messages}"""

_TOOL_OUTPUT_PLACEHOLDER = "[tool output omitted for compression]"

_CONTEXT_SUMMARY_PREFIX = "[Compressed Context Summary]"

# Required sections in the structured summary
REQUIRED_SECTIONS = ("Goal", "Progress", "Key Decisions", "Files Modified", "Next Steps")


# ---------------------------------------------------------------------------
# ContextCompressor
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CompressionStats:
    """Statistics from a compression operation."""

    original_tokens: int
    compressed_tokens: int
    messages_removed: int
    messages_kept: int
    compression_ratio: float
    used_iterative_update: bool


class ContextCompressor:
    """Structured context compression for long conversations.

    Splits the conversation into three zones:

    - **Head**: Protected first N messages (system prompt + initial exchange).
      ``protect_first_n`` accounts for tool-call message pairs.
    - **Tail**: Recent messages kept verbatim (by token budget).
    - **Middle**: Everything in between, compressed into a structured summary.

    Tool outputs in the middle zone are pruned (replaced with a placeholder)
    before summarization to reduce noise.

    When a prior summary already exists (identifiable by the
    ``[Compressed Context Summary]`` prefix), the compressor performs an
    iterative update instead of regenerating from scratch.

    Parameters
    ----------
    threshold_percent:
        Compress when token usage exceeds this fraction of context window.
    protect_first_n:
        Number of logical message groups to protect at the start.  Accounts
        for tool-call pairs (an assistant message with tool_calls followed
        by one or more tool-result messages counts as one group).
    tail_token_budget:
        Keep this many tokens of recent context verbatim.
    summary_target_ratio:
        Summary length as a fraction of the compressed content's token count.
    summary_tokens_ceiling:
        Maximum summary length in tokens.
    summarize_model:
        Model identifier used for summarization calls.
    """

    def __init__(
        self,
        *,
        threshold_percent: float = 0.50,
        protect_first_n: int = 3,
        tail_token_budget: int = 20_000,
        summary_target_ratio: float = 0.20,
        summary_tokens_ceiling: int = 12_000,
        summarize_model: str = "llama3.2",
    ) -> None:
        if not 0.0 < threshold_percent < 1.0:
            raise ValueError("threshold_percent must be between 0 and 1 (exclusive)")
        if protect_first_n < 0:
            raise ValueError("protect_first_n must be non-negative")
        if tail_token_budget < 0:
            raise ValueError("tail_token_budget must be non-negative")

        self.threshold_percent = threshold_percent
        self.protect_first_n = protect_first_n
        self.tail_token_budget = tail_token_budget
        self.summary_target_ratio = summary_target_ratio
        self.summary_tokens_ceiling = summary_tokens_ceiling
        self.summarize_model = summarize_model

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def needs_compression(self, messages: list[ChatMessage], model_context_window: int) -> bool:
        """Return True if the conversation needs compression.

        Checks whether the estimated token usage of *messages* exceeds
        ``threshold_percent`` of *model_context_window*.
        """
        if model_context_window <= 0:
            return False
        current_tokens = estimate_message_tokens(messages)
        threshold = int(model_context_window * self.threshold_percent)
        return current_tokens > threshold

    async def compress(
        self,
        messages: list[ChatMessage],
        model: str,
        router: ModelRouter,
    ) -> tuple[list[ChatMessage], CompressionStats]:
        """Compress the conversation history.

        Operates on a *copy* of the input messages.  The original list
        is never mutated.

        Returns
        -------
        tuple[list[ChatMessage], CompressionStats]
            The compressed message list and statistics about the operation.
        """
        # Work on a copy -- never mutate the caller's list
        msgs = list(messages)
        original_tokens = estimate_message_tokens(msgs)

        # --- Check for existing summary (iterative update) ---
        # Search the full message list before zone splitting.  If found,
        # extract the summary text and remove the summary message so it
        # doesn't get double-counted in zone splitting.
        existing_summary = self._find_existing_summary(msgs)
        is_iterative = existing_summary is not None
        if is_iterative:
            msgs = [m for m in msgs if not m.text_content.startswith(_CONTEXT_SUMMARY_PREFIX)]

        # --- Identify the three zones ---
        head, middle, tail = self._split_zones(msgs)

        if not middle:
            # Nothing to compress -- restore any removed summary into head
            if is_iterative and existing_summary is not None:
                summary_msg = ChatMessage(
                    role="user",
                    content=f"{_CONTEXT_SUMMARY_PREFIX}\n{existing_summary}",
                )
                return head + [summary_msg] + tail, CompressionStats(
                    original_tokens=original_tokens,
                    compressed_tokens=original_tokens,
                    messages_removed=0,
                    messages_kept=len(messages),
                    compression_ratio=1.0,
                    used_iterative_update=False,
                )
            return list(messages), CompressionStats(
                original_tokens=original_tokens,
                compressed_tokens=original_tokens,
                messages_removed=0,
                messages_kept=len(messages),
                compression_ratio=1.0,
                used_iterative_update=False,
            )

        # --- Prune tool outputs in the middle zone ---
        pruned_middle = self._prune_tool_outputs(middle)

        # --- Build summary ---
        middle_tokens = estimate_message_tokens(pruned_middle)
        target_tokens = min(
            int(middle_tokens * self.summary_target_ratio),
            self.summary_tokens_ceiling,
        )
        # Ensure we have at least a reasonable minimum
        target_tokens = max(target_tokens, 200)

        summary_text = await self._generate_summary(
            pruned_middle,
            target_tokens=target_tokens,
            router=router,
            existing_summary=existing_summary,
        )

        # --- Build the summary message ---
        summary_msg = ChatMessage(
            role="user",
            content=f"{_CONTEXT_SUMMARY_PREFIX}\n{summary_text}",
        )

        # --- Assemble the compressed conversation ---
        compressed = head + [summary_msg] + tail

        compressed_tokens = estimate_message_tokens(compressed)

        stats = CompressionStats(
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            messages_removed=len(middle),
            messages_kept=len(head) + 1 + len(tail),  # +1 for summary
            compression_ratio=(
                compressed_tokens / original_tokens if original_tokens > 0 else 1.0
            ),
            used_iterative_update=is_iterative,
        )

        logger.info(
            "Context compressed: %d -> %d tokens (%.1f%%), removed %d messages, iterative=%s",
            original_tokens,
            compressed_tokens,
            stats.compression_ratio * 100,
            stats.messages_removed,
            is_iterative,
        )

        return compressed, stats

    # ------------------------------------------------------------------
    # Zone splitting
    # ------------------------------------------------------------------

    def _split_zones(
        self,
        messages: list[ChatMessage],
    ) -> tuple[list[ChatMessage], list[ChatMessage], list[ChatMessage]]:
        """Split messages into head, middle, and tail zones.

        Head: First ``protect_first_n`` logical groups (accounting for
        tool-call message pairs).

        Tail: Recent messages fitting within ``tail_token_budget``.

        Middle: Everything between head and tail.
        """
        # --- Head zone: protect_first_n logical message groups ---
        head_end_idx = self._find_head_boundary(messages)

        # --- Tail zone: walk backward until token budget exhausted ---
        tail_start_idx = self._find_tail_boundary(messages, head_end_idx)

        head = messages[:head_end_idx]
        middle = messages[head_end_idx:tail_start_idx]
        tail = messages[tail_start_idx:]

        return head, middle, tail

    def _find_head_boundary(self, messages: list[ChatMessage]) -> int:
        """Find the index where the head zone ends.

        Counts ``protect_first_n`` logical message groups.  A "group" is:
        - A single message for non-tool-call messages
        - An assistant message with tool_calls PLUS all following tool-result
          messages for that call (counted as one group together)
        """
        if self.protect_first_n <= 0:
            return 0

        groups_counted = 0
        idx = 0

        while idx < len(messages) and groups_counted < self.protect_first_n:
            msg = messages[idx]

            if msg.role == "assistant" and msg.tool_calls:
                # This is a tool-call assistant message.
                # Count it plus all following tool-result messages as one group.
                idx += 1
                while idx < len(messages) and messages[idx].role == "tool":
                    idx += 1
                groups_counted += 1
            else:
                idx += 1
                groups_counted += 1

        return idx

    def _find_tail_boundary(self, messages: list[ChatMessage], head_end: int) -> int:
        """Find the index where the tail zone starts.

        Walks backward from the end of messages, accumulating tokens
        until ``tail_token_budget`` is reached.  Ensures we don't
        overlap with the head zone.
        """
        if self.tail_token_budget <= 0:
            return len(messages)

        running_tokens = 0
        tail_start = len(messages)

        for i in range(len(messages) - 1, head_end - 1, -1):
            msg_tokens = estimate_message_tokens([messages[i]])
            if running_tokens + msg_tokens > self.tail_token_budget:
                break
            running_tokens += msg_tokens
            tail_start = i

        # Don't let tail overlap with head
        if tail_start < head_end:
            tail_start = head_end

        return tail_start

    # ------------------------------------------------------------------
    # Tool output pruning
    # ------------------------------------------------------------------

    @staticmethod
    def _prune_tool_outputs(messages: list[ChatMessage]) -> list[ChatMessage]:
        """Replace tool-result message contents with a short placeholder.

        This reduces the token cost of the middle zone before summarization.
        The summary prompt instructs the LLM to note any errors/critical
        results, so important tool information is captured in the summary
        itself.
        """
        pruned: list[ChatMessage] = []
        for msg in messages:
            if msg.role == "tool":
                pruned.append(
                    ChatMessage(
                        role=msg.role,
                        content=_TOOL_OUTPUT_PLACEHOLDER,
                        tool_call_id=msg.tool_call_id,
                        name=msg.name,
                    )
                )
            else:
                pruned.append(msg)
        return pruned

    # ------------------------------------------------------------------
    # Summary detection
    # ------------------------------------------------------------------

    @staticmethod
    def _find_existing_summary(messages: list[ChatMessage]) -> str | None:
        """Find an existing compressed summary in the message list.

        Returns the summary text (without prefix) if found, else None.
        """
        for msg in messages:
            if msg.text_content.startswith(_CONTEXT_SUMMARY_PREFIX):
                # Strip the prefix to get the raw summary
                return msg.text_content[len(_CONTEXT_SUMMARY_PREFIX) :].strip()
        return None

    # ------------------------------------------------------------------
    # Summary generation
    # ------------------------------------------------------------------

    async def _generate_summary(
        self,
        messages: list[ChatMessage],
        *,
        target_tokens: int,
        router: ModelRouter,
        existing_summary: str | None = None,
    ) -> str:
        """Generate a structured summary via LLM.

        Uses a separate, non-tool-capable call path (``tools=None``)
        to avoid recursion.  Falls back to a text-based summary if
        the LLM call fails.
        """
        if existing_summary is not None:
            return await self._generate_iterative_update(
                messages,
                target_tokens=target_tokens,
                router=router,
                existing_summary=existing_summary,
            )

        # Build the conversation text for summarization
        conversation_text = self._format_messages_for_summary(messages)

        system_prompt = _SUMMARY_SYSTEM_PROMPT.format(target_tokens=target_tokens)

        try:
            response = await router.complete(
                [
                    ChatMessage(role="system", content=system_prompt),
                    ChatMessage(
                        role="user",
                        content=(
                            "Summarize this conversation into the structured format:\n\n"
                            f"{conversation_text}"
                        ),
                    ),
                ],
                model=self.summarize_model,
                temperature=0.2,
                max_tokens=self.summary_tokens_ceiling,
                tools=None,  # No tools -- prevents recursion
            )
            return response.content
        except Exception:
            logger.warning(
                "LLM summarization failed for context compression, using fallback",
                exc_info=True,
            )
            return self._fallback_summary(messages)

    async def _generate_iterative_update(
        self,
        messages: list[ChatMessage],
        *,
        target_tokens: int,
        router: ModelRouter,
        existing_summary: str,
    ) -> str:
        """Update an existing summary with new conversation data."""
        new_messages_text = self._format_messages_for_summary(messages)

        prompt = _ITERATIVE_UPDATE_PROMPT.format(
            target_tokens=target_tokens,
            existing_summary=existing_summary,
            new_messages=new_messages_text,
        )

        try:
            response = await router.complete(
                [
                    ChatMessage(role="system", content="You are a context compressor."),
                    ChatMessage(role="user", content=prompt),
                ],
                model=self.summarize_model,
                temperature=0.2,
                max_tokens=self.summary_tokens_ceiling,
                tools=None,  # No tools -- prevents recursion
            )
            return response.content
        except Exception:
            logger.warning(
                "LLM iterative summary update failed, using fallback",
                exc_info=True,
            )
            return self._fallback_summary(messages, existing_summary=existing_summary)

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_messages_for_summary(
        messages: list[ChatMessage],
        max_content_chars: int = 2000,
    ) -> str:
        """Format messages into a readable text block for the summary prompt."""
        lines: list[str] = []
        for msg in messages:
            content = msg.text_content[:max_content_chars]
            if len(msg.text_content) > max_content_chars:
                content += "..."
            role_label = msg.role
            if msg.name:
                role_label = f"{msg.role}({msg.name})"
            lines.append(f"[{role_label}]: {content}")
        return "\n".join(lines)

    @staticmethod
    def _fallback_summary(
        messages: list[ChatMessage],
        existing_summary: str | None = None,
    ) -> str:
        """Create a basic structured summary without LLM.

        Used as a fallback when the LLM call fails.
        """
        lines: list[str] = []

        if existing_summary:
            lines.append("## Goal\n(Preserved from prior summary)")
            lines.append(f"\n{existing_summary}\n")
            lines.append("## Progress\n(New messages since last summary)")
        else:
            lines.append("## Goal\n(Extracted from conversation)")

        lines.append("\n## Progress")
        msg_count = 0
        for msg in messages:
            if msg.role in ("user", "assistant") and msg.text_content.strip():
                preview = msg.text_content[:200].replace("\n", " ")
                lines.append(f"- [{msg.role}] {preview}")
                msg_count += 1
                if msg_count >= 10:
                    lines.append(f"  ... and {len(messages) - 10} more messages")
                    break

        lines.append("\n## Key Decisions\n- (see conversation above)")
        lines.append("\n## Files Modified\n- (see conversation above)")
        lines.append("\n## Next Steps\n- Continue with current task")

        return "\n".join(lines)
