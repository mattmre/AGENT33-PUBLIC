"""Tests for run-scoped workflow WebSocket status streaming."""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agent33.main import app
from agent33.security.auth import create_access_token
from agent33.workflows.events import WorkflowEvent, WorkflowEventType
from agent33.workflows.executor import WorkflowExecutor
from agent33.workflows.ws_manager import WorkflowWSManager


@pytest.fixture(autouse=True)
def clear_workflow_state() -> None:
    """Clear workflow registry, history, scheduler, and WS state between tests."""
    from agent33.api.routes import workflows

    def _reset() -> None:
        workflows.reset_workflow_state()
        if workflows._scheduler is not None:
            with contextlib.suppress(RuntimeError):
                workflows._scheduler.stop()
            workflows._scheduler = None
        workflows.set_ws_manager(None)
        app.state.ws_manager = None

    _reset()
    yield
    _reset()


@pytest.fixture
def executor_client() -> TestClient:
    token = create_access_token(
        "workflow-executor",
        scopes=["workflows:read", "workflows:write", "workflows:execute"],
    )
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def workflow_name(executor_client: TestClient, route_approval_headers) -> str:
    name = f"workflow-{uuid.uuid4().hex[:8]}"
    payload = {
        "name": name,
        "version": "1.0.0",
        "description": "Workflow WS test",
        "steps": [
            {
                "id": "step-a",
                "action": "transform",
                "transform": "inputs",
            }
        ],
        "execution": {"mode": "sequential"},
    }
    response = executor_client.post(
        "/v1/workflows/",
        json=payload,
        headers=route_approval_headers(
            executor_client,
            route_name="workflows.create",
            operation="create",
            arguments=payload,
            details="Pytest workflow WS setup",
        ),
    )
    assert response.status_code == 201
    return name


def _mock_ws(*, alive: bool = True) -> MagicMock:
    ws = MagicMock()
    if alive:
        ws.send_text = AsyncMock()
    else:
        ws.send_text = AsyncMock(side_effect=RuntimeError("connection closed"))
    return ws


def _seed_run(
    manager: WorkflowWSManager,
    run_id: str,
    workflow_name: str,
    events: list[WorkflowEvent] | None = None,
) -> None:
    asyncio.run(manager.register_run(run_id, workflow_name))
    for event in events or []:
        asyncio.run(manager.publish_event(event))


def _install_manager(manager: WorkflowWSManager) -> None:
    from agent33.api.routes import workflows

    app.state.ws_manager = manager
    workflows.set_ws_manager(manager)


class TestWorkflowEventType:
    """Tests for the WorkflowEventType enum."""

    def test_all_event_types_defined(self) -> None:
        expected = {
            "sync",
            "heartbeat",
            "workflow_started",
            "step_started",
            "step_completed",
            "step_failed",
            "step_skipped",
            "step_retrying",
            "workflow_completed",
            "workflow_failed",
        }
        actual = {event_type.value for event_type in WorkflowEventType}
        assert actual == expected


class TestWorkflowEvent:
    """Tests for the WorkflowEvent dataclass."""

    def test_create_minimal_event(self) -> None:
        event = WorkflowEvent(
            event_type=WorkflowEventType.WORKFLOW_STARTED,
            run_id="run-1",
            workflow_name="wf-1",
        )
        assert event.run_id == "run-1"
        assert event.workflow_name == "wf-1"
        assert event.step_id is None
        assert event.data == {}
        assert isinstance(event.timestamp, float)

    def test_frozen(self) -> None:
        event = WorkflowEvent(
            event_type=WorkflowEventType.WORKFLOW_STARTED,
            run_id="run-1",
            workflow_name="wf-1",
        )
        with pytest.raises(FrozenInstanceError):
            event.run_id = "run-2"  # type: ignore[misc]

    def test_to_dict_uses_run_scoped_contract(self) -> None:
        event = WorkflowEvent(
            event_type=WorkflowEventType.STEP_COMPLETED,
            run_id="run-2",
            workflow_name="wf-2",
            timestamp=1700000000.0,
            step_id="step-a",
            data={"duration_ms": 5.5},
        )
        assert event.to_dict() == {
            "type": "step_completed",
            "run_id": "run-2",
            "workflow_name": "wf-2",
            "timestamp": 1700000000.0,
            "schema_version": 1,
            "step_id": "step-a",
            "data": {"duration_ms": 5.5},
        }

    def test_to_json_round_trip(self) -> None:
        event = WorkflowEvent(
            event_type=WorkflowEventType.HEARTBEAT,
            run_id="run-3",
            workflow_name="wf-3",
            timestamp=1700000001.0,
            data={"status": "running"},
        )
        assert json.loads(event.to_json()) == event.to_dict()


