import type { DomainConfig } from "../../types";
import { improvementCyclePresetBinding } from "../../features/improvement-cycle/presets";

export const workflowsDomain: DomainConfig = {
  id: "workflows",
  title: "Workflows",
  description: "Workflow registry, execution, and scheduling orchestration.",
  operations: [
    {
      id: "workflows-list",
      title: "List Workflows",
      method: "GET",
      path: "/v1/workflows/",
      description: "List workflow definitions.",
      instructionalText: "View all pre-registered automation sequences and background pipeline scripts."
    },
    {
      id: "workflows-get",
      title: "Get Workflow",
      method: "GET",
      path: "/v1/workflows/{name}",
      description: "Get workflow details.",
      instructionalText: "Examine the specific steps, expected inputs, and code logic inside a registered workflow module.",
      schemaInfo: {
        parameters: [
          { name: "name", type: "string", description: "The registered name of the workflow.", required: true }
        ]
      },
      defaultPathParams: {
        name: "hello-flow"
      }
    },
    {
      id: "workflows-create",
      title: "Create Workflow",
      method: "POST",
      path: "/v1/workflows/",
      description: "Register a workflow definition.",
      instructionalText: "Deploy a brand new sequence of automated steps into the system repository, allowing it to be executed manually or continuously scheduled later. Improvement-cycle presets can load canonical templates before you submit the JSON.",
      schemaInfo: {
        body: {
          description: "A JSON specifying the workflow inputs, steps, and expected outputs.",
          example: '{\n  "name": "data-sync-flow",\n  "version": "1.0.0",\n  "description": "Syncs data daily",\n  "inputs": { "source": { "type": "string" } },\n  "steps": [\n    { "id": "step1", "action": "fetch", "inputs": { "url": "{{ source }}" } }\n  ]\n}'
        }
      },
      defaultBody: JSON.stringify(
        {
          name: "hello-flow",
          version: "1.0.0",
          description: "Simple flow",
          triggers: { manual: true },
          inputs: {
            name: { type: "string", required: true }
          },
          outputs: {
            message: { type: "string" }
          },
          steps: [
            {
              id: "step-1",
              action: "transform",
              inputs: { template: { message: "Hello {{ name }}" } }
            }
          ],
          execution: { mode: "sequential" }
        },
        null,
        2
      ),
      presetBinding: improvementCyclePresetBinding
    },
    {
      id: "workflows-execute",
      title: "Execute Workflow",
      method: "POST",
      path: "/v1/workflows/{name}/execute",
      description: "Execute a registered workflow.",
      instructionalText: "Instantly start running an automation sequence by supplying its required initial inputs. The system will process each step in its pipeline. Improvement-cycle presets can populate the workflow name and deterministic sample inputs before execution.",
      schemaInfo: {
        parameters: [
          { name: "name", type: "string", description: "The name of the workflow to run.", required: true }
        ],
        body: {
          description: "An object containing the expected input parameters for this workflow.",
          example: '{\n  "inputs": {\n    "name": "AGENT-33",\n    "timeout": 300\n  }\n}'
        }
      },
      defaultPathParams: {
        name: "hello-flow"
      },
      defaultBody: JSON.stringify(
        {
          inputs: {
            name: "AGENT-33"
          }
        },
        null,
        2
      ),
      uxHint: "workflow-execute",
      presetBinding: improvementCyclePresetBinding
    },
    {
      id: "workflows-schedule-create",
      title: "Schedule Workflow",
      method: "POST",
      path: "/v1/workflows/{name}/schedule",
      description: "Create repeating cron/interval execution for a workflow.",
      instructionalText: "Set a workflow to automatically run in the background on a perfectly timed interval schedule without needing further intervention.",
      schemaInfo: {
        parameters: [
          { name: "name", type: "string", description: "The target workflow to schedule.", required: true }
        ],
        body: {
          description: "Specify the frequency (either in seconds or a cron expression) and the inputs to pass when running.",
          example: '{\n  "interval_seconds": 3600,\n  "inputs": { "target": "daily-report" }\n}'
        }
      },
      defaultPathParams: {
        name: "hello-flow"
      },
      defaultBody: JSON.stringify(
        {
          interval_seconds: 900,
          inputs: {
            name: "AGENT-33"
          }
        },
        null,
        2
      ),
      uxHint: "workflow-schedule"
    },
    {
      id: "workflows-schedule-list",
      title: "List Schedules",
      method: "GET",
      path: "/v1/workflows/schedules",
      description: "List active workflow schedules.",
      instructionalText: "Review any active background timers currently ticking down to trigger their associated automation routines."
    },
    {
      id: "workflows-schedule-delete",
      title: "Delete Schedule",
      method: "DELETE",
      path: "/v1/workflows/schedules/{job_id}",
      description: "Delete a schedule by job ID.",
      instructionalText: "Stop and permanently delete an active background workflow timer so that it ceases to continuously run.",
      schemaInfo: {
        parameters: [
          { name: "job_id", type: "string", description: "The active timer ID returned when the schedule was created.", required: true }
        ]
      },
      defaultPathParams: {
        job_id: "replace-with-job-id"
      }
    },
    {
      id: "workflows-history",
      title: "Workflow History",
      method: "GET",
      path: "/v1/workflows/{name}/history",
      description: "Recent execution history for a workflow.",
      instructionalText: "Lookup the success/failure statuses and timestamps of every time this particular script was run in the past.",
      schemaInfo: {
        parameters: [
          { name: "name", type: "string", description: "The registered name of the workflow.", required: true }
        ]
      },
      defaultPathParams: {
        name: "hello-flow"
      }
    },
    {
      id: "workflows-graph",
      title: "Workflow Graph",
      method: "GET",
      path: "/v1/visualizations/workflows/{workflow_id}/graph",
      description: "Get workflow graph visualization data.",
      instructionalText: "Generate structural mapping data so internal systems can cleanly visualize exactly how a workflow's logic jumps from node to node.",
      schemaInfo: {
        parameters: [
          { name: "workflow_id", type: "string", description: "The underlying identifier for the workflow.", required: true }
        ]
      },
      defaultPathParams: {
        workflow_id: "hello-flow"
      },
      uxHint: "workflow-graph"
    }
  ]
};
