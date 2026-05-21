"""Tests for the 10 partial competitive features (Phase 3)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

# ---------------------------------------------------------------------------
# CA-007: Artifact-Graph Diffing
# ---------------------------------------------------------------------------


def test_artifact_graph_compute_diff():
    from agent33.automation.sensors.file_change import ArtifactGraph

    g = ArtifactGraph()
    g.add_artifact("a", deps=[])
    g.add_artifact("b", deps=["a"])
    g.add_artifact("c", deps=["b"])

    # Record initial state
    g.record_state("a", "hash1")
    g.record_state("b", "hash2")
    g.record_state("c", "hash3")

    # No changes yet (first recording, no previous)
    assert g.compute_diff() == set()

    # Change artifact 'a'
    g.record_state("a", "hash1_changed")
    affected = g.compute_diff()

    # 'a' changed, so 'b' and 'c' are downstream-affected
    assert "a" in affected
    assert "b" in affected
    assert "c" in affected


def test_artifact_graph_no_change():
    from agent33.automation.sensors.file_change import ArtifactGraph

    g = ArtifactGraph()
    g.add_artifact("x")
    g.record_state("x", "h1")
    g.record_state("x", "h1")  # Same hash
    assert g.compute_diff() == set()


# ---------------------------------------------------------------------------
# CA-011: Dry-Run Execution Mode (verify the executor already supports it)
# ---------------------------------------------------------------------------


def test_dry_run_flag_in_definition():
    """The WorkflowExecution model should accept dry_run=True."""
    from agent33.workflows.definition import WorkflowExecution

    exe = WorkflowExecution(dry_run=True)
    assert exe.dry_run is True


# ---------------------------------------------------------------------------
# CA-013: Artifact Filtering Module
# ---------------------------------------------------------------------------


def test_artifact_filter_include_exclude():
    from agent33.automation.filters import Artifact, ArtifactFilter

    artifacts = [
        Artifact(id="1", name="build.py", artifact_type="code"),
        Artifact(id="2", name="test.py", artifact_type="code"),
        Artifact(id="3", name="readme.md", artifact_type="doc"),
    ]

    f = ArtifactFilter().include(["*.py"]).exclude(["test*"])
    result = f.apply(artifacts)
    assert len(result) == 1
    assert result[0].name == "build.py"


def test_artifact_filter_by_type():
    from agent33.automation.filters import Artifact, ArtifactFilter

    artifacts = [
        Artifact(id="1", name="a", artifact_type="code"),
        Artifact(id="2", name="b", artifact_type="doc"),
    ]

    result = ArtifactFilter().by_type(["doc"]).apply(artifacts)
    assert len(result) == 1
    assert result[0].artifact_type == "doc"


def test_artifact_filter_by_age():
    from agent33.automation.filters import Artifact, ArtifactFilter

    old = Artifact(id="1", name="old", created_at=time.time() - 1000)
    new = Artifact(id="2", name="new", created_at=time.time())

    result = ArtifactFilter().by_age(60).apply([old, new])
    assert len(result) == 1
    assert result[0].name == "new"


# ---------------------------------------------------------------------------
# CA-024: Runtime Partitioning
# ---------------------------------------------------------------------------


def test_partition_executor_static_keys():
    from agent33.workflows.partitioning import PartitionDefinition, PartitionExecutor

    partition = PartitionDefinition(static_keys=["us", "eu", "ap"])
    executor = PartitionExecutor(partition)

    async def run(key: str) -> dict[str, Any]:
        return {"region": key, "status": "ok"}

    results = asyncio.run(executor.execute(run))
    assert len(results) == 3
    assert all(r.status == "success" for r in results)
    keys = {r.key for r in results}
    assert keys == {"us", "eu", "ap"}


def test_partition_executor_dynamic_discovery():
    from agent33.workflows.partitioning import PartitionDefinition, PartitionExecutor

    async def discover() -> list[str]:
        return ["shard-0", "shard-1"]

    partition = PartitionDefinition(discover=discover)
    executor = PartitionExecutor(partition)

    async def run(key: str) -> dict[str, Any]:
        return {"shard": key}

    results = asyncio.run(executor.execute(run))
    assert len(results) == 2


# ---------------------------------------------------------------------------
# CA-025: IO Manager Abstraction
# ---------------------------------------------------------------------------


def test_memory_io_manager():
    from agent33.workflows.io_manager import IOContext, MemoryIOManager

    mgr = MemoryIOManager()
    ctx = IOContext(step_id="step1", run_id="run1", key="data")

    mgr.handle_output(ctx, {"result": 42})
    loaded = mgr.load_input(ctx)
    assert loaded == {"result": 42}


def test_file_io_manager(tmp_path):
    from agent33.workflows.io_manager import FileIOManager, IOContext

    mgr = FileIOManager(tmp_path)
    ctx = IOContext(step_id="s1", run_id="r1", key="out")

    mgr.handle_output(ctx, {"value": "hello"})
    loaded = mgr.load_input(ctx)
    assert loaded == {"value": "hello"}


def test_database_io_manager():
    from agent33.workflows.io_manager import DatabaseIOManager, IOContext

    mgr = DatabaseIOManager()
    ctx = IOContext(step_id="s1", run_id="r1", key="k")

    assert mgr.load_input(ctx) is None
    mgr.handle_output(ctx, [1, 2, 3])
    assert mgr.load_input(ctx) == [1, 2, 3]


# ---------------------------------------------------------------------------
# CA-030: Workflow Migration Tooling
# ---------------------------------------------------------------------------


def test_workflow_migration_upgrade():
    from agent33.workflows.migration import WorkflowMigration

    mig = WorkflowMigration()
    mig.register(
        "1.0.0",
        "2.0.0",
        upgrade_fn=lambda d: {**d, "new_field": True},
        downgrade_fn=lambda d: {k: v for k, v in d.items() if k != "new_field"},
    )

    result = mig.upgrade({"version": "1.0.0", "name": "test"}, "1.0.0", "2.0.0")
    assert result["version"] == "2.0.0"
    assert result["new_field"] is True


def test_workflow_migration_validate():
    from agent33.workflows.migration import WorkflowMigration

    mig = WorkflowMigration()
    mig.register("1.0.0", "2.0.0", upgrade_fn=lambda d: d)

    assert mig.validate_migration("1.0.0", "2.0.0") is True
    assert mig.validate_migration("2.0.0", "3.0.0") is False


def test_workflow_migration_downgrade():
    from agent33.workflows.migration import WorkflowMigration

    mig = WorkflowMigration()
    mig.register(
        "1.0.0",
        "2.0.0",
        upgrade_fn=lambda d: {**d, "added": True},
        downgrade_fn=lambda d: {k: v for k, v in d.items() if k != "added"},
    )

    result = mig.downgrade({"version": "2.0.0", "added": True}, "2.0.0", "1.0.0")
    assert result["version"] == "1.0.0"
    assert "added" not in result


# ---------------------------------------------------------------------------
# CA-043: Backpressure Signaling
# ---------------------------------------------------------------------------


def test_backpressure_controller():
    from agent33.workflows.executor import BackpressureController

    ctrl = BackpressureController(max_tokens=2)

    async def _test():
        assert not ctrl.is_pressured()

        assert await ctrl.acquire() is True
        assert await ctrl.acquire() is True
        assert ctrl.is_pressured()
        assert await ctrl.acquire() is False

        await ctrl.release()
        assert not ctrl.is_pressured()
        assert await ctrl.acquire() is True

    asyncio.run(_test())


# ---------------------------------------------------------------------------
# CA-046: Deep History States
# ---------------------------------------------------------------------------


def test_history_state_deep():
    from agent33.workflows.state_machine import HistoryState

    hs = HistoryState(id="h1", parent_state="parent", deep=True)
    config = {"level0": "A", "level0.level1": "B", "level0.level1.level2": "C"}
    hs.save(config)

    restored = hs.restore()
    assert restored == config
    assert hs.has_saved_state


def test_history_state_shallow():
    from agent33.workflows.state_machine import HistoryState

    hs = HistoryState(id="h2", parent_state="parent", deep=False)
    config = {"level0": "A", "level0.level1": "B"}
    hs.save(config)

    restored = hs.restore()
    # Shallow only keeps top-level (no dots in key)
    assert restored == {"level0": "A"}


# ---------------------------------------------------------------------------
# CA-058: State Model Testing
# ---------------------------------------------------------------------------


def test_state_model_tester_detects_unreachable():
    from agent33.testing.state_model import StateModelTester
    from agent33.workflows.state_machine import (
        StatechartDefinition,
        StateNode,
        Transition,
    )

    defn = StatechartDefinition(
        id="test",
        initial="a",
        states={
            "a": StateNode(on={"go": Transition(target="b")}),
            "b": StateNode(final=True),
            "orphan": StateNode(),  # unreachable
        },
    )

    tester = StateModelTester(defn)
    report = tester.explore()

    assert "a" in report.reachable_states
    assert "b" in report.reachable_states
    assert "orphan" in report.unreachable_states


def test_state_model_tester_detects_deadlock():
    from agent33.testing.state_model import StateModelTester
    from agent33.workflows.state_machine import StatechartDefinition, StateNode

    defn = StatechartDefinition(
        id="test",
        initial="start",
        states={
            "start": StateNode(on={"go": "stuck"}),
            "stuck": StateNode(),  # non-final, no transitions = deadlock
        },
    )

    tester = StateModelTester(defn)
    report = tester.explore()
    assert "stuck" in report.deadlock_states


# ---------------------------------------------------------------------------
# CA-060: Dollar-Cost Attribution
# ---------------------------------------------------------------------------


def test_cost_tracker_record_and_report():
    from agent33.observability.metrics import DEFAULT_MODEL_PRICING, CostTracker

    tracker = CostTracker(pricing=dict(DEFAULT_MODEL_PRICING))
    cost = tracker.record_usage("gpt-4", tokens_in=1000, tokens_out=500, scope="workflow:build")

    assert cost > 0

    report = tracker.get_cost(scope="workflow:build")
    assert report.total_cost == cost
    assert report.invocations == 1
    assert report.input_tokens == 1000
    assert report.output_tokens == 500


def test_cost_tracker_custom_pricing():
    from agent33.observability.metrics import CostTracker

    tracker = CostTracker(pricing={})
    tracker.set_pricing("custom-model", input_per_1k=0.01, output_per_1k=0.02)

    cost = tracker.record_usage("custom-model", tokens_in=2000, tokens_out=1000)
    # 2 * 0.01 + 1 * 0.02 = 0.04
    assert abs(cost - 0.04) < 1e-9
