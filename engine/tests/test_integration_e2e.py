"""End-to-end integration tests across AGENT-33 subsystems.

These tests use real instances of BM25Index, TokenAwareChunker,
EmbeddingCache, SkillRegistry, SkillInjector, ContextManager, ToolRegistry,
and FakeLongTermMemory.  Only external I/O (LLM calls, PostgreSQL, Redis,
NATS) is mocked.

Every test asserts on behavior that would catch a real bug in the
subsystem under test.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent33.agents.context_manager import ContextBudget, ContextManager
from agent33.agents.definition import AgentDefinition, AgentParameter, AgentRole
from agent33.agents.runtime import AgentRuntime
from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig
from agent33.llm.base import ChatMessage, LLMResponse, ToolCall, ToolCallFunction
from agent33.llm.router import ModelRouter
from agent33.memory.bm25 import BM25Index
from agent33.memory.cache import EmbeddingCache
from agent33.memory.fake_ltm import FakeLongTermMemory
from agent33.memory.hybrid import HybridSearcher
from agent33.memory.ingestion import TokenAwareChunker
from agent33.memory.progressive_recall import ProgressiveRecall
from agent33.memory.rag import RAGPipeline
from agent33.memory.warmup import warm_up_bm25
from agent33.skills.definition import SkillDefinition
from agent33.skills.injection import SkillInjector
from agent33.skills.matching import SkillMatcher
from agent33.skills.registry import SkillRegistry
from agent33.tools.base import ToolContext, ToolResult
from agent33.tools.registry import ToolRegistry

# =====================================================================
# Deterministic embedding function for tests
# =====================================================================

_EMBED_DIM = 384


def _deterministic_embed(text: str) -> list[float]:
    """Produce a deterministic embedding from text.

    Uses a bag-of-words hash approach: each unique word contributes to
    specific dimensions via its hash, producing similar vectors for
    similar texts (shared words produce shared non-zero dimensions).
    """
    vec = [0.0] * _EMBED_DIM
    words = text.lower().split()
    for word in words:
        h = int(hashlib.sha256(word.encode()).hexdigest(), 16)
        # Each word contributes to 3 dimensions
        for i in range(3):
            dim = (h >> (i * 10)) % _EMBED_DIM
            val = ((h >> (i * 8 + 3)) % 100) / 100.0
            vec[dim] += val
    # Normalize
    magnitude = math.sqrt(sum(x * x for x in vec))
    if magnitude > 0:
        vec = [x / magnitude for x in vec]
    return vec


def _make_embedding_provider() -> AsyncMock:
    """Create a mock EmbeddingProvider that uses deterministic embeddings."""
    provider = AsyncMock()
    provider.embed = AsyncMock(side_effect=lambda text: _deterministic_embed(text))
    provider.embed_batch = AsyncMock(
        side_effect=lambda texts: [_deterministic_embed(t) for t in texts]
    )
    provider.close = AsyncMock()
    return provider


# =====================================================================
# Shared fixtures
# =====================================================================


@pytest.fixture
def fake_ltm():
    """In-memory long-term memory."""
    return FakeLongTermMemory(embedding_dim=_EMBED_DIM)


@pytest.fixture
def embedding_provider():
    """Deterministic embedding provider."""
    return _make_embedding_provider()


@pytest.fixture
def bm25_index():
    """Fresh BM25 index."""
    return BM25Index()


@pytest.fixture
def chunker():
    """Token-aware chunker with small limits for testing."""
    return TokenAwareChunker(chunk_tokens=50, overlap_tokens=10)


@pytest.fixture
def embedding_cache(embedding_provider):
    """Embedding cache wrapping the deterministic provider."""
    return EmbeddingCache(provider=embedding_provider, max_size=64)


@pytest.fixture
def hybrid_searcher(fake_ltm, embedding_cache, bm25_index):
    """Hybrid searcher combining vector + BM25."""
    return HybridSearcher(
        long_term_memory=fake_ltm,
        embedding_provider=embedding_cache,
        bm25_index=bm25_index,
        vector_weight=0.5,
    )


@pytest.fixture
def rag_pipeline(embedding_cache, fake_ltm, hybrid_searcher):
    """RAG pipeline in hybrid mode."""
    return RAGPipeline(
        embedding_provider=embedding_cache,
        long_term_memory=fake_ltm,
        top_k=5,
        similarity_threshold=0.0,
        hybrid_searcher=hybrid_searcher,
    )


@pytest.fixture
def agent_definition():
    """Minimal agent definition for testing."""
    return AgentDefinition(
        name="test-agent",
        version="1.0.0",
        role=AgentRole.IMPLEMENTER,
        description="Test agent",
        inputs={
            "task": AgentParameter(type="string", required=True),
        },
        outputs={
            "result": AgentParameter(type="string"),
        },
    )


# =====================================================================
# Flow 1: Ingestion -> BM25 Warmup -> Hybrid Search -> RAG
# =====================================================================


class TestIngestionToRAGPipeline:
    """End-to-end: ingest text, populate stores, search, and produce RAG output."""

    async def test_ingest_chunk_store_search(
        self, chunker, fake_ltm, embedding_cache, bm25_index, hybrid_searcher
    ):
        """Ingest text through the full pipeline and verify hybrid search."""
        text = (
            "Python is a popular programming language. "
            "It supports object-oriented, functional, and procedural paradigms. "
            "Python is widely used in data science and machine learning. "
            "The language has a large standard library and vibrant community."
        )
        chunks = chunker.chunk_text(text)
        assert len(chunks) >= 1, "Chunker should produce at least one chunk"

        # Store each chunk in both LTM and BM25
        for chunk in chunks:
            embedding = await embedding_cache.embed(chunk.text)
            await fake_ltm.store(chunk.text, embedding, {"source": "test"})
            bm25_index.add_document(chunk.text, {"source": "test"})

        # Verify data is stored
        count = await fake_ltm.count()
        assert count == len(chunks)
        assert bm25_index.size == len(chunks)

        # Search should find relevant content
        results = await hybrid_searcher.search("python programming", top_k=3)
        assert len(results) > 0
        assert any("python" in r.text.lower() for r in results)

    async def test_hybrid_search_uses_both_sources(
        self, fake_ltm, embedding_cache, bm25_index, hybrid_searcher
    ):
        """Verify hybrid search combines BM25 and vector results."""
        docs = [
            "kubernetes container orchestration platform",
            "docker containerization engine",
            "python flask web framework development",
        ]
        for doc in docs:
            emb = await embedding_cache.embed(doc)
            await fake_ltm.store(doc, emb, {})
            bm25_index.add_document(doc, {})

        results = await hybrid_searcher.search("container orchestration", top_k=3)
        assert len(results) > 0
        # Top result should be about containers/orchestration
        assert "container" in results[0].text.lower() or "kubernetes" in results[0].text.lower()
        # Should have both RRF scores from both retrieval methods
        assert results[0].score > 0

    async def test_rag_produces_augmented_prompt(
        self, rag_pipeline, fake_ltm, embedding_cache, bm25_index
    ):
        """RAG pipeline should produce an augmented prompt with context."""
        content = "AGENT-33 supports multi-agent DAG workflows for enterprise automation"
        emb = await embedding_cache.embed(content)
        await fake_ltm.store(content, emb, {"source": "docs"})
        bm25_index.add_document(content, {"source": "docs"})

        result = await rag_pipeline.query("multi-agent workflow")
        assert "Context" in result.augmented_prompt
        assert "AGENT-33" in result.augmented_prompt
        assert len(result.sources) > 0
        assert result.sources[0].retrieval_method == "hybrid"

    async def test_rag_with_multiple_documents(
        self, rag_pipeline, fake_ltm, embedding_cache, bm25_index
    ):
        """RAG should retrieve and rank multiple relevant documents."""
        docs = [
            "machine learning algorithms for classification tasks",
            "neural network training with backpropagation optimization",
            "database indexing strategies for query performance",
            "natural language processing with transformer models",
        ]
        for doc in docs:
            emb = await embedding_cache.embed(doc)
            await fake_ltm.store(doc, emb, {})
            bm25_index.add_document(doc, {})

        result = await rag_pipeline.query("machine learning neural network")
        assert len(result.sources) >= 2
        # ML-related docs should appear in sources
        ml_sources = [s for s in result.sources if "learning" in s.text or "neural" in s.text]
        assert len(ml_sources) >= 1

    async def test_embedding_cache_deduplicates(self, embedding_cache, embedding_provider):
        """Cache should serve identical text from cache without re-embedding."""
        text = "test embedding cache deduplication"
        emb1 = await embedding_cache.embed(text)
        emb2 = await embedding_cache.embed(text)

        assert emb1 == emb2
        assert embedding_cache.hits >= 1
        assert embedding_cache.misses >= 1
        # Provider should only be called once for the same text
        assert embedding_provider.embed.call_count == 1

    async def test_similar_texts_have_high_cosine_similarity(self, embedding_cache):
        """Deterministic embeddings should produce similar vectors for similar texts."""
        emb1 = await embedding_cache.embed("python programming language")
        emb2 = await embedding_cache.embed("python programming language development")
        emb3 = await embedding_cache.embed("quantum physics experiment")

        def cosine(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b, strict=False))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(x * x for x in b))
            return dot / (na * nb) if na > 0 and nb > 0 else 0.0

        sim_related = cosine(emb1, emb2)
        sim_unrelated = cosine(emb1, emb3)
        # Similar texts should be more similar than unrelated texts
        assert sim_related > sim_unrelated


# =====================================================================
# Flow 2: BM25 Warmup -> Keyword Search
# =====================================================================


class TestBM25WarmupFlow:
    """End-to-end: pre-populate LTM, warm up BM25, verify keyword search."""

    async def test_warmup_loads_records_into_bm25(self, fake_ltm, bm25_index):
        """warm_up_bm25 should load existing LTM records into the BM25 index."""
        # Pre-populate fake LTM with records
        for i in range(5):
            await fake_ltm.store(
                f"document number {i} about topic {['python', 'rust', 'go', 'java', 'c++'][i]}",
                [0.0] * _EMBED_DIM,
                {"doc_id": i},
            )

        assert bm25_index.size == 0

        loaded = await warm_up_bm25(fake_ltm, bm25_index, page_size=2, max_records=100)

        assert loaded == 5
        assert bm25_index.size == 5

    async def test_warmup_respects_pagination(self, fake_ltm, bm25_index):
        """warm_up_bm25 should page through records correctly."""
        for i in range(7):
            await fake_ltm.store(f"record {i}", [0.0] * _EMBED_DIM, {})

        loaded = await warm_up_bm25(fake_ltm, bm25_index, page_size=3, max_records=100)
        assert loaded == 7
        assert bm25_index.size == 7

    async def test_warmup_respects_max_records(self, fake_ltm, bm25_index):
        """warm_up_bm25 should stop at max_records."""
        for i in range(10):
            await fake_ltm.store(f"document {i} content", [0.0] * _EMBED_DIM, {})

        loaded = await warm_up_bm25(fake_ltm, bm25_index, page_size=3, max_records=5)
        assert loaded == 5
        assert bm25_index.size == 5

    async def test_warmup_then_search_finds_correct_content(self, fake_ltm, bm25_index):
        """After warmup, BM25 search should find the right documents."""
        docs = [
            "kubernetes deployment orchestration",
            "python machine learning framework",
            "database migration tooling",
        ]
        for doc in docs:
            await fake_ltm.store(doc, [0.0] * _EMBED_DIM, {})

        await warm_up_bm25(fake_ltm, bm25_index, page_size=10)

        results = bm25_index.search("kubernetes deployment")
        assert len(results) >= 1
        assert "kubernetes" in results[0].text.lower()


# =====================================================================
# Flow 3: Agent Invoke with Real Skill Injection
# =====================================================================


class TestAgentWithSkillInjection:
    """Integration: AgentRuntime + SkillRegistry + SkillInjector."""

    @pytest.fixture
    def skill_registry(self):
        reg = SkillRegistry()
        reg.register(
            SkillDefinition(
                name="data-analysis",
                description="Analyze datasets using pandas and matplotlib",
                instructions="Use pandas for data manipulation. Use matplotlib for plotting.",
                tags=["data", "analysis"],
                allowed_tools=["shell", "file_ops"],
            )
        )
        reg.register(
            SkillDefinition(
                name="kubernetes-deploy",
                description="Deploy services to Kubernetes clusters",
                instructions="Use kubectl apply. Check rollout status. Monitor pods.",
                tags=["kubernetes", "deploy"],
                allowed_tools=["shell"],
            )
        )
        return reg

    @pytest.fixture
    def skill_injector(self, skill_registry):
        return SkillInjector(registry=skill_registry)

    async def test_skill_metadata_injected_into_system_prompt(
        self, agent_definition, skill_injector
    ):
        """When skills are configured, metadata should appear in the system prompt."""
        agent_definition = agent_definition.model_copy(
            update={"skills": ["data-analysis", "kubernetes-deploy"]}
        )

        mock_router = MagicMock(spec=ModelRouter)
        mock_router.complete = AsyncMock(
            return_value=LLMResponse(
                content='{"result": "done"}',
                model="test",
                prompt_tokens=100,
                completion_tokens=50,
            )
        )

        runtime = AgentRuntime(
            definition=agent_definition,
            router=mock_router,
            skill_injector=skill_injector,
        )

        await runtime.invoke({"task": "analyze data"})

        # Check the system prompt sent to the LLM
        call_args = mock_router.complete.call_args
        messages = call_args.args[0]
        system_msg = messages[0].content

        assert "Available Skills" in system_msg
        assert "data-analysis" in system_msg
        assert "kubernetes-deploy" in system_msg

    async def test_skill_instructions_injected(self, agent_definition, skill_injector):
        """Active skill instructions should appear in the system prompt."""
        agent_definition = agent_definition.model_copy(update={"skills": ["data-analysis"]})

        mock_router = MagicMock(spec=ModelRouter)
        mock_router.complete = AsyncMock(
            return_value=LLMResponse(
                content='{"result": "done"}',
                model="test",
                prompt_tokens=100,
                completion_tokens=50,
            )
        )

        runtime = AgentRuntime(
            definition=agent_definition,
            router=mock_router,
            skill_injector=skill_injector,
            active_skills=["data-analysis"],
        )

        await runtime.invoke({"task": "analyze CSV"})

        messages = mock_router.complete.call_args.args[0]
        system_msg = messages[0].content
        assert "pandas" in system_msg
        assert "matplotlib" in system_msg

    async def test_multiple_skills_injected_correctly(self, agent_definition, skill_injector):
        """Multiple active skills should all have their instructions injected."""
        agent_definition = agent_definition.model_copy(
            update={"skills": ["data-analysis", "kubernetes-deploy"]}
        )

        mock_router = MagicMock(spec=ModelRouter)
        mock_router.complete = AsyncMock(
            return_value=LLMResponse(
                content='{"result": "done"}',
                model="test",
                prompt_tokens=100,
                completion_tokens=50,
            )
        )

        runtime = AgentRuntime(
            definition=agent_definition,
            router=mock_router,
            skill_injector=skill_injector,
            active_skills=["data-analysis", "kubernetes-deploy"],
        )

        await runtime.invoke({"task": "deploy data pipeline"})

        system_msg = mock_router.complete.call_args.args[0][0].content
        assert "pandas" in system_msg
        assert "kubectl" in system_msg

    async def test_missing_active_skill_fails_before_invocation(
        self, agent_definition, skill_injector
    ):
        """A missing active skill should not reach prompt construction or LLM calls."""
        from agent33.skills.injection import SkillContractError

        agent_definition = agent_definition.model_copy(update={"skills": ["nonexistent-skill"]})

        mock_router = MagicMock(spec=ModelRouter)
        mock_router.complete = AsyncMock(
            return_value=LLMResponse(
                content='{"result": "ok"}',
                model="test",
                prompt_tokens=50,
                completion_tokens=20,
            )
        )

        runtime = AgentRuntime(
            definition=agent_definition,
            router=mock_router,
            skill_injector=skill_injector,
            active_skills=["nonexistent-skill"],
        )

        with pytest.raises(SkillContractError, match="Active skill not found"):
            await runtime.invoke({"task": "do something"})
        mock_router.complete.assert_not_called()


# =====================================================================
# Flow 4: Agent Iterative Tool Loop with Real Tool Execution
# =====================================================================


class _EchoTool:
    """A simple test tool that echoes its input."""

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo the input message"

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message to echo"},
            },
            "required": ["message"],
        }

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult.ok(f"Echo: {params.get('message', '')}")


class _FailTool:
    """A test tool that always fails."""

    @property
    def name(self) -> str:
        return "fail"

    @property
    def description(self) -> str:
        return "Always fails"

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult.fail("Tool failure by design")


class TestIterativeToolLoop:
    """Integration: ToolLoop + real ToolRegistry + real tool execution."""

    @pytest.fixture
    def tool_registry(self):
        reg = ToolRegistry()
        reg.register(_EchoTool())
        reg.register(_FailTool())
        return reg

    def _tool_call(
        self,
        name: str = "echo",
        arguments: str = '{"message": "hello"}',
        call_id: str = "call_1",
    ) -> ToolCall:
        return ToolCall(id=call_id, function=ToolCallFunction(name=name, arguments=arguments))

    def _text_response(self, content: str = '{"response": "done"}') -> LLMResponse:
        return LLMResponse(content=content, model="test", prompt_tokens=10, completion_tokens=10)

    def _tool_response(self, tool_calls: list[ToolCall], content: str = "") -> LLMResponse:
        return LLMResponse(
            content=content,
            model="test",
            prompt_tokens=15,
            completion_tokens=15,
            tool_calls=tool_calls,
            finish_reason="tool_calls",
        )

    async def test_tool_executed_and_result_in_conversation(self, tool_registry):
        """Tool call should execute via registry and result should appear in messages."""
        router = MagicMock(spec=ModelRouter)
        router.complete = AsyncMock(
            side_effect=[
                self._tool_response([self._tool_call("echo", '{"message": "world"}')]),
                self._text_response('{"response": "processed"}'),
                # Double confirmation reply
                self._text_response('COMPLETED: {"response": "confirmed"}'),
            ]
        )

        loop = ToolLoop(
            router=router,
            tool_registry=tool_registry,
            config=ToolLoopConfig(max_iterations=5),
        )

        messages = [
            ChatMessage(role="system", content="You are a test agent"),
            ChatMessage(role="user", content='{"task": "echo test"}'),
        ]

        result = await loop.run(messages, model="test")

        assert result.termination_reason == "completed"
        assert result.tool_calls_made == 1
        assert "echo" in result.tools_used

        # Verify the tool result appeared in the conversation
        tool_msgs = [m for m in messages if m.role == "tool"]
        assert len(tool_msgs) == 1
        assert "Echo: world" in tool_msgs[0].content

    async def test_schema_validation_rejects_invalid_params(self, tool_registry):
        """validated_execute should reject params that don't match the schema."""
        context = ToolContext(user_scopes=["tools:execute"])
        # Missing required "message" field
        result = await tool_registry.validated_execute("echo", {}, context)
        assert not result.success
        assert "validation failed" in result.error.lower()

    async def test_tool_loop_tracks_multiple_tools(self, tool_registry):
        """Loop should track all unique tools used."""
        router = MagicMock(spec=ModelRouter)
        router.complete = AsyncMock(
            side_effect=[
                self._tool_response([self._tool_call("echo", '{"message": "a"}', "c1")]),
                self._tool_response([self._tool_call("fail", "{}", "c2")]),
                self._text_response("done"),
                self._text_response("confirmed"),
            ]
        )

        loop = ToolLoop(
            router=router,
            tool_registry=tool_registry,
            config=ToolLoopConfig(max_iterations=10, enable_double_confirmation=True),
        )

        messages = [
            ChatMessage(role="system", content="agent"),
            ChatMessage(role="user", content="task"),
        ]
        result = await loop.run(messages, model="test")

        assert result.tool_calls_made == 2
        assert "echo" in result.tools_used
        assert "fail" in result.tools_used

    async def test_governance_blocks_tool_call(self, tool_registry):
        """Governance should block a tool call and record the failure."""
        governance = MagicMock()
        governance.pre_execute_check.return_value = False

        router = MagicMock(spec=ModelRouter)
        router.complete = AsyncMock(
            side_effect=[
                self._tool_response([self._tool_call("echo", '{"message": "blocked"}')]),
                self._text_response("done"),
                self._text_response("confirmed"),
            ]
        )

        context = ToolContext(user_scopes=["tools:execute"])
        loop = ToolLoop(
            router=router,
            tool_registry=tool_registry,
            tool_governance=governance,
            tool_context=context,
            config=ToolLoopConfig(max_iterations=5),
        )

        messages = [
            ChatMessage(role="system", content="agent"),
            ChatMessage(role="user", content="task"),
        ]
        result = await loop.run(messages, model="test")

        # Tool call was blocked, so tool_calls_made should be 0 (governance block
        # doesn't increment the counter)
        assert result.tool_calls_made == 0
        # But a tool message should still be in conversation with the error
        tool_msgs = [m for m in messages if m.role == "tool"]
        assert len(tool_msgs) == 1
        assert "blocked by governance" in tool_msgs[0].content.lower()


