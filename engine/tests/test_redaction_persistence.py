"""Tests for Phase 52 gap-close: secret redaction on persistence/retrieval paths.

Covers observation capture, session summarizer, RAG pipeline, shared memory,
and the three new patterns (Anthropic, JWT, Azure connection strings).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent33.memory.observation import Observation, ObservationCapture
from agent33.security.redaction import redact_secrets

# ---------------------------------------------------------------------------
# New patterns: Anthropic, JWT, Azure
# ---------------------------------------------------------------------------


class TestAnthropicKeyPattern:
    """Anthropic sk-ant- keys are redacted."""

    def test_anthropic_key_redacted(self) -> None:
        key = "sk-ant-" + "a" * 30
        text = f"ANTHROPIC_API_KEY={key}"
        result = redact_secrets(text)
        assert key not in result
        # Smart masking: prefix preserved, middle replaced
        assert "..." in result or "***" in result

    def test_anthropic_key_short_not_matched(self) -> None:
        # sk-ant- followed by < 20 chars: below threshold
        text = "sk-ant-short"
        assert redact_secrets(text) == text

    def test_anthropic_key_in_json(self) -> None:
        key = "sk-ant-api11223344556677889900aabb"
        text = f'{{"api_key": "{key}"}}'
        result = redact_secrets(text)
        assert key not in result


class TestJWTPattern:
    """JWT tokens (eyJ...) are redacted."""

    def test_jwt_token_redacted(self) -> None:
        # Minimal realistic JWT: header.payload.signature
        token = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
            ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0"
            ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        text = f"Bearer {token}"
        result = redact_secrets(text)
        assert token not in result

    def test_jwt_short_segments_not_matched(self) -> None:
        # Segments too short to be real JWT
        text = "eyJhYg.eyJjZA.sig"
        assert redact_secrets(text) == text

    def test_jwt_in_header(self) -> None:
        token = (
            "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9"
            ".eyJpc3MiOiJhZ2VudDMzIiwic3ViIjoiMTIzIn0"
            ".dGhpc19pc19hX3NpZ25hdHVyZV92YWx1ZQ"
        )
        text = f"Authorization: Bearer {token}"
        result = redact_secrets(text)
        assert token not in result


class TestAzureConnectionStringPattern:
    """Azure storage connection strings are redacted."""

    def test_azure_https_connection_string(self) -> None:
        conn = (
            "DefaultEndpointsProtocol=https;"
            "AccountName=mystorageaccount;"
            "AccountKey=abc123def456ghi789jkl012mno345pqr678stu901vwx234yz=="
        )
        text = f"AZURE_STORAGE={conn}"
        result = redact_secrets(text)
        assert "AccountKey=abc123" not in result

    def test_azure_http_connection_string(self) -> None:
        conn = (
            "DefaultEndpointsProtocol=http;"
            "AccountName=devstoreaccount1;"
            "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq"
        )
        text = f"CONN={conn}"
        result = redact_secrets(text)
        assert "AccountKey=" not in result or "..." in result or "***" in result

    def test_non_azure_connection_string_unchanged(self) -> None:
        text = "Protocol=https;Server=myhost;Database=mydb"
        assert redact_secrets(text) == text


# ---------------------------------------------------------------------------
# Observation redaction on persistence
# ---------------------------------------------------------------------------


class TestObservationRedaction:
    """Secrets in observation content are redacted before LTM and NATS."""

    @pytest.mark.asyncio
    async def test_content_redacted_before_ltm_storage(self) -> None:
        """The content stored in LTM must have secrets removed."""
        mock_memory = AsyncMock()
        mock_embed = AsyncMock()
        mock_embed.embed.return_value = [0.1] * 1536

        capture = ObservationCapture(
            long_term_memory=mock_memory,
            embedding_provider=mock_embed,
            redact_enabled=True,
        )

        api_key = "sk-" + "a" * 30
        obs = Observation(content=f"Config: API_KEY={api_key}")
        await capture.record(obs)

        # Verify LTM store was called with redacted content
        mock_memory.store.assert_called_once()
        stored_content = mock_memory.store.call_args[1]["content"]
        assert api_key not in stored_content
        assert "***" in stored_content or "..." in stored_content

    @pytest.mark.asyncio
    async def test_content_redacted_before_nats_publish(self) -> None:
        """The content published to NATS must have secrets removed."""
        mock_nats = AsyncMock()

        capture = ObservationCapture(
            nats_bus=mock_nats,
            redact_enabled=True,
        )

        secret = "ghp_" + "x" * 36
        obs = Observation(content=f"Token: {secret}")
        await capture.record(obs)

        mock_nats.publish.assert_called_once()
        published_payload = mock_nats.publish.call_args[0][1]
        assert secret not in published_payload["content"]

    @pytest.mark.asyncio
    async def test_embedding_uses_redacted_content(self) -> None:
        """The embedding provider receives redacted content, not raw."""
        mock_memory = AsyncMock()
        mock_embed = AsyncMock()
        mock_embed.embed.return_value = [0.1] * 1536

        capture = ObservationCapture(
            long_term_memory=mock_memory,
            embedding_provider=mock_embed,
            redact_enabled=True,
        )

        api_key = "sk-" + "b" * 30
        obs = Observation(content=f"key={api_key}")
        await capture.record(obs)

        embed_input = mock_embed.embed.call_args[0][0]
        assert api_key not in embed_input

    @pytest.mark.asyncio
    async def test_redaction_disabled_preserves_content(self) -> None:
        """When redact_enabled=False, raw content is stored."""
        mock_memory = AsyncMock()
        mock_embed = AsyncMock()
        mock_embed.embed.return_value = [0.1] * 1536

        capture = ObservationCapture(
            long_term_memory=mock_memory,
            embedding_provider=mock_embed,
            redact_enabled=False,
        )

        api_key = "sk-" + "c" * 30
        obs = Observation(content=f"key={api_key}")
        await capture.record(obs)

        stored_content = mock_memory.store.call_args[1]["content"]
        assert api_key in stored_content

    @pytest.mark.asyncio
    async def test_buffer_retains_original_observation(self) -> None:
        """The in-memory buffer keeps the original observation object."""
        capture = ObservationCapture(redact_enabled=True)
        api_key = "sk-" + "d" * 30
        obs = Observation(content=f"key={api_key}")
        await capture.record(obs)

        flushed = await capture.flush()
        # The buffer stores the original Observation dataclass unchanged
        assert flushed[0].content == f"key={api_key}"


# ---------------------------------------------------------------------------
# Summarizer redaction
# ---------------------------------------------------------------------------


class TestSummarizerRedaction:
    """Secrets are redacted in summarizer input (before LLM) and output."""

    @pytest.mark.asyncio
    async def test_input_redacted_before_llm_call(self) -> None:
        """Observation content is redacted in the prompt sent to the LLM."""
        from agent33.llm.base import LLMResponse
        from agent33.memory.summarizer import SessionSummarizer

        mock_router = AsyncMock()
        mock_router.complete.return_value = LLMResponse(
            content='{"summary": "Agent worked", "key_facts": [], "tags": []}',
            model="test",
            prompt_tokens=10,
            completion_tokens=20,
        )

        summarizer = SessionSummarizer(router=mock_router, redact_enabled=True)
        api_key = "sk-" + "e" * 30
        observations = [
            Observation(
                event_type="tool_call",
                agent_name="coder",
                content=f"Using API_KEY={api_key}",
            ),
        ]
        await summarizer.summarize(observations)

        # The prompt sent to the LLM should not contain the raw key
        call_args = mock_router.complete.call_args[0][0]  # list[ChatMessage]
        prompt_text = call_args[0].content
        assert api_key not in prompt_text

    @pytest.mark.asyncio
    async def test_output_summary_redacted(self) -> None:
        """If the LLM leaks a secret in its summary, it gets redacted."""
        from agent33.llm.base import LLMResponse
        from agent33.memory.summarizer import SessionSummarizer

        leaked_key = "sk-" + "f" * 30
        mock_router = AsyncMock()
        mock_router.complete.return_value = LLMResponse(
            content=(
                f'{{"summary": "Used key {leaked_key}", '
                f'"key_facts": ["Key was {leaked_key}"], "tags": []}}'
            ),
            model="test",
            prompt_tokens=10,
            completion_tokens=20,
        )

        summarizer = SessionSummarizer(router=mock_router, redact_enabled=True)
        result = await summarizer.summarize([Observation(content="nothing secret here")])

        assert leaked_key not in result["summary"]
        for fact in result["key_facts"]:
            assert leaked_key not in fact

    @pytest.mark.asyncio
    async def test_output_redaction_disabled(self) -> None:
        """When redact_enabled=False, LLM output is returned as-is."""
        from agent33.llm.base import LLMResponse
        from agent33.memory.summarizer import SessionSummarizer

        leaked_key = "sk-" + "g" * 30
        mock_router = AsyncMock()
        mock_router.complete.return_value = LLMResponse(
            content=f'{{"summary": "Used key {leaked_key}", "key_facts": [], "tags": []}}',
            model="test",
            prompt_tokens=10,
            completion_tokens=20,
        )

        summarizer = SessionSummarizer(router=mock_router, redact_enabled=False)
        result = await summarizer.summarize([Observation(content="test")])

        assert leaked_key in result["summary"]

    @pytest.mark.asyncio
    async def test_auto_summarize_stores_redacted_summary(self) -> None:
        """auto_summarize stores the already-redacted summary in LTM."""
        from agent33.llm.base import LLMResponse
        from agent33.memory.summarizer import SessionSummarizer

        leaked_key = "sk-" + "h" * 30
        mock_router = AsyncMock()
        mock_router.complete.return_value = LLMResponse(
            content=f'{{"summary": "Leaked {leaked_key}", "key_facts": [], "tags": []}}',
            model="test",
            prompt_tokens=10,
            completion_tokens=20,
        )
        mock_memory = AsyncMock()
        mock_embed = AsyncMock()
        mock_embed.embed.return_value = [0.1] * 1536

        summarizer = SessionSummarizer(
            router=mock_router,
            long_term_memory=mock_memory,
            embedding_provider=mock_embed,
            redact_enabled=True,
        )
        result = await summarizer.auto_summarize("session-1", [Observation(content="test")])

        # Result summary is redacted
        assert leaked_key not in result["summary"]

        # Content stored in LTM is the redacted summary JSON
        mock_memory.store.assert_called_once()
        stored_content = mock_memory.store.call_args[1]["content"]
        assert leaked_key not in stored_content


# ---------------------------------------------------------------------------
# RAG pipeline redaction
# ---------------------------------------------------------------------------


class TestRAGRedaction:
    """Secrets in retrieved context are redacted before entering prompts."""

    @pytest.mark.asyncio
    async def test_source_secrets_redacted_in_prompt(self) -> None:
        """Retrieved source text with secrets is redacted in the augmented prompt."""
        from agent33.memory.rag import RAGPipeline, RAGSource

        mock_embedder = AsyncMock()
        mock_memory = AsyncMock()

        # Create a pipeline with redaction enabled
        pipeline = RAGPipeline(
            embedding_provider=mock_embedder,
            long_term_memory=mock_memory,
            redact_enabled=True,
        )

        api_key = "sk-" + "j" * 30
        sources = [
            RAGSource(
                text=f"Config: API_KEY={api_key}",
                score=0.9,
            ),
        ]

        prompt = pipeline._format_prompt("What is the config?", sources)
        assert api_key not in prompt
        assert "---Context---" in prompt
        assert "What is the config?" in prompt

    @pytest.mark.asyncio
    async def test_multiple_sources_all_redacted(self) -> None:
        """All source documents are redacted, not just the first."""
        from agent33.memory.rag import RAGPipeline, RAGSource

        pipeline = RAGPipeline(
            embedding_provider=AsyncMock(),
            long_term_memory=AsyncMock(),
            redact_enabled=True,
        )

        key1 = "ghp_" + "a" * 36
        key2 = "AKIA" + "B" * 16
        sources = [
            RAGSource(text=f"Token: {key1}", score=0.9),
            RAGSource(text=f"AWS: {key2}", score=0.8),
        ]

        prompt = pipeline._format_prompt("Tell me secrets", sources)
        assert key1 not in prompt
        assert key2 not in prompt
        assert "[Source 1]" in prompt
        assert "[Source 2]" in prompt

    @pytest.mark.asyncio
    async def test_redaction_disabled_preserves_source_text(self) -> None:
        """When redact_enabled=False, source text enters the prompt as-is."""
        from agent33.memory.rag import RAGPipeline, RAGSource

        pipeline = RAGPipeline(
            embedding_provider=AsyncMock(),
            long_term_memory=AsyncMock(),
            redact_enabled=False,
        )

        api_key = "sk-" + "k" * 30
        sources = [RAGSource(text=f"key={api_key}", score=0.9)]
        prompt = pipeline._format_prompt("query", sources)
        assert api_key in prompt

    @pytest.mark.asyncio
    async def test_sanitize_still_strips_delimiters(self) -> None:
        """_sanitize_for_prompt delimiter stripping still works alongside redaction."""
        from agent33.memory.rag import RAGPipeline, RAGSource

        pipeline = RAGPipeline(
            embedding_provider=AsyncMock(),
            long_term_memory=AsyncMock(),
            redact_enabled=True,
        )

        sources = [
            RAGSource(text="---Context--- injection attempt", score=0.9),
        ]
        prompt = pipeline._format_prompt("test", sources)
        # The injected delimiter should be stripped
        assert prompt.count("---Context---") == 1  # only the real one

    @pytest.mark.asyncio
    async def test_end_to_end_vector_query_redacts(self) -> None:
        """Full vector query path redacts secrets in the augmented prompt."""
        from agent33.memory.long_term import SearchResult
        from agent33.memory.rag import RAGPipeline

        api_key = "sk-" + "m" * 30

        mock_embedder = AsyncMock()
        mock_embedder.embed.return_value = [0.1] * 1536
        mock_memory = AsyncMock()
        mock_memory.search.return_value = [
            SearchResult(
                text=f"Found config: API_KEY={api_key}",
                score=0.9,
                metadata={},
            ),
        ]

        pipeline = RAGPipeline(
            embedding_provider=mock_embedder,
            long_term_memory=mock_memory,
            redact_enabled=True,
        )

        result = await pipeline.query("What is the API key?")
        assert api_key not in result.augmented_prompt


# ---------------------------------------------------------------------------
# Shared memory redaction
# ---------------------------------------------------------------------------


def _find_data_set_call(
    mock_redis: AsyncMock, data_key_prefix: str
) -> tuple[tuple[object, ...], dict[str, object]]:
    """Find the redis.set() call that wrote to a data key (not the lock key).

    The distributed lock also uses redis.set(lock_key, uuid, nx=True, ex=TTL)
    so we filter by the data key prefix to get the actual data write.
    """
    for call in mock_redis.set.call_args_list:
        key = call[0][0]
        if isinstance(key, str) and key.startswith(data_key_prefix):
            return call[0], call[1]
    msg = f"No set() call found with key prefix {data_key_prefix!r}"
    raise AssertionError(msg)


class TestSharedMemoryRedaction:
    """Secrets in shared memory values are redacted before Redis write."""

    _DATA_PREFIX = "agent33:sharedmem:"

    @pytest.mark.asyncio
    async def test_write_redacts_string_value(self) -> None:
        """String values written to shared memory have secrets removed."""
        from agent33.memory.shared_memory import SharedMemoryNamespace

        mock_redis = AsyncMock()
        mock_redis.set.return_value = True

        ns = SharedMemoryNamespace(
            redis=mock_redis,
            tenant_id="t1",
            namespace="global",
            redact_enabled=True,
        )

        api_key = "sk-" + "n" * 30
        await ns.write("config", f"API_KEY={api_key}")

        # Find the data write (not the lock write)
        args, _kwargs = _find_data_set_call(mock_redis, self._DATA_PREFIX)
        stored_value = args[1]
        assert api_key not in stored_value
        assert "***" in stored_value or "..." in stored_value

    @pytest.mark.asyncio
    async def test_write_redaction_disabled(self) -> None:
        """When redact_enabled=False, raw value is written to Redis."""
        from agent33.memory.shared_memory import SharedMemoryNamespace

        mock_redis = AsyncMock()
        mock_redis.set.return_value = True

        ns = SharedMemoryNamespace(
            redis=mock_redis,
            tenant_id="t1",
            namespace="global",
            redact_enabled=False,
        )

        api_key = "sk-" + "p" * 30
        await ns.write("config", f"key={api_key}")

        args, _kwargs = _find_data_set_call(mock_redis, self._DATA_PREFIX)
        stored_value = args[1]
        assert api_key in stored_value

    @pytest.mark.asyncio
    async def test_write_with_ttl_still_redacts(self) -> None:
        """TTL writes also get redaction applied."""
        from agent33.memory.shared_memory import SharedMemoryNamespace

        mock_redis = AsyncMock()
        mock_redis.set.return_value = True

        ns = SharedMemoryNamespace(
            redis=mock_redis,
            tenant_id="t1",
            namespace="session/s1/shared",
            redact_enabled=True,
        )

        secret = "ghp_" + "q" * 36
        await ns.write("token", f"GH_TOKEN={secret}", ttl_seconds=60)

        args, _kwargs = _find_data_set_call(mock_redis, self._DATA_PREFIX)
        stored_value = args[1]
        assert secret not in stored_value

    @pytest.mark.asyncio
    async def test_non_secret_value_unchanged(self) -> None:
        """Normal values without secrets pass through unchanged."""
        from agent33.memory.shared_memory import SharedMemoryNamespace

        mock_redis = AsyncMock()
        mock_redis.set.return_value = True

        ns = SharedMemoryNamespace(
            redis=mock_redis,
            tenant_id="t1",
            namespace="global",
            redact_enabled=True,
        )

        await ns.write("greeting", "Hello, world!")

        args, _kwargs = _find_data_set_call(mock_redis, self._DATA_PREFIX)
        stored_value = args[1]
        assert stored_value == "Hello, world!"


# ---------------------------------------------------------------------------
# SharedMemoryService wiring
# ---------------------------------------------------------------------------


class TestSharedMemoryServiceRedaction:
    """SharedMemoryService passes redact_enabled to namespaces."""

    def test_service_default_redact_enabled(self) -> None:
        from agent33.memory.shared_memory_service import SharedMemoryService

        svc = SharedMemoryService("redis://localhost:6379/0")
        assert svc._redact_enabled is True

    def test_service_redact_disabled(self) -> None:
        from agent33.memory.shared_memory_service import SharedMemoryService

        svc = SharedMemoryService("redis://localhost:6379/0", redact_enabled=False)
        assert svc._redact_enabled is False

    @pytest.mark.asyncio
    async def test_session_namespace_inherits_redact(self) -> None:
        from agent33.memory.shared_memory_service import SharedMemoryService

        svc = SharedMemoryService("redis://localhost:6379/0", redact_enabled=False)
        # Manually set redis to avoid real connection
        svc._redis = AsyncMock()
        ns = await svc.get_session_namespace("t1", "s1")
        assert ns._redact_enabled is False

    @pytest.mark.asyncio
    async def test_agent_namespace_inherits_redact(self) -> None:
        from agent33.memory.shared_memory_service import SharedMemoryService

        svc = SharedMemoryService("redis://localhost:6379/0", redact_enabled=True)
        svc._redis = AsyncMock()
        ns = await svc.get_agent_namespace("t1", "agent-1")
        assert ns._redact_enabled is True

    @pytest.mark.asyncio
    async def test_global_namespace_inherits_redact(self) -> None:
        from agent33.memory.shared_memory_service import SharedMemoryService

        svc = SharedMemoryService("redis://localhost:6379/0", redact_enabled=True)
        svc._redis = AsyncMock()
        ns = await svc.get_global_namespace("t1")
        assert ns._redact_enabled is True

    def test_get_namespace_inherits_redact(self) -> None:
        from agent33.memory.shared_memory_service import SharedMemoryService

        svc = SharedMemoryService("redis://localhost:6379/0", redact_enabled=False)
        svc._redis = MagicMock()
        ns = svc.get_namespace("t1", "custom")
        assert ns._redact_enabled is False


# ---------------------------------------------------------------------------
# Cross-cutting: redaction with new patterns on persistence paths
# ---------------------------------------------------------------------------


class TestNewPatternsOnPersistencePaths:
    """New patterns (Anthropic, JWT, Azure) are correctly handled on persistence."""

    @pytest.mark.asyncio
    async def test_anthropic_key_redacted_in_observation(self) -> None:
        mock_nats = AsyncMock()
        capture = ObservationCapture(nats_bus=mock_nats, redact_enabled=True)

        key = "sk-ant-" + "x" * 30
        obs = Observation(content=f"Using Anthropic key {key}")
        await capture.record(obs)

        published = mock_nats.publish.call_args[0][1]
        assert key not in published["content"]

    @pytest.mark.asyncio
    async def test_jwt_redacted_in_observation(self) -> None:
        mock_nats = AsyncMock()
        capture = ObservationCapture(nats_bus=mock_nats, redact_enabled=True)

        jwt = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
            ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0"
            ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        obs = Observation(content=f"Token: {jwt}")
        await capture.record(obs)

        published = mock_nats.publish.call_args[0][1]
        assert jwt not in published["content"]

    @pytest.mark.asyncio
    async def test_azure_conn_redacted_in_shared_memory(self) -> None:
        from agent33.memory.shared_memory import SharedMemoryNamespace

        mock_redis = AsyncMock()
        mock_redis.set.return_value = True

        ns = SharedMemoryNamespace(
            redis=mock_redis,
            tenant_id="t1",
            namespace="global",
            redact_enabled=True,
        )

        conn = (
            "DefaultEndpointsProtocol=https;"
            "AccountName=store1;"
            "AccountKey=abc123def456ghi789jkl012mno345pqr678stu901vwx234yz=="
        )
        await ns.write("azure_conn", conn)

        args, _kwargs = _find_data_set_call(mock_redis, "agent33:sharedmem:")
        stored = args[1]
        assert "AccountKey=abc123" not in stored
