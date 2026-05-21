"""Tests for AirLLM provider."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from agent33.llm.base import ChatMessage


class TestAirLLMProvider:
    """Test AirLLMProvider with mocked airllm/torch dependencies."""

    def test_import_error_without_airllm(self) -> None:
        """Provider raises ImportError when airllm not installed."""
        # Ensure the module is freshly imported with airllm mocked as None
        mod_name = "agent33.llm.airllm_provider"
        saved = sys.modules.pop(mod_name, None)
        try:
            with patch.dict("sys.modules", {"airllm": None}):
                import importlib

                mod = importlib.import_module(mod_name)
                importlib.reload(mod)
                with pytest.raises(ImportError, match="airllm is not installed"):
                    mod.AirLLMProvider(model_path="/fake/model")
        finally:
            if saved is not None:
                sys.modules[mod_name] = saved

    @pytest.mark.asyncio
    async def test_list_models(self) -> None:
        """list_models returns airllm-prefixed model name."""
        # Pre-populate sys.modules so import doesn't trigger real airllm/torch
        mock_airllm = MagicMock()
        mock_transformers = MagicMock()
        mod_name = "agent33.llm.airllm_provider"
        saved = sys.modules.pop(mod_name, None)
        try:
            with patch.dict(
                "sys.modules",
                {"airllm": mock_airllm, "transformers": mock_transformers},
            ):
                import importlib

                mod = importlib.import_module(mod_name)
                importlib.reload(mod)
                provider = mod.AirLLMProvider(model_path="/models/meta-llama/Llama-3-70B")
                models = await provider.list_models()
                assert len(models) == 1
                assert models[0] == "airllm-Llama-3-70B"
        finally:
            if saved is not None:
                sys.modules[mod_name] = saved

    def test_format_chat_fallback(self) -> None:
        """_format_chat falls back to simple format without tokenizer."""
        # Import the module with mocked deps
        mock_airllm = MagicMock()
        mock_transformers = MagicMock()
        mod_name = "agent33.llm.airllm_provider"
        saved = sys.modules.pop(mod_name, None)
        try:
            with patch.dict(
                "sys.modules",
                {"airllm": mock_airllm, "transformers": mock_transformers},
            ):
                import importlib

                mod = importlib.import_module(mod_name)
                importlib.reload(mod)

                messages = [
                    ChatMessage(role="system", content="You are helpful"),
                    ChatMessage(role="user", content="Hi"),
                ]
                result = mod._format_chat(messages)
                assert "<|system|>" in result
                assert "<|user|>" in result
                assert "<|assistant|>" in result
        finally:
            if saved is not None:
                sys.modules[mod_name] = saved


class TestRouterIntegration:
    """Test that ModelRouter routes airllm- prefixed models correctly."""

    def test_airllm_prefix_in_default_map(self) -> None:
        from agent33.llm.router import _DEFAULT_PREFIX_MAP

        prefixes = [p for p, _ in _DEFAULT_PREFIX_MAP]
        assert "airllm-" in prefixes

    def test_router_routes_to_airllm(self) -> None:
        from agent33.llm.router import ModelRouter

        mock_provider = MagicMock()
        router = ModelRouter(providers={"airllm": mock_provider})
        result = router.route("airllm-llama70b")
        assert result is mock_provider
