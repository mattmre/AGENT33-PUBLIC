"""Helpers for reconstructing streamed tool calls."""

from __future__ import annotations

import dataclasses

from agent33.llm.base import ToolCall, ToolCallDelta, ToolCallFunction


@dataclasses.dataclass(slots=True)
class _PartialToolCall:
    id: str = ""
    name: str = ""
    arguments_parts: list[str] = dataclasses.field(default_factory=list)


class ToolCallAssembler:
    """Accumulate tool-call deltas and emit complete tool calls."""

    def __init__(self) -> None:
        self._partials: dict[int, _PartialToolCall] = {}

    def add_delta(self, delta: ToolCallDelta | None) -> None:
        """Record a streamed tool-call fragment."""
        if delta is None:
            return
        partial = self._partials.setdefault(delta.index, _PartialToolCall())
        if delta.id:
            partial.id = delta.id
        if delta.name:
            partial.name = delta.name
        if delta.arguments_fragment:
            partial.arguments_parts.append(delta.arguments_fragment)

    def close(self) -> list[ToolCall]:
        """Finalize and return all assembled tool calls."""
        tool_calls: list[ToolCall] = []
        for index in sorted(self._partials):
            partial = self._partials[index]
            if not partial.name:
                continue
            arguments = "".join(partial.arguments_parts).strip() or "{}"
            tool_calls.append(
                ToolCall(
                    id=partial.id or f"call_{index}",
                    function=ToolCallFunction(name=partial.name, arguments=arguments),
                )
            )
        self._partials.clear()
        return tool_calls
