"""First-success smoke task helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent33.ops.run_ledger import LedgerRunRecord, RunLedgerRepository


@dataclass(frozen=True)
class FirstSuccessSmokePlan:
    title: str
    steps: tuple[str, ...]
    proof: str


DEFAULT_FIRST_SUCCESS_PLAN = FirstSuccessSmokePlan(
    title="First-success setup smoke",
    steps=(
        "Confirm a provider/model readiness check can be read.",
        "Confirm a safe read-only tool path is discoverable.",
        "Record evidence that the smoke task completed without mutation.",
    ),
    proof="A completed run-ledger record with a summary event and smoke evidence.",
)


def create_first_success_smoke_run(
    repository: RunLedgerRepository,
    tenant_id: str,
    plan: FirstSuccessSmokePlan = DEFAULT_FIRST_SUCCESS_PLAN,
) -> LedgerRunRecord:
    """Create a proof-bearing, read-only first-success run."""
    task = repository.create_task(tenant_id, plan.title, status="complete")
    run = repository.create_run(
        tenant_id,
        task.id,
        status="succeeded",
        source_id="doctor:first-success",
    )
    repository.add_event(
        tenant_id,
        run.id,
        "status",
        "First-success smoke completed as a safe read-only setup proof.",
    )
    repository.add_evidence(
        tenant_id,
        run.id,
        "summary",
        "First-success smoke proof",
        uri="doctor:first-success",
    )
    return repository.get_record(tenant_id, run.id)