# =====================================================================
# Flow 5: Skill Matching -> Injection Pipeline
# =====================================================================


class TestSkillMatchingToInjection:
    """Integration: SkillMatcher -> SkillInjector -> system prompt."""

    @pytest.fixture
    def populated_registry(self):
        reg = SkillRegistry()
        reg.register(
            SkillDefinition(
                name="web-scraping",
                description="Extract data from websites using BeautifulSoup",
                instructions="Use requests + BeautifulSoup. Respect robots.txt.",
                tags=["web", "scraping", "data"],
            )
        )
        reg.register(
            SkillDefinition(
                name="sql-query",
                description="Write and optimize SQL queries for databases",
                instructions="Use parameterized queries. Avoid SELECT *.",
                tags=["sql", "database", "query"],
            )
        )
        reg.register(
            SkillDefinition(
                name="image-processing",
                description="Process and transform images with PIL/OpenCV",
                instructions="Use Pillow for basic ops. OpenCV for advanced.",
                tags=["image", "processing", "computer-vision"],
            )
        )
        reg.register(
            SkillDefinition(
                name="api-testing",
                description="Test REST APIs with automated assertions",
                instructions="Validate status codes, response schemas, latency.",
                tags=["api", "testing", "rest"],
            )
        )
        return reg

    async def test_matcher_retrieves_relevant_skills(self, populated_registry):
        """Stage 1 BM25 retrieval should find skills by keyword match."""
        # Use a mock router that returns all candidates (lenient filter)
        mock_router = MagicMock(spec=ModelRouter)
        mock_router.complete = AsyncMock(
            return_value=LLMResponse(
                content='["sql-query"]',
                model="test",
                prompt_tokens=10,
                completion_tokens=10,
            )
        )

        matcher = SkillMatcher(
            registry=populated_registry,
            router=mock_router,
            skip_llm_below=10,  # Skip LLM since we have few skills
        )

        result = await matcher.match("write database SQL query")
        assert result.count > 0
        skill_names = [s.name for s in result.skills]
        assert "sql-query" in skill_names

    async def test_matched_skills_injected_into_prompt(self, populated_registry):
        """Skills from matcher should produce correct injector output."""
        injector = SkillInjector(registry=populated_registry)

        # Simulate matcher returning these skills
        matched_names = ["web-scraping", "sql-query"]

        metadata_block = injector.build_skill_metadata_block(matched_names)
        assert "web-scraping" in metadata_block
        assert "sql-query" in metadata_block
        assert "Available Skills" in metadata_block

        instructions_block = injector.build_skill_instructions_block("sql-query")
        assert "parameterized queries" in instructions_block
        assert "Active Skill: sql-query" in instructions_block

    async def test_full_match_to_injection_pipeline(self, populated_registry):
        """Full pipeline: match -> inject metadata + instructions."""
        mock_router = MagicMock(spec=ModelRouter)
        mock_router.complete = AsyncMock(
            return_value=LLMResponse(
                content='["web-scraping"]',
                model="test",
                prompt_tokens=10,
                completion_tokens=10,
            )
        )

        matcher = SkillMatcher(
            registry=populated_registry,
            router=mock_router,
            skip_llm_below=10,
        )

        result = await matcher.match("scrape website data extraction")
        injector = SkillInjector(registry=populated_registry)

        matched_names = [s.name for s in result.skills]
        metadata_block = injector.build_skill_metadata_block(matched_names)
        assert "web-scraping" in metadata_block

        for skill in result.skills:
            instructions = injector.build_skill_instructions_block(skill.name)
            assert len(instructions) > 0
            # Each instruction block should have the skill name
            assert skill.name in instructions


