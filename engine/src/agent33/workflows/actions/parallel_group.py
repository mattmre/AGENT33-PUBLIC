"""Action that runs sub-steps in parallel."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = structlog.get_logger()


async def execute(
    sub_step_ids: list[str],
    run_step: Callable[[str], Awaitable[dict[str, Any]]],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute a group of sub-steps concurrently.

    Args:
        sub_step_ids: List of step IDs to run in parallel.
        run_step: An async callable that executes a single step by ID
                  and returns its output dict.
        dry_run: If True, skip actual execution.

    Returns:
        A dict mapping sub-step IDs to their outputs.
    """
    logger.info("parallel_group", step_count=len(sub_step_ids))

    if dry_run:
        return {
            "dry_run": True,
            "steps": sub_step_ids,
            "results": {sid: {"dry_run": True} for sid in sub_step_ids},
        }

    tasks = [run_step(sid) for sid in sub_step_ids]
    results_list = await asyncio.gather(*tasks, return_exceptions=True)

    results: dict[str, Any] = {}
    errors: list[str] = []

    for sid, result in zip(sub_step_ids, results_list, strict=True):
        if isinstance(result, BaseException):
            errors.append(f"Step '{sid}' failed: {result}")
            results[sid] = {"error": str(result)}
        else:
            results[sid] = result

    if errors:
        logger.warning("parallel_group_partial_failure", errors=errors)

    logger.info("parallel_group_complete", completed=len(results), errors=len(errors))
    return {"results": results, "errors": errors}
