"""Test harness for agent definitions -- canned input/output regression testing."""

from __future__ import annotations

import dataclasses
import json
import logging
from typing import TYPE_CHECKING, Any

from agent33.agents.definition import AgentDefinition
from agent33.agents.runtime import AgentResult, AgentRuntime
from agent33.llm.base import ChatMessage, LLMResponse, LLMStreamChunk
from agent33.llm.router import ModelRouter

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True, slots=True)
class CannedPair:
    """A canned input/output pair for regression testing."""

    input_data: dict[str, Any]
    expected_output: dict[str, Any]


class _CannedProvider:
    """Minimal LLM provider that returns pre-configured responses."""

    def __init__(self, responses: dict[str, str]) -> None:
        self._responses = responses

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        user_content = ""
        for msg in reversed(messages):
            if msg.role == "user":
                user_content = msg.text_content
                break

        response_text = self._responses.get(user_content, json.dumps({"result": user_content}))
        return LLMResponse(
            content=response_text,
            model=model,
            prompt_tokens=len(user_content),
            completion_tokens=len(response_text),
        )

    async def list_models(self) -> list[str]:
        return ["mock"]

    async def stream_complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[LLMStreamChunk, None]:
        response = await self.complete(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
        )
        yield LLMStreamChunk(
            delta_content=response.content,
            finish_reason=response.finish_reason,
            model=response.model,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            usage_available=response.usage_available,
        )


class AgentTestHarness:
    """Loads and tests agent definitions with canned inputs and outputs."""

    def __init__(self) -> None:
        self._definition: AgentDefinition | None = None
        self._canned_pairs: list[CannedPair] = []

    def load_agent(self, path: str | Path) -> AgentDefinition:
        """Load an agent definition from a JSON file."""
        self._definition = AgentDefinition.load_from_file(path)
        logger.info("Loaded agent: %s v%s", self._definition.name, self._definition.version)
        return self._definition

    def load_definition(self, definition: AgentDefinition) -> None:
        """Load a pre-built agent definition directly."""
        self._definition = definition

    def add_canned_pair(
        self,
        input_data: dict[str, Any],
        expected_output: dict[str, Any],
    ) -> None:
        """Register a canned input/output pair for regression testing."""
        self._canned_pairs.append(
            CannedPair(input_data=input_data, expected_output=expected_output),
        )

    async def test_with_input(
        self,
        input_data: dict[str, Any],
        responses: dict[str, str] | None = None,
    ) -> AgentResult:
        """Execute the agent with the given input data and optional canned LLM responses.

        Parameters
        ----------
        input_data:
            Agent input data dictionary.
        responses:
            Optional mapping of user message content to LLM response content.
            If not provided, the LLM will echo the input back as JSON.

        Returns
        -------
        AgentResult:
            The result of the agent invocation.
        """
        defn = self._require_definition()
        responses = responses or {}

        provider = _CannedProvider(responses)
        router = ModelRouter()
        router.register("mock", provider)

        runtime = AgentRuntime(definition=defn, router=router, model="mock")
        return await runtime.invoke(input_data)

    async def run_regression(
        self,
        responses: dict[str, str] | None = None,
    ) -> list[tuple[CannedPair, AgentResult]]:
        """Run all registered canned pairs and return results.

        Returns a list of ``(pair, result)`` tuples.
        """
        results: list[tuple[CannedPair, AgentResult]] = []
        for pair in self._canned_pairs:
            result = await self.test_with_input(pair.input_data, responses)
            results.append((pair, result))
        return results

    def _require_definition(self) -> AgentDefinition:
        if self._definition is None:
            raise RuntimeError("No agent loaded. Call load_agent() or load_definition() first.")
        return self._definition