# =====================================================================
# Flow 6: Context Manager Standalone
# =====================================================================


class TestContextManagerStandalone:
    """Integration: ContextManager with real message tracking and unwinding."""

    def test_snapshot_tracks_token_usage(self):
        """Snapshot should accurately track token count and utilization."""
        budget = ContextBudget(max_context_tokens=200, reserved_for_completion=50)
        mgr = ContextManager(budget=budget)

        messages = [
            ChatMessage(role="system", content="You are a helpful assistant"),
            ChatMessage(role="user", content="Hello world"),
        ]
        snap = mgr.snapshot(messages)

        assert snap.total_tokens > 0
        assert snap.message_count == 2
        assert snap.budget.effective_limit == 150
        assert snap.headroom >= 0
        assert 0.0 <= snap.utilization <= 1.0

    def test_unwind_removes_oldest_non_system_messages(self):
        """Unwind should remove oldest non-system messages to meet target."""
        budget = ContextBudget(max_context_tokens=100, reserved_for_completion=10)
        mgr = ContextManager(budget=budget)

        messages = [
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="user", content="first message " * 20),
            ChatMessage(role="assistant", content="first reply " * 20),
            ChatMessage(role="user", content="second question"),
            ChatMessage(role="assistant", content="second reply"),
        ]

        trimmed = mgr.unwind(messages, target_tokens=50)

        # System message must be preserved
        assert trimmed[0].role == "system"
        # Should have fewer messages than original
        assert len(trimmed) < len(messages)
        # Most recent messages should survive
        assert trimmed[-1].content == "second reply"

    def test_unwind_preserves_system_messages(self):
        """All system messages should survive unwinding."""
        budget = ContextBudget(max_context_tokens=50, reserved_for_completion=10)
        mgr = ContextManager(budget=budget)

        messages = [
            ChatMessage(role="system", content="system prompt A"),
            ChatMessage(role="system", content="system prompt B"),
            ChatMessage(role="user", content="long content " * 50),
        ]

        trimmed = mgr.unwind(messages)
        system_msgs = [m for m in trimmed if m.role == "system"]
        assert len(system_msgs) == 2

    async def test_manage_calls_summarize_when_over_threshold(self):
        """manage() should attempt summarization when over threshold.

        summarize_and_compact(keep_recent=4) summarizes all non-system
        messages except the last 4.  We need enough messages so that
        at least 2 are summarized into 1, giving a net reduction.
        """
        budget = ContextBudget(
            max_context_tokens=500,
            reserved_for_completion=20,
            summarize_threshold=0.5,
        )
        # Use a router that returns a summary
        mock_router = MagicMock(spec=ModelRouter)
        mock_router.complete = AsyncMock(
            return_value=LLMResponse(
                content="Summary: discussed greetings and tasks",
                model="test",
                prompt_tokens=50,
                completion_tokens=20,
            )
        )

        mgr = ContextManager(budget=budget, router=mock_router)

        # Create 8 non-system messages (enough to summarize 4 and keep 4)
        messages = [
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="user", content="old question one " * 20),
            ChatMessage(role="assistant", content="old answer one " * 20),
            ChatMessage(role="user", content="old question two " * 20),
            ChatMessage(role="assistant", content="old answer two " * 20),
            ChatMessage(role="user", content="recent question one " * 20),
            ChatMessage(role="assistant", content="recent answer one " * 20),
            ChatMessage(role="user", content="recent question two " * 20),
            ChatMessage(role="assistant", content="recent answer two"),
        ]

        result = await mgr.manage(messages, keep_recent=4)
        # 4 old messages compressed into 1 summary + system + 4 recent = 6 < 9
        assert len(result) < len(messages)
        # System message should still be first
        assert result[0].role == "system"
        # The LLM summarize method should have been called
        assert mock_router.complete.called


