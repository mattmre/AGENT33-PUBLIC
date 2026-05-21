"""Automatic session title generation (Phase 59).

Provides two paths for generating concise session titles:

1. **LLM-based**: Uses the ModelRouter to generate a 5-7 word title from
   the first user message.  Preferred when a router is available.
2. **Heuristic**: Extracts the first ~10 words from the first user message,
   cleans them, and truncates to a reasonable length.  Used as a fallback
   when the LLM is unavailable or the call fails.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent33.llm.router import ModelRouter

logger = logging.getLogger(__name__)

# Maximum length for a generated title (characters).
_MAX_TITLE_LENGTH = 80

# Maximum number of words to keep in the heuristic path.
_HEURISTIC_WORD_LIMIT = 10

_TITLE_PROMPT = (
    "Generate a concise 5-7 word title for this conversation. "
    "Return ONLY the title text, no quotes, no explanation.\n\n"
    "First message: {first_message}"
)


# ---------------------------------------------------------------------------
# Heuristic title generation
# ---------------------------------------------------------------------------


def generate_title_heuristic(first_message: str) -> str:
    """Generate a title from the first user message using heuristics.

    Strategy:
    - Strip leading/trailing whitespace
    - Take the first ``_HEURISTIC_WORD_LIMIT`` words
    - Remove special characters (keep alphanumeric, spaces, hyphens)
    - Truncate to ``_MAX_TITLE_LENGTH`` characters
    - Append ellipsis if truncated

    Returns an empty string if the input is empty.
    """
    if not first_message or not first_message.strip():
        return ""

    # Normalise whitespace.
    cleaned = " ".join(first_message.split())

    # Take the first N words.
    words = cleaned.split()[:_HEURISTIC_WORD_LIMIT]
    title = " ".join(words)

    # Remove control characters and excessive punctuation, but keep
    # basic punctuation that makes titles readable.
    title = re.sub(r"[^\w\s\-.,!?:;'\"()/]", "", title)

    # Collapse repeated whitespace.
    title = " ".join(title.split())

    # Truncate.
    if len(title) > _MAX_TITLE_LENGTH:
        title = title[:_MAX_TITLE_LENGTH].rstrip() + "..."

    return title


# ---------------------------------------------------------------------------
# LLM-based title generation
# ---------------------------------------------------------------------------


async def generate_title_llm(
    first_message: str,
    router: ModelRouter,
    *,
    model: str = "llama3.2",
) -> str:
    """Generate a session title using an LLM via the ModelRouter.

    Falls back to the heuristic generator if the LLM call fails.

    Parameters
    ----------
    first_message:
        The first user message in the session.
    router:
        The ModelRouter instance to use for LLM completion.
    model:
        The model to use for title generation (default: llama3.2).

    Returns
    -------
    str
        A concise title for the session.
    """
    if not first_message or not first_message.strip():
        return ""

    from agent33.llm.base import ChatMessage

    prompt = _TITLE_PROMPT.format(first_message=first_message[:500])

    try:
        response = await router.complete(
            [ChatMessage(role="user", content=prompt)],
            model=model,
            temperature=0.3,
            max_tokens=30,
        )

        title = response.content.strip()

        # Strip wrapping quotes if the LLM included them.
        if (title.startswith('"') and title.endswith('"')) or (
            title.startswith("'") and title.endswith("'")
        ):
            title = title[1:-1].strip()

        # Truncate if the LLM returned something too long.
        if len(title) > _MAX_TITLE_LENGTH:
            title = title[:_MAX_TITLE_LENGTH].rstrip() + "..."

        if title:
            return title

    except Exception:
        logger.warning("LLM title generation failed, falling back to heuristic", exc_info=True)

    # Fallback to heuristic.
    return generate_title_heuristic(first_message)


# ---------------------------------------------------------------------------
# Unified title generator service
# ---------------------------------------------------------------------------


class TitleGenerator:
    """Generates session titles using LLM with heuristic fallback.

    Parameters
    ----------
    router:
        Optional ModelRouter for LLM-based generation.  When ``None``,
        only the heuristic path is available.
    model:
        Model identifier for LLM-based generation.
    """

    def __init__(
        self,
        router: ModelRouter | None = None,
        model: str = "llama3.2",
    ) -> None:
        self._router = router
        self._model = model

    async def generate(self, first_message: str) -> str:
        """Generate a title for a session.

        Uses LLM when a router is available, otherwise falls back to
        the heuristic path.
        """
        if self._router is not None:
            return await generate_title_llm(
                first_message,
                self._router,
                model=self._model,
            )
        return generate_title_heuristic(first_message)

    @property
    def has_llm(self) -> bool:
        """Whether an LLM router is configured."""
        return self._router is not None
