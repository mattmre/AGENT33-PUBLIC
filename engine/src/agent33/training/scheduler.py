"""Training scheduler - autonomous improvement scheduling."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent33.training.optimizer import AgentOptimizer

logger = logging.getLogger(__name__)


class TrainingScheduler:
    """Schedules optimization runs during idle periods or at intervals.

    Monitors request activity and triggers optimization when the system
    is idle or after a configurable number of requests.
    """

    def __init__(
        self,
        optimizer: AgentOptimizer,
        optimize_every_n_requests: int = 100,
        idle_optimize_seconds: int = 300,
    ) -> None:
        self._optimizer = optimizer
        self._optimize_interval = optimize_every_n_requests
        self._idle_seconds = idle_optimize_seconds
        self._request_count: int = 0
        self._last_request_time: float = time.monotonic()
        self._running: bool = False
        self._task: asyncio.Task[None] | None = None
        self._agents: dict[str, str] = {}  # agent_name -> current_prompt

    def record_request(self, agent_name: str, prompt: str) -> None:
        """Record that a request was processed."""
        self._request_count += 1
        self._last_request_time = time.monotonic()
        if agent_name not in self._agents:
            self._agents[agent_name] = prompt

    async def start(self) -> None:
        """Start the background scheduler loop."""
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("training scheduler started")

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("training scheduler stopped")

    async def _loop(self) -> None:
        """Background loop checking for optimization triggers."""
        last_optimized_count = 0

        while self._running:
            await asyncio.sleep(30)  # Check every 30 seconds

            now = time.monotonic()
            idle_time = now - self._last_request_time
            requests_since = self._request_count - last_optimized_count

            should_optimize = (requests_since >= self._optimize_interval) or (
                idle_time >= self._idle_seconds and requests_since > 0
            )

            if should_optimize and self._agents:
                logger.info(
                    "triggering optimization (requests=%d, idle=%.0fs)",
                    requests_since,
                    idle_time,
                )
                for agent_name, prompt in list(self._agents.items()):
                    try:
                        new_prompt = await self._optimizer.optimize(agent_name, prompt)
                        self._agents[agent_name] = new_prompt
                    except Exception:
                        logger.warning("optimization failed for %s", agent_name, exc_info=True)
                last_optimized_count = self._request_count