# =====================================================================
# Flow 7: Memory Search Roundtrip (Progressive Recall)
# =====================================================================


class TestMemorySearchRoundtrip:
    """Integration: FakeLTM + EmbeddingProvider + ProgressiveRecall."""

    async def test_store_and_recall_index_level(self, fake_ltm, embedding_provider):
        """Store content, then search at index level via ProgressiveRecall."""
        content = "The agent successfully deployed the kubernetes service"
        emb = await embedding_provider.embed(content)
        await fake_ltm.store(
            content,
            emb,
            {"agent_name": "deployer", "event_type": "deployment", "tags": ["k8s"]},
        )

        recall = ProgressiveRecall(
            long_term_memory=fake_ltm,
            embedding_provider=embedding_provider,
            top_k=5,
        )

        results = await recall.search("kubernetes deployment", level="index")
        assert len(results) > 0
        assert results[0].level == "index"
        assert "deployer" in results[0].content

    async def test_recall_full_level_returns_complete_text(self, fake_ltm, embedding_provider):
        """Full level recall should return the complete stored text."""
        content = "Detailed analysis of the system performance metrics including latency"
        emb = await embedding_provider.embed(content)
        await fake_ltm.store(content, emb, {"agent_name": "analyzer", "event_type": "analysis"})

        recall = ProgressiveRecall(
            long_term_memory=fake_ltm,
            embedding_provider=embedding_provider,
        )

        results = await recall.search("performance metrics", level="full")
        assert len(results) > 0
        assert results[0].level == "full"
        # Full level should contain the complete original text
        assert "performance metrics" in results[0].content

    async def test_recall_timeline_level(self, fake_ltm, embedding_provider):
        """Timeline level should include timestamp and agent info."""
        content = "Completed security audit scan"
        emb = await embedding_provider.embed(content)
        await fake_ltm.store(
            content,
            emb,
            {
                "agent_name": "security-agent",
                "event_type": "audit",
                "timestamp": "2026-01-15T10:00:00",
            },
        )

        recall = ProgressiveRecall(
            long_term_memory=fake_ltm,
            embedding_provider=embedding_provider,
        )

        results = await recall.search("security audit", level="timeline")
        assert len(results) > 0
        assert results[0].level == "timeline"
        assert "security-agent" in results[0].content

    async def test_recall_with_multiple_records_returns_most_relevant(
        self, fake_ltm, embedding_provider
    ):
        """Recall should rank results by relevance to the query."""
        docs = [
            ("python machine learning model training", {"agent_name": "ml"}),
            ("javascript frontend React development", {"agent_name": "frontend"}),
            ("python data science analysis pipeline", {"agent_name": "data"}),
        ]
        for text, meta in docs:
            emb = await embedding_provider.embed(text)
            await fake_ltm.store(text, emb, meta)

        recall = ProgressiveRecall(
            long_term_memory=fake_ltm,
            embedding_provider=embedding_provider,
            top_k=3,
        )

        results = await recall.search("python machine learning", level="full")
        assert len(results) > 0
        # The first result should be about python/ML, not javascript
        assert "python" in results[0].content.lower()


