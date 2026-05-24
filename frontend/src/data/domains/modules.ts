import type { DomainConfig } from "../../types";

export const modulesDomain: DomainConfig = {
  id: "modules",
  title: "Modules & Capabilities",
  description: "Manage and monitor loaded capabilities, add-ons, and agent skills.",
  operations: [
    {
      id: "skills-match",
      title: "Match Skills",
      description: "Match an operator request to available skills through the hybrid matcher.",
      method: "POST",
      path: "/v1/skills/match",
      defaultBody: JSON.stringify(
        {
          query: "Find a skill that can review a pull request.",
          context: {
            surface: "advanced-control-plane"
          }
        },
        null,
        2
      )
    },
    {
      id: "skills-thresholds",
      title: "Skill Match Thresholds",
      description: "Inspect the active thresholds used by the skill matching pipeline.",
      method: "GET",
      path: "/v1/skills/match/thresholds"
    },
    {
      id: "skills-authoring-draft",
      title: "Draft Skill",
      description: "Generate an operator-authored SKILL.md draft from structured intent.",
      method: "POST",
      path: "/v1/skills/authoring/drafts",
      defaultBody: JSON.stringify(
        {
          name: "review-helper",
          description: "Helps review pull requests for regressions.",
          use_case: "Inspect a focused diff and identify actionable risks.",
          workflow_steps: ["Read the diff", "Check tests", "Report findings"],
          success_criteria: ["Findings cite files and lines"],
          allowed_tools: ["shell"],
          approval_required_for: ["destructive file operations"],
          install: false
        },
        null,
        2
      )
    }
  ]
};
