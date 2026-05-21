"""Anthropic prompt caching support.

Injects ``cache_control`` breakpoints into serialized message payloads so the
Anthropic API can reuse cached prefixes across multi-turn conversations.

Anthropic allows a maximum of **4** cache breakpoints per request. The
``system_and_3`` strategy places them at:

1. The system prompt (always stable across turns).
2-4. The last three non-system messages (rolling window that maximises reuse
     of recent context while staying within the breakpoint budget).

See https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching for
the upstream specification.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

logger = logging.getLogger(__name__)

_MAX_BREAKPOINTS = 4


def _ensure_content_blocks(content: Any) -> list[dict[str, Any]]:
    """Normalise message content to a list of content blocks.

    Anthropic's API accepts content as either a plain string or a list of typed
    blocks.  When we need to attach ``cache_control`` metadata we must use the
    block form, so plain strings are wrapped in a single ``{"type": "text"}``
    block.
    """
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return list(content)  # already block form -- shallow copy
    # Fallback: treat as opaque and wrap in text block.
    return [{"type": "text", "text": str(content)}]


def _apply_cache_marker(
    message: dict[str, Any],
    cache_type: str = "ephemeral",
) -> dict[str, Any]:
    """Add a ``cache_control`` marker to a single serialized message.

    * For messages with a ``content`` field (system, user, assistant), the
      marker is placed on the **last** content block so the entire prefix up to
      and including this message is cached.
    * For ``tool`` role messages the Anthropic API expects ``cache_control`` at
      the top level of the message dict, not inside content blocks.
    """
    role = message.get("role", "")

    if role == "tool":
        # Tool results: top-level cache_control
        message["cache_control"] = {"type": cache_type}
        return message

    content = message.get("content")
    if content is None:
        return message

    blocks = _ensure_content_blocks(content)
    if blocks:
        blocks[-1]["cache_control"] = {"type": cache_type}
    message["content"] = blocks
    return message


def apply_anthropic_cache_control(
    messages: list[dict[str, Any]],
    cache_ttl: str = "5m",
) -> list[dict[str, Any]]:
    """Apply cache-control breakpoints using the *system_and_3* strategy.

    Parameters
    ----------
    messages:
        Serialized message dicts (already in OpenAI/Anthropic wire format).
        The list is **deep-copied** so the caller's original is never mutated.
    cache_ttl:
        Desired cache time-to-live hint.  Currently only ``"ephemeral"`` is
        supported by Anthropic, so this parameter is accepted for forward
        compatibility but the marker always uses ``{"type": "ephemeral"}``.

    Returns
    -------
    list[dict[str, Any]]
        A new list of message dicts with up to 4 ``cache_control`` markers
        injected.
    """
    if not messages:
        return []

    # Deep-copy to avoid mutating caller's data.
    messages = copy.deepcopy(messages)

    breakpoints_placed = 0

    # --- Breakpoint 1: system prompt ---
    for msg in messages:
        if msg.get("role") == "system":
            _apply_cache_marker(msg)
            breakpoints_placed += 1
            break  # only the first system message

    # --- Breakpoints 2-4: last 3 non-system messages ---
    non_system = [m for m in messages if m.get("role") != "system"]
    remaining_budget = _MAX_BREAKPOINTS - breakpoints_placed
    tail = non_system[-remaining_budget:] if remaining_budget > 0 else []
    for msg in tail:
        _apply_cache_marker(msg)
        breakpoints_placed += 1

    logger.debug(
        "prompt_caching: placed %d/%d breakpoints (cache_ttl=%s)",
        breakpoints_placed,
        _MAX_BREAKPOINTS,
        cache_ttl,
    )

    return messages


def is_anthropic_model(model_name: str) -> bool:
    """Return ``True`` if *model_name* looks like an Anthropic Claude model."""
    return model_name.startswith("claude-")
