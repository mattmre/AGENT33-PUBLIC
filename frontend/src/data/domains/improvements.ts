import type { DomainConfig } from "../../types";

const prettyJson = (value: unknown): string => JSON.stringify(value, null, 2);

export const improvementsDomain: DomainConfig = {
  id: "improvements",
  title: "Improvements",
  description:
    "Research intake, lessons, checklists, metrics, refreshes, and learning signals.",
  operations: [
    {
      id: "imp-intake-create",
      title: "Create Intake",
      method: "POST",
      path: "/v1/improvements/intakes",
      description: "Submit a new research intake record.",
      defaultBody: prettyJson({
        title: "UI parity backlog",
        summary: "Need to align the frontend control plane with backend capabilities.",
        source: "session-57",
        submitted_by: "session-operator",
        tenant_id: "default",
        research_type: "external",
        category: "frontend",
        urgency: "medium",
        impact_areas: ["frontend", "workflow-ui"],
        affected_phases: [25, 26, 27],
        priority_score: 8
      })
    },
    {
      id: "imp-intake-competitive-repos",
      title: "Create Competitive Repo Intakes",
      method: "POST",
      path: "/v1/improvements/intakes/competitive/repos",
      description: "Submit repository-harvest records as competitive research intakes.",
      defaultBody: prettyJson({
        records: [
          {
            rank: 1,
            full_name: "acme/agent-ui",
            url: "https://github.com/acme/agent-ui",
            stars: 1200,
            source_query: "topic:agent-ui"
          }
        ],
        submitted_by: "repo-harvester",
        tenant_id: "default"
      })
    },
    {
      id: "imp-feature-candidates-score",
      title: "Score Feature Candidates",
      method: "POST",
      path: "/v1/improvements/feature-candidates/score",
      description: "Score competitive feature candidates with weighted prioritization.",
      defaultBody: prettyJson({
        candidates: [
          {
            feature_name: "Evidence-backed approvals",
            category: "workflow-ui",
            source_repo: "acme/agent-ui",
            evidence_path: "frontend/src/features/improvement-cycle",
            maturity: "beta",
            security_impact: "medium",
            implementation_hint: "Reuse existing explanation and review artifacts",
            impact_score: 9,
            feasibility_score: 7,
            risk_score: 4
          }
        ],
        top_n: 5
      })
    },
    {
      id: "imp-intake-list",
      title: "List Intakes",
      method: "GET",
      path: "/v1/improvements/intakes",
      description: "List research intakes with optional filters.",
      defaultQuery: {
        status: "submitted",
        research_type: "external",
        tenant_id: "default"
      }
    },
    {
      id: "imp-intake-get",
      title: "Get Intake",
      method: "GET",
      path: "/v1/improvements/intakes/{intake_id}",
      description: "Get one research intake by ID.",
      defaultPathParams: {
        intake_id: "replace-with-intake-id"
      }
    },
    {
      id: "imp-intake-transition",
      title: "Transition Intake",
      method: "POST",
      path: "/v1/improvements/intakes/{intake_id}/transition",
      description: "Move an intake through its lifecycle.",
      defaultPathParams: {
        intake_id: "replace-with-intake-id"
      },
      defaultBody: prettyJson({
        new_status: "triaged",
        decision_by: "session-operator",
        rationale: "Ready for the next implementation wave.",
        action_items: ["Draft implementation checklist"]
      })
    },
    {
      id: "imp-lesson-create",
      title: "Create Lesson",
      method: "POST",
      path: "/v1/improvements/lessons",
      description: "Record a new lesson learned entry.",
      defaultBody: prettyJson({
        recorded_by: "session-operator",
        phase: "phase-26",
        release: "session-57",
        event_type: "observation",
        what_happened: "The frontend improvements domain drifted from the backend API.",
        root_cause: "No regression tests covered the contract metadata.",
        impact: "Operators saw stale payloads and unsupported paths in the UI explorer.",
        insight: "Frontend domain metadata needs direct contract tests.",
        recommendation: "Add a regression suite before building new wizard flows.",
        applies_to: ["frontend", "improvements"],
        actions: [
          {
            description: "Align the improvements domain metadata",
            owner: "frontend",
            target_date: ""
          }
        ]
      })
    },
    {
      id: "imp-lesson-list",
      title: "List Lessons",
      method: "GET",
      path: "/v1/improvements/lessons",
      description: "List lessons learned with optional filters.",
      defaultQuery: {
        phase: "phase-26",
        event_type: "observation"
      }
    },
    {
      id: "imp-lesson-get",
      title: "Get Lesson",
      method: "GET",
      path: "/v1/improvements/lessons/{lesson_id}",
      description: "Get one lesson learned record by ID.",
      defaultPathParams: {
        lesson_id: "replace-with-lesson-id"
      }
    },
    {
      id: "imp-lesson-complete-action",
      title: "Complete Lesson Action",
      method: "POST",
      path: "/v1/improvements/lessons/{lesson_id}/complete-action",
      description: "Mark a lesson action item complete by index.",
      defaultPathParams: {
        lesson_id: "replace-with-lesson-id"
      },
      defaultBody: prettyJson({
        action_index: 0
      })
    },
    {
      id: "imp-lesson-verify",
      title: "Verify Lesson",
      method: "POST",
      path: "/v1/improvements/lessons/{lesson_id}/verify",
      description: "Verify that a lesson has been implemented.",
      defaultPathParams: {
        lesson_id: "replace-with-lesson-id"
      },
      defaultBody: prettyJson({
        evidence: "Regression tests passed in CI."
      })
    },
    {
      id: "imp-checklist-create",
      title: "Create Checklist",
      method: "POST",
      path: "/v1/improvements/checklists",
      description: "Create a periodic improvement checklist.",
      defaultBody: prettyJson({
        period: "monthly",
        reference: "2026-03"
      })
    },
    {
      id: "imp-checklist-list",
      title: "List Checklists",
      method: "GET",
      path: "/v1/improvements/checklists",
      description: "List improvement checklists with optional period filtering.",
      defaultQuery: {
        period: "monthly"
      }
    },
    {
      id: "imp-checklist-get",
      title: "Get Checklist",
      method: "GET",
      path: "/v1/improvements/checklists/{checklist_id}",
      description: "Get one improvement checklist by ID.",
      defaultPathParams: {
        checklist_id: "replace-with-checklist-id"
      }
    },
    {
      id: "imp-checklist-complete",
      title: "Complete Checklist Item",
      method: "POST",
      path: "/v1/improvements/checklists/{checklist_id}/complete",
      description: "Complete one checklist item and attach notes.",
      defaultPathParams: {
        checklist_id: "replace-with-checklist-id"
      },
      defaultBody: prettyJson({
        check_id: "CI-01",
        notes: "Validated during Session 57 frontend test work."
      })
    },
    {
      id: "imp-checklist-evaluate",
      title: "Evaluate Checklist",
      method: "GET",
      path: "/v1/improvements/checklists/{checklist_id}/evaluate",
      description: "Evaluate checklist completion status.",
      defaultPathParams: {
        checklist_id: "replace-with-checklist-id"
      }
    },
    {
      id: "imp-metrics",
      title: "Get Latest Metrics",
      method: "GET",
      path: "/v1/improvements/metrics",
      description: "Get the latest improvement metrics snapshot."
    },
    {
      id: "imp-metrics-history",
      title: "Get Metrics History",
      method: "GET",
      path: "/v1/improvements/metrics/history",
      description: "List recent metrics snapshots.",
      defaultQuery: {
        limit: "10"
      }
    },
    {
      id: "imp-metrics-snapshot",
      title: "Save Metrics Snapshot",
      method: "POST",
      path: "/v1/improvements/metrics/snapshot",
      description: "Save a custom metrics snapshot.",
      defaultBody: prettyJson({
        period: "2026-Q1",
        metrics: [
          {
            metric_id: "IM-01",
            name: "Cycle time",
            baseline: 10,
            current: 8.2,
            target: 6,
            unit: "hours",
            trend: "improving"
          }
        ]
      })
    },
    {
      id: "imp-metrics-default",
      title: "Create Default Snapshot",
      method: "POST",
      path: "/v1/improvements/metrics/default-snapshot",
      description: "Create the canonical default metrics snapshot.",
      defaultQuery: {
        period: "2026-Q1"
      }
    },
    {
      id: "imp-metrics-trend",
      title: "Get Metrics Trend",
      method: "GET",
      path: "/v1/improvements/metrics/trend/{metric_id}",
      description: "Get trend data for a specific metric.",
      defaultPathParams: {
        metric_id: "IM-01"
      },
      defaultQuery: {
        periods: "6"
      }
    },
    {
      id: "imp-refresh-create",
      title: "Create Refresh",
      method: "POST",
      path: "/v1/improvements/refreshes",
      description: "Record a roadmap refresh event.",
      defaultBody: prettyJson({
        scope: "minor",
        participants: ["product", "engineering"],
        activities: ["retrospective", "prioritization"]
      })
    },
    {
      id: "imp-refresh-list",
      title: "List Refreshes",
      method: "GET",
      path: "/v1/improvements/refreshes",
      description: "List roadmap refresh events.",
      defaultQuery: {
        scope: "minor"
      }
    },
    {
      id: "imp-refresh-get",
      title: "Get Refresh",
      method: "GET",
      path: "/v1/improvements/refreshes/{refresh_id}",
      description: "Get one roadmap refresh by ID.",
      defaultPathParams: {
        refresh_id: "replace-with-refresh-id"
      }
    },
    {
      id: "imp-refresh-complete",
      title: "Complete Refresh",
      method: "POST",
      path: "/v1/improvements/refreshes/{refresh_id}/complete",
      description: "Mark a roadmap refresh complete with outcome details.",
      defaultPathParams: {
        refresh_id: "replace-with-refresh-id"
      },
      defaultBody: prettyJson({
        outcome: "Re-prioritized the UX backlog",
        changes: ["Promoted frontend contract tests", "Scheduled wizard follow-up"]
      })
    },
    {
      id: "imp-learning-signal-create",
      title: "Record Learning Signal",
      method: "POST",
      path: "/v1/improvements/learning/signals",
      description: "Record one continuous-learning signal.",
      instructionalText:
        "Requires improvement learning to be enabled; the backend returns 404 when learning is disabled.",
      defaultBody: prettyJson({
        signal_type: "process",
        severity: "medium",
        summary: "Frontend contract drift detected",
        details: "The improvements domain config exposed stale request shapes.",
        source: "session-57",
        tenant_id: "default",
        context: {
          area: "frontend"
        }
      })
    },
    {
      id: "imp-learning-signal-list",
      title: "List Learning Signals",
      method: "GET",
      path: "/v1/improvements/learning/signals",
      description: "List learning signals with optional filters.",
      instructionalText:
        "Requires improvement learning to be enabled; the backend returns 404 when learning is disabled.",
      defaultQuery: {
        signal_type: "process",
        severity: "medium",
        tenant_id: "default",
        limit: "50"
      }
    },
    {
      id: "imp-learning-summary",
      title: "Get Learning Summary",
      method: "GET",
      path: "/v1/improvements/learning/summary",
      description: "Summarize learning signals and optionally generate intakes.",
      instructionalText:
        "Requires improvement learning to be enabled; the backend returns 404 when learning is disabled.",
      defaultQuery: {
        limit: "20",
        generate_intakes: "false",
        tenant_id: "default",
        window_days: "30"
      }
    },
    {
      id: "imp-learning-trends",
      title: "Get Learning Trends",
      method: "GET",
      path: "/v1/improvements/learning/trends",
      description: "Get dedup-aware learning trend analytics.",
      instructionalText:
        "Requires improvement learning to be enabled; the backend returns 404 when learning is disabled.",
      defaultQuery: {
        window_days: "7",
        dimension: "signal_type",
        tenant_id: "default"
      }
    },
    {
      id: "imp-learning-calibration",
      title: "Get Learning Calibration",
      method: "GET",
      path: "/v1/improvements/learning/calibration",
      description: "Calibrate auto-intake and retention thresholds from recent signals.",
      instructionalText:
        "Requires improvement learning to be enabled; the backend returns 404 when learning is disabled.",
      defaultQuery: {
        window_days: "30",
        target_auto_intakes_per_window: "5",
        tenant_id: "default"
      }
    },
    {
      id: "imp-learning-backup",
      title: "Backup Learning State",
      method: "POST",
      path: "/v1/improvements/learning/backup",
      description: "Create a portable JSON backup of learning state.",
      instructionalText:
        "Backup and restore remain available even when improvement learning is disabled; use this operator endpoint to export persisted learning state.",
      defaultBody: prettyJson({
        backup_path: ""
      })
    },
    {
      id: "imp-learning-restore",
      title: "Restore Learning State",
      method: "POST",
      path: "/v1/improvements/learning/restore",
      description: "Restore learning state from a portable JSON backup.",
      instructionalText:
        "Backup and restore remain available even when improvement learning is disabled; use this operator endpoint to restore persisted learning state from backup data.",
      defaultBody: prettyJson({
        backup_path: "/path/to/agent33-learning-backup.json"
      })
    }
  ]
};
