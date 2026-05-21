from __future__ import annotations

import pytest

from agent33.workflows.roles import (
    RoleContract,
    build_role_orchestration_plan,
    build_worktree_isolation_plan,
)


def test_build_worktree_isolation_plan_uses_role_write_scopes() -> None:
    role = RoleContract(
        role_id="Review Worker",
        write_scopes=["engine/tests"],
        evidence_requirements=["pytest"],
    )

    plan = build_worktree_isolation_plan(role, slice_id="S143-5")

    assert plan.branch_name == "s143-5-review-worker"
    assert plan.worktree_name == "s143-5-review-worker"
    assert plan.write_scopes == ["engine/tests"]
    assert plan.evidence_requirements == ["pytest"]


def test_build_role_orchestration_plan_assigns_isolated_worktrees() -> None:
    roles = [
        RoleContract(
            role_id="backend-worker",
            write_scopes=["engine/src/agent33/workflows"],
            evidence_requirements=["pytest"],
        ),
        RoleContract(
            role_id="docs-worker",
            write_scopes=["docs/research"],
            evidence_requirements=["git diff --check"],
        ),
    ]

    plan = build_role_orchestration_plan(roles, slice_id="S147-5")

    assert plan.slice_id == "S147-5"
    assert plan.shared_read_only is True
    assert [item.branch_name for item in plan.plans] == [
        "s147-5-backend-worker",
        "s147-5-docs-worker",
    ]
    assert plan.by_role("docs-worker").evidence_requirements == ["git diff --check"]  # type: ignore[union-attr]


def test_build_role_orchestration_plan_rejects_duplicate_write_scopes() -> None:
    roles = [
        RoleContract(role_id="worker-a", write_scopes=["engine/src"]),
        RoleContract(role_id="worker-b", write_scopes=["engine/src/"]),
    ]

    with pytest.raises(ValueError, match="engine/src"):
        build_role_orchestration_plan(roles, slice_id="S147-5")


def test_build_role_orchestration_plan_can_allow_shared_write_scopes() -> None:
    roles = [
        RoleContract(role_id="worker-a", write_scopes=["engine/src"]),
        RoleContract(role_id="worker-b", write_scopes=["engine/src"]),
    ]

    plan = build_role_orchestration_plan(
        roles,
        slice_id="S147-5",
        allow_shared_write_scopes=True,
    )

    assert len(plan.plans) == 2
