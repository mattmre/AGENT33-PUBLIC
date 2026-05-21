import type { DomainConfig } from "../../types";

export const autonomyDomain: DomainConfig = {
  id: "autonomy",
  title: "Autonomy",
  description: "Budget lifecycle and policy enforcement.",
  operations: [
    {
      id: "autonomy-create",
      title: "Create Budget",
      method: "POST",
      path: "/v1/autonomy/budgets",
      description: "Create autonomy budget.",
      defaultBody: JSON.stringify(
        {
          task_id: "TASK-201",
          agent_id: "AGT-001",
          in_scope: ["engine/src/**"],
          out_of_scope: ["infra/**"],
          default_escalation_target: "orchestrator"
        },
        null,
        2
      )
    },
    {
      id: "autonomy-list",
      title: "List Budgets",
      method: "GET",
      path: "/v1/autonomy/budgets",
      description: "List autonomy budgets."
    },
    {
      id: "autonomy-get",
      title: "Get Budget",
      method: "GET",
      path: "/v1/autonomy/budgets/{budget_id}",
      description: "Get budget details.",
      defaultPathParams: {
        budget_id: "replace-with-budget-id"
      }
    },
    {
      id: "autonomy-delete",
      title: "Delete Budget",
      method: "DELETE",
      path: "/v1/autonomy/budgets/{budget_id}",
      description: "Delete budget.",
      defaultPathParams: {
        budget_id: "replace-with-budget-id"
      }
    },
    {
      id: "autonomy-transition",
      title: "Transition Budget",
      method: "POST",
      path: "/v1/autonomy/budgets/{budget_id}/transition",
      description: "Transition budget state.",
      defaultPathParams: {
        budget_id: "replace-with-budget-id"
      },
      defaultBody: JSON.stringify(
        {
          to_state: "active"
        },
        null,
        2
      )
    },
    {
      id: "autonomy-activate",
      title: "Activate Budget",
      method: "POST",
      path: "/v1/autonomy/budgets/{budget_id}/activate",
      description: "Activate budget.",
      defaultPathParams: {
        budget_id: "replace-with-budget-id"
      },
      defaultBody: "{}"
    },
    {
      id: "autonomy-suspend",
      title: "Suspend Budget",
      method: "POST",
      path: "/v1/autonomy/budgets/{budget_id}/suspend",
      description: "Suspend budget.",
      defaultPathParams: {
        budget_id: "replace-with-budget-id"
      },
      defaultBody: "{}"
    },
    {
      id: "autonomy-complete",
      title: "Complete Budget",
      method: "POST",
      path: "/v1/autonomy/budgets/{budget_id}/complete",
      description: "Complete budget lifecycle.",
      defaultPathParams: {
        budget_id: "replace-with-budget-id"
      },
      defaultBody: "{}"
    },
    {
      id: "autonomy-preflight",
      title: "Budget Preflight",
      method: "GET",
      path: "/v1/autonomy/budgets/{budget_id}/preflight",
      description: "Run preflight checks.",
      defaultPathParams: {
        budget_id: "replace-with-budget-id"
      }
    },
    {
      id: "autonomy-enforcer",
      title: "Create Enforcer",
      method: "POST",
      path: "/v1/autonomy/budgets/{budget_id}/enforcer",
      description: "Create runtime enforcer.",
      defaultPathParams: {
        budget_id: "replace-with-budget-id"
      },
      defaultBody: "{}"
    },
    {
      id: "autonomy-enforce-file",
      title: "Enforce File Access",
      method: "POST",
      path: "/v1/autonomy/budgets/{budget_id}/enforce/file",
      description: "Validate file action against budget.",
      defaultPathParams: {
        budget_id: "replace-with-budget-id"
      },
      defaultBody: JSON.stringify(
        {
          path: "engine/src/agent33/main.py",
          action: "read"
        },
        null,
        2
      )
    },
    {
      id: "autonomy-enforce-command",
      title: "Enforce Command",
      method: "POST",
      path: "/v1/autonomy/budgets/{budget_id}/enforce/command",
      description: "Validate command execution.",
      defaultPathParams: {
        budget_id: "replace-with-budget-id"
      },
      defaultBody: JSON.stringify(
        {
          command: "pytest -q"
        },
        null,
        2
      )
    },
    {
      id: "autonomy-enforce-network",
      title: "Enforce Network",
      method: "POST",
      path: "/v1/autonomy/budgets/{budget_id}/enforce/network",
      description: "Validate network access.",
      defaultPathParams: {
        budget_id: "replace-with-budget-id"
      },
      defaultBody: JSON.stringify(
        {
          host: "api.github.com",
          protocol: "https"
        },
        null,
        2
      )
    },
    {
      id: "autonomy-escalations",
      title: "List Escalations",
      method: "GET",
      path: "/v1/autonomy/escalations",
      description: "List escalations."
    },
    {
      id: "autonomy-escalate",
      title: "Escalate",
      method: "POST",
      path: "/v1/autonomy/budgets/{budget_id}/escalate",
      description: "Create escalation event.",
      defaultPathParams: {
        budget_id: "replace-with-budget-id"
      },
      defaultBody: JSON.stringify(
        {
          description: "Manual escalation from UI",
          target: "director",
          urgency: "normal"
        },
        null,
        2
      )
    },
    {
      id: "autonomy-ack",
      title: "Acknowledge Escalation",
      method: "POST",
      path: "/v1/autonomy/escalations/{escalation_id}/acknowledge",
      description: "Acknowledge escalation.",
      defaultPathParams: {
        escalation_id: "replace-with-escalation-id"
      },
      defaultBody: "{}"
    },
    {
      id: "autonomy-resolve",
      title: "Resolve Escalation",
      method: "POST",
      path: "/v1/autonomy/escalations/{escalation_id}/resolve",
      description: "Resolve escalation.",
      defaultPathParams: {
        escalation_id: "replace-with-escalation-id"
      },
      defaultBody: JSON.stringify(
        {
          resolution: "Approved by reviewer"
        },
        null,
        2
      )
    }
  ]
};
