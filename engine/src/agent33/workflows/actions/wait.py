"""Action that waits for a specified duration or until a condition is met."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from agent33.workflows.expressions import ExpressionEvaluator

logger = structlog.get_logger()

_DEFAULT_POLL_INTERVAL = 2.0
_DEFAULT_MAX_WAIT = 300


async def execute(
    inputs: dict[str, Any],
    duration_seconds: int | None = None,
    wait_condition: str | None = None,
    timeout_seconds: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Wait for a fixed duration or until a condition becomes truthy.

    If duration_seconds is provided, sleep for that amount of time.
    If wait_condition is provided, poll the condition at regular intervals
    until it evaluates to True or the timeout is reached.

    Args:
        inputs: Context variables for condition evaluation.
        duration_seconds: Fixed number of seconds to wait.
        wait_condition: A Jinja2 expression to poll.
        timeout_seconds: Max seconds to wait when polling a condition.
        dry_run: If True, return immediately.

    Returns:
        A dict with waited_seconds and whether condition was met.
    """
    logger.info(
        "wait",
        duration_seconds=duration_seconds,
        has_condition=wait_condition is not None,
    )

    if dry_run:
        return {"dry_run": True, "waited_seconds": 0}

    # Fixed duration wait
    if duration_seconds is not None and wait_condition is None:
        await asyncio.sleep(duration_seconds)
        return {"waited_seconds": duration_seconds, "condition_met": True}

    # Condition-based wait with polling
    if wait_condition is not None:
        evaluator = ExpressionEvaluator()
        max_wait = timeout_seconds or _DEFAULT_MAX_WAIT
        start = time.monotonic()

        while True:
            elapsed = time.monotonic() - start
            try:
                result = evaluator.evaluate_condition(wait_condition, inputs)
                if result:
                    waited = time.monotonic() - start
                    logger.info("wait_condition_met", waited_seconds=waited)
                    return {"waited_seconds": waited, "condition_met": True}
            except Exception as exc:
                logger.warning("wait_condition_error", error=str(exc))

            if elapsed >= max_wait:
                waited = time.monotonic() - start
                logger.warning("wait_timeout", waited_seconds=waited)
                return {"waited_seconds": waited, "condition_met": False}

            await asyncio.sleep(min(_DEFAULT_POLL_INTERVAL, max_wait - elapsed))

    # No duration or condition -- no-op
    return {"waited_seconds": 0, "condition_met": True}
