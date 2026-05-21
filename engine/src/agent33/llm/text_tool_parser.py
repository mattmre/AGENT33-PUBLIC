"""Text-based tool call parsing for models without native function calling.

Provides parsers that extract tool calls from LLM text output when the model
doesn't return structured tool_calls in the API response. Only activates when
response.tool_calls is None — zero impact on native function-calling models.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

from agent33.llm.base import ToolCall, ToolCallFunction


class TextToolParser(Protocol):
    """Protocol for parsing tool calls from LLM text output."""

    def parse(self, text: str) -> list[ToolCall] | None:
        """Parse tool calls from text. Returns None if no tool calls found."""
        ...


@dataclass(frozen=True, slots=True)
class ReActParser:
    """Parses ReAct-style tool calls.

    Expected format:
        Action: tool_name
        Action Input: {"arg": "value"}
    """

    _PATTERN: re.Pattern[str] = re.compile(
        r"Action\s*:\s*(\S+)\s*\n\s*Action\s+Input\s*:\s*(.+?)(?:\n|$)",
        re.DOTALL,
    )

    def parse(self, text: str) -> list[ToolCall] | None:
        matches = list(self._PATTERN.finditer(text))
        if not matches:
            return None
        calls: list[ToolCall] = []
        for i, m in enumerate(matches):
            name = m.group(1).strip()
            raw_args = m.group(2).strip()
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                args = {"input": raw_args}
            args_str = json.dumps(args) if isinstance(args, dict) else raw_args
            calls.append(
                ToolCall(
                    id=f"text_react_{i}",
                    function=ToolCallFunction(name=name, arguments=args_str),
                )
            )
        return calls or None


@dataclass(frozen=True, slots=True)
class XMLToolParser:
    """Parses XML-style tool calls.

    Expected format:
        <tool_call>
        <name>tool_name</name>
        <arguments>{"arg": "value"}</arguments>
        </tool_call>
    """

    _PATTERN: re.Pattern[str] = re.compile(
        r"<tool_call>\s*<name>\s*(.+?)\s*</name>\s*"
        r"<arguments>\s*(.+?)\s*</arguments>\s*</tool_call>",
        re.DOTALL,
    )

    def parse(self, text: str) -> list[ToolCall] | None:
        matches = list(self._PATTERN.finditer(text))
        if not matches:
            return None
        calls: list[ToolCall] = []
        for i, m in enumerate(matches):
            name = m.group(1).strip()
            raw_args = m.group(2).strip()
            try:
                json.loads(raw_args)  # validate
                args_str = raw_args
            except json.JSONDecodeError:
                args_str = json.dumps({"input": raw_args})
            calls.append(
                ToolCall(
                    id=f"text_xml_{i}",
                    function=ToolCallFunction(name=name, arguments=args_str),
                )
            )
        return calls or None


@dataclass(frozen=True, slots=True)
class HermesToolParser:
    """Parses Hermes/ChatML-style tool calls.

    Expected format:
        <|tool_call|>{"name": "tool_name", "arguments": {"arg": "value"}}<|/tool_call|>
    """

    _PATTERN: re.Pattern[str] = re.compile(
        r"<\|tool_call\|>\s*(.+?)\s*<\|/tool_call\|>",
        re.DOTALL,
    )

    def parse(self, text: str) -> list[ToolCall] | None:
        matches = list(self._PATTERN.finditer(text))
        if not matches:
            return None
        calls: list[ToolCall] = []
        for i, m in enumerate(matches):
            raw = m.group(1).strip()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            name = data.get("name", "")
            arguments = data.get("arguments", {})
            if not name:
                continue
            args_str = json.dumps(arguments) if isinstance(arguments, dict) else str(arguments)
            calls.append(
                ToolCall(
                    id=f"text_hermes_{i}",
                    function=ToolCallFunction(name=name, arguments=args_str),
                )
            )
        return calls or None


@dataclass(frozen=True, slots=True)
class ChainedParser:
    """Tries multiple parsers in order, returns first successful parse."""

    parsers: tuple[TextToolParser, ...] = (
        ReActParser(),
        XMLToolParser(),
        HermesToolParser(),
    )

    def parse(self, text: str) -> list[ToolCall] | None:
        for parser in self.parsers:
            result = parser.parse(text)
            if result is not None:
                return result
        return None
