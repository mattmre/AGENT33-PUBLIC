"""Hook chain runners: sequential and concurrent execution."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from agent33.hooks.models import HookChainResult, HookResult

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from agent33.hooks.models import HookContext

logger = logging.getLogger(__name__)


class HookChainRunner:
    """Execute a chain of hooks sequentially with priority ordering and failure isolation.

    Generalizes the ``ConnectorExecutor`` chaining pattern from
    ``engine/src/agent33/connectors/executor.py`` into the hook framework.

    Each hook receives the context and a ``call_next`` delegate. Hooks run in
    priority order (lowest number first). Abort propagation and per-hook
    timeouts are enforced.
    """

    def __init__(
        self,
        hooks: list[Any],
        timeout_ms: float = 500.0,
        fail_open: bool = True,
    ) -> None:
        self._hooks = sorted(hooks, key=lambda h: h.priority)
        self._timeout_ms = timeout_ms
        self._fail_open = fail_open

    async def run(self, context: HookContext) -> HookContext:
        """Execute all hooks in priority order via middleware chain delegation.

        Returns the (possibly modified) context. If any hook aborts, the
        context ``abort`` flag is set and remaining hooks are skipped.
        """
        start = time.monotonic()

        # Build the chain from innermost to outermost
        async def terminal(ctx: HookContext) -> HookContext:
            return ctx

        chain: Callable[[HookContext], Awaitable[HookContext]] = terminal
        for hook in reversed(self._hooks):
            if not hook.enabled:
                continue
            downstream = chain
            current_hook = hook

            async def link(
                ctx: HookContext,
                h: Any = current_hook,
                next_fn: Callable[[HookContext], Awaitable[HookContext]] = downstream,
            ) -> HookContext:
                if ctx.abort:
                    return ctx
                hook_start = time.monotonic()
                try:
                    raw_result = await asyncio.wait_for(
                        h.execute(ctx, next_fn),
                        timeout=self._timeout_ms / 1000.0,
                    )
                    result_ctx: HookContext = raw_result
                    duration = (time.monotonic() - hook_start) * 1000
                    result_ctx.results.append(
                        HookResult(
                            hook_name=h.name,
                            success=True,
                            duration_ms=round(duration, 2),
                        )
                    )
                    return result_ctx
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    duration = (time.monotonic() - hook_start) * 1000
                    ctx.results.append(
                        HookResult(
                            hook_name=h.name,
                            success=False,
                            error=str(exc),
                            duration_ms=round(duration, 2),
                        )
                    )
                    logger.warning(
                        "hook %s failed (fail_%s): %s",
                        h.name,
                        "open" if self._fail_open else "closed",
                        exc,
                    )
                    if self._fail_open:
                        # Skip this hook, continue chain
                        return await next_fn(ctx)
                    else:
                        ctx.abort = True
                        ctx.abort_reason = f"Hook '{h.name}' failed: {exc}"
                        return ctx

            chain = link

        result_context = await chain(context)

        total_duration = (time.monotonic() - start) * 1000
        logger.debug(
            "hook_chain_complete event=%s hooks=%d duration_ms=%.2f aborted=%s",
            context.event_type,
            len(result_context.results),
            total_duration,
            result_context.abort,
        )
        return result_context

    def to_chain_result(self, context: HookContext) -> HookChainResult:
        """Build a ``HookChainResult`` summary from a completed context."""
        total_duration = sum(r.duration_ms for r in context.results)
        return HookChainResult(
            event_type=context.event_type,
            hook_results=list(context.results),
            aborted=context.abort,
            abort_reason=context.abort_reason,
            total_duration_ms=round(total_duration, 2),
        )


class ConcurrentHookChainRunner:
    """Run all hooks concurrently. Use for independent post-processing hooks.

    Unlike :class:`HookChainRunner`, this runner executes all hooks in
    parallel via ``asyncio.gather``. Each hook receives a no-op ``call_next``
    since there is no chaining. Abort from any hook is collected but does
    not stop others.
    """

    def __init__(
        self,
        hooks: list[Any],
        timeout_ms: float = 500.0,
    ) -> None:
        self._hooks = [h for h in hooks if h.enabled]
        self._timeout_ms = timeout_ms

    async def run(self, context: HookContext) -> HookContext:
        """Execute all enabled hooks concurrently."""
        if not self._hooks:
            return context

        async def _noop_next(ctx: HookContext) -> HookContext:
            return ctx

        async def _run_single(hook: Any) -> HookResult:
            hook_start = time.monotonic()
            try:
                await asyncio.wait_for(
                    hook.execute(context, _noop_next),
                    timeout=self._timeout_ms / 1000.0,
                )
                duration = (time.monotonic() - hook_start) * 1000
                return HookResult(
                    hook_name=hook.name,
                    success=True,
                    duration_ms=round(duration, 2),
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                duration = (time.monotonic() - hook_start) * 1000
                logger.warning("concurrent hook %s failed: %s", hook.name, exc)
                return HookResult(
                    hook_name=hook.name,
                    success=False,
                    error=str(exc),
                    duration_ms=round(duration, 2),
                )

        tasks = [_run_single(hook) for hook in self._hooks]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, HookResult):
                context.results.append(res)
            elif isinstance(res, BaseException):
                context.results.append(
                    HookResult(
                        hook_name="unknown",
                        success=False,
                        error=str(res),
                    )
                )

        return context
