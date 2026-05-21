"""Tests for POST-4.2: SSE event schema versioning with strict rejection.

Covers:
- Test 1: version match — stream proceeds normally
- Test 2: version mismatch — client raises SchemaVersionMismatchError
- Test 3: server emits schema_version on ALL event types
- Test 4: schema_version absent — treated as version 0 (mismatch)
"""

from __future__ import annotations

import json

import pytest

from agent33.config import settings
from agent33.workflows.events import (
    CURRENT_SCHEMA_VERSION,
    SCHEMA_VERSION_V1,
    SCHEMA_VERSION_V2,
    SchemaVersionMismatchError,
    WorkflowEvent,
    WorkflowEventType,
    check_schema_version,
    resolve_active_schema_version,
)
from agent33.workflows.ws_manager import WorkflowWSManager


class TestVersionMatchStreamProceedsNormally:
    """Test 1: When a client receives a v1 event it proceeds without error."""

    def test_to_dict_includes_schema_version_1(self) -> None:
        event = WorkflowEvent(
            event_type=WorkflowEventType.STEP_STARTED,
            run_id="run-v1",
            workflow_name="wf-v1",
            step_id="step-a",
        )
        result = event.to_dict()

        assert result["schema_version"] == 1

    def test_version_check_does_not_raise_on_matching_version(self) -> None:
        event = WorkflowEvent(
            event_type=WorkflowEventType.STEP_COMPLETED,
            run_id="run-v1",
            workflow_name="wf-v1",
            step_id="step-a",
        )
        event_dict = event.to_dict()

        # Must not raise — matching version means the stream should proceed.
        check_schema_version(event_dict, expected_version=1)

    def test_other_fields_are_still_correct_after_adding_version(self) -> None:
        event = WorkflowEvent(
            event_type=WorkflowEventType.WORKFLOW_STARTED,
            run_id="run-fields",
            workflow_name="wf-fields",
            timestamp=1700000000.0,
        )
        result = event.to_dict()

        assert result["type"] == "workflow_started"
        assert result["run_id"] == "run-fields"
        assert result["workflow_name"] == "wf-fields"
        assert result["timestamp"] == 1700000000.0
        assert result["schema_version"] == CURRENT_SCHEMA_VERSION

    def test_default_schema_version_equals_current_schema_version(self) -> None:
        event = WorkflowEvent(
            event_type=WorkflowEventType.HEARTBEAT,
            run_id="run-default",
            workflow_name="wf-default",
        )
        assert event.schema_version == CURRENT_SCHEMA_VERSION


class TestActiveSchemaVersionResolution:
    """Backend rollout foundation keeps v1 default and allows explicit v2 opt-in."""

    def test_default_resolver_keeps_v1_when_flag_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "sse_schema_v2_enabled", False)
        monkeypatch.setattr(
            "agent33.workflows.events.sse_schema_v2_kill_switch_active",
            lambda: False,
        )

        assert resolve_active_schema_version() == SCHEMA_VERSION_V1
        event = WorkflowEvent(
            event_type=WorkflowEventType.WORKFLOW_STARTED,
            run_id="run-default-v1",
            workflow_name="wf-default-v1",
        )
        assert event.schema_version == SCHEMA_VERSION_V1

    def test_resolver_emits_v2_when_flag_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "sse_schema_v2_enabled", True)
        monkeypatch.setattr(
            "agent33.workflows.events.sse_schema_v2_kill_switch_active",
            lambda: False,
        )

        assert resolve_active_schema_version() == SCHEMA_VERSION_V2
        event = WorkflowEvent(
            event_type=WorkflowEventType.WORKFLOW_STARTED,
            run_id="run-v2",
            workflow_name="wf-v2",
        )
        assert event.schema_version == SCHEMA_VERSION_V2

    def test_kill_switch_forces_v1_even_when_flag_enabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "sse_schema_v2_enabled", True)
        monkeypatch.setattr(
            "agent33.workflows.events.sse_schema_v2_kill_switch_active",
            lambda: True,
        )

        assert resolve_active_schema_version() == SCHEMA_VERSION_V1
        event = WorkflowEvent(
            event_type=WorkflowEventType.WORKFLOW_STARTED,
            run_id="run-kill-switch",
            workflow_name="wf-kill-switch",
        )
        assert event.schema_version == SCHEMA_VERSION_V1

    @pytest.mark.asyncio
    async def test_registered_run_keeps_single_schema_version_across_flag_changes(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "sse_schema_v2_enabled", True)
        monkeypatch.setattr(
            "agent33.workflows.events.sse_schema_v2_kill_switch_active",
            lambda: False,
        )
        manager = WorkflowWSManager()
        await manager.register_run("run-sticky-version", "wf-sticky-version")

        sync_event = await manager.build_sync_event("run-sticky-version")
        assert sync_event is not None
        assert sync_event.schema_version == SCHEMA_VERSION_V2

        monkeypatch.setattr(settings, "sse_schema_v2_enabled", False)
        event = WorkflowEvent(
            event_type=WorkflowEventType.STEP_STARTED,
            run_id="run-sticky-version",
            workflow_name="wf-sticky-version",
            step_id="step-a",
        )
        assert event.schema_version == SCHEMA_VERSION_V1

        await manager.publish_event(event)
        replay_events = await manager.replay_sse_events("run-sticky-version", after_event_id="0")
        heartbeat_event = await manager.build_heartbeat_event("run-sticky-version")

        assert [replay_event.schema_version for replay_event in replay_events] == [
            SCHEMA_VERSION_V2
        ]
        assert heartbeat_event is not None
        assert heartbeat_event.schema_version == SCHEMA_VERSION_V2