class TestWorkflowWSManager:
    """Tests for the run-scoped WebSocket manager."""

    @pytest.mark.asyncio
    async def test_broadcast_is_run_scoped_even_for_same_workflow(self) -> None:
        manager = WorkflowWSManager()
        ws_one = _mock_ws()
        ws_two = _mock_ws()

        await manager.register_run("run-1", "same-workflow")
        await manager.register_run("run-2", "same-workflow")
        await manager.connect(ws_one, "run-1")
        await manager.connect(ws_two, "run-2")

        await manager.publish_event(
            WorkflowEvent(
                event_type=WorkflowEventType.STEP_STARTED,
                run_id="run-1",
                workflow_name="same-workflow",
                step_id="step-a",
            )
        )

        for _ in range(20):
            if ws_one.send_text.await_count == 1:
                break
            await asyncio.sleep(0.01)

        ws_one.send_text.assert_awaited_once()
        ws_two.send_text.assert_not_awaited()
        await manager.disconnect(ws_one)
        await manager.disconnect(ws_two)

    @pytest.mark.asyncio
    async def test_sse_backpressure_drops_oldest_event_and_keeps_latest(self) -> None:
        manager = WorkflowWSManager(sse_queue_maxsize=1)
        await manager.register_run("run-sse-backpressure", "wf-backpressure")
        queue = await manager.subscribe_sse("run-sse-backpressure")

        assert queue is not None

        await manager.publish_event(
            WorkflowEvent(
                event_type=WorkflowEventType.STEP_STARTED,
                run_id="run-sse-backpressure",
                workflow_name="wf-backpressure",
                step_id="step-a",
            )
        )
        await manager.publish_event(
            WorkflowEvent(
                event_type=WorkflowEventType.STEP_COMPLETED,
                run_id="run-sse-backpressure",
                workflow_name="wf-backpressure",
                step_id="step-a",
            )
        )

        retained_event = queue.get_nowait()
        assert retained_event.event_type == WorkflowEventType.STEP_COMPLETED
        assert queue.empty()

    @pytest.mark.asyncio
    async def test_sse_replay_returns_buffered_events_after_cursor(self) -> None:
        manager = WorkflowWSManager(sse_replay_buffer_size=4)
        await manager.register_run("run-sse-replay", "wf-replay")

        await manager.publish_event(
            WorkflowEvent(
                event_type=WorkflowEventType.STEP_STARTED,
                run_id="run-sse-replay",
                workflow_name="wf-replay",
                step_id="step-a",
            )
        )
        await manager.publish_event(
            WorkflowEvent(
                event_type=WorkflowEventType.STEP_COMPLETED,
                run_id="run-sse-replay",
                workflow_name="wf-replay",
                step_id="step-a",
            )
        )

        replay_events = await manager.replay_sse_events("run-sse-replay", after_event_id="1")

        assert len(replay_events) == 1
        assert replay_events[0].event_type == WorkflowEventType.STEP_COMPLETED
        assert replay_events[0].event_id == "2"

    @pytest.mark.asyncio
    async def test_sse_replay_buffer_is_bounded(self) -> None:
        manager = WorkflowWSManager(sse_replay_buffer_size=2)
        await manager.register_run("run-sse-bounded", "wf-bounded")

        for step_id in ("step-a", "step-b", "step-c"):
            await manager.publish_event(
                WorkflowEvent(
                    event_type=WorkflowEventType.STEP_COMPLETED,
                    run_id="run-sse-bounded",
                    workflow_name="wf-bounded",
                    step_id=step_id,
                )
            )

        replay_events = await manager.replay_sse_events("run-sse-bounded", after_event_id="0")

        assert [event.event_id for event in replay_events] == ["2", "3"]
        assert [event.step_id for event in replay_events] == ["step-b", "step-c"]

    @pytest.mark.asyncio
    async def test_run_access_requires_matching_owner_and_tenant(self) -> None:
        manager = WorkflowWSManager()
        await manager.register_run(
            "run-owned",
            "wf-owned",
            owner_subject="owner-a",
            tenant_id="tenant-a",
        )

        assert await manager.can_access_run(
            "run-owned",
            subject="owner-a",
            tenant_id="tenant-a",
        )
        assert not await manager.can_access_run(
            "run-owned",
            subject="owner-b",
            tenant_id="tenant-a",
        )
        assert not await manager.can_access_run(
            "run-owned",
            subject="owner-a",
            tenant_id="tenant-b",
        )
        assert await manager.can_access_run(
            "run-owned",
            subject="admin-user",
            tenant_id="tenant-b",
            is_admin=True,
        )

    @pytest.mark.asyncio
    async def test_build_sync_event_reflects_latest_snapshot(self) -> None:
        manager = WorkflowWSManager()
        run_id = "run-sync"

        await manager.register_run(run_id, "snapshot-workflow")
        await manager.publish_event(
            WorkflowEvent(
                event_type=WorkflowEventType.WORKFLOW_STARTED,
                run_id=run_id,
                workflow_name="snapshot-workflow",
            )
        )
        await manager.publish_event(
            WorkflowEvent(
                event_type=WorkflowEventType.STEP_COMPLETED,
                run_id=run_id,
                workflow_name="snapshot-workflow",
                step_id="step-a",
            )
        )

        sync_event = await manager.build_sync_event(run_id)
        assert sync_event is not None
        assert sync_event.event_type == WorkflowEventType.SYNC
        assert sync_event.run_id == run_id
        assert sync_event.workflow_name == "snapshot-workflow"
        assert sync_event.data["status"] == "running"
        assert sync_event.data["step_statuses"] == {"step-a": "success"}
        assert sync_event.data["last_event_type"] == "step_completed"

    @pytest.mark.asyncio
    async def test_publish_event_preserves_order_without_waiting_on_slow_subscribers(self) -> None:
        manager = WorkflowWSManager()
        sent_payloads: list[str] = []

        async def _slow_send(payload: str) -> None:
            await asyncio.sleep(0.05)
            sent_payloads.append(payload)

        slow_ws = MagicMock()
        slow_ws.send_text = AsyncMock(side_effect=_slow_send)

        await manager.register_run("run-ordered", "ordered-workflow")
        await manager.connect(slow_ws, "run-ordered")

        first = WorkflowEvent(
            event_type=WorkflowEventType.STEP_STARTED,
            run_id="run-ordered",
            workflow_name="ordered-workflow",
            step_id="step-a",
        )
        second = WorkflowEvent(
            event_type=WorkflowEventType.STEP_COMPLETED,
            run_id="run-ordered",
            workflow_name="ordered-workflow",
            step_id="step-a",
        )

        started = asyncio.get_running_loop().time()
        await manager.publish_event(first)
        await manager.publish_event(second)
        elapsed = asyncio.get_running_loop().time() - started

        assert elapsed < 0.05

        for _ in range(20):
            if len(sent_payloads) == 2:
                break
            await asyncio.sleep(0.01)

        assert [json.loads(payload)["type"] for payload in sent_payloads] == [
            "step_started",
            "step_completed",
        ]
        await manager.disconnect(slow_ws)

    @pytest.mark.asyncio
    async def test_run_access_is_tenant_scoped(self) -> None:
        manager = WorkflowWSManager()
        await manager.register_run("run-tenant", "tenant-workflow", tenant_id="tenant-a")

        assert (
            await manager.can_access_run(
                "run-tenant",
                tenant_id="tenant-a",
                scopes=[],
            )
            is True
        )
        assert (
            await manager.can_access_run(
                "run-tenant",
                tenant_id="tenant-b",
                scopes=[],
            )
            is False
        )
        assert await manager.can_access_run("run-tenant", tenant_id="", scopes=["admin"]) is True


