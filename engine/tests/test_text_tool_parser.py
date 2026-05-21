"""Tests for text-based tool call parsing (Phase 36)."""

from __future__ import annotations

import json

from agent33.llm.text_tool_parser import (
    ChainedParser,
    HermesToolParser,
    ReActParser,
    XMLToolParser,
)

PLAIN_TEXT = "The weather today is sunny with a high of 72°F."


# ---------------------------------------------------------------------------
# ReActParser
# ---------------------------------------------------------------------------


class TestReActParser:
    def test_single_tool_call(self) -> None:
        text = (
            "Thought: I need to search for the answer.\n"
            "Action: search\n"
            'Action Input: {"query": "best pizza"}\n'
        )
        parser = ReActParser()
        result = parser.parse(text)
        assert result is not None
        assert len(result) == 1
        tc = result[0]
        assert tc.id == "text_react_0"
        assert tc.function.name == "search"
        assert json.loads(tc.function.arguments) == {"query": "best pizza"}

    def test_multiple_tool_calls(self) -> None:
        text = (
            "Action: search\n"
            'Action Input: {"query": "python"}\n'
            "some intermediate text\n"
            "Action: calculate\n"
            'Action Input: {"expr": "2+2"}\n'
        )
        parser = ReActParser()
        result = parser.parse(text)
        assert result is not None
        assert len(result) == 2
        assert result[0].function.name == "search"
        assert result[1].function.name == "calculate"
        assert result[0].id == "text_react_0"
        assert result[1].id == "text_react_1"

    def test_invalid_json_wraps_input(self) -> None:
        text = "Action: lookup\nAction Input: not valid json\n"
        parser = ReActParser()
        result = parser.parse(text)
        assert result is not None
        assert len(result) == 1
        args = json.loads(result[0].function.arguments)
        assert args == {"input": "not valid json"}

    def test_no_match_returns_none(self) -> None:
        parser = ReActParser()
        assert parser.parse(PLAIN_TEXT) is None

    def test_plain_text_returns_none(self) -> None:
        parser = ReActParser()
        assert parser.parse("Just a normal response with no tool patterns.") is None


# ---------------------------------------------------------------------------
# XMLToolParser
# ---------------------------------------------------------------------------


class TestXMLToolParser:
    def test_valid_tool_call(self) -> None:
        text = (
            "<tool_call>\n"
            "  <name>get_weather</name>\n"
            '  <arguments>{"city": "London"}</arguments>\n'
            "</tool_call>"
        )
        parser = XMLToolParser()
        result = parser.parse(text)
        assert result is not None
        assert len(result) == 1
        tc = result[0]
        assert tc.id == "text_xml_0"
        assert tc.function.name == "get_weather"
        assert json.loads(tc.function.arguments) == {"city": "London"}

    def test_malformed_json_wraps_input(self) -> None:
        text = (
            "<tool_call>\n"
            "  <name>do_thing</name>\n"
            "  <arguments>not json at all</arguments>\n"
            "</tool_call>"
        )
        parser = XMLToolParser()
        result = parser.parse(text)
        assert result is not None
        assert len(result) == 1
        args = json.loads(result[0].function.arguments)
        assert args == {"input": "not json at all"}

    def test_multiple_xml_calls(self) -> None:
        text = (
            '<tool_call><name>a</name><arguments>{"x": 1}</arguments></tool_call>\n'
            '<tool_call><name>b</name><arguments>{"y": 2}</arguments></tool_call>'
        )
        parser = XMLToolParser()
        result = parser.parse(text)
        assert result is not None
        assert len(result) == 2
        assert result[0].function.name == "a"
        assert result[1].function.name == "b"

    def test_no_match_returns_none(self) -> None:
        parser = XMLToolParser()
        assert parser.parse(PLAIN_TEXT) is None


# ---------------------------------------------------------------------------
# HermesToolParser
# ---------------------------------------------------------------------------


class TestHermesToolParser:
    def test_valid_json(self) -> None:
        text = '<|tool_call|>{"name": "calc", "arguments": {"expr": "1+1"}}<|/tool_call|>'
        parser = HermesToolParser()
        result = parser.parse(text)
        assert result is not None
        assert len(result) == 1
        tc = result[0]
        assert tc.id == "text_hermes_0"
        assert tc.function.name == "calc"
        assert json.loads(tc.function.arguments) == {"expr": "1+1"}

    def test_missing_name_skipped(self) -> None:
        text = '<|tool_call|>{"arguments": {"x": 1}}<|/tool_call|>'
        parser = HermesToolParser()
        result = parser.parse(text)
        # The match is found but name is empty, so it's skipped → None
        assert result is None

    def test_invalid_json_skipped(self) -> None:
        text = "<|tool_call|>not json<|/tool_call|>"
        parser = HermesToolParser()
        result = parser.parse(text)
        assert result is None

    def test_no_match_returns_none(self) -> None:
        parser = HermesToolParser()
        assert parser.parse(PLAIN_TEXT) is None


# ---------------------------------------------------------------------------
# ChainedParser
# ---------------------------------------------------------------------------


class TestChainedParser:
    def test_tries_parsers_in_order_react_first(self) -> None:
        text = 'Action: search\nAction Input: {"q": "hello"}\n'
        parser = ChainedParser()
        result = parser.parse(text)
        assert result is not None
        # Should match ReAct (first parser)
        assert result[0].id.startswith("text_react_")

    def test_falls_through_to_xml(self) -> None:
        text = '<tool_call><name>foo</name><arguments>{"bar": 1}</arguments></tool_call>'
        parser = ChainedParser()
        result = parser.parse(text)
        assert result is not None
        assert result[0].id.startswith("text_xml_")

    def test_falls_through_to_hermes(self) -> None:
        text = '<|tool_call|>{"name": "baz", "arguments": {}}<|/tool_call|>'
        parser = ChainedParser()
        result = parser.parse(text)
        assert result is not None
        assert result[0].id.startswith("text_hermes_")

    def test_returns_none_when_none_match(self) -> None:
        parser = ChainedParser()
        assert parser.parse(PLAIN_TEXT) is None

    def test_all_parsers_return_none_for_plain_text(self) -> None:
        """Verify every individual parser returns None for plain text."""
        for parser in (ReActParser(), XMLToolParser(), HermesToolParser(), ChainedParser()):
            assert parser.parse(PLAIN_TEXT) is None