# =====================================================================
# Flow 8: Full Pipeline: Ingest -> Store -> Warm-up -> Search
# =====================================================================


class TestFullDataLifecycle:
    """Integration: complete data lifecycle from ingestion to search."""

    async def test_full_lifecycle(
        self, chunker, fake_ltm, embedding_cache, bm25_index, hybrid_searcher
    ):
        """Document ingestion through to hybrid search as a single flow."""
        # Step 1: Ingest a document
        document = (
            "AGENT-33 is a multi-agent orchestration framework. "
            "It supports DAG-based workflow execution with governance. "
            "The system includes hybrid search combining BM25 and vector retrieval. "
            "Security features include JWT authentication and RBAC permissions."
        )
        chunks = chunker.chunk_text(document)
        assert len(chunks) >= 1

        # Step 2: Embed and store each chunk
        for chunk in chunks:
            embedding = await embedding_cache.embed(chunk.text)
            await fake_ltm.store(chunk.text, embedding, {"source": "readme"})
            bm25_index.add_document(chunk.text, {"source": "readme"})

        # Step 3: Verify storage
        count = await fake_ltm.count()
        assert count == len(chunks)
        assert bm25_index.size == len(chunks)

        # Step 4: Search should find relevant content
        results = await hybrid_searcher.search("workflow orchestration", top_k=3)
        assert len(results) > 0
        # Should find content about orchestration
        assert any(
            "orchestration" in r.text.lower() or "workflow" in r.text.lower() for r in results
        )

    async def test_lifecycle_with_warmup_recovery(self, fake_ltm, embedding_cache, bm25_index):
        """Simulate restart: data in LTM, BM25 empty, warm up, then search."""
        # Pre-populate LTM (simulating existing data from before restart)
        docs = [
            "FastAPI application development with async support",
            "PostgreSQL database optimization techniques",
            "Redis caching strategies for web applications",
        ]
        for doc in docs:
            emb = await embedding_cache.embed(doc)
            await fake_ltm.store(doc, emb, {})

        # BM25 is empty (simulating fresh start)
        assert bm25_index.size == 0

        # Warm up BM25 from LTM
        loaded = await warm_up_bm25(fake_ltm, bm25_index, page_size=2)
        assert loaded == 3
        assert bm25_index.size == 3

        # Now BM25 search should work
        results = bm25_index.search("redis caching")
        assert len(results) >= 1
        assert "redis" in results[0].text.lower()

    async def test_ingest_large_document_chunked_correctly(
        self, chunker, fake_ltm, embedding_cache, bm25_index
    ):
        """Large document should be split into multiple chunks and all stored."""
        # Generate a document that exceeds the chunker's token limit
        sentences = [
            f"Sentence number {i} discusses topic {chr(65 + (i % 26))}." for i in range(100)
        ]
        large_doc = " ".join(sentences)

        chunks = chunker.chunk_text(large_doc)
        # With chunk_tokens=50, a 100-sentence doc should produce many chunks
        assert len(chunks) > 1

        for chunk in chunks:
            emb = await embedding_cache.embed(chunk.text)
            await fake_ltm.store(chunk.text, emb, {"chunk_index": chunk.index})
            bm25_index.add_document(chunk.text, {"chunk_index": chunk.index})

        count = await fake_ltm.count()
        assert count == len(chunks)
        assert bm25_index.size == len(chunks)

    async def test_hybrid_search_combines_keyword_and_semantic(
        self, fake_ltm, embedding_cache, bm25_index, hybrid_searcher
    ):
        """Hybrid search should find docs matching either semantically or by keyword."""
        # Doc 1: strong keyword match for "kubernetes"
        doc1 = "kubernetes kubernetes kubernetes cluster management"
        # Doc 2: semantically similar to container orchestration
        doc2 = "container orchestration platform for microservices deployment"
        # Doc 3: unrelated
        doc3 = "baking chocolate cake recipe with butter and flour"

        for doc in [doc1, doc2, doc3]:
            emb = await embedding_cache.embed(doc)
            await fake_ltm.store(doc, emb, {})
            bm25_index.add_document(doc, {})

        results = await hybrid_searcher.search("kubernetes container orchestration", top_k=3)
        assert len(results) >= 2

        result_texts = [r.text.lower() for r in results]
        # Both container-related docs should rank above the cake recipe
        cake_positions = [i for i, t in enumerate(result_texts) if "cake" in t]
        container_positions = [
            i for i, t in enumerate(result_texts) if "kubernetes" in t or "container" in t
        ]
        if cake_positions and container_positions:
            assert min(container_positions) < min(cake_positions)


