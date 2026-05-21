import type { DomainConfig } from "../../types";

export const evaluationsDomain: DomainConfig = {
  id: "evaluations",
  title: "Evaluations",
  description: "Golden tasks, runs, baselines, regressions.",
  operations: [
    {
      id: "eval-golden-tasks",
      title: "Golden Tasks",
      method: "GET",
      path: "/v1/evaluations/golden-tasks",
      description: "List golden tasks."
    },
    {
      id: "eval-golden-cases",
      title: "Golden Cases",
      method: "GET",
      path: "/v1/evaluations/golden-cases",
      description: "List golden cases."
    },
    {
      id: "eval-gate-tasks",
      title: "Gate Tasks",
      method: "GET",
      path: "/v1/evaluations/gates/{gate}/tasks",
      description: "Tasks for a gate.",
      defaultPathParams: {
        gate: "G-PR"
      }
    },
    {
      id: "eval-run-create",
      title: "Create Run",
      method: "POST",
      path: "/v1/evaluations/runs",
      description: "Create evaluation run.",
      defaultBody: JSON.stringify(
        {
          gate: "G-PR",
          branch: "main",
          commit_hash: "abc123"
        },
        null,
        2
      )
    },
    {
      id: "eval-run-list",
      title: "List Runs",
      method: "GET",
      path: "/v1/evaluations/runs",
      description: "List evaluation runs."
    },
    {
      id: "eval-run-get",
      title: "Get Run",
      method: "GET",
      path: "/v1/evaluations/runs/{run_id}",
      description: "Get run detail.",
      defaultPathParams: {
        run_id: "replace-with-run-id"
      }
    },
    {
      id: "eval-run-results",
      title: "Submit Run Results",
      method: "POST",
      path: "/v1/evaluations/runs/{run_id}/results",
      description: "Submit task results.",
      defaultPathParams: {
        run_id: "replace-with-run-id"
      },
      defaultBody: JSON.stringify(
        {
          task_results: [
            {
              item_id: "GT-01",
              result: "pass",
              checks_passed: 3,
              checks_total: 3,
              duration_ms: 1100
            }
          ],
          rework_count: 0,
          scope_violations: 0
        },
        null,
        2
      )
    },
    {
      id: "eval-run-baseline",
      title: "Save Baseline",
      method: "POST",
      path: "/v1/evaluations/runs/{run_id}/baseline",
      description: "Save run as baseline.",
      defaultPathParams: {
        run_id: "replace-with-run-id"
      },
      defaultBody: JSON.stringify(
        {
          branch: "main",
          commit_hash: "abc123"
        },
        null,
        2
      )
    },
    {
      id: "eval-baselines",
      title: "List Baselines",
      method: "GET",
      path: "/v1/evaluations/baselines",
      description: "List baselines."
    },
    {
      id: "eval-regressions",
      title: "List Regressions",
      method: "GET",
      path: "/v1/evaluations/regressions",
      description: "List regressions."
    },
    {
      id: "eval-triage",
      title: "Triage Regression",
      method: "PATCH",
      path: "/v1/evaluations/regressions/{regression_id}/triage",
      description: "Set triage status.",
      defaultPathParams: {
        regression_id: "replace-with-regression-id"
      },
      defaultBody: JSON.stringify(
        {
          status: "in_progress",
          owner: "qa-team"
        },
        null,
        2
      )
    },
    {
      id: "eval-resolve",
      title: "Resolve Regression",
      method: "POST",
      path: "/v1/evaluations/regressions/{regression_id}/resolve",
      description: "Resolve regression.",
      defaultPathParams: {
        regression_id: "replace-with-regression-id"
      },
      defaultBody: JSON.stringify(
        {
          resolution: "Fixed in commit abcdef"
        },
        null,
        2
      )
    }
  ]
};
