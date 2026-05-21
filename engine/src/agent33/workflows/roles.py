"""Role contracts and worktree isolation helpers."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field


class RoleContract(BaseModel):
    role_id: str
    description: str = ""
    write_scopes: list[str] = Field(default_factory=list)
    evidence_requirements: list[str] = Field(default_factory=list)


class WorktreeIsolationPlan(BaseModel):
    role_id: str
    branch_name: str
    worktree_name: str
    write_scopes: list[str] = Field(default_factory=list)
    evidence_requirements: list[str] = Field(default_factory=list)


class RoleOrchestrationPlan(BaseModel):
    slice_id: str
    plans: list[WorktreeIsolationPlan] = Field(default_factory=list)
    shared_read_only: bool = True

    def by_role(self, role_id: str) -> WorktreeIsolationPlan | None:
        for plan in self.plans:
            if plan.role_id == role_id:
                return plan
        return None


def build_worktree_isolation_plan(role: RoleContract, *, slice_id: str) -> WorktreeIsolationPlan:
    slug = _slugify(f"{slice_id}-{role.role_id}")
    return WorktreeIsolationPlan(
        role_id=role.role_id,
        branch_name=slug,
        worktree_name=slug,
        write_scopes=role.write_scopes,
        evidence_requirements=role.evidence_requirements,
    )


def build_role_orchestration_plan(
    roles: list[RoleContract],
    *,
    slice_id: str,
    allow_shared_write_scopes: bool = False,
) -> RoleOrchestrationPlan:
    plans = [build_worktree_isolation_plan(role, slice_id=slice_id) for role in roles]
    if not allow_shared_write_scopes:
        _raise_for_overlapping_write_scopes(plans)
    return RoleOrchestrationPlan(slice_id=slice_id, plans=plans)


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return normalized or "worktree"


def _raise_for_overlapping_write_scopes(plans: list[WorktreeIsolationPlan]) -> None:
    owners: dict[str, str] = {}
    for plan in plans:
        for scope in plan.write_scopes:
            normalized = scope.rstrip("/")
            existing_owner = owners.get(normalized)
            if existing_owner and existing_owner != plan.role_id:
                raise ValueError(
                    f"write scope {normalized!r} is assigned to both "
                    f"{existing_owner!r} and {plan.role_id!r}"
                )
            owners[normalized] = plan.role_id