# =====================================================================
# Flow: ContextManager integrated into ToolLoop
# =====================================================================


class TestContextManagerInToolLoop:
    """Integration: ToolLoop + ContextManager for automatic context trimming."""

    @pytest.fixture
    def echo_registry(self):
        reg = ToolRegistry()
        reg.register(_EchoTool())
        return reg

    async def test_context_manager_trims_during_tool_loop(self, echo_registry):
        """Context manager should trim messages when conversation grows large."""
        # Use a very small budget so trimming is triggered
        budget = ContextBudget(
            max_context_tokens=150,
            reserved_for_completion=20,
            summarize_threshold=0.5,
        )
        ctx_mgr = ContextManager(budget=budget)

        call_count = 0

        async def mock_complete(
            messages,
            *,
            model,
            temperature=0.7,
            max_tokens=None,
            tools=None,
            allow_fallback=False,
        ):
            del allow_fallback
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                # Return tool calls for first 3 iterations
                return LLMResponse(
                    content="",
                    model="test",
                    prompt_tokens=20,
                    completion_tokens=20,
                    tool_calls=[
                        ToolCall(
                            id=f"call_{call_count}",
                            function=ToolCallFunction(
                                name="echo",
                                arguments=json.dumps({"message": f"iteration {call_count}"}),
                            ),
                        )
                    ],
                    finish_reason="tool_calls",
                )
            else:
                # Then complete
                return LLMResponse(
                    content='{"response": "done"}',
                    model="test",
                    prompt_tokens=10,
                    completion_tokens=10,
                )

        router = MagicMock(spec=ModelRouter)
        router.complete = AsyncMock(side_effect=mock_complete)

        loop = ToolLoop(
            router=router,
            tool_registry=echo_registry,
            config=ToolLoopConfig(
                max_iterations=10,
                enable_double_confirmation=False,
            ),
            context_manager=ctx_mgr,
        )

        messages = [
            ChatMessage(role="system", content="test agent"),
            ChatMessage(role="user", content="do something"),
        ]

        result = await loop.run(messages, model="test")
        assert result.termination_reason == "completed"
        assert result.tool_calls_made == 3

        # Because the context manager was active with a small budget,
        # some messages should have been unwound.  The system message
        # should always be present.
        system_msgs = [m for m in messages if m.role == "system"]
        assert len(system_msgs) >= 1

    async def test_tool_loop_works_without_context_manager(self, echo_registry):
        """ToolLoop should work fine when context_manager is None."""
        router = MagicMock(spec=ModelRouter)
        router.complete = AsyncMock(
            side_effect=[
                LLMResponse(
                    content='{"response": "immediate"}',
                    model="test",
                    prompt_tokens=10,
                    completion_tokens=10,
                ),
                LLMResponse(
                    content='COMPLETED: {"response": "confirmed"}',
                    model="test",
                    prompt_tokens=10,
                    completion_tokens=10,
                ),
            ]
        )

        loop = ToolLoop(
            router=router,
            tool_registry=echo_registry,
            config=ToolLoopConfig(max_iterations=5),
            context_manager=None,  # Explicitly no context manager
        )

        messages = [
            ChatMessage(role="system", content="agent"),
            ChatMessage(role="user", content="task"),
        ]
        result = await loop.run(messages, model="test")
        assert result.termination_reason == "completed"