class TestExecutorEventSink:
    """Tests that WorkflowExecutor emits run-scoped events."""

    @pytest.mark.asyncio
    async def test_executor_emits_run_id_and_workflow_name(self) -> None:
        from agent33.workflows.definition import WorkflowDefinition

        definition = WorkflowDefinition.model_validate(
            {
                "name": "executor-wf",
                "version": "1.0.0",
                "steps": [
                    {
                        "id": "step-a",
                        "action": "transform",
                        "inputs": {"value": "x"},
                    },
                ],
            }
        )

        captured: list[WorkflowEvent] = []
        executor = WorkflowExecutor(
            definition,
            run_id="run-executor",
            event_sink=captured.append,
        )

        await executor.execute({"input": "hello"})

        assert captured
        assert all(event.run_id == "run-executor" for event in captured)
        assert all(event.workflow_name == "executor-wf" for event in captured)
        event_types = {event.event_type for event in captured}
        assert WorkflowEventType.WORKFLOW_STARTED in event_types
        assert WorkflowEventType.WORKFLOW_COMPLETED in event_types

    @pytest.mark.asyncio
    async def test_terminal_failure_event_preserves_step_error_in_snapshot(self) -> None:
        from agent33.workflows.actions import transform
        from agent33.workflows.definition import WorkflowDefinition

        definition = WorkflowDefinition.model_validate(
            {
                "name": "executor-failure-wf",
                "version": "1.0.0",
                "steps": [
                    {
                        "id": "step-a",
                        "action": "transform",
                        "inputs": {"value": "x"},
                    },
                ],
            }
        )

        async def _fail_transform(*args: object, **kwargs: object) -> dict[str, object]:  # noqa: ARG001
            raise RuntimeError("transform exploded")

        manager = WorkflowWSManager()
        await manager.register_run("run-failure", definition.name)
        executor = WorkflowExecutor(
            definition,
            run_id="run-failure",
            event_sink=manager.publish_event,
        )

        original_execute = transform.execute
        transform.execute = _fail_transform
        try:
            result = await executor.execute({"input": "hello"})
        finally:
            transform.execute = original_execute

        assert result.status.value == "failed"
        sync_event = await manager.build_sync_event("run-failure")
        assert sync_event is not None
        assert sync_event.data["status"] == "failed"
        assert sync_event.data["error"] == "transform exploded"
        assert sync_event.data["last_event_type"] == "workflow_failed"


