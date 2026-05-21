"""Session title generator -- creates short human-readable titles.

Phase 59: Uses the cheapest available model (LOW effort) to generate
a concise 3-7 word title from the first user/assistant exchange.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from agent33.llm.base import ChatMessage

if TYPE_CHECKING:
    from agent33.llm.router import ModelRouter

logger = logging.getLogger(__name__)

_MAX_INPUT_CHARS = 500
_TITLE_PROMPT = (
    "Generate a 3-7 word title for this conversation. Only output the title, nothing else."
)

# Matches surrounding single or double quotes.
_QUOTE_RE = re.compile(r'^["\'](.+?)["\']$')


async def generate_title(
    user_msg: str,
    assistant_msg: str,
    router: ModelRouter,
    model: str | None = None,
) -> str | None:
    """Generate a short session title from the first exchange.

    Parameters
    ----------
    user_msg:
        The first user message in the session.
    assistant_msg:
        The first assistant response in the session.
    router:
        The model router for LLM completions.
    model:
        Optional model override.  When *None*, the default model on the
        router is used (callers should pass the cheapest/LOW-effort model).

    Returns
    -------
    str | None
        A 3-7 word title string, or *None* if generation fails.
    """
    truncated_user = user_msg[:_MAX_INPUT_CHARS]
    truncated_assistant = assistant_msg[:_MAX_INPUT_CHARS]

    messages = [
        ChatMessage(role="system", content=_TITLE_PROMPT),
        ChatMessage(
            role="user",
            content=(f"User: {truncated_user}\n\nAssistant: {truncated_assistant}"),
        ),
    ]

    resolved_model = model or "llama3.2"

    try:
        response = await router.complete(
            messages,
            model=resolved_model,
            temperature=0.3,
            max_tokens=30,
        )
    except Exception:
        logger.debug("title generation failed", exc_info=True)
        return None

    title = _clean_title(response.content)
    if title is None:
        logger.debug("title generation returned unusable output: %r", response.content)
    return title


def _clean_title(raw: str) -> str | None:
    """Clean and validate LLM output as a short title.

    Returns *None* when the output is empty or exceeds the expected
    length (more than 12 words), which indicates the model did not
    follow instructions.
    """
    stripped = raw.strip()
    if not stripped:
        return None

    # Remove surrounding quotes the LLM may add.
    match = _QUOTE_RE.match(stripped)
    if match:
        stripped = match.group(1).strip()

    # Reject obviously wrong outputs (too long or multi-line).
    if "\n" in stripped:
        # Take only the first line.
        stripped = stripped.split("\n", 1)[0].strip()

    words = stripped.split()
    if len(words) > 12 or len(words) == 0:
        return None

    return stripped