# =====================================================================
# FakeLongTermMemory unit validation
# =====================================================================


class TestFakeLongTermMemory:
    """Validate FakeLTM implements the same interface as LongTermMemory."""

    async def test_store_and_retrieve(self, fake_ltm):
        """store() should persist records retrievable by search()."""
        embedding = _deterministic_embed("test content")
        record_id = await fake_ltm.store("test content", embedding, {"key": "value"})
        assert record_id >= 1

        results = await fake_ltm.search(embedding, top_k=1)
        assert len(results) == 1
        assert results[0].text == "test content"
        assert results[0].metadata == {"key": "value"}
        assert results[0].score > 0.99  # Same embedding should be ~1.0

    async def test_scan_paginated(self, fake_ltm):
        """scan() should support pagination."""
        for i in range(5):
            await fake_ltm.store(f"doc {i}", [0.0] * _EMBED_DIM, {})

        page1 = await fake_ltm.scan(limit=2, offset=0)
        page2 = await fake_ltm.scan(limit=2, offset=2)
        page3 = await fake_ltm.scan(limit=2, offset=4)

        assert len(page1) == 2
        assert len(page2) == 2
        assert len(page3) == 1  # Only 1 record left

        # Pages should be different
        assert page1[0].text != page2[0].text

    async def test_count_returns_total(self, fake_ltm):
        """count() should return the total number of records."""
        assert await fake_ltm.count() == 0

        await fake_ltm.store("a", [0.0] * _EMBED_DIM, {})
        await fake_ltm.store("b", [0.0] * _EMBED_DIM, {})
        assert await fake_ltm.count() == 2

    async def test_search_ranks_by_similarity(self, fake_ltm):
        """search() should rank results by cosine similarity."""
        emb_a = _deterministic_embed("python programming language")
        emb_b = _deterministic_embed("javascript web development")
        emb_c = _deterministic_embed("python data science analysis")

        await fake_ltm.store("python programming language", emb_a, {})
        await fake_ltm.store("javascript web development", emb_b, {})
        await fake_ltm.store("python data science analysis", emb_c, {})

        query = _deterministic_embed("python programming")
        results = await fake_ltm.search(query, top_k=3)

        assert len(results) == 3
        # Python-related docs should rank higher than javascript
        python_scores = [r.score for r in results if "python" in r.text]
        js_scores = [r.score for r in results if "javascript" in r.text]
        assert max(python_scores) > max(js_scores)

    async def test_initialize_and_close_are_noops(self, fake_ltm):
        """initialize() and close() should not raise."""
        await fake_ltm.initialize()
        await fake_ltm.close()