class TestWorkflowExecuteRoute:
    """Tests for run IDs on workflow execution responses and history."""

    def test_execute_route_returns_run_id(
        self,
        executor_client: TestClient,
        workflow_name: str,
    ) -> None:
        response = executor_client.post(
            f"/v1/workflows/{workflow_name}/execute",
            json={"inputs": {"value": 42}},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["run_id"], str)
        assert data["workflow_name"] == workflow_name

        history_response = executor_client.get(f"/v1/workflows/{workflow_name}/history")
        assert history_response.status_code == 200
        history = history_response.json()
        assert history[0]["run_id"] == data["run_id"]
        assert history[0]["workflow_name"] == workflow_name

    def test_execute_route_uses_caller_supplied_run_id(
        self,
        executor_client: TestClient,
        workflow_name: str,
    ) -> None:
        run_id = f"live-{uuid.uuid4().hex}"
        response = executor_client.post(
            f"/v1/workflows/{workflow_name}/execute",
            json={"inputs": {"value": 42}, "run_id": run_id},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == run_id
        history_response = executor_client.get(f"/v1/workflows/{workflow_name}/history")
        assert history_response.status_code == 200
        assert history_response.json()[0]["run_id"] == run_id

    @pytest.mark.asyncio
    async def test_caller_supplied_run_id_can_attach_to_live_subscription_before_completion(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from agent33.api.routes import workflows
        from agent33.workflows.actions import transform
        from agent33.workflows.definition import WorkflowDefinition

        manager = WorkflowWSManager(heartbeat_interval_seconds=60)
        _install_manager(manager)

        definition = WorkflowDefinition.model_validate(
            {
                "name": "live-ws-workflow",
                "version": "1.0.0",
                "steps": [
                    {
                        "id": "step-a",
                        "action": "transform",
                        "transform": "inputs",
                    }
                ],
                "execution": {"mode": "sequential"},
            }
        )
        run_id = f"live-{uuid.uuid4().hex}"
        execution_started = asyncio.Event()
        allow_finish = asyncio.Event()

        async def _blocking_transform(*args: object, **kwargs: object) -> dict[str, object]:  # noqa: ARG001
            execution_started.set()
            await allow_finish.wait()
            return {"value": "done"}

        monkeypatch.setattr(transform, "execute", _blocking_transform)
        request = workflows.WorkflowExecuteRequest(inputs={"value": 42}, run_id=run_id)
        execution = asyncio.create_task(
            workflows._execute_single(
                definition,
                definition.name,
                request,
                ws_manager=manager,
                run_id=run_id,
            )
        )

        await asyncio.wait_for(execution_started.wait(), timeout=2)
        assert not execution.done(), (
            "execution completed before a client could attach to the websocket"
        )
        assert await manager.has_run(run_id)

        ws = _mock_ws()
        connected = await manager.connect(ws, run_id)
        assert connected is True
        sent = await manager.send_sync(ws, run_id)
        assert sent is True

        sync_payload = json.loads(ws.send_text.await_args_list[0].args[0])
        assert sync_payload["type"] == "sync"
        assert sync_payload["run_id"] == run_id
        assert sync_payload["workflow_name"] == definition.name
        assert sync_payload["data"]["status"] == "running"
        assert sync_payload["data"]["step_statuses"] == {"step-a": "running"}

        allow_finish.set()
        response = await execution

        for _ in range(20):
            if ws.send_text.await_count >= 3:
                break
            await asyncio.sleep(0.01)

        assert response["run_id"] == run_id
        live_payloads = [json.loads(call.args[0]) for call in ws.send_text.await_args_list[1:]]
        assert [payload["type"] for payload in live_payloads] == [
            "step_completed",
            "workflow_completed",
        ]
        assert all(payload["run_id"] == run_id for payload in live_payloads)
        assert live_payloads[-1]["data"]["status"] == "success"
        await manager.disconnect(ws)

    def test_repeated_execution_preserves_distinct_run_ids(
        self,
        executor_client: TestClient,
        workflow_name: str,
    ) -> None:
        response = executor_client.post(
            f"/v1/workflows/{workflow_name}/execute",
            json={"inputs": {"value": 42}, "repeat_count": 2, "autonomous": True},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["run_ids"]) == 2
        assert len(set(data["run_ids"])) == 2
        assert [summary["run_id"] for summary in data["results_summary"]] == data["run_ids"]

        history_response = executor_client.get(f"/v1/workflows/{workflow_name}/history")
        history = history_response.json()
        history_run_ids = {entry["run_id"] for entry in history}
        assert set(data["run_ids"]).issubset(history_run_ids)

    def test_history_is_filtered_by_tenant(self, workflow_name: str) -> None:
        tenant_a_token = create_access_token(
            "tenant-a-user",
            scopes=["workflows:read", "workflows:write", "workflows:execute"],
            tenant_id="tenant-a",
        )
        tenant_b_token = create_access_token(
            "tenant-b-user",
            scopes=["workflows:read", "workflows:write", "workflows:execute"],
            tenant_id="tenant-b",
        )
        tenant_a_client = TestClient(
            app,
            headers={"Authorization": f"Bearer {tenant_a_token}"},
        )
        tenant_b_client = TestClient(
            app,
            headers={"Authorization": f"Bearer {tenant_b_token}"},
        )

        exec_response = tenant_a_client.post(
            f"/v1/workflows/{workflow_name}/execute",
            json={"inputs": {"value": 42}},
        )
        assert exec_response.status_code == 200

        tenant_a_history = tenant_a_client.get(f"/v1/workflows/{workflow_name}/history")
        assert tenant_a_history.status_code == 200
        assert len(tenant_a_history.json()) == 1

        tenant_b_history = tenant_b_client.get(f"/v1/workflows/{workflow_name}/history")
        assert tenant_b_history.status_code == 200
        assert tenant_b_history.json() == []


class TestWorkflowWSEndpoint:
    """Tests for the run-scoped WebSocket endpoint."""

    def test_route_uses_run_scoped_path(self) -> None:
        paths = {route.path for route in app.routes if hasattr(route, "path")}
        assert "/v1/workflows/{run_id}/ws" in paths
        assert "/v1/workflows/ws" not in paths

    def test_ws_endpoint_rejects_missing_token(self) -> None:
        manager = WorkflowWSManager()
        _seed_run(manager, "run-missing-token", "wf-auth")
        _install_manager(manager)

        client = TestClient(app)
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect("/v1/workflows/run-missing-token/ws"),
        ):
            pass

    def test_ws_endpoint_rejects_missing_workflow_read_scope(self) -> None:
        manager = WorkflowWSManager()
        _seed_run(manager, "run-no-scope", "wf-auth")
        _install_manager(manager)

        token = create_access_token("ws-user", scopes=["workflows:execute"])
        client = TestClient(app)
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(f"/v1/workflows/run-no-scope/ws?token={token}"),
        ):
            pass

    def test_ws_endpoint_rejects_invalid_token(self) -> None:
        manager = WorkflowWSManager()
        _seed_run(manager, "run-invalid-token", "wf-auth")
        _install_manager(manager)

        client = TestClient(app)
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect("/v1/workflows/run-invalid-token/ws?token=bad-token"),
        ):
            pass

    def test_ws_endpoint_accepts_run_path_and_sends_sync(self) -> None:
        manager = WorkflowWSManager(heartbeat_interval_seconds=60)
        run_id = "run-path"
        _seed_run(manager, run_id, "wf-path")
        _install_manager(manager)

        token = create_access_token("ws-user", scopes=["workflows:read"])
        client = TestClient(app)
        with client.websocket_connect(f"/v1/workflows/{run_id}/ws?token={token}") as websocket:
            message = websocket.receive_json()
            assert message["type"] == "sync"
            assert message["run_id"] == run_id
            assert message["workflow_name"] == "wf-path"

    def test_ws_endpoint_accepts_header_bearer_auth(self) -> None:
        manager = WorkflowWSManager(heartbeat_interval_seconds=60)
        run_id = "run-header-auth"
        _seed_run(manager, run_id, "wf-path")
        _install_manager(manager)

        token = create_access_token("ws-user", scopes=["workflows:read"])
        client = TestClient(app)
        with client.websocket_connect(
            f"/v1/workflows/{run_id}/ws",
            headers={"Authorization": f"Bearer {token}"},
        ) as websocket:
            assert websocket.receive_json()["type"] == "sync"

    def test_ws_endpoint_rejects_cross_tenant_access(self) -> None:
        manager = WorkflowWSManager()
        asyncio.run(manager.register_run("run-tenant", "wf-auth", tenant_id="tenant-a"))
        _install_manager(manager)

        token = create_access_token(
            "ws-user",
            scopes=["workflows:read"],
            tenant_id="tenant-b",
        )
        client = TestClient(app)
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(f"/v1/workflows/run-tenant/ws?token={token}"),
        ):
            pass

    def test_ws_initial_sync_includes_snapshot(self) -> None:
        manager = WorkflowWSManager(heartbeat_interval_seconds=60)
        run_id = "run-sync"
        _seed_run(
            manager,
            run_id,
            "wf-sync",
            events=[
                WorkflowEvent(
                    event_type=WorkflowEventType.WORKFLOW_STARTED,
                    run_id=run_id,
                    workflow_name="wf-sync",
                ),
                WorkflowEvent(
                    event_type=WorkflowEventType.STEP_COMPLETED,
                    run_id=run_id,
                    workflow_name="wf-sync",
                    step_id="step-a",
                ),
            ],
        )
        _install_manager(manager)

        token = create_access_token("ws-user", scopes=["workflows:read"])
        client = TestClient(app)
        with client.websocket_connect(f"/v1/workflows/{run_id}/ws?token={token}") as websocket:
            message = websocket.receive_json()
            assert message["type"] == "sync"
            assert message["data"]["status"] == "running"
            assert message["data"]["step_statuses"] == {"step-a": "success"}
            assert message["data"]["last_event_type"] == "step_completed"

    def test_ws_heartbeat_keepalive_is_emitted(self) -> None:
        manager = WorkflowWSManager(heartbeat_interval_seconds=0.01)
        run_id = "run-heartbeat"
        _seed_run(manager, run_id, "wf-heartbeat")
        _install_manager(manager)

        token = create_access_token("ws-user", scopes=["workflows:read"])
        client = TestClient(app)
        with client.websocket_connect(f"/v1/workflows/{run_id}/ws?token={token}") as websocket:
            sync_message = websocket.receive_json()
            assert sync_message["type"] == "sync"

            heartbeat = websocket.receive_json()
            assert heartbeat["type"] == "heartbeat"
            assert heartbeat["run_id"] == run_id
            assert heartbeat["workflow_name"] == "wf-heartbeat"
            assert heartbeat["data"]["status"] == "pending"
            assert heartbeat["data"]["terminal"] is False
