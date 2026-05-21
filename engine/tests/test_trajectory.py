"""Tests for Phase 59: Trajectory saver."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent33.agents.runtime import AgentRuntime
from agent33.agents.trajectory import (
    _build_trajectory_record,
    _trajectory_filename,
    convert_scratchpad_to_think,
    get_trajectory_stats,
    save_trajectory,
)

# ---------------------------------------------------------------------------
# convert_scratchpad_to_think
# ---------------------------------------------------------------------------


class TestConvertScratchpadToThink:
    def test_basic_conversion(self) -> None:
        text = "<scratchpad>reasoning here</scratchpad>"
        assert convert_scratchpad_to_think(text) == "<think>reasoning here</think>"

    def test_case_insensitive(self) -> None:
        text = "<Scratchpad>reasoning</Scratchpad>"
        assert convert_scratchpad_to_think(text) == "<think>reasoning</think>"

    def test_multiline_content(self) -> None:
        text = "<scratchpad>\nstep 1\nstep 2\n</scratchpad>"
        result = convert_scratchpad_to_think(text)
        assert result == "<think>\nstep 1\nstep 2\n</think>"

    def test_multiple_blocks(self) -> None:
        text = "<scratchpad>first</scratchpad> then <scratchpad>second</scratchpad>"
        result = convert_scratchpad_to_think(text)
        assert result == "<think>first</think> then <think>second</think>"

    def test_no_scratchpad_unchanged(self) -> None:
        text = "Hello, this is a normal message."
        assert convert_scratchpad_to_think(text) == text

    def test_existing_think_tags_unchanged(self) -> None:
        text = "<think>already correct</think>"
        assert convert_scratchpad_to_think(text) == text

    def test_mixed_content(self) -> None:
        text = "Before <scratchpad>inside</scratchpad> after"
        assert convert_scratchpad_to_think(text) == "Before <think>inside</think> after"


# ---------------------------------------------------------------------------
# _trajectory_filename
# ---------------------------------------------------------------------------


class TestTrajectoryFilename:
    def test_success_filename(self) -> None:
        assert _trajectory_filename(True) == "trajectories_success.jsonl"

    def test_failure_filename(self) -> None:
        assert _trajectory_filename(False) == "trajectories_failed.jsonl"


# ---------------------------------------------------------------------------
# _build_trajectory_record
# ---------------------------------------------------------------------------


class TestBuildTrajectoryRecord:
    def test_basic_structure(self) -> None:
        conversation = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        record = _build_trajectory_record(conversation, "llama3.2", True)

        assert "conversations" in record
        assert "model" in record
        assert "completed" in record
        assert "timestamp" in record

        assert record["model"] == "llama3.2"
        assert record["completed"] is True

    def test_sharegpt_role_mapping(self) -> None:
        conversation = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
            {"role": "tool", "content": "result"},
        ]
        record = _build_trajectory_record(conversation, "test", True)
        turns = record["conversations"]

        assert turns[0]["from"] == "system"
        assert turns[1]["from"] == "human"
        assert turns[2]["from"] == "gpt"
        assert turns[3]["from"] == "tool"

    def test_scratchpad_normalised(self) -> None:
        conversation = [
            {"role": "assistant", "content": "<scratchpad>thinking</scratchpad> answer"},
        ]
        record = _build_trajectory_record(conversation, "test", True)
        assert "<think>thinking</think>" in record["conversations"][0]["value"]
        assert "<scratchpad>" not in record["conversations"][0]["value"]

    def test_secret_redaction_applied(self) -> None:
        conversation = [
            {"role": "user", "content": "My key is sk-abcdefghijklmnopqrstuvwxyz123456"},
        ]
        record = _build_trajectory_record(conversation, "test", True, redaction_enabled=True)
        value = record["conversations"][0]["value"]
        # The key should be redacted (not present in full).
        assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in value

    def test_secret_redaction_disabled(self) -> None:
        conversation = [
            {"role": "user", "content": "My key is sk-abcdefghijklmnopqrstuvwxyz123456"},
        ]
        record = _build_trajectory_record(conversation, "test", True, redaction_enabled=False)
        value = record["conversations"][0]["value"]
        assert "sk-abcdefghijklmnopqrstuvwxyz123456" in value

    def test_timestamp_is_iso_format(self) -> None:
        record = _build_trajectory_record([{"role": "user", "content": "hi"}], "test", True)
        # Should parse without error.
        from datetime import datetime

        datetime.fromisoformat(record["timestamp"])

    def test_failed_trajectory_flag(self) -> None:
        record = _build_trajectory_record([{"role": "user", "content": "hi"}], "test", False)
        assert record["completed"] is False


# ---------------------------------------------------------------------------
# save_trajectory (async, with filesystem)
# ---------------------------------------------------------------------------


class TestSaveTrajectory:
    async def test_creates_success_file(self, tmp_path: Path) -> None:
        conversation = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        await save_trajectory(conversation, "llama3.2", True, str(tmp_path))

        expected = tmp_path / "trajectories_success.jsonl"
        assert expected.exists()

        with open(expected, encoding="utf-8") as f:
            record = json.loads(f.readline())

        assert record["completed"] is True
        assert record["model"] == "llama3.2"
        assert len(record["conversations"]) == 2
        assert record["conversations"][0]["from"] == "human"
        assert record["conversations"][1]["from"] == "gpt"

    async def test_creates_failed_file(self, tmp_path: Path) -> None:
        conversation = [
            {"role": "user", "content": "Do something"},
            {"role": "assistant", "content": "Error occurred"},
        ]
        await save_trajectory(conversation, "llama3.2", False, str(tmp_path))

        expected = tmp_path / "trajectories_failed.jsonl"
        assert expected.exists()

        with open(expected, encoding="utf-8") as f:
            record = json.loads(f.readline())
        assert record["completed"] is False

    async def test_appends_to_existing_file(self, tmp_path: Path) -> None:
        conv1 = [{"role": "user", "content": "First"}]
        conv2 = [{"role": "user", "content": "Second"}]

        await save_trajectory(conv1, "model-a", True, str(tmp_path))
        await save_trajectory(conv2, "model-b", True, str(tmp_path))

        expected = tmp_path / "trajectories_success.jsonl"
        lines = expected.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

        r1 = json.loads(lines[0])
        r2 = json.loads(lines[1])
        assert r1["model"] == "model-a"
        assert r2["model"] == "model-b"

    async def test_custom_filename(self, tmp_path: Path) -> None:
        conversation = [{"role": "user", "content": "Hello"}]
        await save_trajectory(conversation, "test", True, str(tmp_path), filename="custom.jsonl")

        assert (tmp_path / "custom.jsonl").exists()

    async def test_creates_parent_directories(self, tmp_path: Path) -> None:
        nested_dir = str(tmp_path / "deep" / "nested" / "dir")
        conversation = [{"role": "user", "content": "Hello"}]
        await save_trajectory(conversation, "test", True, nested_dir)

        assert (Path(nested_dir) / "trajectories_success.jsonl").exists()

    async def test_empty_conversation_skipped(self, tmp_path: Path) -> None:
        await save_trajectory([], "test", True, str(tmp_path))
        # No file should be created.
        assert not (tmp_path / "trajectories_success.jsonl").exists()

    async def test_redaction_applied_in_saved_file(self, tmp_path: Path) -> None:
        conversation = [
            {"role": "user", "content": "Use key sk-abcdefghijklmnopqrstuvwxyz123456"},
        ]
        await save_trajectory(conversation, "test", True, str(tmp_path))

        with open(tmp_path / "trajectories_success.jsonl", encoding="utf-8") as f:
            record = json.loads(f.readline())

        value = record["conversations"][0]["value"]
        assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in value

    async def test_scratchpad_normalised_in_saved_file(self, tmp_path: Path) -> None:
        conversation = [
            {"role": "assistant", "content": "<scratchpad>reason</scratchpad> answer"},
        ]
        await save_trajectory(conversation, "test", True, str(tmp_path))

        with open(tmp_path / "trajectories_success.jsonl", encoding="utf-8") as f:
            record = json.loads(f.readline())

        assert "<think>reason</think>" in record["conversations"][0]["value"]

    async def test_separates_success_and_failure(self, tmp_path: Path) -> None:
        success_conv = [{"role": "user", "content": "Success"}]
        failure_conv = [{"role": "user", "content": "Failure"}]

        await save_trajectory(success_conv, "test", True, str(tmp_path))
        await save_trajectory(failure_conv, "test", False, str(tmp_path))

        success_path = tmp_path / "trajectories_success.jsonl"
        failure_path = tmp_path / "trajectories_failed.jsonl"
        assert success_path.exists()
        assert failure_path.exists()

        with open(success_path, encoding="utf-8") as f:
            assert json.loads(f.readline())["completed"] is True
        with open(failure_path, encoding="utf-8") as f:
            assert json.loads(f.readline())["completed"] is False


# ---------------------------------------------------------------------------
# get_trajectory_stats
# ---------------------------------------------------------------------------


class TestGetTrajectoryStats:
    async def test_empty_dir(self, tmp_path: Path) -> None:
        stats = get_trajectory_stats(str(tmp_path))
        assert stats["output_dir"] == str(tmp_path)
        assert stats["files"] == {}

    async def test_nonexistent_dir(self, tmp_path: Path) -> None:
        stats = get_trajectory_stats(str(tmp_path / "noexist"))
        assert stats["files"] == {}

    async def test_counts_records(self, tmp_path: Path) -> None:
        # Write 3 success records.
        for i in range(3):
            await save_trajectory(
                [{"role": "user", "content": f"msg{i}"}], "test", True, str(tmp_path)
            )
        # Write 1 failure record.
        await save_trajectory([{"role": "user", "content": "fail"}], "test", False, str(tmp_path))

        stats = get_trajectory_stats(str(tmp_path))
        assert stats["files"]["trajectories_success.jsonl"]["record_count"] == 3
        assert stats["files"]["trajectories_failed.jsonl"]["record_count"] == 1
        assert stats["files"]["trajectories_success.jsonl"]["size_bytes"] > 0


def _mock_runtime_definition() -> MagicMock:
    definition = MagicMock()
    definition.name = "trajectory-agent"
    definition.inputs = {}
    definition.outputs = {"result": MagicMock(type="string", description="result")}
    definition.constraints = MagicMock(
        max_tokens=256,
        max_retries=0,
        timeout_seconds=30,
    )
    definition.capabilities = []
    definition.spec_capabilities = []
    definition.governance = MagicMock(
        scope="",
        commands="",
        network="",
        approval_required=[],
        tool_policies={},
    )
    definition.autonomy_level = MagicMock(value="full")
    definition.ownership = MagicMock(owner="", escalation_target="")
    definition.dependencies = []
    definition.skills = []
    definition.description = "trajectory runtime test"
    definition.agent_id = ""
    return definition


def _mock_runtime_router(
    *,
    response_content: str = '{"result": "ok"}',
    side_effect: Exception | None = None,
) -> MagicMock:
    response = MagicMock()
    response.content = response_content
    response.total_tokens = 42
    response.model = "test-model"

    router = MagicMock()
    if side_effect is None:
        router.complete = AsyncMock(return_value=response)
    else:
        router.complete = AsyncMock(side_effect=side_effect)
    return router


def _configure_runtime_trajectory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    enabled: bool,
) -> tuple[object, object, str]:
    from agent33 import config as config_module
    from agent33.agents import runtime as runtime_module

    expected_output_dir = str((tmp_path / "trajectories").resolve())
    monkeypatch.setattr(config_module.settings, "trajectory_capture_enabled", enabled)
    monkeypatch.setattr(config_module.settings, "trajectory_output_dir", "trajectories")
    monkeypatch.setattr(runtime_module.Path, "cwd", lambda: tmp_path)
    return config_module, runtime_module, expected_output_dir


class TestRuntimeInvokeTrajectory:
    async def test_invoke_saves_successful_trajectory(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        config_module, runtime_module, expected_output_dir = _configure_runtime_trajectory(
            monkeypatch,
            tmp_path,
            enabled=True,
        )

        save_mock = AsyncMock()
        monkeypatch.setattr(runtime_module, "save_trajectory", save_mock)

        runtime = AgentRuntime(
            definition=_mock_runtime_definition(),
            router=_mock_runtime_router(),
        )

        result = await runtime.invoke({"query": "hello"})

        assert result.output == {"result": "ok"}
        save_mock.assert_awaited_once()
        args, kwargs = save_mock.await_args
        conversation, model, completed, output_dir = args[:4]
        assert model == "test-model"
        assert completed is True
        assert output_dir == expected_output_dir
        assert conversation[0]["role"] == "system"
        assert conversation[1]["role"] == "user"
        assert '"query": "hello"' in conversation[1]["content"]
        assert conversation[2] == {"role": "assistant", "content": '{"result": "ok"}'}
        assert kwargs["redaction_enabled"] == config_module.settings.redact_secrets_enabled

    async def test_invoke_saves_failed_trajectory(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        config_module, runtime_module, expected_output_dir = _configure_runtime_trajectory(
            monkeypatch,
            tmp_path,
            enabled=True,
        )
        # Pin the default model so the assertion is deterministic regardless of
        # environment variables (e.g. OLLAMA_DEFAULT_MODEL in CI).
        monkeypatch.setattr(config_module.settings, "ollama_default_model", "llama3.2")
        monkeypatch.setattr(config_module.settings, "local_orchestration_engine", "")

        save_mock = AsyncMock()
        monkeypatch.setattr(runtime_module, "save_trajectory", save_mock)

        runtime = AgentRuntime(
            definition=_mock_runtime_definition(),
            router=_mock_runtime_router(side_effect=RuntimeError("router boom")),
        )

        with pytest.raises(RuntimeError, match="failed after 1 attempts"):
            await runtime.invoke({"query": "hello"})

        save_mock.assert_awaited_once()
        args, _kwargs = save_mock.await_args
        conversation, model, completed, output_dir = args[:4]
        assert model == "llama3.2"
        assert completed is False
        assert output_dir == expected_output_dir
        assert conversation[-1]["role"] == "assistant"
        assert (
            "RuntimeError: Agent 'trajectory-agent' failed after 1 attempts"
            in conversation[-1]["content"]
        )

    async def test_invoke_saves_trajectory_on_post_llm_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        config_module, runtime_module, expected_output_dir = _configure_runtime_trajectory(
            monkeypatch,
            tmp_path,
            enabled=True,
        )

        save_mock = AsyncMock()
        monkeypatch.setattr(runtime_module, "save_trajectory", save_mock)
        monkeypatch.setattr(
            runtime_module,
            "_parse_output",
            MagicMock(side_effect=ValueError("parse boom")),
        )

        runtime = AgentRuntime(
            definition=_mock_runtime_definition(),
            router=_mock_runtime_router(),
        )

        with pytest.raises(ValueError, match="parse boom"):
            await runtime.invoke({"query": "hello"})

        save_mock.assert_awaited_once()
        args, _kwargs = save_mock.await_args
        conversation, model, completed, output_dir = args[:4]
        assert model == "test-model"
        assert completed is False
        assert output_dir == expected_output_dir
        assert conversation[-2] == {"role": "assistant", "content": '{"result": "ok"}'}
        assert "ValueError: parse boom" in conversation[-1]["content"]

    async def test_invoke_trajectory_save_is_fail_open(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _config_module, runtime_module, _expected_output_dir = _configure_runtime_trajectory(
            monkeypatch,
            tmp_path,
            enabled=True,
        )
        monkeypatch.setattr(
            runtime_module,
            "save_trajectory",
            AsyncMock(side_effect=RuntimeError("disk full")),
        )

        runtime = AgentRuntime(
            definition=_mock_runtime_definition(),
            router=_mock_runtime_router(),
        )

        result = await runtime.invoke({"query": "hello"})

        assert result.output == {"result": "ok"}


# ---------------------------------------------------------------------------
# Iterative invoke trajectory tests
# ---------------------------------------------------------------------------


def _mock_tool_registry() -> MagicMock:
    """Create a minimal ToolRegistry mock for iterative tests."""
    registry = MagicMock()
    registry.list_all.return_value = []
    return registry


def _mock_tool_loop_result(
    *,
    output: dict[str, object] | None = None,
    raw_response: str = '{"result": "ok"}',
    model: str = "test-model",
    termination_reason: str = "completed",
) -> object:
    """Create a ToolLoopResult for testing."""
    from agent33.agents.tool_loop import ToolLoopResult

    return ToolLoopResult(
        output=output or {"result": "ok"},
        raw_response=raw_response,
        tokens_used=42,
        model=model,
        iterations=3,
        tool_calls_made=2,
        tools_used=["shell", "file_read"],
        termination_reason=termination_reason,
    )


class TestIterativeTrajectory:
    """Tests for trajectory persistence in invoke_iterative()."""

    async def test_invoke_iterative_saves_successful_trajectory(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        config_module, runtime_module, expected_output_dir = _configure_runtime_trajectory(
            monkeypatch,
            tmp_path,
            enabled=True,
        )
        monkeypatch.setattr(config_module.settings, "redact_secrets_enabled", True)

        save_mock = AsyncMock()
        monkeypatch.setattr(runtime_module, "save_trajectory", save_mock)

        loop_result = _mock_tool_loop_result()

        with patch("agent33.agents.tool_loop.ToolLoop.run", new_callable=AsyncMock) as run_mock:
            run_mock.return_value = loop_result

            runtime = AgentRuntime(
                definition=_mock_runtime_definition(),
                router=_mock_runtime_router(),
                tool_registry=_mock_tool_registry(),
            )
            result = await runtime.invoke_iterative({"query": "hello"})

        assert result.output == {"result": "ok"}
        assert result.iterations == 3
        save_mock.assert_awaited_once()
        args, _kwargs = save_mock.await_args
        conversation, model, completed, output_dir = args[:4]
        assert model == "test-model"
        assert completed is True
        assert output_dir == expected_output_dir
        # Conversation should have at least system + user messages
        assert conversation[0]["role"] == "system"
        assert conversation[1]["role"] == "user"
        assert '"query": "hello"' in conversation[1]["content"]

    async def test_invoke_iterative_saves_failed_trajectory(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        config_module, runtime_module, expected_output_dir = _configure_runtime_trajectory(
            monkeypatch,
            tmp_path,
            enabled=True,
        )
        monkeypatch.setattr(config_module.settings, "redact_secrets_enabled", True)

        save_mock = AsyncMock()
        monkeypatch.setattr(runtime_module, "save_trajectory", save_mock)

        with patch("agent33.agents.tool_loop.ToolLoop.run", new_callable=AsyncMock) as run_mock:
            run_mock.side_effect = RuntimeError("tool loop exploded")

            runtime = AgentRuntime(
                definition=_mock_runtime_definition(),
                router=_mock_runtime_router(),
                tool_registry=_mock_tool_registry(),
            )

            with pytest.raises(RuntimeError, match="tool loop exploded"):
                await runtime.invoke_iterative({"query": "hello"})

        save_mock.assert_awaited_once()
        args, _kwargs = save_mock.await_args
        conversation, model, completed, output_dir = args[:4]
        assert completed is False
        assert output_dir == expected_output_dir
        # Last message should be the synthetic error turn
        assert conversation[-1]["role"] == "assistant"
        assert "RuntimeError: tool loop exploded" in conversation[-1]["content"]

    async def test_invoke_iterative_trajectory_is_fail_open(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Trajectory save errors must not affect the returned result."""
        config_module, runtime_module, _expected_output_dir = _configure_runtime_trajectory(
            monkeypatch,
            tmp_path,
            enabled=True,
        )
        monkeypatch.setattr(config_module.settings, "redact_secrets_enabled", True)
        monkeypatch.setattr(
            runtime_module,
            "save_trajectory",
            AsyncMock(side_effect=RuntimeError("disk full")),
        )

        loop_result = _mock_tool_loop_result()

        with patch("agent33.agents.tool_loop.ToolLoop.run", new_callable=AsyncMock) as run_mock:
            run_mock.return_value = loop_result

            runtime = AgentRuntime(
                definition=_mock_runtime_definition(),
                router=_mock_runtime_router(),
                tool_registry=_mock_tool_registry(),
            )
            result = await runtime.invoke_iterative({"query": "hello"})

        # Result must still be returned despite trajectory save failure
        assert result.output == {"result": "ok"}
        assert result.iterations == 3

    async def test_invoke_iterative_trajectory_disabled(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When trajectory capture is disabled, save_trajectory must not be called."""
        _config_module, runtime_module, _expected_output_dir = _configure_runtime_trajectory(
            monkeypatch,
            tmp_path,
            enabled=False,
        )

        save_mock = AsyncMock()
        monkeypatch.setattr(runtime_module, "save_trajectory", save_mock)

        loop_result = _mock_tool_loop_result()

        with patch("agent33.agents.tool_loop.ToolLoop.run", new_callable=AsyncMock) as run_mock:
            run_mock.return_value = loop_result

            runtime = AgentRuntime(
                definition=_mock_runtime_definition(),
                router=_mock_runtime_router(),
                tool_registry=_mock_tool_registry(),
            )
            await runtime.invoke_iterative({"query": "hello"})

        save_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# Streaming invoke trajectory tests
# ---------------------------------------------------------------------------


def _make_stream_events(
    *,
    termination_reason: str = "completed",
) -> list[object]:
    """Build a minimal sequence of ToolLoopEvents for stream tests."""
    from agent33.agents.events import ToolLoopEvent

    return [
        ToolLoopEvent(
            event_type="loop_started",
            iteration=0,
            data={"max_iterations": 20, "tools_count": 0},
        ),
        ToolLoopEvent(
            event_type="iteration_started",
            iteration=1,
            data={"message_count": 2},
        ),
        ToolLoopEvent(
            event_type="completed",
            iteration=1,
            data={
                "termination_reason": termination_reason,
                "total_tokens": 42,
                "tokens_available": True,
                "tool_calls_made": 0,
                "tools_used": [],
                "output": {"result": "ok"},
            },
        ),
    ]


class TestStreamingTrajectory:
    """Tests for trajectory persistence in invoke_iterative_stream()."""

    async def test_streaming_saves_successful_trajectory(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        config_module, runtime_module, expected_output_dir = _configure_runtime_trajectory(
            monkeypatch,
            tmp_path,
            enabled=True,
        )
        from agent33.llm.base import ChatMessage

        monkeypatch.setattr(config_module.settings, "redact_secrets_enabled", True)

        save_mock = AsyncMock()
        monkeypatch.setattr(runtime_module, "save_trajectory", save_mock)

        events = _make_stream_events()
        fake_accumulated = [
            ChatMessage(role="system", content="You are a test agent."),
            ChatMessage(role="user", content='{"query": "hello"}'),
            ChatMessage(role="assistant", content='{"result": "ok"}'),
        ]

        import agent33.agents.tool_loop as tl_mod

        original_init = tl_mod.ToolLoop.__init__
        captured_loop: dict[str, object] = {}

        def patched_init(self_loop, *a, **kw):  # type: ignore[no-untyped-def]
            original_init(self_loop, *a, **kw)  # type: ignore[misc]
            captured_loop["instance"] = self_loop

        async def fake_run_stream(
            self_loop,  # noqa: ARG001
            messages: list[ChatMessage],  # noqa: ARG001
            model: str,  # noqa: ARG001
            temperature: float = 0.7,  # noqa: ARG001
            max_tokens: int | None = None,  # noqa: ARG001
        ):  # type: ignore[override]
            for event in events:
                yield event
            # Set accumulated messages after yielding all events
            if "instance" in captured_loop:
                captured_loop["instance"]._last_accumulated_messages = fake_accumulated  # type: ignore[union-attr]

        with (
            patch.object(tl_mod.ToolLoop, "__init__", patched_init),
            patch.object(tl_mod.ToolLoop, "run_stream", fake_run_stream),
        ):
            runtime = AgentRuntime(
                definition=_mock_runtime_definition(),
                router=_mock_runtime_router(),
                tool_registry=_mock_tool_registry(),
            )

            collected_events = []
            async for event in runtime.invoke_iterative_stream({"query": "hello"}):
                collected_events.append(event)

        assert any(e.event_type == "completed" for e in collected_events)
        save_mock.assert_awaited_once()
        args, _kwargs = save_mock.await_args
        conversation, model, completed, output_dir = args[:4]
        assert completed is True
        assert output_dir == expected_output_dir
        # Verify conversation content matches fake_accumulated
        assert conversation[0]["role"] == "system"
        assert conversation[-1]["role"] == "assistant"
        assert conversation[-1]["content"] == '{"result": "ok"}'

    async def test_streaming_trajectory_is_fail_open(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Trajectory save errors must not affect the stream output."""
        config_module, runtime_module, _expected_output_dir = _configure_runtime_trajectory(
            monkeypatch,
            tmp_path,
            enabled=True,
        )
        from agent33.llm.base import ChatMessage

        monkeypatch.setattr(config_module.settings, "redact_secrets_enabled", True)
        monkeypatch.setattr(
            runtime_module,
            "save_trajectory",
            AsyncMock(side_effect=RuntimeError("disk full")),
        )

        events = _make_stream_events()
        fake_accumulated = [
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="user", content="usr"),
        ]

        import agent33.agents.tool_loop as tl_mod

        original_init = tl_mod.ToolLoop.__init__
        captured_loop: dict[str, object] = {}

        def patched_init(self_loop, *a, **kw):  # type: ignore[no-untyped-def]
            original_init(self_loop, *a, **kw)  # type: ignore[misc]
            captured_loop["instance"] = self_loop

        async def fake_run_stream(
            self_loop,  # noqa: ARG001
            messages: list[ChatMessage],  # noqa: ARG001
            model: str,  # noqa: ARG001
            temperature: float = 0.7,  # noqa: ARG001
            max_tokens: int | None = None,  # noqa: ARG001
        ):  # type: ignore[override]
            for event in events:
                yield event
            if "instance" in captured_loop:
                captured_loop["instance"]._last_accumulated_messages = fake_accumulated  # type: ignore[union-attr]

        with (
            patch.object(tl_mod.ToolLoop, "__init__", patched_init),
            patch.object(tl_mod.ToolLoop, "run_stream", fake_run_stream),
        ):
            runtime = AgentRuntime(
                definition=_mock_runtime_definition(),
                router=_mock_runtime_router(),
                tool_registry=_mock_tool_registry(),
            )

            collected_events = []
            async for event in runtime.invoke_iterative_stream({"query": "hello"}):
                collected_events.append(event)

        # Stream must complete even though save_trajectory raised
        assert any(e.event_type == "completed" for e in collected_events)

    async def test_streaming_trajectory_disabled(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When trajectory capture is disabled, save_trajectory must not be called."""
        _config_module, runtime_module, _expected_output_dir = _configure_runtime_trajectory(
            monkeypatch,
            tmp_path,
            enabled=False,
        )
        from agent33.llm.base import ChatMessage

        save_mock = AsyncMock()
        monkeypatch.setattr(runtime_module, "save_trajectory", save_mock)

        events = _make_stream_events()

        import agent33.agents.tool_loop as tl_mod

        original_init = tl_mod.ToolLoop.__init__
        captured_loop: dict[str, object] = {}

        def patched_init(self_loop, *a, **kw):  # type: ignore[no-untyped-def]
            original_init(self_loop, *a, **kw)  # type: ignore[misc]
            captured_loop["instance"] = self_loop

        async def fake_run_stream(
            self_loop,  # noqa: ARG001
            messages: list[ChatMessage],  # noqa: ARG001
            model: str,  # noqa: ARG001
            temperature: float = 0.7,  # noqa: ARG001
            max_tokens: int | None = None,  # noqa: ARG001
        ):  # type: ignore[override]
            for event in events:
                yield event
            if "instance" in captured_loop:
                captured_loop["instance"]._last_accumulated_messages = [  # type: ignore[union-attr]
                    ChatMessage(role="system", content="sys"),
                ]

        with (
            patch.object(tl_mod.ToolLoop, "__init__", patched_init),
            patch.object(tl_mod.ToolLoop, "run_stream", fake_run_stream),
        ):
            runtime = AgentRuntime(
                definition=_mock_runtime_definition(),
                router=_mock_runtime_router(),
                tool_registry=_mock_tool_registry(),
            )

            async for _ in runtime.invoke_iterative_stream({"query": "hello"}):
                pass

        save_mock.assert_not_awaited()
