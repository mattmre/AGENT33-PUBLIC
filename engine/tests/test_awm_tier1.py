"""Comprehensive tests for AWM Tier 1 adaptations.

Covers:
- A4: TokenCounter protocol and implementations
- A1: MCP interface interop bridge
- A2: Database-backed verification
- A3: Multi-turn evaluation scenarios
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from agent33.agents.tokenizer import (
    EstimateTokenCounter,
    TiktokenCounter,
    TokenCounter,
    create_token_counter,
)
from agent33.evaluation.db_verifier import (
    ComparisonMode,
    DatabaseVerifier,
    VerificationResult,
    VerificationSpec,
)
from agent33.evaluation.multi_turn import (
    MultiTurnEvaluator,
    MultiTurnResult,
    MultiTurnScenario,
    ToolCallCheckResult,
    ToolCallExpectation,
    ToolCallRecord,
)
from agent33.tools.mcp_bridge import (
    MCPBridge,
    MCPServerConnection,
    MCPToolAdapter,
    MCPToolSpec,
)


class TestEstimateTokenCounter:
    """Tests for the heuristic-based token counter."""

    def test_count_short_text(self) -> None:
        counter = EstimateTokenCounter()
        result = counter.count("Hello world")
        assert result >= 1
        assert result == int(len("Hello world") / 3.5)

    def test_count_long_text(self) -> None:
        counter = EstimateTokenCounter()
        text = "x" * 3500
        result = counter.count(text)
        assert result == 1000  # 3500 / 3.5

    def test_count_empty_string(self) -> None:
        counter = EstimateTokenCounter()
        assert counter.count("") == 0

    def test_count_single_char(self) -> None:
        counter = EstimateTokenCounter()
        assert counter.count("a") == 1  # max(1, int(1/3.5)) = max(1, 0) = 1

    def test_count_custom_chars_per_token(self) -> None:
        counter = EstimateTokenCounter(chars_per_token=4.0)
        assert counter.count("12345678") == 2  # 8/4.0

    def test_count_messages_single(self) -> None:
        counter = EstimateTokenCounter()
        msgs = [{"role": "user", "content": "Hello world"}]
        result = counter.count_messages(msgs)
        # overhead (4) + content tokens + reply priming (3)
        expected = 4 + counter.count("Hello world") + counter.count("user") + 3
        assert result == expected

    def test_count_messages_multiple(self) -> None:
        counter = EstimateTokenCounter()
        msgs = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]
        result = counter.count_messages(msgs)
        # 2 messages * 4 overhead + tokens for all strings + 3 priming
        assert result > 0

    def test_count_messages_with_name_key(self) -> None:
        counter = EstimateTokenCounter()
        msgs = [{"role": "user", "content": "Hi", "name": "bob"}]
        result = counter.count_messages(msgs)
        # Should count the "name" value as a string too
        assert result > 0

    def test_count_messages_empty_list(self) -> None:
        counter = EstimateTokenCounter()
        # Just the reply priming
        assert counter.count_messages([]) == 3

    def test_count_messages_non_string_values(self) -> None:
        counter = EstimateTokenCounter()
        msgs = [{"role": "user", "content": "hello", "tool_calls": [1, 2]}]
        # Non-string values should not be counted as text
        result = counter.count_messages(msgs)
        expected_without_list = counter.count_messages([{"role": "user", "content": "hello"}])
        assert result == expected_without_list

    def test_name_property(self) -> None:
        counter = EstimateTokenCounter()
        assert counter.name == "estimate"

    def test_protocol_compliance(self) -> None:
        counter = EstimateTokenCounter()
        assert isinstance(counter, TokenCounter)


class TestTiktokenCounter:
    """Tests for the tiktoken-based counter."""

    def test_count_with_tiktoken_available(self) -> None:
        mock_encoding = MagicMock()
        mock_encoding.encode.return_value = [1, 2, 3, 4, 5]

        counter = TiktokenCounter.__new__(TiktokenCounter)
        counter._fallback = EstimateTokenCounter()
        counter._encoding = mock_encoding
        counter._available = True

        assert counter.count("Hello world") == 5
        mock_encoding.encode.assert_called_with("Hello world")

    def test_count_falls_back_when_import_fails(self) -> None:
        with patch.dict("sys.modules", {"tiktoken": None}):
            counter = TiktokenCounter(model="gpt-4o")
            # Should fall back to estimate
            assert not counter._available
            result = counter.count("Hello world")
            assert result == EstimateTokenCounter().count("Hello world")

    def test_count_messages_with_tiktoken(self) -> None:
        mock_encoding = MagicMock()
        mock_encoding.encode.side_effect = lambda text: list(range(len(text.split())))

        counter = TiktokenCounter.__new__(TiktokenCounter)
        counter._fallback = EstimateTokenCounter()
        counter._encoding = mock_encoding
        counter._available = True

        msgs = [{"role": "user", "content": "hello world"}]
        result = counter.count_messages(msgs)
        # 4 (overhead) + encode("user") + encode("hello world") + 3 (priming)
        assert result > 0

    def test_count_messages_name_key_adjustment(self) -> None:
        """Verify the -1 adjustment for name keys per OpenAI token counting."""
        mock_encoding = MagicMock()
        # Each encode returns 5 tokens regardless of text
        mock_encoding.encode.return_value = [1, 2, 3, 4, 5]

        counter = TiktokenCounter.__new__(TiktokenCounter)
        counter._fallback = EstimateTokenCounter()
        counter._encoding = mock_encoding
        counter._available = True

        msgs_no_name = [{"role": "user", "content": "hi"}]
        msgs_with_name = [{"role": "user", "content": "hi", "name": "bob"}]
        result_no_name = counter.count_messages(msgs_no_name)
        result_with_name = counter.count_messages(msgs_with_name)
        # Without name: 4 (overhead) + 5 (role) + 5 (content) + 3 (priming) = 17
        assert result_no_name == 17
        # With name: 4 + 5 (role) + 5 (content) + 5 (name_value) - 1 (name_key) + 3 = 21
        assert result_with_name == 21
        assert result_with_name > result_no_name

    def test_count_messages_fallback(self) -> None:
        counter = TiktokenCounter.__new__(TiktokenCounter)
        counter._fallback = EstimateTokenCounter()
        counter._encoding = None
        counter._available = False

        msgs = [{"role": "user", "content": "hi"}]
        result = counter.count_messages(msgs)
        expected = EstimateTokenCounter().count_messages(msgs)
        assert result == expected

    def test_name_property_available(self) -> None:
        counter = TiktokenCounter.__new__(TiktokenCounter)
        counter._fallback = EstimateTokenCounter()
        counter._encoding = MagicMock()
        counter._available = True
        assert counter.name == "tiktoken"

    def test_name_property_fallback(self) -> None:
        counter = TiktokenCounter.__new__(TiktokenCounter)
        counter._fallback = EstimateTokenCounter()
        counter._encoding = None
        counter._available = False
        assert counter.name == "tiktoken-fallback(estimate)"

    def test_protocol_compliance(self) -> None:
        counter = TiktokenCounter.__new__(TiktokenCounter)
        counter._fallback = EstimateTokenCounter()
        counter._encoding = None
        counter._available = False
        assert isinstance(counter, TokenCounter)


class TestCreateTokenCounter:
    """Tests for the factory function."""

    def test_prefer_tiktoken_true_falls_back(self) -> None:
        # tiktoken is unlikely to be installed in test env
        counter = create_token_counter(prefer_tiktoken=True)
        # Should either be tiktoken or estimate
        assert counter.name in ("tiktoken", "estimate")

    def test_prefer_tiktoken_false(self) -> None:
        counter = create_token_counter(prefer_tiktoken=False)
        assert counter.name == "estimate"

    def test_returns_protocol_instance(self) -> None:
        counter = create_token_counter()
        assert isinstance(counter, TokenCounter)

    def test_custom_model(self) -> None:
        counter = create_token_counter(prefer_tiktoken=True, model="gpt-3.5-turbo")
        assert counter.name in ("tiktoken", "estimate")


class TestTokenCounterIntegration:
    """Tests that existing subsystems accept and use TokenCounter."""

    def test_context_manager_with_custom_counter(self) -> None:
        from agent33.agents.context_manager import ContextManager
        from agent33.llm.base import ChatMessage

        # Custom counter that always returns 10
        mock_counter = MagicMock(spec=TokenCounter)
        mock_counter.count.return_value = 10
        mock_counter.count_messages.return_value = 50

        mgr = ContextManager(token_counter=mock_counter)
        assert mgr.token_counter is mock_counter

        msgs = [ChatMessage(role="user", content="Hello")]
        snap = mgr.snapshot(msgs)
        # Should have called count_messages on our mock
        mock_counter.count_messages.assert_called_once()
        assert snap.total_tokens == 50

    def test_context_manager_backward_compat(self) -> None:
        from agent33.agents.context_manager import ContextManager
        from agent33.llm.base import ChatMessage

        # No token_counter arg — should use default EstimateTokenCounter
        mgr = ContextManager()
        msgs = [ChatMessage(role="user", content="Hello world")]
        snap = mgr.snapshot(msgs)
        assert snap.total_tokens > 0

    def test_context_manager_default_counter_type(self) -> None:
        from agent33.agents.context_manager import ContextManager

        mgr = ContextManager()
        assert isinstance(mgr.token_counter, EstimateTokenCounter)

    def test_token_aware_chunker_with_custom_counter(self) -> None:
        from agent33.memory.ingestion import TokenAwareChunker

        # Counter that returns 5 tokens for any text
        mock_counter = MagicMock(spec=TokenCounter)
        mock_counter.count.return_value = 5

        chunker = TokenAwareChunker(chunk_tokens=20, token_counter=mock_counter)
        text = "Sentence one. Sentence two. Sentence three. Sentence four."
        chunks = chunker.chunk_text(text)
        # With 5 tokens per sentence and 20 token limit, should produce chunks
        assert len(chunks) >= 1
        mock_counter.count.assert_called()

    def test_token_aware_chunker_backward_compat(self) -> None:
        from agent33.memory.ingestion import TokenAwareChunker

        chunker = TokenAwareChunker()
        text = "Hello world. This is a test."
        chunks = chunker.chunk_text(text)
        assert len(chunks) >= 1

    def test_short_term_memory_with_custom_counter(self) -> None:
        from agent33.memory.short_term import ShortTermMemory

        mock_counter = MagicMock(spec=TokenCounter)
        mock_counter.count.return_value = 10

        mem = ShortTermMemory(token_counter=mock_counter)
        mem.add("user", "Hello")
        mem.add("assistant", "World")
        count = mem.token_count()
        assert count == 20  # 2 messages * 10 tokens each
        assert mock_counter.count.call_count == 2

    def test_short_term_memory_backward_compat(self) -> None:
        from agent33.memory.short_term import ShortTermMemory

        mem = ShortTermMemory()
        mem.add("user", "Hello world")
        count = mem.token_count()
        assert count > 0

    def test_short_term_memory_get_context_with_counter(self) -> None:
        from agent33.memory.short_term import ShortTermMemory

        mock_counter = MagicMock(spec=TokenCounter)
        mock_counter.count.return_value = 10

        mem = ShortTermMemory(token_counter=mock_counter)
        mem.add("user", "First")
        mem.add("user", "Second")
        mem.add("user", "Third")
        # max_tokens=25 should fit 2 messages (10 each = 20)
        context = mem.get_context(max_tokens=25)
        assert len(context) == 2
        # Should keep the most recent
        assert context[-1]["content"] == "Third"


# ---------------------------------------------------------------------------
# A1: MCP Bridge
# ---------------------------------------------------------------------------


class TestMCPToolSpec:
    """Tests for the MCP tool specification model."""

    def test_basic_creation(self) -> None:
        spec = MCPToolSpec(name="calculator", description="Performs math")
        assert spec.name == "calculator"
        assert spec.description == "Performs math"
        assert spec.input_schema == {}

    def test_with_schema(self) -> None:
        schema = {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        }
        spec = MCPToolSpec(name="calc", description="Math", input_schema=schema)
        assert spec.input_schema["type"] == "object"
        assert "expression" in spec.input_schema["properties"]

    def test_empty_description(self) -> None:
        spec = MCPToolSpec(name="test")
        assert spec.description == ""

    def test_serialization_roundtrip(self) -> None:
        spec = MCPToolSpec(name="x", description="y", input_schema={"type": "object"})
        data = spec.model_dump()
        restored = MCPToolSpec.model_validate(data)
        assert restored == spec


class TestMCPServerConnection:
    """Tests for MCP server connection management."""

    def test_initial_state(self) -> None:
        conn = MCPServerConnection(name="test", url="https://mcp.example.com")
        assert conn.name == "test"
        assert conn.url == "https://mcp.example.com"
        assert not conn.connected
        assert conn.tools == []

    def test_url_trailing_slash_stripped(self) -> None:
        conn = MCPServerConnection(name="test", url="https://mcp.example.com/")
        assert conn.url == "https://mcp.example.com"

    def test_localhost_url_rejected(self) -> None:
        with pytest.raises(ValueError, match="blocked by SSRF policy"):
            MCPServerConnection(name="test", url="http://localhost:8080")

    @pytest.mark.asyncio
    async def test_connect_discovers_tools(self) -> None:
        conn = MCPServerConnection(name="test", url="https://mcp.example.com")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "tools": [
                    {
                        "name": "calc",
                        "description": "Calculator",
                        "inputSchema": {"type": "object"},
                    }
                ]
            }
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        conn._client = mock_client

        # Monkey-patch to skip creating a real client
        async def patched_connect() -> None:
            conn._tools = await conn.list_tools()
            conn._connected = True

        conn.connect = patched_connect  # type: ignore[assignment]
        await conn.connect()

        assert conn.connected
        assert len(conn.tools) == 1
        assert conn.tools[0].name == "calc"

    @pytest.mark.asyncio
    async def test_disconnect(self) -> None:
        conn = MCPServerConnection(name="test", url="https://mcp.example.com")
        mock_client = AsyncMock()
        conn._client = mock_client
        conn._connected = True
        conn._tools = [MCPToolSpec(name="x")]

        await conn.disconnect()
        assert not conn.connected
        assert conn.tools == []
        mock_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_tools(self) -> None:
        conn = MCPServerConnection(name="test", url="https://mcp.example.com")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "tools": [
                    {"name": "tool1", "description": "T1", "inputSchema": {}},
                    {"name": "tool2", "description": "T2"},
                ]
            }
        }
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        conn._client = mock_client

        tools = await conn.list_tools()
        assert len(tools) == 2
        assert tools[0].name == "tool1"
        assert tools[1].name == "tool2"

    @pytest.mark.asyncio
    async def test_call_tool(self) -> None:
        conn = MCPServerConnection(name="test", url="https://mcp.example.com")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"result": {"content": [{"type": "text", "text": "42"}]}}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        conn._client = mock_client

        result = await conn.call_tool("calc", {"expr": "6*7"})
        assert result == [{"type": "text", "text": "42"}]

    @pytest.mark.asyncio
    async def test_health_check_success(self) -> None:
        conn = MCPServerConnection(name="test", url="https://mcp.example.com")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"result": {}}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        conn._client = mock_client

        assert await conn.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self) -> None:
        conn = MCPServerConnection(name="test", url="https://mcp.example.com")
        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("Connection refused")
        conn._client = mock_client

        assert await conn.health_check() is False

    @pytest.mark.asyncio
    async def test_rpc_error_response(self) -> None:
        conn = MCPServerConnection(name="test", url="https://mcp.example.com")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"error": {"code": -32600, "message": "Invalid request"}}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        conn._client = mock_client

        with pytest.raises(RuntimeError, match="Invalid request"):
            await conn._rpc("bad_method", {})

    @pytest.mark.asyncio
    async def test_timeout_configuration(self) -> None:
        conn = MCPServerConnection(name="test", url="https://mcp.example.com", timeout=5.0)
        assert conn._timeout == 5.0


class TestMCPToolAdapter:
    """Tests for the MCP-to-AGENT33 tool adapter."""

    def _make_adapter(self) -> MCPToolAdapter:
        spec = MCPToolSpec(
            name="search",
            description="Search the web",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )
        conn = MCPServerConnection(name="test", url="https://mcp.example.com")
        return MCPToolAdapter(spec=spec, connection=conn)

    def test_name_property(self) -> None:
        adapter = self._make_adapter()
        assert adapter.name == "search"

    def test_description_property(self) -> None:
        adapter = self._make_adapter()
        assert adapter.description == "Search the web"

    def test_parameters_schema(self) -> None:
        adapter = self._make_adapter()
        schema = adapter.parameters_schema
        assert schema["type"] == "object"
        assert "query" in schema["properties"]

    @pytest.mark.asyncio
    async def test_execute_delegates_to_connection(self) -> None:
        adapter = self._make_adapter()
        adapter._connection.call_tool = AsyncMock(return_value="result text")

        from agent33.tools.base import ToolContext

        ctx = ToolContext()
        result = await adapter.execute({"query": "test"}, ctx)
        assert result.success
        assert result.output == "result text"
        adapter._connection.call_tool.assert_called_once_with("search", {"query": "test"})

    @pytest.mark.asyncio
    async def test_execute_handles_content_blocks(self) -> None:
        adapter = self._make_adapter()
        adapter._connection.call_tool = AsyncMock(
            return_value=[
                {"type": "text", "text": "line1"},
                {"type": "text", "text": "line2"},
            ]
        )

        from agent33.tools.base import ToolContext

        result = await adapter.execute({"query": "test"}, ToolContext())
        assert result.success
        assert "line1" in result.output
        assert "line2" in result.output

    @pytest.mark.asyncio
    async def test_execute_handles_error(self) -> None:
        adapter = self._make_adapter()
        adapter._connection.call_tool = AsyncMock(side_effect=RuntimeError("Server error"))

        from agent33.tools.base import ToolContext

        result = await adapter.execute({"query": "test"}, ToolContext())
        assert not result.success
        assert "Server error" in result.error

    @pytest.mark.asyncio
    async def test_validated_execute_passes_valid_params(self) -> None:
        adapter = self._make_adapter()
        adapter._connection.call_tool = AsyncMock(return_value="ok")

        from agent33.tools.base import ToolContext

        result = await adapter.validated_execute({"query": "test"}, ToolContext())
        assert result.success

    @pytest.mark.asyncio
    async def test_validated_execute_rejects_invalid_params(self) -> None:
        adapter = self._make_adapter()

        from agent33.tools.base import ToolContext

        result = await adapter.validated_execute({}, ToolContext())
        assert not result.success
        assert "validation failed" in result.error.lower()

    def test_schema_aware_tool_interface(self) -> None:
        """Verify adapter satisfies SchemaAwareTool protocol structurally."""
        adapter = self._make_adapter()
        # Check all required attributes exist
        assert hasattr(adapter, "name")
        assert hasattr(adapter, "description")
        assert hasattr(adapter, "parameters_schema")
        assert hasattr(adapter, "execute")


class TestMCPBridge:
    """Tests for the top-level MCP bridge manager."""

    def test_add_server(self) -> None:
        bridge = MCPBridge()
        bridge.add_server("local", "https://mcp.example.com")
        assert "local" in bridge._servers

    def test_add_server_with_timeout(self) -> None:
        bridge = MCPBridge()
        bridge.add_server("local", "https://mcp.example.com", timeout=5.0)
        assert bridge._servers["local"]._timeout == 5.0

    @pytest.mark.asyncio
    async def test_initialize_registers_tools(self) -> None:
        mock_registry = MagicMock()
        bridge = MCPBridge(tool_registry=mock_registry)
        bridge.add_server("test", "https://mcp.example.com")

        # Patch the connection to return tools
        conn = bridge._servers["test"]
        conn.connect = AsyncMock()
        conn._tools = [
            MCPToolSpec(name="tool_a", description="A"),
            MCPToolSpec(name="tool_b", description="B"),
        ]
        conn._connected = True

        await bridge.initialize()

        assert len(bridge.get_mcp_tools()) == 2
        assert mock_registry.register.call_count == 2

    @pytest.mark.asyncio
    async def test_initialize_handles_connection_failure(self) -> None:
        bridge = MCPBridge()
        bridge.add_server("bad", "https://bad.example.com")
        conn = bridge._servers["bad"]
        conn.connect = AsyncMock(side_effect=Exception("Connection refused"))

        # Should not raise
        await bridge.initialize()
        assert len(bridge.get_mcp_tools()) == 0

    @pytest.mark.asyncio
    async def test_shutdown(self) -> None:
        bridge = MCPBridge()
        bridge.add_server("test", "https://mcp.example.com")
        conn = bridge._servers["test"]
        conn.disconnect = AsyncMock()

        await bridge.shutdown()
        conn.disconnect.assert_called_once()
        assert len(bridge.get_mcp_tools()) == 0

    @pytest.mark.asyncio
    async def test_get_mcp_tools_empty(self) -> None:
        bridge = MCPBridge()
        assert bridge.get_mcp_tools() == []

    @pytest.mark.asyncio
    async def test_no_registry(self) -> None:
        """Bridge works without a tool registry (tools still discoverable)."""
        bridge = MCPBridge(tool_registry=None)
        bridge.add_server("test", "https://mcp.example.com")
        conn = bridge._servers["test"]
        conn.connect = AsyncMock()
        conn._tools = [MCPToolSpec(name="solo")]
        conn._connected = True

        await bridge.initialize()
        assert len(bridge.get_mcp_tools()) == 1


# ---------------------------------------------------------------------------
# A2: Database Verification
# ---------------------------------------------------------------------------


class TestComparisonMode:
    """Tests for the ComparisonMode enum."""

    def test_exact(self) -> None:
        assert ComparisonMode.EXACT == "exact"

    def test_contains(self) -> None:
        assert ComparisonMode.CONTAINS == "contains"

    def test_row_count(self) -> None:
        assert ComparisonMode.ROW_COUNT == "row_count"

    def test_not_empty(self) -> None:
        assert ComparisonMode.NOT_EMPTY == "not_empty"

    def test_regex(self) -> None:
        assert ComparisonMode.REGEX == "regex"

    def test_json_subset(self) -> None:
        assert ComparisonMode.JSON_SUBSET == "json_subset"

    def test_all_values(self) -> None:
        assert len(ComparisonMode) == 6


class TestVerificationSpec:
    """Tests for the verification specification model."""

    def test_basic_creation(self) -> None:
        spec = VerificationSpec(name="check1", query="SELECT 1")
        assert spec.name == "check1"
        assert spec.query == "SELECT 1"
        assert spec.comparison_mode == ComparisonMode.EXACT
        assert spec.database == "default"
        assert spec.timeout_seconds == 10.0

    def test_custom_values(self) -> None:
        spec = VerificationSpec(
            name="check2",
            query="SELECT count(*) FROM users",
            expected=5,
            comparison_mode=ComparisonMode.ROW_COUNT,
            database="analytics",
            timeout_seconds=30.0,
        )
        assert spec.expected == 5
        assert spec.comparison_mode == ComparisonMode.ROW_COUNT
        assert spec.database == "analytics"

    def test_timeout_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            VerificationSpec(name="bad", query="SELECT 1", timeout_seconds=0)

    def test_timeout_must_be_positive_negative(self) -> None:
        with pytest.raises(ValidationError):
            VerificationSpec(name="bad", query="SELECT 1", timeout_seconds=-1)


class TestVerificationResult:
    """Tests for the verification result model."""

    def test_passed_result(self) -> None:
        result = VerificationResult(
            spec_name="test", passed=True, actual_value=42, expected_value=42
        )
        assert result.passed
        assert result.error_message is None

    def test_failed_result(self) -> None:
        result = VerificationResult(
            spec_name="test",
            passed=False,
            error_message="Mismatch",
            actual_value=41,
            expected_value=42,
        )
        assert not result.passed
        assert result.error_message == "Mismatch"

    def test_duration_default(self) -> None:
        result = VerificationResult(spec_name="test", passed=True)
        assert result.duration_ms == 0.0


class TestDatabaseVerifier:
    """Tests for the DatabaseVerifier class."""

    @pytest.mark.asyncio
    async def test_exact_match_pass(self) -> None:
        rows = [{"id": 1, "name": "Alice"}]
        executor: AsyncMock = AsyncMock(return_value=rows)
        verifier = DatabaseVerifier(execute_query=executor)
        spec = VerificationSpec(
            name="exact_test",
            query="SELECT * FROM users WHERE id=1",
            expected=[{"id": 1, "name": "Alice"}],
            comparison_mode=ComparisonMode.EXACT,
        )
        result = await verifier.verify(spec)
        assert result.passed
        assert result.actual_value == rows

    @pytest.mark.asyncio
    async def test_exact_match_fail(self) -> None:
        executor: AsyncMock = AsyncMock(return_value=[{"id": 1, "name": "Bob"}])
        verifier = DatabaseVerifier(execute_query=executor)
        spec = VerificationSpec(
            name="exact_fail",
            query="SELECT * FROM users",
            expected=[{"id": 1, "name": "Alice"}],
            comparison_mode=ComparisonMode.EXACT,
        )
        result = await verifier.verify(spec)
        assert not result.passed
        assert "Expected" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_contains_string_pass(self) -> None:
        executor: AsyncMock = AsyncMock(return_value=[{"name": "Alice Wonderland"}])
        verifier = DatabaseVerifier(execute_query=executor)
        spec = VerificationSpec(
            name="contains_str",
            query="SELECT name FROM users",
            expected="Alice",
            comparison_mode=ComparisonMode.CONTAINS,
        )
        result = await verifier.verify(spec)
        assert result.passed

    @pytest.mark.asyncio
    async def test_contains_string_fail(self) -> None:
        executor: AsyncMock = AsyncMock(return_value=[{"name": "Bob"}])
        verifier = DatabaseVerifier(execute_query=executor)
        spec = VerificationSpec(
            name="contains_fail",
            query="SELECT name FROM users",
            expected="Alice",
            comparison_mode=ComparisonMode.CONTAINS,
        )
        result = await verifier.verify(spec)
        assert not result.passed

    @pytest.mark.asyncio
    async def test_contains_dict_pass(self) -> None:
        executor: AsyncMock = AsyncMock(
            return_value=[
                {"id": 1, "name": "Alice", "age": 30},
                {"id": 2, "name": "Bob", "age": 25},
            ]
        )
        verifier = DatabaseVerifier(execute_query=executor)
        spec = VerificationSpec(
            name="contains_dict",
            query="SELECT * FROM users",
            expected={"name": "Alice", "age": 30},
            comparison_mode=ComparisonMode.CONTAINS,
        )
        result = await verifier.verify(spec)
        assert result.passed

    @pytest.mark.asyncio
    async def test_contains_dict_fail(self) -> None:
        executor: AsyncMock = AsyncMock(return_value=[{"id": 1, "name": "Alice", "age": 30}])
        verifier = DatabaseVerifier(execute_query=executor)
        spec = VerificationSpec(
            name="contains_dict_fail",
            query="SELECT * FROM users",
            expected={"name": "Alice", "age": 25},
            comparison_mode=ComparisonMode.CONTAINS,
        )
        result = await verifier.verify(spec)
        assert not result.passed

    @pytest.mark.asyncio
    async def test_row_count_pass(self) -> None:
        executor: AsyncMock = AsyncMock(return_value=[{"a": 1}, {"a": 2}, {"a": 3}])
        verifier = DatabaseVerifier(execute_query=executor)
        spec = VerificationSpec(
            name="row_count",
            query="SELECT * FROM t",
            expected=3,
            comparison_mode=ComparisonMode.ROW_COUNT,
        )
        result = await verifier.verify(spec)
        assert result.passed
        assert result.actual_value == 3

    @pytest.mark.asyncio
    async def test_row_count_fail(self) -> None:
        executor: AsyncMock = AsyncMock(return_value=[{"a": 1}])
        verifier = DatabaseVerifier(execute_query=executor)
        spec = VerificationSpec(
            name="row_count_fail",
            query="SELECT * FROM t",
            expected=3,
            comparison_mode=ComparisonMode.ROW_COUNT,
        )
        result = await verifier.verify(spec)
        assert not result.passed
        assert result.actual_value == 1

    @pytest.mark.asyncio
    async def test_row_count_bad_expected_type(self) -> None:
        executor: AsyncMock = AsyncMock(return_value=[{"a": 1}])
        verifier = DatabaseVerifier(execute_query=executor)
        spec = VerificationSpec(
            name="row_count_bad",
            query="SELECT * FROM t",
            expected="three",
            comparison_mode=ComparisonMode.ROW_COUNT,
        )
        result = await verifier.verify(spec)
        assert not result.passed
        assert "integer" in (result.error_message or "").lower()

    @pytest.mark.asyncio
    async def test_not_empty_pass(self) -> None:
        executor: AsyncMock = AsyncMock(return_value=[{"x": 1}])
        verifier = DatabaseVerifier(execute_query=executor)
        spec = VerificationSpec(
            name="not_empty",
            query="SELECT 1",
            comparison_mode=ComparisonMode.NOT_EMPTY,
        )
        result = await verifier.verify(spec)
        assert result.passed

    @pytest.mark.asyncio
    async def test_not_empty_fail(self) -> None:
        executor: AsyncMock = AsyncMock(return_value=[])
        verifier = DatabaseVerifier(execute_query=executor)
        spec = VerificationSpec(
            name="not_empty_fail",
            query="SELECT 1 WHERE 1=0",
            comparison_mode=ComparisonMode.NOT_EMPTY,
        )
        result = await verifier.verify(spec)
        assert not result.passed
        assert "0 rows" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_regex_pass(self) -> None:
        executor: AsyncMock = AsyncMock(return_value=[{"email": "alice@example.com"}])
        verifier = DatabaseVerifier(execute_query=executor)
        spec = VerificationSpec(
            name="regex",
            query="SELECT email FROM users",
            expected=r"\w+@\w+\.\w+",
            comparison_mode=ComparisonMode.REGEX,
        )
        result = await verifier.verify(spec)
        assert result.passed

    @pytest.mark.asyncio
    async def test_regex_fail(self) -> None:
        executor: AsyncMock = AsyncMock(return_value=[{"email": "not-an-email"}])
        verifier = DatabaseVerifier(execute_query=executor)
        spec = VerificationSpec(
            name="regex_fail",
            query="SELECT email FROM users",
            expected=r"^\w+@\w+\.\w+$",
            comparison_mode=ComparisonMode.REGEX,
        )
        result = await verifier.verify(spec)
        assert not result.passed

    @pytest.mark.asyncio
    async def test_regex_invalid_pattern(self) -> None:
        executor: AsyncMock = AsyncMock(return_value=[{"x": "abc"}])
        verifier = DatabaseVerifier(execute_query=executor)
        spec = VerificationSpec(
            name="regex_invalid",
            query="SELECT 1",
            expected="[invalid",
            comparison_mode=ComparisonMode.REGEX,
        )
        result = await verifier.verify(spec)
        assert not result.passed
        assert "Invalid regex" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_json_subset_pass(self) -> None:
        executor: AsyncMock = AsyncMock(
            return_value=[{"id": 1, "data": {"name": "Alice", "age": 30, "city": "NYC"}}]
        )
        verifier = DatabaseVerifier(execute_query=executor)
        spec = VerificationSpec(
            name="json_subset",
            query="SELECT * FROM t",
            expected={"data": {"name": "Alice"}},
            comparison_mode=ComparisonMode.JSON_SUBSET,
        )
        result = await verifier.verify(spec)
        assert result.passed

    @pytest.mark.asyncio
    async def test_json_subset_fail(self) -> None:
        executor: AsyncMock = AsyncMock(return_value=[{"id": 1, "data": {"name": "Bob"}}])
        verifier = DatabaseVerifier(execute_query=executor)
        spec = VerificationSpec(
            name="json_subset_fail",
            query="SELECT * FROM t",
            expected={"data": {"name": "Alice"}},
            comparison_mode=ComparisonMode.JSON_SUBSET,
        )
        result = await verifier.verify(spec)
        assert not result.passed

    @pytest.mark.asyncio
    async def test_json_subset_non_dict_expected(self) -> None:
        executor: AsyncMock = AsyncMock(return_value=[{"x": 1}])
        verifier = DatabaseVerifier(execute_query=executor)
        spec = VerificationSpec(
            name="json_subset_bad",
            query="SELECT 1",
            expected="not a dict",
            comparison_mode=ComparisonMode.JSON_SUBSET,
        )
        result = await verifier.verify(spec)
        assert not result.passed
        assert "dict" in (result.error_message or "").lower()

    @pytest.mark.asyncio
    async def test_verify_all(self) -> None:
        executor: AsyncMock = AsyncMock(return_value=[{"x": 1}])
        verifier = DatabaseVerifier(execute_query=executor)
        specs = [
            VerificationSpec(
                name="a",
                query="SELECT 1",
                expected=[{"x": 1}],
                comparison_mode=ComparisonMode.EXACT,
            ),
            VerificationSpec(
                name="b",
                query="SELECT 1",
                comparison_mode=ComparisonMode.NOT_EMPTY,
            ),
        ]
        results = await verifier.verify_all(specs)
        assert len(results) == 2
        assert results[0].passed
        assert results[1].passed

    @pytest.mark.asyncio
    async def test_no_executor_configured(self) -> None:
        verifier = DatabaseVerifier()
        spec = VerificationSpec(name="no_exec", query="SELECT 1")
        result = await verifier.verify(spec)
        assert not result.passed
        assert "No query executor" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_query_execution_error(self) -> None:
        executor: AsyncMock = AsyncMock(side_effect=RuntimeError("DB down"))
        verifier = DatabaseVerifier(execute_query=executor)
        spec = VerificationSpec(name="error", query="SELECT 1")
        result = await verifier.verify(spec)
        assert not result.passed
        assert "DB down" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_duration_recorded(self) -> None:
        executor: AsyncMock = AsyncMock(return_value=[])
        verifier = DatabaseVerifier(execute_query=executor)
        spec = VerificationSpec(
            name="timing",
            query="SELECT 1",
            comparison_mode=ComparisonMode.NOT_EMPTY,
        )
        result = await verifier.verify(spec)
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_contains_list_pass(self) -> None:
        executor: AsyncMock = AsyncMock(
            return_value=[
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
            ]
        )
        verifier = DatabaseVerifier(execute_query=executor)
        spec = VerificationSpec(
            name="contains_list",
            query="SELECT * FROM users",
            expected=[{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
            comparison_mode=ComparisonMode.CONTAINS,
        )
        result = await verifier.verify(spec)
        assert result.passed


# ---------------------------------------------------------------------------
# A3: Multi-Turn Evaluation
# ---------------------------------------------------------------------------


class TestToolCallExpectation:
    """Tests for tool call expectations."""

    def test_required_default(self) -> None:
        exp = ToolCallExpectation(tool_name="search")
        assert exp.required is True

    def test_optional_args(self) -> None:
        exp = ToolCallExpectation(
            tool_name="search",
            expected_arguments={"query": "test"},
            order=1,
        )
        assert exp.expected_arguments == {"query": "test"}
        assert exp.order == 1

    def test_not_required(self) -> None:
        exp = ToolCallExpectation(tool_name="cache", required=False)
        assert exp.required is False

    def test_no_order(self) -> None:
        exp = ToolCallExpectation(tool_name="x")
        assert exp.order is None

    def test_serialization(self) -> None:
        exp = ToolCallExpectation(
            tool_name="calc",
            required=True,
            order=2,
            expected_arguments={"x": 1},
        )
        data = exp.model_dump()
        restored = ToolCallExpectation.model_validate(data)
        assert restored == exp


class TestMultiTurnScenario:
    """Tests for multi-turn scenario definitions."""

    def test_basic_creation(self) -> None:
        scenario = MultiTurnScenario(
            scenario_id="S1",
            description="Test scenario",
            initial_message="Hello",
        )
        assert scenario.scenario_id == "S1"
        assert scenario.max_turns == 10
        assert scenario.tags == []

    def test_custom_values(self) -> None:
        scenario = MultiTurnScenario(
            scenario_id="S2",
            initial_message="Start",
            expected_tool_calls=[
                ToolCallExpectation(tool_name="search"),
            ],
            max_turns=5,
            success_criteria="find_answer",
            tags=["search", "web"],
        )
        assert len(scenario.expected_tool_calls) == 1
        assert scenario.max_turns == 5
        assert scenario.tags == ["search", "web"]

    def test_defaults(self) -> None:
        scenario = MultiTurnScenario(scenario_id="S3", initial_message="Go")
        assert scenario.description == ""
        assert scenario.expected_tool_calls == []
        assert scenario.success_criteria == ""


class TestToolCallCheckResult:
    """Tests for tool call check results."""

    def test_full_match_accuracy(self) -> None:
        result = ToolCallCheckResult(
            matched=["search", "calc"],
            missing=[],
            unexpected=[],
            order_violations=[],
        )
        assert result.accuracy == 1.0

    def test_partial_match_accuracy(self) -> None:
        result = ToolCallCheckResult(
            matched=["search"],
            missing=["calc"],
            unexpected=[],
            order_violations=[],
        )
        assert result.accuracy == 0.5

    def test_no_match_accuracy(self) -> None:
        result = ToolCallCheckResult(
            matched=[],
            missing=["search", "calc"],
            unexpected=[],
            order_violations=[],
        )
        assert result.accuracy == 0.0

    def test_no_expectations_accuracy(self) -> None:
        result = ToolCallCheckResult(
            matched=[],
            missing=[],
            unexpected=["extra"],
            order_violations=[],
        )
        assert result.accuracy == 1.0  # vacuously true

    def test_with_order_violations(self) -> None:
        result = ToolCallCheckResult(
            matched=["a", "b"],
            missing=[],
            unexpected=[],
            order_violations=["a before b"],
        )
        assert result.accuracy == 1.0  # accuracy is about matching, not order


class TestToolCallRecord:
    """Tests for tool call records."""

    def test_basic_creation(self) -> None:
        record = ToolCallRecord(
            tool_name="search",
            arguments={"query": "test"},
            result="found it",
        )
        assert record.tool_name == "search"
        assert record.arguments == {"query": "test"}
        assert record.result == "found it"

    def test_default_timestamp(self) -> None:
        record = ToolCallRecord(tool_name="x")
        assert record.timestamp is not None
        assert record.timestamp.tzinfo is not None

    def test_default_arguments(self) -> None:
        record = ToolCallRecord(tool_name="x")
        assert record.arguments == {}

    def test_default_result(self) -> None:
        record = ToolCallRecord(tool_name="x")
        assert record.result == ""


class TestMultiTurnEvaluator:
    """Tests for the multi-turn evaluator."""

    @pytest.mark.asyncio
    async def test_single_turn_success(self) -> None:
        tool_call = ToolCallRecord(tool_name="search", arguments={"query": "test"}, result="found")

        async def run_turn(
            msg: str, history: list[dict[str, Any]]
        ) -> tuple[str, list[ToolCallRecord]]:
            return "I found the answer", [tool_call]

        evaluator = MultiTurnEvaluator(run_turn=run_turn)
        scenario = MultiTurnScenario(
            scenario_id="S1",
            initial_message="Find something",
            expected_tool_calls=[
                ToolCallExpectation(tool_name="search"),
            ],
            max_turns=1,
        )
        result = await evaluator.evaluate(scenario)
        assert result.scenario_id == "S1"
        assert result.turns == 1
        assert result.tool_call_accuracy == 1.0
        assert result.success

    @pytest.mark.asyncio
    async def test_multi_turn_with_tool_calls(self) -> None:
        turn_count = 0

        async def run_turn(
            msg: str, history: list[dict[str, Any]]
        ) -> tuple[str, list[ToolCallRecord]]:
            nonlocal turn_count
            turn_count += 1
            if turn_count == 1:
                return "Searching...", [
                    ToolCallRecord(tool_name="search", arguments={"q": "test"})
                ]
            if turn_count == 2:
                return "Calculating...", [
                    ToolCallRecord(tool_name="calc", arguments={"expr": "2+2"})
                ]
            return "Done.", []

        evaluator = MultiTurnEvaluator(run_turn=run_turn)
        scenario = MultiTurnScenario(
            scenario_id="S2",
            initial_message="Do research",
            expected_tool_calls=[
                ToolCallExpectation(tool_name="search"),
                ToolCallExpectation(tool_name="calc"),
            ],
            max_turns=5,
        )
        result = await evaluator.evaluate(scenario)
        assert result.turns == 3  # search, calc, done (stops when no tools)
        assert len(result.tool_calls_made) == 2
        assert result.tool_call_accuracy == 1.0
        assert result.success

    @pytest.mark.asyncio
    async def test_max_turns_exceeded(self) -> None:
        async def run_turn(
            msg: str, history: list[dict[str, Any]]
        ) -> tuple[str, list[ToolCallRecord]]:
            return "Still working...", [ToolCallRecord(tool_name="search")]

        evaluator = MultiTurnEvaluator(run_turn=run_turn)
        scenario = MultiTurnScenario(
            scenario_id="S3",
            initial_message="Go",
            expected_tool_calls=[
                ToolCallExpectation(tool_name="search"),
            ],
            max_turns=3,
        )
        result = await evaluator.evaluate(scenario)
        assert result.turns == 3
        assert len(result.tool_calls_made) == 3

    @pytest.mark.asyncio
    async def test_missing_tool_calls(self) -> None:
        async def run_turn(
            msg: str, history: list[dict[str, Any]]
        ) -> tuple[str, list[ToolCallRecord]]:
            return "I didn't use any tools", []

        evaluator = MultiTurnEvaluator(run_turn=run_turn)
        scenario = MultiTurnScenario(
            scenario_id="S4",
            initial_message="Find something",
            expected_tool_calls=[
                ToolCallExpectation(tool_name="search"),
                ToolCallExpectation(tool_name="calc"),
            ],
            max_turns=3,
        )
        result = await evaluator.evaluate(scenario)
        assert result.tool_call_accuracy == 0.0
        assert not result.success

    @pytest.mark.asyncio
    async def test_partial_tool_calls(self) -> None:
        async def run_turn(
            msg: str, history: list[dict[str, Any]]
        ) -> tuple[str, list[ToolCallRecord]]:
            if not history:
                return "Searched!", [ToolCallRecord(tool_name="search")]
            return "Done", []

        evaluator = MultiTurnEvaluator(run_turn=run_turn)
        scenario = MultiTurnScenario(
            scenario_id="S5",
            initial_message="Do both",
            expected_tool_calls=[
                ToolCallExpectation(tool_name="search"),
                ToolCallExpectation(tool_name="calc"),
            ],
            max_turns=5,
        )
        result = await evaluator.evaluate(scenario)
        assert result.tool_call_accuracy == 0.5
        assert not result.success

    @pytest.mark.asyncio
    async def test_unexpected_tool_calls(self) -> None:
        async def run_turn(
            msg: str, history: list[dict[str, Any]]
        ) -> tuple[str, list[ToolCallRecord]]:
            if not history:
                return "Used extra tools", [
                    ToolCallRecord(tool_name="search"),
                    ToolCallRecord(tool_name="browser"),
                ]
            return "Done", []

        evaluator = MultiTurnEvaluator(run_turn=run_turn)
        scenario = MultiTurnScenario(
            scenario_id="S6",
            initial_message="Search",
            expected_tool_calls=[
                ToolCallExpectation(tool_name="search"),
            ],
            max_turns=3,
        )
        result = await evaluator.evaluate(scenario)
        # search matched, browser is unexpected but doesn't reduce accuracy
        assert result.tool_call_accuracy == 1.0
        assert not result.success

    @pytest.mark.asyncio
    async def test_order_violation_detection(self) -> None:
        async def run_turn(
            msg: str, history: list[dict[str, Any]]
        ) -> tuple[str, list[ToolCallRecord]]:
            if not history:
                # Wrong order: calc before search
                return "Done", [
                    ToolCallRecord(tool_name="calc"),
                    ToolCallRecord(tool_name="search"),
                ]
            return "Done", []

        evaluator = MultiTurnEvaluator(run_turn=run_turn)
        scenario = MultiTurnScenario(
            scenario_id="S7",
            initial_message="Do both",
            expected_tool_calls=[
                ToolCallExpectation(tool_name="search", order=1),
                ToolCallExpectation(tool_name="calc", order=2),
            ],
            max_turns=3,
        )
        result = await evaluator.evaluate(scenario)
        # Both tools matched, but order is wrong
        assert result.tool_call_accuracy == 1.0
        assert not result.success  # order violations cause failure

    @pytest.mark.asyncio
    async def test_correct_order(self) -> None:
        async def run_turn(
            msg: str, history: list[dict[str, Any]]
        ) -> tuple[str, list[ToolCallRecord]]:
            if not history:
                return "Done", [
                    ToolCallRecord(tool_name="search"),
                    ToolCallRecord(tool_name="calc"),
                ]
            return "Done", []

        evaluator = MultiTurnEvaluator(run_turn=run_turn)
        scenario = MultiTurnScenario(
            scenario_id="S8",
            initial_message="Do both",
            expected_tool_calls=[
                ToolCallExpectation(tool_name="search", order=1),
                ToolCallExpectation(tool_name="calc", order=2),
            ],
            max_turns=3,
        )
        result = await evaluator.evaluate(scenario)
        assert result.success

    @pytest.mark.asyncio
    async def test_argument_matching(self) -> None:
        async def run_turn(
            msg: str, history: list[dict[str, Any]]
        ) -> tuple[str, list[ToolCallRecord]]:
            if not history:
                return "Found", [
                    ToolCallRecord(
                        tool_name="search",
                        arguments={"query": "python", "limit": 10},
                    )
                ]
            return "Done", []

        evaluator = MultiTurnEvaluator(run_turn=run_turn)
        scenario = MultiTurnScenario(
            scenario_id="S9",
            initial_message="Search",
            expected_tool_calls=[
                ToolCallExpectation(
                    tool_name="search",
                    expected_arguments={"query": "python"},
                ),
            ],
            max_turns=3,
        )
        result = await evaluator.evaluate(scenario)
        # Subset match: expected args are subset of actual
        assert result.tool_call_accuracy == 1.0
        assert result.success

    @pytest.mark.asyncio
    async def test_argument_mismatch(self) -> None:
        async def run_turn(
            msg: str, history: list[dict[str, Any]]
        ) -> tuple[str, list[ToolCallRecord]]:
            if not history:
                return "Found", [
                    ToolCallRecord(
                        tool_name="search",
                        arguments={"query": "java"},
                    )
                ]
            return "Done", []

        evaluator = MultiTurnEvaluator(run_turn=run_turn)
        scenario = MultiTurnScenario(
            scenario_id="S10",
            initial_message="Search",
            expected_tool_calls=[
                ToolCallExpectation(
                    tool_name="search",
                    expected_arguments={"query": "python"},
                ),
            ],
            max_turns=3,
        )
        result = await evaluator.evaluate(scenario)
        # search was called but with wrong args
        assert result.tool_call_accuracy == 0.0
        assert not result.success

    @pytest.mark.asyncio
    async def test_optional_tool_call_not_missing(self) -> None:
        async def run_turn(
            msg: str, history: list[dict[str, Any]]
        ) -> tuple[str, list[ToolCallRecord]]:
            if not history:
                return "Done", [ToolCallRecord(tool_name="search")]
            return "Done", []

        evaluator = MultiTurnEvaluator(run_turn=run_turn)
        scenario = MultiTurnScenario(
            scenario_id="S11",
            initial_message="Go",
            expected_tool_calls=[
                ToolCallExpectation(tool_name="search", required=True),
                ToolCallExpectation(tool_name="cache", required=False),
            ],
            max_turns=3,
        )
        result = await evaluator.evaluate(scenario)
        # cache is optional, so missing it doesn't reduce accuracy
        assert result.tool_call_accuracy == 1.0
        assert result.success

    @pytest.mark.asyncio
    async def test_duration_recorded(self) -> None:
        async def run_turn(
            msg: str, history: list[dict[str, Any]]
        ) -> tuple[str, list[ToolCallRecord]]:
            return "Done", []

        evaluator = MultiTurnEvaluator(run_turn=run_turn)
        scenario = MultiTurnScenario(
            scenario_id="S12",
            initial_message="Go",
            max_turns=1,
        )
        result = await evaluator.evaluate(scenario)
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_tool_calls_made_recorded(self) -> None:
        records = [
            ToolCallRecord(tool_name="a", arguments={"x": 1}, result="ok"),
            ToolCallRecord(tool_name="b"),
        ]

        async def run_turn(
            msg: str, history: list[dict[str, Any]]
        ) -> tuple[str, list[ToolCallRecord]]:
            if not history:
                return "Working", records
            return "Done", []

        evaluator = MultiTurnEvaluator(run_turn=run_turn)
        scenario = MultiTurnScenario(
            scenario_id="S13",
            initial_message="Go",
            max_turns=3,
        )
        result = await evaluator.evaluate(scenario)
        assert len(result.tool_calls_made) == 2
        assert result.tool_calls_made[0].tool_name == "a"
        assert result.tool_calls_made[1].tool_name == "b"

    @pytest.mark.asyncio
    async def test_no_expected_tools_vacuous_success(self) -> None:
        async def run_turn(
            msg: str, history: list[dict[str, Any]]
        ) -> tuple[str, list[ToolCallRecord]]:
            return "Done", []

        evaluator = MultiTurnEvaluator(run_turn=run_turn)
        scenario = MultiTurnScenario(
            scenario_id="S14",
            initial_message="Go",
            expected_tool_calls=[],
            max_turns=1,
        )
        result = await evaluator.evaluate(scenario)
        assert result.tool_call_accuracy == 1.0
        assert result.success


class TestMultiTurnResult:
    """Tests for the multi-turn result model."""

    def test_default_values(self) -> None:
        result = MultiTurnResult(scenario_id="S1")
        assert result.turns == 0
        assert result.tool_calls_made == []
        assert result.tool_call_accuracy == 0.0
        assert result.success is False
        assert result.duration_ms == 0.0
        assert result.tokens_used == 0

    def test_populated_values(self) -> None:
        result = MultiTurnResult(
            scenario_id="S1",
            turns=3,
            tool_calls_made=[ToolCallRecord(tool_name="x")],
            tool_call_accuracy=0.75,
            success=True,
            duration_ms=1234.5,
            tokens_used=500,
        )
        assert result.turns == 3
        assert result.tool_call_accuracy == 0.75
        assert result.tokens_used == 500