class TestVersionMismatchRaisesError:
    """Test 2: When a client receives a v2 event it raises SchemaVersionMismatchError."""

    def test_mismatch_raises_schema_version_mismatch_error(self) -> None:
        future_event_dict = {
            "type": "step_started",
            "run_id": "run-v2",
            "workflow_name": "wf-v2",
            "timestamp": 1700000000.0,
            "schema_version": 2,
        }

        with pytest.raises(SchemaVersionMismatchError) as exc_info:
            check_schema_version(future_event_dict, expected_version=1)

        assert exc_info.value.received == 2
        assert exc_info.value.expected == 1

    def test_error_message_describes_the_mismatch(self) -> None:
        future_event_dict = {"schema_version": 2}

        with pytest.raises(SchemaVersionMismatchError) as exc_info:
            check_schema_version(future_event_dict, expected_version=1)

        assert "expected 1" in str(exc_info.value)
        assert "got 2" in str(exc_info.value)

    def test_no_events_consumed_after_mismatch(self) -> None:
        """Simulates strict rejection: once mismatch detected, processing halts."""
        stream = [
            {"type": "step_started", "schema_version": 2},
            {"type": "step_completed", "schema_version": 2},
        ]
        processed: list[dict[str, object]] = []

        with pytest.raises(SchemaVersionMismatchError):
            for event_dict in stream:
                check_schema_version(event_dict, expected_version=1)
                processed.append(event_dict)

        # Strict rejection: the loop must have terminated on the very first event.
        assert len(processed) == 0


class TestAllEventTypesEmitSchemaVersion:
    """Test 3: Every WorkflowEventType member includes schema_version in its serialized form."""

    @pytest.mark.parametrize("event_type", list(WorkflowEventType))
    def test_to_json_includes_schema_version_for_event_type(
        self, event_type: WorkflowEventType
    ) -> None:
        event = WorkflowEvent(
            event_type=event_type,
            run_id="run-all-types",
            workflow_name="wf-all-types",
        )
        parsed = json.loads(event.to_json())

        assert "schema_version" in parsed, (
            f"Event type {event_type!r} is missing 'schema_version' in to_json() output"
        )
        assert parsed["schema_version"] == CURRENT_SCHEMA_VERSION, (
            f"Event type {event_type!r}: expected schema_version={CURRENT_SCHEMA_VERSION}, "
            f"got {parsed['schema_version']}"
        )

    @pytest.mark.parametrize("event_type", list(WorkflowEventType))
    def test_to_dict_includes_schema_version_for_event_type(
        self, event_type: WorkflowEventType
    ) -> None:
        event = WorkflowEvent(
            event_type=event_type,
            run_id="run-all-types",
            workflow_name="wf-all-types",
        )
        result = event.to_dict()

        assert "schema_version" in result, (
            f"Event type {event_type!r} is missing 'schema_version' in to_dict() output"
        )
        assert result["schema_version"] == CURRENT_SCHEMA_VERSION


class TestAbsentSchemaVersionTreatedAsVersionZero:
    """Test 4: An event dict missing schema_version is treated as version 0 (always a mismatch)."""

    def test_missing_schema_version_raises_schema_version_mismatch_error(self) -> None:
        legacy_event_dict = {
            "type": "step_started",
            "run_id": "run-legacy",
            "workflow_name": "wf-legacy",
            "timestamp": 1700000000.0,
            # No "schema_version" key — pre-versioning payload.
        }

        with pytest.raises(SchemaVersionMismatchError) as exc_info:
            check_schema_version(legacy_event_dict, expected_version=1)

        assert exc_info.value.received == 0
        assert exc_info.value.expected == 1

    def test_missing_schema_version_error_attributes(self) -> None:
        with pytest.raises(SchemaVersionMismatchError) as exc_info:
            check_schema_version({}, expected_version=1)

        error = exc_info.value
        # Absent key → treated as 0.
        assert error.received == 0
        assert error.expected == 1
        assert "expected 1" in str(error)
        assert "got 0" in str(error)

    def test_explicit_version_zero_also_raises(self) -> None:
        """An explicit schema_version=0 is not a sentinel for 'unknown'; it still mismatches."""
        event_dict = {"schema_version": 0}

        with pytest.raises(SchemaVersionMismatchError) as exc_info:
            check_schema_version(event_dict, expected_version=1)

        assert exc_info.value.received == 0
