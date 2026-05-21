"""Benchmark test -- measure topological sort performance on a 100-step DAG."""

from __future__ import annotations

import time

from agent33.workflows.dag import DAGBuilder
from agent33.workflows.definition import WorkflowStep


def _make_linear_dag(n: int) -> list[WorkflowStep]:
    """Create a linear chain of n steps where each depends on the previous."""
    steps: list[WorkflowStep] = []
    for i in range(n):
        step_id = f"step-{i:04d}"
        depends_on = [f"step-{i - 1:04d}"] if i > 0 else []
        steps.append(
            WorkflowStep(
                id=step_id,
                action="invoke-agent",
                agent="test-agent",
                depends_on=depends_on,
            )
        )
    return steps


def _make_wide_dag(n: int) -> list[WorkflowStep]:
    """Create a DAG with a root, n-2 parallel middle steps, and a final join step."""
    steps: list[WorkflowStep] = [
        WorkflowStep(id="root", action="invoke-agent", agent="test-agent"),
    ]
    middle_ids: list[str] = []
    for i in range(n - 2):
        step_id = f"mid-{i:04d}"
        middle_ids.append(step_id)
        steps.append(
            WorkflowStep(
                id=step_id,
                action="invoke-agent",
                agent="test-agent",
                depends_on=["root"],
            )
        )
    steps.append(
        WorkflowStep(
            id="join",
            action="invoke-agent",
            agent="test-agent",
            depends_on=middle_ids,
        )
    )
    return steps


def _make_diamond_dag(n: int) -> list[WorkflowStep]:
    """Create a diamond-shaped DAG with layers of fan-out and fan-in."""
    steps: list[WorkflowStep] = [
        WorkflowStep(id="start", action="invoke-agent", agent="test-agent"),
    ]
    prev_layer = ["start"]
    step_count = 1
    layer_size = 4

    while step_count < n - 1:
        current_layer: list[str] = []
        for _j in range(min(layer_size, n - 1 - step_count)):
            step_id = f"s-{step_count:04d}"
            steps.append(
                WorkflowStep(
                    id=step_id,
                    action="invoke-agent",
                    agent="test-agent",
                    depends_on=list(prev_layer),
                )
            )
            current_layer.append(step_id)
            step_count += 1
        prev_layer = current_layer

    steps.append(
        WorkflowStep(
            id="end",
            action="invoke-agent",
            agent="test-agent",
            depends_on=list(prev_layer),
        )
    )
    return steps


class TestDAGPerformance:
    """Performance benchmarks for DAG topological sorting."""

    def test_linear_100_steps(self) -> None:
        steps = _make_linear_dag(100)
        start = time.perf_counter()
        dag = DAGBuilder(steps).build()
        elapsed = time.perf_counter() - start

        order = dag.topological_order()
        assert len(order) == 100
        assert order[0] == "step-0000"
        assert order[-1] == "step-0099"
        # Should complete well under 1 second.
        assert elapsed < 1.0, f"Linear DAG sort took {elapsed:.3f}s"

    def test_wide_100_steps(self) -> None:
        steps = _make_wide_dag(100)
        start = time.perf_counter()
        dag = DAGBuilder(steps).build()
        elapsed = time.perf_counter() - start

        order = dag.topological_order()
        assert len(order) == 100
        assert order[0] == "root"
        assert order[-1] == "join"
        groups = dag.parallel_groups()
        # Middle steps should all be in the same parallel group.
        assert any(len(g) == 98 for g in groups)
        assert elapsed < 1.0, f"Wide DAG sort took {elapsed:.3f}s"

    def test_diamond_100_steps(self) -> None:
        steps = _make_diamond_dag(100)
        start = time.perf_counter()
        dag = DAGBuilder(steps).build()
        elapsed = time.perf_counter() - start

        order = dag.topological_order()
        assert len(order) == len(steps)
        assert order[0] == "start"
        assert order[-1] == "end"
        assert elapsed < 1.0, f"Diamond DAG sort took {elapsed:.3f}s"

    def test_sort_is_deterministic(self) -> None:
        steps = _make_wide_dag(50)
        results = [DAGBuilder(steps).build().topological_order() for _ in range(10)]
        assert all(r == results[0] for r in results)
