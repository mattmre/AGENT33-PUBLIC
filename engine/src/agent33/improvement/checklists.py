"""Canonical improvement checklists (CI-01..CI-15).

Implements the three periodic checklists from
``core/orchestrator/CONTINUOUS_IMPROVEMENT.md``.
"""

from __future__ import annotations

from agent33.improvement.models import (
    ChecklistItem,
    ChecklistPeriod,
    ImprovementChecklist,
)

# ---------------------------------------------------------------------------
# Per-Release checklist (CI-REL): CI-01..CI-05
# ---------------------------------------------------------------------------

_PER_RELEASE: list[tuple[str, str]] = [
    ("CI-01", "Retrospective conducted"),
    ("CI-02", "Lessons learned documented"),
    ("CI-03", "Action items created"),
    ("CI-04", "Metrics captured"),
    ("CI-05", "Process improvements identified"),
]

# ---------------------------------------------------------------------------
# Monthly checklist (CI-MON): CI-06..CI-10
# ---------------------------------------------------------------------------

_MONTHLY: list[tuple[str, str]] = [
    ("CI-06", "Workflow efficiency reviewed"),
    ("CI-07", "Bottlenecks identified"),
    ("CI-08", "Tool performance assessed"),
    ("CI-09", "Documentation currency checked"),
    ("CI-10", "Training gaps identified"),
]

# ---------------------------------------------------------------------------
# Quarterly checklist (CI-QTR): CI-11..CI-15
# ---------------------------------------------------------------------------

_QUARTERLY: list[tuple[str, str]] = [
    ("CI-11", "Full process audit completed"),
    ("CI-12", "Tool stack evaluated"),
    ("CI-13", "Research backlog triaged"),
    ("CI-14", "Roadmap aligned with strategy"),
    ("CI-15", "Governance artifacts updated"),
]


_PERIOD_MAP: dict[ChecklistPeriod, list[tuple[str, str]]] = {
    ChecklistPeriod.PER_RELEASE: _PER_RELEASE,
    ChecklistPeriod.MONTHLY: _MONTHLY,
    ChecklistPeriod.QUARTERLY: _QUARTERLY,
}


def build_checklist(
    period: ChecklistPeriod,
    reference: str = "",
) -> ImprovementChecklist:
    """Build the canonical improvement checklist for the given period."""
    items = [ChecklistItem(check_id=cid, name=name) for cid, name in _PERIOD_MAP[period]]
    return ImprovementChecklist(
        period=period,
        reference=reference,
        items=items,
    )


class ChecklistEvaluator:
    """Evaluate an improvement checklist for completion."""

    def evaluate(self, checklist: ImprovementChecklist) -> tuple[bool, list[str]]:
        """Return (all_complete, list of incomplete item descriptions)."""
        incomplete: list[str] = []
        for item in checklist.items:
            if not item.completed:
                incomplete.append(f"{item.check_id} ({item.name})")
        return len(incomplete) == 0, incomplete

    def complete_item(
        self,
        checklist: ImprovementChecklist,
        check_id: str,
        notes: str = "",
    ) -> ChecklistItem | None:
        """Mark a checklist item as completed."""
        for item in checklist.items:
            if item.check_id == check_id:
                item.completed = True
                if notes:
                    item.notes = notes
                return item
        return None
