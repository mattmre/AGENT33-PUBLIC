"""Tests for llama.cpp provider wiring (local orchestration engine)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent33.agents.runtime import AgentRuntime, _resolve_default_model
from agent33.api.routes.agents import _default_agent_model, _llamacpp_enabled
from agent33.config import settings
from agent33.llm.openai import OpenAIProvider
from agent33.llm.router import ModelRouter
from agent33.llm.runtime_config import build_model_router


class TestLlamaCppEnabled:
    """Verify the _llamacpp_enabled() helper returns the correct boolean."""

    def test_llamacpp_enabled_when_engine_is_llamacpp(self) -> None:
        with patch.object(settings, "local_orchestration_engine", "llama.cpp"):
            assert _llamacpp_enabled() is True

    def test_llamacpp_enabled_when_engine_is_llamacpp_noslash(self) -> None:
        with patch.object(settings, "local_orchestration_engine", "llamacpp"):
            assert _llamacpp_enabled() is True

    def test_llamacpp_enabled_when_engine_is_vllm(self) -> None:
        with patch.object(settings, "local_orchestration_engine", "vLLM"):
            assert _llamacpp_enabled() is True

    def test_llamacpp_disabled_when_engine_is_ollama(self) -> None:
        with patch.object(settings, "local_orchestration_engine", "ollama"):
            assert _llamacpp_enabled() is False


class TestDefaultAgentModel:
    """Verify _default_agent_model() returns the right model name."""

    def test_default_model_returns_local_model_when_llamacpp(self) -> None:
        with (
            patch.object(settings, "local_orchestration_engine", "llama.cpp"),
            patch.object(settings, "local_orchestration_model", "test-local-model"),
        ):
            assert _default_agent_model() == "test-local-model"

    def test_default_model_returns_ollama_model_when_disabled(self) -> None:
        with (
            patch.object(settings, "local_orchestration_engine", "ollama"),
            patch.object(settings, "ollama_default_model", "llama3.2"),
        ):
            assert _default_agent_model() == "llama3.2"


class TestModelRouterRegistration:
    """Verify that llamacpp provider can be registered on a ModelRouter."""

    def test_model_router_registers_llamacpp_when_enabled(self) -> None:
        router = ModelRouter(default_provider="llamacpp")
        provider = OpenAIProvider(
            api_key="local",
            base_url="http://localhost:8033/v1",
            default_model="qwen3-coder-next",
        )
        router.register("llamacpp", provider)

        # Verify the provider is stored under the "llamacpp" key
        assert "llamacpp" in router._providers
        assert router._providers["llamacpp"] is provider
        assert router._default_provider == "llamacpp"

    @pytest.mark.parametrize(
        "engine_value",
        ["llama.cpp", "llamacpp", "vLLM"],
    )
    def test_model_router_default_provider_is_llamacpp_for_valid_engines(
        self, engine_value: str
    ) -> None:
        """Local orchestration engines should result in llamacpp as default."""
        with patch.object(settings, "local_orchestration_engine", engine_value):
            assert _llamacpp_enabled() is True
            router = ModelRouter(default_provider="llamacpp" if _llamacpp_enabled() else "ollama")
            assert router._default_provider == "llamacpp"

    @pytest.mark.asyncio
    async def test_runtime_router_registers_lm_studio_provider(self) -> None:
        """LM Studio model refs must route to the local OpenAI-compatible provider."""
        router = build_model_router()
        try:
            resolved = router.resolve("lmstudio/qwen2.5-coder-7b-instruct")
            assert resolved.provider_name == "lmstudio"
            assert resolved.model_name == "qwen2.5-coder-7b-instruct"
        finally:
            for provider in router.providers.values():
                close = getattr(provider, "close", None)
                if close is not None:
                    await close()


class TestResolveDefaultModel:
    """Verify _resolve_default_model() used by AgentRuntime.__init__."""

    def test_returns_local_model_when_llamacpp_engine(self) -> None:
        with (
            patch.object(settings, "local_orchestration_engine", "llama.cpp"),
            patch.object(settings, "local_orchestration_model", "my-local-gguf"),
        ):
            assert _resolve_default_model() == "my-local-gguf"

    def test_returns_local_model_when_vllm_engine(self) -> None:
        with (
            patch.object(settings, "local_orchestration_engine", "vLLM"),
            patch.object(settings, "local_orchestration_model", "my-local-vllm-model"),
        ):
            assert _resolve_default_model() == "my-local-vllm-model"

    def test_returns_ollama_model_when_engine_is_ollama(self) -> None:
        with (
            patch.object(settings, "local_orchestration_engine", "ollama"),
            patch.object(settings, "ollama_default_model", "mistral-nemo"),
        ):
            assert _resolve_default_model() == "mistral-nemo"

    def test_runtime_uses_resolved_default_when_model_is_none(self) -> None:
        """AgentRuntime should use _resolve_default_model() -- not 'llama3.2'."""
        from agent33.agents.definition import (
            AgentCapability,
            AgentConstraints,
            AgentDefinition,
            AgentParameter,
            AgentRole,
        )

        definition = AgentDefinition(
            name="test-agent",
            version="1.0.0",
            role=AgentRole.IMPLEMENTER,
            description="test",
            capabilities=[AgentCapability.CODE_EXECUTION],
            inputs={
                "task": AgentParameter(type="string", description="t", required=True),
            },
            outputs={
                "result": AgentParameter(type="string", description="r"),
            },
            constraints=AgentConstraints(),
        )
        mock_router = MagicMock(spec=ModelRouter)

        with (
            patch.object(settings, "local_orchestration_engine", "llama.cpp"),
            patch.object(settings, "local_orchestration_model", "custom-gguf-model"),
        ):
            runtime = AgentRuntime(definition=definition, router=mock_router, model=None)

        assert runtime._model == "custom-gguf-model"

    def test_runtime_respects_explicit_model(self) -> None:
        """When model is explicitly provided, _resolve_default_model() is not used."""
        from agent33.agents.definition import (
            AgentCapability,
            AgentConstraints,
            AgentDefinition,
            AgentParameter,
            AgentRole,
        )

        definition = AgentDefinition(
            name="test-agent",
            version="1.0.0",
            role=AgentRole.IMPLEMENTER,
            description="test",
            capabilities=[AgentCapability.CODE_EXECUTION],
            inputs={
                "task": AgentParameter(type="string", description="t", required=True),
            },
            outputs={
                "result": AgentParameter(type="string", description="r"),
            },
            constraints=AgentConstraints(),
        )
        mock_router = MagicMock(spec=ModelRouter)

        runtime = AgentRuntime(definition=definition, router=mock_router, model="explicit-model")

        assert runtime._model == "explicit-model"
