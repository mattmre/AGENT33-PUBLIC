"""Golden task and golden case registry.

Implements the golden task definitions from ``core/arch/evaluation-harness.md``
and tagging from ``core/arch/REGRESSION_GATES.md``.
"""

from __future__ import annotations

from agent33.evaluation.models import (
    GoldenCaseDef,
    GoldenTag,
    GoldenTaskDef,
)

# ---------------------------------------------------------------------------
# Golden task definitions (GT-01 .. GT-07)
# ---------------------------------------------------------------------------

GOLDEN_TASKS: dict[str, GoldenTaskDef] = {
    "GT-01": GoldenTaskDef(
        task_id="GT-01",
        name="Documentation-Only Task",
        description="Create or update a markdown file with specified content structure.",
        tags=[GoldenTag.GT_SMOKE, GoldenTag.GT_CRITICAL],
        owner="documentation-agent",
        checks=[
            "File modified correctly",
            "Entry format matches existing",
            "Diff size < 20 lines",
            "No other files modified",
        ],
    ),
    "GT-02": GoldenTaskDef(
        task_id="GT-02",
        name="Task Queue Update",
        description="Add a new task to TASKS.md following minimum task payload template.",
        tags=[GoldenTag.GT_CRITICAL],
        owner="orchestrator",
        checks=[
            "Task appears in queue section",
            "Payload complete (ID, title, owner, acceptance, verification)",
            "Format matches existing entries",
            "No side effects",
        ],
    ),
    "GT-03": GoldenTaskDef(
        task_id="GT-03",
        name="Cross-Reference Validation",
        description="Verify and fix broken cross-references between documents.",
        tags=[GoldenTag.GT_RELEASE],
        owner="qa-agent",
        checks=[
            "All links in target file checked",
            "Report generated with link statuses",
            "Broken links corrected or flagged",
            "Evidence recorded in session log",
        ],
    ),
    "GT-04": GoldenTaskDef(
        task_id="GT-04",
        name="Template Instantiation",
        description="Create a new document using an existing template.",
        tags=[GoldenTag.GT_SMOKE, GoldenTag.GT_RELEASE],
        owner="documentation-agent",
        checks=[
            "File created at expected path",
            "All template sections present",
            "No placeholders remain",
            "Content accuracy",
        ],
    ),
    "GT-05": GoldenTaskDef(
        task_id="GT-05",
        name="Scope Lock Enforcement",
        description="Reject an out-of-scope request and document the escalation.",
        tags=[GoldenTag.GT_CRITICAL, GoldenTag.GT_REGRESSION],
        owner="orchestrator",
        checks=[
            "Request rejected (no code files created/modified)",
            "Escalation documented",
            "Clear rationale provided",
            "Alternative offered",
        ],
    ),
    "GT-06": GoldenTaskDef(
        task_id="GT-06",
        name="Evidence Capture Workflow",
        description="Complete a task and produce compliant evidence capture.",
        tags=[GoldenTag.GT_CRITICAL],
        owner="qa-agent",
        checks=[
            "Task completed",
            "Evidence capture sections filled",
            "At least one verification command with output",
            "Diff summary present",
        ],
    ),
    "GT-07": GoldenTaskDef(
        task_id="GT-07",
        name="Multi-File Coordinated Update",
        description="Update multiple related files while maintaining consistency.",
        tags=[GoldenTag.GT_RELEASE, GoldenTag.GT_REGRESSION],
        owner="architect",
        checks=[
            "All target files updated",
            "Cross-references valid",
            "Consistency maintained across files",
            "No broken links",
        ],
    ),
}

# ---------------------------------------------------------------------------
# Golden case definitions (GC-01 .. GC-04)
# ---------------------------------------------------------------------------

GOLDEN_CASES: dict[str, GoldenCaseDef] = {
    "GC-01": GoldenCaseDef(
        case_id="GC-01",
        name="Clean Single-File PR",
        description="A PR with a single, well-scoped documentation change.",
        tags=[GoldenTag.GT_SMOKE],
        owner="reviewer",
        checks=[
            "Scope assessment correct",
            "Diff size classified correctly",
            "Risk triggers: none",
            "No unnecessary reviewer required",
            "Merge readiness correct",
        ],
    ),
    "GC-02": GoldenCaseDef(
        case_id="GC-02",
        name="Multi-File Consistency PR",
        description="A PR updating multiple related documents for consistency.",
        tags=[GoldenTag.GT_CRITICAL, GoldenTag.GT_RELEASE],
        owner="architect",
        checks=[
            "Consistency verified across files",
            "Cross-reference audit passes",
            "Diff size classified correctly",
            "Architecture review triggered",
            "Required reviewers assigned",
        ],
    ),
    "GC-03": GoldenCaseDef(
        case_id="GC-03",
        name="Out-of-Scope PR Rejection",
        description="A PR that violates scope lock and should be rejected.",
        tags=[GoldenTag.GT_CRITICAL, GoldenTag.GT_REGRESSION],
        owner="orchestrator",
        checks=[
            "Scope violation detected",
            "Clear rejection rationale",
            "Suggested action provided",
            "Merge readiness: not ready",
        ],
    ),
    "GC-04": GoldenCaseDef(
        case_id="GC-04",
        name="Rework-Required PR",
        description="A PR with issues that require revision before merge.",
        tags=[GoldenTag.GT_RELEASE],
        owner="reviewer",
        checks=[
            "Issues identified",
            "Format check notes",
            "Cross-reference audit",
            "Specific rework items listed",
            "Merge readiness: not ready",
        ],
    ),
}


# ---------------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------------


def get_task(task_id: str) -> GoldenTaskDef | None:
    """Get a golden task definition by ID."""
    return GOLDEN_TASKS.get(task_id)


def get_case(case_id: str) -> GoldenCaseDef | None:
    """Get a golden case definition by ID."""
    return GOLDEN_CASES.get(case_id)


def tasks_by_tag(tag: GoldenTag) -> list[GoldenTaskDef]:
    """Return golden tasks that have the given tag."""
    return [t for t in GOLDEN_TASKS.values() if tag in t.tags]


def cases_by_tag(tag: GoldenTag) -> list[GoldenCaseDef]:
    """Return golden cases that have the given tag."""
    return [c for c in GOLDEN_CASES.values() if tag in c.tags]


def tasks_for_gate(gate_tag: GoldenTag) -> list[str]:
    """Return task IDs required for a gate's tag."""
    tasks = tasks_by_tag(gate_tag)
    cases = cases_by_tag(gate_tag)
    return [t.task_id for t in tasks] + [c.case_id for c in cases]
