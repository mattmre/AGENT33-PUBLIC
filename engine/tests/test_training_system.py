"""Tests for the self-evolving training system."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent33.training.emitter import TraceEmitter


class TestTraceEmitter:
    """Test structured trace emission."""

    def test_new_rollout(self) -> None:
        emitter = TraceEmitter()
        rid = emitter.new_rollout()
        assert rid
        assert emitter.rollout_id == rid

    def test_emit_spans(self) -> None:
        emitter = TraceEmitter()
        emitter.new_rollout()

        pid = emitter.emit_prompt("agent1", [{"role": "user", "content": "hi"}])
        _tid = emitter.emit_tool_call("agent1", "shell", {"cmd": "ls"})
        _rid = emitter.emit_result("agent1", "output text", parent_id=pid)
        _rew = emitter.emit_reward("agent1", 0.85, "good output")

        spans = emitter.collect()
        assert len(spans) == 4
        assert spans[0].span_type == "prompt"
        assert spans[1].span_type == "tool_call"
        assert spans[2].span_type == "result"
        assert spans[2].parent_span_id == pid
        assert spans[3].span_type == "reward"
        assert "0.85" in spans[3].content

    def test_new_rollout_clears(self) -> None:
        emitter = TraceEmitter()
        emitter.new_rollout()
        emitter.emit_prompt("a", [])
        assert len(emitter.collect()) == 1
        emitter.new_rollout()
        assert len(emitter.collect()) == 0


class TestSelfEvaluator:
    """Test autonomous self-evaluation."""

    @pytest.mark.asyncio
    async def test_evaluate_parses_score(self) -> None:
        from agent33.llm.base import LLMResponse
        from agent33.training.evaluator import SelfEvaluator

        mock_router = AsyncMock()
        mock_router.complete.return_value = LLMResponse(
            content='{"score": 0.85, "reason": "good output"}',
            model="test",
            prompt_tokens=10,
            completion_tokens=5,
        )

        evaluator = SelfEvaluator(router=mock_router)
        score = await evaluator.evaluate("result text", "task context")
        assert score == 0.85

    @pytest.mark.asyncio
    async def test_evaluate_handles_bad_json(self) -> None:
        from agent33.llm.base import LLMResponse
        from agent33.training.evaluator import SelfEvaluator

        mock_router = AsyncMock()
        mock_router.complete.return_value = LLMResponse(
            content="not json",
            model="test",
            prompt_tokens=10,
            completion_tokens=5,
        )

        evaluator = SelfEvaluator(router=mock_router)
        score = await evaluator.evaluate("result", "context")
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_evaluate_clamps_score(self) -> None:
        from agent33.llm.base import LLMResponse
        from agent33.training.evaluator import SelfEvaluator

        mock_router = AsyncMock()
        mock_router.complete.return_value = LLMResponse(
            content='{"score": 5.0, "reason": "over max"}',
            model="test",
            prompt_tokens=10,
            completion_tokens=5,
        )

        evaluator = SelfEvaluator(router=mock_router)
        score = await evaluator.evaluate("result", "context")
        assert score == 1.0


class TestAPOAlgorithm:
    """Test Automatic Prompt Optimization."""

    @pytest.mark.asyncio
    async def test_apo_returns_prompt(self) -> None:
        from agent33.llm.base import LLMResponse
        from agent33.training.algorithm import APO

        mock_router = AsyncMock()
        mock_router.complete.return_value = LLMResponse(
            content="You are an improved agent. Be more precise.",
            model="test",
            prompt_tokens=10,
            completion_tokens=20,
        )

        apo = APO(router=mock_router)
        rollouts = [
            {"total_reward": 0.9, "spans": [{"span_type": "result", "content": "good"}]},
            {"total_reward": 0.2, "spans": [{"span_type": "result", "content": "bad"}]},
        ]
        result = await apo.run(rollouts, "You are an agent.")
        assert "improved" in result.lower() or len(result) > 0

    @pytest.mark.asyncio
    async def test_apo_empty_rollouts(self) -> None:
        from agent33.training.algorithm import APO

        apo = APO(router=AsyncMock())
        result = await apo.run([], "original prompt")
        assert result == "original prompt"


class TestSFTAlgorithm:
    """Test SFT data extraction."""

    @pytest.mark.asyncio
    async def test_sft_extracts_pairs(self) -> None:
        from agent33.training.algorithm import SFT

        sft = SFT()
        rollouts = [
            {
                "total_reward": 0.9,
                "spans": [
                    {"span_type": "prompt", "content": "input data"},
                    {"span_type": "result", "content": "output data"},
                ],
            },
        ]
        result = await sft.run(rollouts, "prompt")
        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["input"] == "input data"
        assert data[0]["output"] == "output data"


class TestTrainingScheduler:
    """Test training scheduler."""

    def test_record_request(self) -> None:
        from agent33.training.scheduler import TrainingScheduler

        scheduler = TrainingScheduler(
            optimizer=MagicMock(),
            optimize_every_n_requests=10,
        )
        scheduler.record_request("agent1", "prompt text")
        assert scheduler._request_count == 1
        assert "agent1" in scheduler._agents


class TestAgentOptimizer:
    """Test agent optimizer."""

    @pytest.mark.asyncio
    async def test_optimize_skips_few_rollouts(self) -> None:
        from agent33.training.optimizer import AgentOptimizer

        mock_store = AsyncMock()
        mock_store.get_rollouts.return_value = [{"rollout_id": "r1", "total_reward": 0.5}]

        optimizer = AgentOptimizer(
            store=mock_store,
            algorithm=AsyncMock(),
            router=AsyncMock(),
            min_rollouts=10,
        )
        result = await optimizer.optimize("agent1", "original prompt")
        assert result == "original prompt"  # Not enough data, returns original
