import type { WorkflowStarterDraft } from "../workflow-starter/types";
import type { OutcomeWorkflow } from "./types";
import { buildProductBuilderLifecycle } from "./productization";

export const OUTCOME_WORKFLOWS: OutcomeWorkflow[] = [
  {
    id: "build-first-app",
    title: "Build my first app",
    audience: "Founder / layman builder",
    summary: "Turn a rough product idea into a scoped MVP plan and starter build workflow.",
    goal:
      "Help me turn a rough product idea into a small MVP. Ask only the questions needed, recommend a stack, create a build plan, and prepare the first implementation steps.",
    output:
      "Product brief, MVP scope, recommended stack, implementation plan, validation checklist, and next build step.",
    kind: "automation-loop",
    estimatedTime: "15-30 min plan",
    safetyLevel: "Review-gated",
    deliverables: ["Product brief", "MVP scope", "Build plan", "Validation checklist"],
    requires: ["Model connected", "Agent OS workspace recommended"],
    tags: ["product", "mvp", "starter"]
  },
  {
    id: "create-landing-page",
    title: "Create a landing page",
    audience: "Founder / agency",
    summary: "Generate a landing-page plan, copy blocks, sections, and implementation tasks.",
    goal:
      "Create a landing page for a product. Define the target customer, value proposition, page sections, copy blocks, design direction, and implementation tasks.",
    output:
      "Landing page outline, section-by-section copy, design notes, implementation checklist, and QA criteria.",
    kind: "automation-loop",
    estimatedTime: "10-20 min",
    safetyLevel: "Review-gated",
    deliverables: ["Copy blocks", "Section plan", "Implementation checklist"],
    requires: ["Model connected"],
    tags: ["marketing", "web", "quick win"]
  },
  {
    id: "analyze-repo",
    title: "Analyze my repo",
    audience: "Developer / maintainer",
    summary: "Inspect a repository and produce prioritized fixes with evidence.",
    goal:
      "Analyze this repository for architecture risks, test gaps, confusing user flows, and quick wins. Produce an implementation-ready fix queue with evidence.",
    output:
      "Ranked findings, affected files, suggested PR slices, validation commands, and rollback notes.",
    kind: "research",
    estimatedTime: "20-45 min",
    safetyLevel: "Plan-only",
    deliverables: ["Findings", "PR plan", "Validation commands"],
    requires: ["Repo workspace", "Read-only tools"],
    tags: ["developer", "repo", "quality"]
  },
  {
    id: "competitive-research",
    title: "Run competitive research",
    audience: "Product owner",
    summary: "Compare competitors and produce a ranked improvement backlog.",
    goal:
      "Research current agent platforms, MCP ecosystems, agent OS runtimes, and workflow UX patterns. Compare them with AGENT-33 and recommend ranked improvements.",
    output:
      "Competitive brief with sources, feature gaps, likely competitor direction, and ranked implementation proposals.",
    kind: "research",
    estimatedTime: "30-60 min",
    safetyLevel: "Plan-only",
    deliverables: ["Competitive brief", "Gap matrix", "Roadmap proposals"],
    requires: ["Web research tools"],
    tags: ["research", "strategy", "competitive"]
  },
  {
    id: "saas-scaffold",
    title: "Plan a SaaS scaffold",
    audience: "Founder / developer",
    summary: "Create a safe plan for auth, billing, dashboard, tests, and deployment.",
    goal:
      "Plan a SaaS application scaffold with authentication, billing, dashboard, admin area, test strategy, and deployment readiness checklist.",
    output:
      "SaaS scaffold architecture, module breakdown, data model sketch, build sequence, tests, and launch checklist.",
    kind: "automation-loop",
    estimatedTime: "30-60 min plan",
    safetyLevel: "Review-gated",
    deliverables: ["Architecture", "Module plan", "Test plan", "Launch checklist"],
    requires: ["Model connected", "Agent OS workspace"],
    tags: ["saas", "product", "architecture"]
  },
  {
    id: "internal-tool",
    title: "Build an internal tool",
    audience: "Operations team",
    summary: "Design a CRUD/admin workflow from a spreadsheet, API, or business process.",
    goal:
      "Design an internal tool from a business process. Identify data inputs, roles, screens, automation steps, and validation rules.",
    output:
      "Internal tool spec, screen list, data model, automation rules, and implementation plan.",
    kind: "automation-loop",
    estimatedTime: "20-40 min",
    safetyLevel: "Review-gated",
    deliverables: ["Tool spec", "Screen list", "Data model", "Automation rules"],
    requires: ["Business process description"],
    tags: ["ops", "crud", "automation"]
  },
  {
    id: "data-dashboard",
    title: "Create a data dashboard",
    audience: "Analyst / founder",
    summary: "Turn CSV/API metrics into dashboard requirements and build tasks.",
    goal:
      "Create a data dashboard plan from available metrics. Define KPIs, data sources, charts, filters, alerts, and validation checks.",
    output:
      "Dashboard requirements, KPI list, chart plan, data-source assumptions, and implementation checklist.",
    kind: "automation-loop",
    estimatedTime: "20-45 min",
    safetyLevel: "Review-gated",
    deliverables: ["KPI map", "Chart plan", "Data assumptions", "Build checklist"],
    requires: ["Data source description"],
    tags: ["data", "dashboard", "analytics"]
  },
  {
    id: "security-review",
    title: "Run a security review",
    audience: "Security / compliance",
    summary: "Review a planned change or repo area for risk and mitigation.",
    goal:
      "Run a security review for a product or code change. Identify threats, sensitive data paths, unsafe defaults, required approvals, and mitigations.",
    output:
      "Threat model, risk list, mitigation plan, approval gates, and validation checks.",
    kind: "research",
    estimatedTime: "20-45 min",
    safetyLevel: "Plan-only",
    deliverables: ["Threat model", "Mitigations", "Approval gates"],
    requires: ["Scope or repo path"],
    tags: ["security", "compliance", "review"]
  },
  {
    id: "test-generation",
    title: "Generate a test plan",
    audience: "Developer / QA",
    summary: "Find missing coverage and propose implementation-ready tests.",
    goal:
      "Review the target feature and produce a test plan with unit, integration, accessibility, and workflow coverage. Include commands and acceptance criteria.",
    output:
      "Test matrix, missing coverage, suggested test files, validation commands, and acceptance criteria.",
    kind: "research",
    estimatedTime: "15-30 min",
    safetyLevel: "Plan-only",
    deliverables: ["Test matrix", "Coverage gaps", "Validation commands"],
    requires: ["Feature scope"],
    tags: ["testing", "quality", "developer"]
  },
  {
    id: "release-readiness",
    title: "Check release readiness",
    audience: "Product / DevOps",
    summary: "Build a go/no-go checklist for a release or PR wave.",
    goal:
      "Assess release readiness. Check tests, docs, migration risks, rollback plan, observability, support notes, and stakeholder communication.",
    output:
      "Go/no-go checklist, risk register, rollback plan, release notes, and validation summary.",
    kind: "research",
    estimatedTime: "15-30 min",
    safetyLevel: "Plan-only",
    deliverables: ["Readiness checklist", "Risk register", "Rollback plan"],
    requires: ["Release scope"],
    tags: ["release", "devops", "quality"]
  },
  {
    id: "client-kickoff",
    title: "Kick off a client project",
    audience: "Agency operator",
    summary: "Package client goals into a repeatable delivery plan and status cadence.",
    goal:
      "Create a client project kickoff plan. Capture goals, stakeholders, constraints, deliverables, milestones, review cadence, and reporting format.",
    output:
      "Client charter, milestone plan, deliverable list, review cadence, and first-week task plan.",
    kind: "automation-loop",
    estimatedTime: "20-40 min",
    safetyLevel: "Review-gated",
    deliverables: ["Client charter", "Milestones", "Status cadence"],
    requires: ["Client goal"],
    tags: ["agency", "client", "planning"]
  },
  {
    id: "enterprise-program",
    title: "Design an enterprise program",
    audience: "Enterprise product owner",
    summary: "Turn a large initiative into milestones, release gates, risks, and agent workstreams.",
    goal:
      "Design a governed enterprise delivery program for a large initiative. Break it into milestones, agent workstreams, release gates, dependencies, risks, and stakeholder reports.",
    output:
      "Program charter, milestone roadmap, dependency map, risk register, agent workstream plan, and reporting cadence.",
    kind: "automation-loop",
    estimatedTime: "45-90 min plan",
    safetyLevel: "Review-gated",
    deliverables: ["Program charter", "Milestones", "Risk register", "Workstreams"],
    requires: ["Program objective", "Governance constraints"],
    tags: ["enterprise", "program", "governance"]
  }
];

