"""Tests for streamed tool-call reassembly."""

from __future__ import annotations

from agent33.llm.base import ToolCallDelta
from agent33.llm.stream_assembler import ToolCallAssembler


def test_close_returns_empty_when_no_deltas_seen() -> None:
    assembler = ToolCallAssembler()
    assert assembler.close() == []


def test_single_tool_call_is_assembled_from_fragments() -> None:
    assembler = ToolCallAssembler()
    assembler.add_delta(ToolCallDelta(index=0, id="call_1", name="shell"))
    assembler.add_delta(ToolCallDelta(index=0, arguments_fragment='{"command": '))
    assembler.add_delta(ToolCallDelta(index=0, arguments_fragment='"dir"}'))

    tool_calls = assembler.close()

    assert len(tool_calls) == 1
    assert tool_calls[0].id == "call_1"
    assert tool_calls[0].function.name == "shell"
    assert tool_calls[0].function.arguments == '{"command": "dir"}'


def test_multiple_tool_calls_are_sorted_by_index() -> None:
    assembler = ToolCallAssembler()
    assembler.add_delta(ToolCallDelta(index=1, id="call_2", name="web_fetch"))
    assembler.add_delta(ToolCallDelta(index=1, arguments_fragment='{"url": "https://a"}'))
    assembler.add_delta(ToolCallDelta(index=0, id="call_1", name="shell"))
    assembler.add_delta(ToolCallDelta(index=0, arguments_fragment='{"command": "pwd"}'))

    tool_calls = assembler.close()

    assert [tool_call.id for tool_call in tool_calls] == ["call_1", "call_2"]
    assert [tool_call.function.name for tool_call in tool_calls] == ["shell", "web_fetch"]


def test_close_defaults_missing_id_and_arguments() -> None:
    assembler = ToolCallAssembler()
    assembler.add_delta(ToolCallDelta(index=3, name="shell"))

    tool_calls = assembler.close()

    assert tool_calls[0].id == "call_3"
    assert tool_calls[0].function.arguments == "{}"


def test_close_clears_internal_state() -> None:
    assembler = ToolCallAssembler()
    assembler.add_delta(ToolCallDelta(index=0, name="shell"))

    assert len(assembler.close()) == 1
    assert assembler.close() == []
