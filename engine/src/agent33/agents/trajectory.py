"""Trajectory saver -- captures agent conversations in ShareGPT format.

Phase 59: Persists successful and failed agent interactions as JSONL
files for downstream training/analysis.  Applies secret redaction
(Phase 52) before writing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent33.security.redaction import redact_secrets

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scratchpad / reasoning tag normalisation
# ---------------------------------------------------------------------------

# Matches <scratchpad>...</scratchpad> (case-insensitive, multiline).
_SCRATCHPAD_RE = re.compile(
    r"<scratchpad>(.*?)</scratchpad>",
    re.DOTALL | re.IGNORECASE,
)


def convert_scratchpad_to_think(content: str) -> str:
    """Normalise ``<scratchpad>`` tags to ``<think>`` tags.

    This converts hermes-agent-style reasoning blocks into the more
    widely adopted ``<think>`` format used by training pipelines.
    """

    def _replace(match: re.Match[str]) -> str:
        return f"<think>{match.group(1)}</think>"

    return _SCRATCHPAD_RE.sub(_replace, content)


# ---------------------------------------------------------------------------
# ShareGPT conversation type
# ---------------------------------------------------------------------------

ShareGPTTurn = dict[str, str]  # {"from": "human"|"gpt"|"system", "value": ...}


def _role_to_sharegpt(role: str) -> str:
    """Map standard chat roles to ShareGPT ``from`` labels."""
    mapping: dict[str, str] = {
        "user": "human",
        "assistant": "gpt",
        "system": "system",
        "tool": "tool",
    }
    return mapping.get(role, role)


# ---------------------------------------------------------------------------
# Trajectory persistence
# ---------------------------------------------------------------------------


def _build_trajectory_record(
    conversation: list[dict[str, str]],
    model: str,
    completed: bool,
    *,
    redaction_enabled: bool = True,
) -> dict[str, Any]:
    """Build a single ShareGPT-format trajectory record.

    Applies secret redaction and scratchpad normalisation to every turn.
    """
    sharegpt_turns: list[ShareGPTTurn] = []
    for turn in conversation:
        role = turn.get("role", "user")
        value = turn.get("content", "")
        # Normalise reasoning tags.
        value = convert_scratchpad_to_think(value)
        # Redact secrets before persistence.
        value = redact_secrets(value, enabled=redaction_enabled)
        sharegpt_turns.append(
            {
                "from": _role_to_sharegpt(role),
                "value": value,
            }
        )

    return {
        "conversations": sharegpt_turns,
        "model": model,
        "completed": completed,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _trajectory_filename(completed: bool) -> str:
    """Return the default JSONL filename based on outcome."""
    return "trajectories_success.jsonl" if completed else "trajectories_failed.jsonl"


def _write_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Append a single JSON record to a JSONL file (synchronous).

    Creates parent directories if needed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


async def save_trajectory(
    conversation: list[dict[str, str]],
    model: str,
    completed: bool,
    output_dir: str,
    filename: str | None = None,
    *,
    redaction_enabled: bool = True,
) -> None:
    """Persist a conversation trajectory in ShareGPT-format JSONL.

    Parameters
    ----------
    conversation:
        List of ``{"role": ..., "content": ...}`` dicts representing the
        full agent conversation.
    model:
        The model identifier used for the conversation.
    completed:
        Whether the conversation completed successfully.
    output_dir:
        Directory where trajectory files are written.
    filename:
        Optional filename override.  When *None*, a default name is
        chosen based on *completed* (``trajectories_success.jsonl`` or
        ``trajectories_failed.jsonl``).
    redaction_enabled:
        Whether to apply secret redaction (default True).
    """
    if not conversation:
        logger.debug("save_trajectory called with empty conversation, skipping")
        return

    record = _build_trajectory_record(
        conversation,
        model,
        completed,
        redaction_enabled=redaction_enabled,
    )

    resolved_filename = filename or _trajectory_filename(completed)
    file_path = Path(output_dir) / resolved_filename

    try:
        await asyncio.to_thread(_write_jsonl, file_path, record)
        logger.debug(
            "trajectory saved to %s (%d turns, completed=%s)",
            file_path,
            len(conversation),
            completed,
        )
    except Exception:
        logger.warning("failed to save trajectory to %s", file_path, exc_info=True)


def get_trajectory_stats(output_dir: str) -> dict[str, Any]:
    """Return basic stats about saved trajectories.

    Useful for health checks and monitoring dashboards.
    """
    result: dict[str, Any] = {"output_dir": output_dir, "files": {}}
    base = Path(output_dir)
    if not base.exists():
        return result

    for name in ("trajectories_success.jsonl", "trajectories_failed.jsonl"):
        p = base / name
        if p.exists():
            stat = os.stat(p)
            # Count lines (each line is one trajectory record).
            with open(p, encoding="utf-8") as fh:
                line_count = sum(1 for _ in fh)
            result["files"][name] = {
                "size_bytes": stat.st_size,
                "record_count": line_count,
            }

    return result