export function buildWorkflowDraft(workflow: OutcomeWorkflow): WorkflowStarterDraft {
  return {
    id: workflow.id,
    name: workflow.id,
    goal: workflow.goal,
    kind: workflow.kind,
    output: workflow.output,
    schedule: "",
    author: "operator",
    sourceLabel: workflow.title,
    lifecyclePlan: buildProductBuilderLifecycle(workflow)
  };
}

export function buildCustomWorkflowDraft(goal: string): WorkflowStarterDraft {
  const cleanGoal = goal.trim();
  return {
    id: `custom-${Date.now().toString(36)}`,
    name: "",
    goal: cleanGoal,
    kind: "automation-loop",
    output:
      "Execution plan, required inputs, safety gates, deliverables, validation checks, and recommended next actions.",
    schedule: "",
    author: "operator",
    sourceLabel: "Custom outcome",
    lifecyclePlan: {
      brief: [
        cleanGoal,
        "Audience: operator-selected",
        "Required inputs: goal, success criteria, constraints"
      ],
      plan: [
        "Turn the goal into a scoped product brief.",
        "Propose the first deliverables and review gates before execution.",
        "Estimate runtime and model/tool prerequisites from the selected workflow type."
      ],
      preview: [
        "Validate inputs before any tool execution.",
        "Draft the first plan and deliverable checklist.",
        "Ask for review before files, credentials, or external systems are changed."
      ],
      handoff: [
        "Create an editable workflow from the approved plan.",
        "Keep host execution operator-triggered.",
        "Open Operations after creation so the run is visible and recoverable."
      ]
    }
  };
}

export function getFeaturedWorkflows(): OutcomeWorkflow[] {
  return OUTCOME_WORKFLOWS.slice(0, 6);
}
