"""Ad-hoc subagent delegation tool (Phase 53).

Allows a parent agent to dynamically spawn a child agent with fresh context
to handle a focused subtask. The child gets its own conversation, restricted
toolset, and focused system prompt built from the parent's goal and context.

Key design decisions:
  - MAX_DEPTH = 2: parent -> child only; grandchild requests are rejected.
  - Delegation depth is tracked via ``ToolContext.tool_policies["delegation_depth"]``
    so it survives serialization boundaries.
  - Blocked tools (``delegate_subtask``, ``clarify``) are stripped from the
    child's toolset to prevent recursion and user interruption.
  - Batch delegation runs up to 3 children concurrently via ``asyncio.Semaphore``.
  - The parent receives only the child's final summary, not intermediate
    tool calls or conversation history.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

from agent33.tools.base import ToolContext, ToolResult
from agent33.tools.builtin.delegate_prompts import (
    BLOCKED_TOOLS,
    build_child_system_prompt,
    strip_blocked_tools,
)

if TYPE_CHECKING:
    from agent33.llm.router import ModelRouter
    from agent33.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

MAX_DEPTH = 2
"""Maximum delegation depth. Parent is depth 0, child is depth 1.
Any request at depth >= MAX_DEPTH is rejected."""


async def _safe_emit(event_sink: Any, event: Any) -> None:
    """Emit an event through the sink, swallowing errors (fail-open)."""
    try:
        await event_sink(event)
    except Exception:
        logger.debug("event_sink failed for %s, continuing", event.event_type, exc_info=True)


_DEFAULT_MAX_ITERATIONS = 20
_DEFAULT_TIMEOUT_SECONDS = 300
_MAX_CONCURRENT_CHILDREN = 3


class _ChildToolRegistryView:
    """Allowlisted registry view used for delegated children."""

    def __init__(self, base_registry: ToolRegistry, allowed_tools: list[str]) -> None:
        self._base_registry = base_registry
        self._allowed_tools = frozenset(allowed_tools)

    def _is_allowed(self, name: str) -> bool:
        return name in self._allowed_tools

    def get(self, name: str) -> Any | None:
        if not self._is_allowed(name):
            return None
        return self._base_registry.get(name)

    def get_entry(self, name: str) -> Any | None:
        if not self._is_allowed(name):
            return None
        return self._base_registry.get_entry(name)

    def list_all(self) -> list[Any]:
        return [
            tool for tool in self._base_registry.list_all() if tool.name in self._allowed_tools
        ]

    async def validated_execute(
        self,
        name: str,
        params: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        if not self._is_allowed(name):
            return ToolResult.fail(f"Tool '{name}' is not available to delegated children")
        return await self._base_registry.validated_execute(name, params, context)


class DelegateSubtaskTool:
    """Delegate a focused subtask to a child agent with fresh context.

    Implements the ``SchemaAwareTool`` protocol.  The tool requires a
    ``ModelRouter`` and ``ToolRegistry`` at construction time (following
    the ``ApplyPatchTool`` pattern of constructor-injected dependencies).
    """

    def __init__(
        self,
        router: ModelRouter,
        tool_registry: ToolRegistry,
    ) -> None:
        self._router = router
        self._tool_registry = tool_registry
        self._semaphore = asyncio.Semaphore(_MAX_CONCURRENT_CHILDREN)

    # ------------------------------------------------------------------
    # SchemaAwareTool protocol
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "delegate_subtask"

    @property
    def description(self) -> str:
        return (
            "Delegate a focused subtask to a child agent with fresh context. "
            "The child gets its own conversation and restricted toolset. "
            "Returns a summary of the child's work."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "What the child agent should accomplish.",
                },
                "context": {
                    "type": "string",
                    "description": "Optional background context from the parent.",
                    "default": "",
                },
                "toolsets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Tool names the child may use. "
                        "Blocked tools (delegate_subtask, clarify) are automatically removed."
                    ),
                    "default": [],
                },
                "max_iterations": {
                    "type": "integer",
                    "description": "Maximum tool-loop iterations for the child.",
                    "default": _DEFAULT_MAX_ITERATIONS,
                    "minimum": 1,
                    "maximum": 100,
                },
                "model_override": {
                    "type": "string",
                    "description": "Optional model name for the child agent.",
                    "default": "",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Child execution timeout in seconds.",
                    "default": _DEFAULT_TIMEOUT_SECONDS,
                    "minimum": 10,
                    "maximum": 600,
                },
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "goal": {"type": "string"},
                            "context": {"type": "string", "default": ""},
                        },
                        "required": ["goal"],
                    },
                    "description": (
                        "Batch mode: list of subtasks to run concurrently. "
                        "When provided, 'goal' and 'context' at the top level are ignored."
                    ),
                },
            },
            "required": ["goal"],
        }

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        """Execute the delegation tool.

        Validates depth, builds a child runtime, and invokes it. Returns
        only the child's final summary to the parent.
        """
        # --- Depth enforcement -------------------------------------------
        current_depth = self._get_depth(context)
        if current_depth >= MAX_DEPTH:
            return ToolResult.fail(
                f"Delegation depth limit reached (current={current_depth}, "
                f"max={MAX_DEPTH}). Cannot delegate further."
            )

        # --- Parameter extraction ----------------------------------------
        tasks: list[dict[str, Any]] | None = params.get("tasks")
        toolsets: list[str] = params.get("toolsets", [])
        max_iterations: int = params.get("max_iterations", _DEFAULT_MAX_ITERATIONS)
        model_override: str = params.get("model_override", "")
        timeout: int = params.get("timeout", _DEFAULT_TIMEOUT_SECONDS)

        # Build child context with incremented depth
        child_context = self._build_child_context(context, current_depth)

        # --- Batch mode --------------------------------------------------
        if tasks is not None:
            return await self._execute_batch(
                tasks=tasks,
                toolsets=toolsets,
                max_iterations=max_iterations,
                model_override=model_override,
                timeout=timeout,
                child_context=child_context,
            )

        # --- Single task mode --------------------------------------------
        goal: str = params.get("goal", "").strip()
        if not goal:
            return ToolResult.fail("No goal provided for delegation.")

        task_context: str = params.get("context", "")

        return await self._execute_single(
            goal=goal,
            context=task_context,
            toolsets=toolsets,
            max_iterations=max_iterations,
            model_override=model_override,
            timeout=timeout,
            child_context=child_context,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_depth(context: ToolContext) -> int:
        """Read the current delegation depth from the tool context."""
        raw = context.tool_policies.get("delegation_depth", "0")
        try:
            return int(raw)
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _build_child_context(parent_context: ToolContext, current_depth: int) -> ToolContext:
        """Create a child ``ToolContext`` with incremented delegation depth."""
        child_policies = dict(parent_context.tool_policies)
        child_policies["delegation_depth"] = str(current_depth + 1)
        return dataclasses.replace(parent_context, tool_policies=child_policies)

    async def _execute_single(
        self,
        *,
        goal: str,
        context: str,
        toolsets: list[str],
        max_iterations: int,
        model_override: str,
        timeout: int,
        child_context: ToolContext,
    ) -> ToolResult:
        """Run a single delegated subtask and return its summary."""
        try:
            result = await asyncio.wait_for(
                self._run_child(
                    goal=goal,
                    context=context,
                    toolsets=toolsets,
                    max_iterations=max_iterations,
                    model_override=model_override,
                    child_context=child_context,
                ),
                timeout=timeout,
            )
            return result
        except TimeoutError:
            return ToolResult.fail(
                f"Child agent timed out after {timeout}s while working on: {goal[:200]}"
            )
        except Exception:
            logger.exception("Delegation failed for goal: %s", goal[:200])
            return ToolResult.fail(f"Delegation failed for goal: {goal[:200]}")

    async def _execute_batch(
        self,
        *,
        tasks: list[dict[str, Any]],
        toolsets: list[str],
        max_iterations: int,
        model_override: str,
        timeout: int,
        child_context: ToolContext,
    ) -> ToolResult:
        """Run multiple subtasks concurrently with a semaphore and aggregate results."""
        if not tasks:
            return ToolResult.fail("Empty task list for batch delegation.")

        async def _run_one(index: int, task: dict[str, Any]) -> dict[str, Any]:
            async with self._semaphore:
                goal = task.get("goal", "").strip()
                if not goal:
                    return {
                        "task_index": index,
                        "status": "error",
                        "summary": "",
                        "error": "No goal provided.",
                    }
                ctx = task.get("context", "")
                try:
                    result = await asyncio.wait_for(
                        self._run_child(
                            goal=goal,
                            context=ctx,
                            toolsets=toolsets,
                            max_iterations=max_iterations,
                            model_override=model_override,
                            child_context=child_context,
                        ),
                        timeout=timeout,
                    )
                    return {
                        "task_index": index,
                        "status": "completed" if result.success else "error",
                        "summary": result.output if result.success else "",
                        "error": result.error if not result.success else "",
                    }
                except TimeoutError:
                    return {
                        "task_index": index,
                        "status": "timeout",
                        "summary": "",
                        "error": f"Timed out after {timeout}s",
                    }
                except Exception as exc:
                    return {
                        "task_index": index,
                        "status": "error",
                        "summary": "",
                        "error": str(exc),
                    }

        # Launch all tasks concurrently (semaphore limits parallelism to 3)
        coros = [_run_one(i, task) for i, task in enumerate(tasks)]
        results = await asyncio.gather(*coros, return_exceptions=True)

        # Convert any unexpected exceptions into error dicts
        aggregated: list[dict[str, Any]] = []
        for i, r in enumerate(results):
            if isinstance(r, BaseException):
                aggregated.append(
                    {
                        "task_index": i,
                        "status": "error",
                        "summary": "",
                        "error": str(r),
                    }
                )
            else:
                aggregated.append(r)

        return ToolResult.ok(json.dumps(aggregated, indent=2))

    async def _run_child(
        self,
        *,
        goal: str,
        context: str,
        toolsets: list[str],
        max_iterations: int,
        model_override: str,
        child_context: ToolContext,
    ) -> ToolResult:
        """Spawn a child agent with fresh context and run it.

        The child agent:
        - Gets a custom system prompt built from goal + context
        - Has blocked tools removed from its toolset
        - Runs its own tool loop with max_iterations (if tools provided)
        - Returns only its final output to the caller

        When ``child_context.event_sink`` is set, the child tool loop
        runs in streaming mode (``run_stream``), and every child event
        is relayed through the sink as ``delegation_progress``.

        We bypass ``AgentRuntime`` and call the LLM router directly so
        the child gets our custom ``build_child_system_prompt`` rather
        than the standard ``_build_system_prompt(definition)`` that
        AgentRuntime generates. This ensures true conversation isolation.
        """
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig
        from agent33.llm.base import ChatMessage

        # Filter toolsets
        filtered_tools = strip_blocked_tools(toolsets) if toolsets else []

        # Log blocked tools that were removed
        removed = set(toolsets) & BLOCKED_TOOLS if toolsets else set()
        if removed:
            logger.info(
                "Stripped blocked tools from child toolset: %s",
                ", ".join(sorted(removed)),
            )

        child_tool_registry: Any = (
            _ChildToolRegistryView(self._tool_registry, filtered_tools)
            if filtered_tools
            else self._tool_registry
        )

        # Build child-specific system prompt (NOT the standard AgentRuntime prompt)
        system_prompt = build_child_system_prompt(goal, context)

        # Determine model
        model = model_override if model_override else "llama3.2"

        # Build fresh conversation messages (no parent history)
        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=json.dumps({"task": goal})),
        ]

        # If the child has tools, use a ToolLoop for iterative execution
        if filtered_tools:
            child_config = ToolLoopConfig(
                max_iterations=max_iterations,
                max_tool_calls_per_iteration=5,
                error_threshold=3,
            )
            loop = ToolLoop(
                router=self._router,
                tool_registry=child_tool_registry,
                tool_context=child_context,
                config=child_config,
                agent_name="delegate-child",
                session_id=child_context.session_id,
            )

            # --- Streaming path: relay child events through event_sink ---
            if child_context.event_sink is not None:
                return await self._run_child_streaming(
                    loop=loop,
                    messages=messages,
                    model=model,
                    goal=goal,
                    event_sink=child_context.event_sink,
                )

            # --- Non-streaming path (backward compatible) ---
            loop_result = await loop.run(
                messages=messages,
                model=model,
                temperature=0.7,
                max_tokens=4096,
            )
            raw = loop_result.raw_response
            output_text = raw if raw else json.dumps(loop_result.output)
            return ToolResult.ok(output_text)

        # No tools: single-shot LLM call
        response = await self._router.complete(
            messages,
            model=model,
            temperature=0.7,
            max_tokens=4096,
        )
        return ToolResult.ok(response.content)

    async def _run_child_streaming(
        self,
        *,
        loop: Any,
        messages: list[Any],
        model: str,
        goal: str,
        event_sink: Any,
    ) -> ToolResult:
        """Run a child tool loop in streaming mode, relaying events.

        Emits ``delegation_started`` before the child runs,
        ``delegation_progress`` for each child event, and
        ``delegation_completed`` when the child finishes.

        All event_sink errors are caught and logged (fail-open):
        delegation must succeed even if the event relay fails.
        """
        from agent33.agents.events import ToolLoopEvent

        delegation_id = uuid.uuid4().hex[:12]

        # Emit delegation_started
        await _safe_emit(
            event_sink,
            ToolLoopEvent(
                event_type="delegation_started",
                iteration=0,
                data={"goal": goal, "delegation_id": delegation_id},
            ),
        )

        # Stream child events and relay as delegation_progress
        output_text = ""
        child_status = "success"
        try:
            async for event in loop.run_stream(
                messages=messages,
                model=model,
                temperature=0.7,
                max_tokens=4096,
            ):
                await _safe_emit(
                    event_sink,
                    ToolLoopEvent(
                        event_type="delegation_progress",
                        iteration=event.iteration,
                        data={
                            "delegation_id": delegation_id,
                            "child_event_type": event.event_type,
                            "child_event": event.data,
                        },
                    ),
                )
                if event.event_type == "completed":
                    completed_data = event.data
                    raw = completed_data.get("output", {}).get("response", "")
                    if not raw:
                        raw = json.dumps(completed_data.get("output", {}))
                    output_text = raw
                    child_status = completed_data.get("termination_reason", "completed")
        except Exception:
            logger.exception(
                "Streaming delegation failed for goal: %s (delegation_id=%s)",
                goal[:200],
                delegation_id,
            )
            child_status = "error"

        # Emit delegation_completed
        await _safe_emit(
            event_sink,
            ToolLoopEvent(
                event_type="delegation_completed",
                iteration=0,
                data={
                    "delegation_id": delegation_id,
                    "status": child_status,
                },
            ),
        )

        if child_status == "error" and not output_text:
            return ToolResult.fail(f"Delegation failed for goal: {goal[:200]}")
        return ToolResult.ok(output_text)
