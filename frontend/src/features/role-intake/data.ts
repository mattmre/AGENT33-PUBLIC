import type { RoleProfile, UserRoleId } from "./types";

export const ROLE_PROFILES: RoleProfile[] = [
  {
    id: "founder",
    title: "Founder",
    headline: "Turn a rough idea into a first product plan.",
    summary:
      "Best when you know the business outcome but do not want to learn workflow syntax, model settings, or agent terms first.",
    bestFor: ["MVP scope", "Landing pages", "SaaS plans"],
    workflowIds: ["build-first-app", "create-landing-page", "saas-scaffold"],
    demoScenarioIds: ["first-product-idea", "landing-page", "support-dashboard"],
    setupFocus: ["Try Demo Mode", "Connect OpenRouter", "Use Workflow Starter"],
    starterKind: "automation-loop"
  },
  {
    id: "developer",
    title: "Developer",
    headline: "Analyze code, plan fixes, and ship safer PR slices.",
    summary:
      "Best when you have a repository or technical task and want evidence, validation commands, and reviewable implementation steps.",
    bestFor: ["Repo triage", "Test plans", "Release readiness"],
    workflowIds: ["analyze-repo", "test-generation", "release-readiness"],
    demoScenarioIds: ["repo-triage", "team-meeting-bot"],
    setupFocus: ["Connect repo workspace", "Check MCP tools", "Review safety gates"],
    starterKind: "research"
  },
  {
    id: "agency",
    title: "Agency",
    headline: "Package client goals into repeatable delivery workflows.",
    summary:
      "Best when you need intake, milestones, copy, reports, approvals, and status cadence for multiple clients.",
    bestFor: ["Client kickoff", "Landing pages", "Weekly reporting"],
    workflowIds: ["client-kickoff", "create-landing-page", "competitive-research"],
    demoScenarioIds: ["landing-page", "customer-export-report", "team-meeting-bot"],
    setupFocus: ["Choose client workflow", "Connect model", "Keep approvals on"],
    starterKind: "automation-loop"
  },
  {
    id: "enterprise",
    title: "Enterprise",
    headline: "Break large programs into governed agent workstreams.",
    summary:
      "Best when the work needs milestones, approvals, risk tracking, stakeholder reporting, and safe handoffs.",
    bestFor: ["Program planning", "Security review", "Release gates"],
    workflowIds: ["enterprise-program", "security-review", "release-readiness"],
    demoScenarioIds: ["repo-triage", "team-meeting-bot"],
    setupFocus: ["Review safety center", "Define approvals", "Check audit readiness"],
    starterKind: "research"
  },
  {
    id: "operator",
    title: "Operator",
    headline: "Turn messy business processes into dashboards and automation.",
    summary:
      "Best when you need internal tools, customer reports, meeting follow-ups, or repeatable operating rhythms.",
    bestFor: ["Internal tools", "Dashboards", "Meeting follow-up"],
    workflowIds: ["internal-tool", "data-dashboard", "release-readiness"],
    demoScenarioIds: ["support-dashboard", "customer-export-report", "team-meeting-bot"],
    setupFocus: ["Describe the process", "Connect model", "Review before running"],
    starterKind: "automation-loop"
  }
];

export function isUserRoleId(value: string | null): value is UserRoleId {
  return ROLE_PROFILES.some((profile) => profile.id === value);
}

export function getRoleProfile(roleId: UserRoleId | null | undefined): RoleProfile | null {
  return ROLE_PROFILES.find((profile) => profile.id === roleId) ?? null;
}
