import type { DemoScenario } from "./types";

export const DEMO_SCENARIOS: DemoScenario[] = [
  {
    id: "support-dashboard",
    title: "Customer support dashboard",
    audience: "Founder / operations lead",
    complexity: "Beginner",
    timeEstimate: "5 min preview",
    forRoles: ["founder", "operator"],
    outcome:
      "A practical product brief, workflow plan, dashboard sections, and QA checklist for a support analytics dashboard.",
    prompt:
      "Build a support dashboard that shows ticket volume, SLA breaches, response time trends, customer sentiment, and next actions for the support manager.",
    sampleInputs: [
      "Current source: CSV export from support tool",
      "Users: support manager and founder",
      "Must-have: SLA alerts, weekly trend chart, urgent ticket queue",
      "Safety: plan-only until model and workspace are connected"
    ],
    runSteps: [
      {
        id: "intake",
        title: "Clarified the goal",
        description: "Converted the rough request into audience, data source, output, and safety constraints.",
        tone: "done"
      },
      {
        id: "plan",
        title: "Generated a reviewable plan",
        description: "Split the dashboard into KPI cards, trend views, alert rules, and validation checks.",
        tone: "done"
      },
      {
        id: "artifact",
        title: "Prepared first deliverables",
        description: "Produced a product brief, screen outline, and implementation checklist without touching code.",
        tone: "active"
      },
      {
        id: "next",
        title: "Waiting for real setup",
        description: "Connect a model and workspace before AGENT33 can turn the plan into files or a PR.",
        tone: "attention"
      }
    ],
    artifacts: [
      {
        id: "brief",
        title: "Product brief",
        description: "A plain-language summary that a non-technical user can review.",
        contents: [
          "Goal: give managers a daily view of support health.",
          "Users: support manager, founder, and operations analyst.",
          "Success: spot SLA risk in under 30 seconds."
        ]
      },
      {
        id: "screens",
        title: "Screen outline",
        description: "The first useful shape of the product before code generation.",
        contents: [
          "Overview: SLA breaches, open tickets, sentiment score, and response time.",
          "Trends: weekly ticket volume and breach rate.",
          "Queue: urgent tickets grouped by customer and age."
        ]
      },
      {
        id: "qa",
        title: "QA checklist",
        description: "Acceptance criteria that protects against shallow generated output.",
        contents: [
          "Charts explain empty and missing-data states.",
          "SLA alert thresholds are configurable.",
          "Every metric has a source and timestamp."
        ]
      }
    ],
    starterDraft: {
      id: "demo-support-dashboard",
      name: "support-dashboard-demo",
      goal:
        "Create a customer support dashboard plan with ticket trends, SLA alerts, urgent queue, roles, validation checks, and implementation steps.",
      kind: "automation-loop",
      output:
        "Product brief, dashboard screen outline, data assumptions, QA checklist, and first implementation tasks.",
      schedule: "",
      author: "demo-operator",
      sourceLabel: "Demo Mode: Customer support dashboard"
    }
  },
  {
    id: "landing-page",
    title: "Landing page launch kit",
    audience: "Founder / agency",
    complexity: "Beginner",
    timeEstimate: "4 min preview",
    forRoles: ["founder", "agency"],
    outcome:
      "A launch-ready landing page structure with positioning, section copy, design notes, and implementation checklist.",
    prompt:
      "Create a landing page for an AI workflow product that helps small teams automate research and weekly reporting.",
    sampleInputs: [
      "Audience: small business owners",
      "Tone: practical, calm, non-technical",
      "Deliverable: page structure and copy blocks",
      "Safety: no deploy until reviewed"
    ],
    runSteps: [
      {
        id: "positioning",
        title: "Found the positioning",
        description: "Identified audience, pain, promise, and proof points.",
        tone: "done"
      },
      {
        id: "copy",
        title: "Drafted page sections",
        description: "Created hero, benefits, workflow, trust, and call-to-action sections.",
        tone: "done"
      },
      {
        id: "checklist",
        title: "Created launch checklist",
        description: "Added review items for clarity, accessibility, responsiveness, and tracking.",
        tone: "active"
      },
      {
        id: "next",
        title: "Ready for real workflow",
        description: "Connect a model to customize copy and generate implementation tasks.",
        tone: "attention"
      }
    ],
    artifacts: [
      {
        id: "hero",
        title: "Hero copy",
        description: "A sample first output users can understand immediately.",
        contents: [
          "Headline: Weekly research reports without hiring an analyst.",
          "Subhead: Connect a model, choose a workflow, and review a ready-to-send brief.",
          "CTA: Build my first reporting workflow."
        ]
      },
      {
        id: "sections",
        title: "Page sections",
        description: "A structured page plan instead of a blank prompt.",
        contents: ["Hero", "Problem", "How it works", "Workflow examples", "Security and review gates", "CTA"]
      }
    ],
    starterDraft: {
      id: "demo-landing-page",
      name: "landing-page-demo",
      goal:
        "Create a landing page launch kit with positioning, section-by-section copy, design notes, implementation tasks, and QA checklist.",
      kind: "automation-loop",
      output: "Landing page outline, copy blocks, design notes, implementation checklist, and launch QA.",
      schedule: "",
      author: "demo-operator",
      sourceLabel: "Demo Mode: Landing page launch kit"
    }
  },
  {
    id: "repo-triage",
    title: "Repo triage report",
    audience: "Developer / maintainer",
    complexity: "Intermediate",
    timeEstimate: "6 min preview",
    forRoles: ["developer", "enterprise"],
    outcome:
      "A prioritized repo improvement report with likely risks, PR slices, validation commands, and rollback notes.",
    prompt:
      "Analyze a repo and identify the top usability, reliability, test, and architecture improvements to tackle first.",
    sampleInputs: [
      "Scope: frontend and engine code",
      "Output: ranked backlog with file evidence",
      "Constraint: plan-only, no code writes",
      "Review: human approves PR slices"
    ],
    runSteps: [
      {
        id: "scan",
        title: "Scanned the project shape",
        description: "Grouped likely surfaces by frontend, engine, docs, tests, and deployment.",
        tone: "done"
      },
      {
        id: "rank",
        title: "Ranked improvement slices",
        description: "Converted findings into PR-sized implementation tasks.",
        tone: "done"
      },
      {
        id: "validate",
        title: "Attached validation commands",
        description: "Mapped each slice to lint, tests, build, and smoke checks.",
        tone: "active"
      },
      {
        id: "next",
        title: "Ready for workspace connection",
        description: "Connect a repo workspace before AGENT33 can cite files or create branches.",
        tone: "attention"
      }
    ],
    artifacts: [
      {
        id: "backlog",
        title: "Ranked backlog",
        description: "A sample output for technical users.",
        contents: [
          "1. Add first-run demo mode before requiring credentials.",
          "2. Unify provider setup and tool connection health.",
          "3. Add artifact views for every workflow result."
        ]
      },
      {
        id: "validation",
        title: "Validation plan",
        description: "Commands users expect before trusting changes.",
        contents: ["npm run lint", "npm run build", "focused feature tests", "Docker smoke test"]
      }
    ],
    starterDraft: {
      id: "demo-repo-triage",
      name: "repo-triage-demo",
      goal:
        "Analyze a repository and produce prioritized usability, reliability, test, and architecture improvement slices with validation commands.",
      kind: "research",
      output: "Ranked findings, file evidence plan, PR slices, validation commands, and rollback notes.",
      schedule: "",
      author: "demo-operator",
      sourceLabel: "Demo Mode: Repo triage report"
    }
  },
  {
    id: "first-product-idea",
    title: "My first product idea",
    audience: "Non-technical founder",
    complexity: "Beginner",
    timeEstimate: "5 min preview",
    forRoles: ["founder"],
    outcome:
      "A rough idea becomes a simple MVP scope, first-week build plan, success checks, and risk notes.",
    prompt:
      "Turn my idea for a simple client portal into a small first version that I can explain to a developer.",
    sampleInputs: [
      "Idea: client portal for intake forms and project updates",
      "Users: owner, client, and project assistant",
      "Must-have: login, forms, status updates, file links",
      "Safety: plan and review before code generation"
    ],
    runSteps: [
      {
        id: "plain-goal",
        title: "Translated the idea",
        description: "Changed the rough request into users, jobs to be done, and first useful outcome.",
        tone: "done"
      },
      {
        id: "mvp",
        title: "Scoped the first version",
        description: "Separated must-have features from later improvements so the project can start small.",
        tone: "done"
      },
      {
        id: "tasks",
        title: "Prepared first-week tasks",
        description: "Grouped the work into setup, screens, data, permissions, and review checkpoints.",
        tone: "active"
      },
      {
        id: "next",
        title: "Waiting for connected workspace",
        description: "Connect a model and repo before AGENT33 turns this plan into implementation steps.",
        tone: "attention"
      }
    ],
    artifacts: [
      {
        id: "brief",
        title: "MVP brief",
        description: "A beginner-readable product summary.",
        contents: [
          "Problem: clients do not know what is needed next.",
          "First version: intake forms, project status, and file links.",
          "Success: owner can onboard one client without email back-and-forth."
        ]
      },
      {
        id: "scope",
        title: "First-version scope",
        description: "A focused scope that avoids overbuilding.",
        contents: ["Login and client list", "Reusable intake form", "Project status timeline", "Admin review before sharing"]
      },
      {
        id: "week-one",
        title: "First-week tasks",
        description: "Concrete work items that can become a real workflow draft.",
        contents: ["Choose starter stack", "Create page map", "Define client/project data", "Add acceptance checks"]
      }
    ],
    starterDraft: {
      id: "demo-first-product-idea",
      name: "first-product-idea-demo",
      goal:
        "Turn a rough client portal idea into a clear MVP brief, first-version scope, first-week build tasks, and review checkpoints.",
      kind: "automation-loop",
      output: "MVP brief, page map, first-week implementation tasks, assumptions, and acceptance checks.",
      schedule: "",
      author: "demo-operator",
      sourceLabel: "Demo Mode: My first product idea"
    }
  },
  {
    id: "customer-export-report",
    title: "Customer export report",
    audience: "Small-business operator",
    complexity: "Beginner",
    timeEstimate: "4 min preview",
    forRoles: ["agency", "operator"],
    outcome:
      "A messy customer export becomes a clean weekly report plan with segments, checks, and follow-up actions.",
    prompt:
      "Help me turn a customer CSV export into a weekly report that shows churn risk and follow-up priorities.",
    sampleInputs: [
      "Source: CSV from billing or CRM",
      "Audience: owner and customer success lead",
      "Must-have: churn risk, overdue follow-ups, top accounts",
      "Safety: no customer emails generated without review"
    ],
    runSteps: [
      {
        id: "columns",
        title: "Mapped the export",
        description: "Identified likely columns, missing fields, and assumptions that need confirmation.",
        tone: "done"
      },
      {
        id: "segments",
        title: "Designed simple segments",
        description: "Grouped customers by renewal risk, activity level, and follow-up urgency.",
        tone: "done"
      },
      {
        id: "report",
        title: "Drafted report sections",
        description: "Prepared a weekly summary, risk table, and review checklist for the operator.",
        tone: "active"
      },
      {
        id: "next",
        title: "Ready for real data setup",
        description: "Connect a workspace before AGENT33 can inspect an actual export or create files.",
        tone: "attention"
      }
    ],
    artifacts: [
      {
        id: "report-outline",
        title: "Report outline",
        description: "A report structure for non-technical teams.",
        contents: ["Weekly summary", "Customers needing action", "Renewal risk watchlist", "Data quality warnings"]
      },
      {
        id: "checks",
        title: "Data checks",
        description: "Simple guardrails before trusting the report.",
        contents: ["Missing renewal date", "Duplicate customer", "No recent activity", "Unclear account owner"]
      },
      {
        id: "actions",
        title: "Follow-up actions",
        description: "Useful next steps after the report is reviewed.",
        contents: ["Confirm high-risk accounts", "Assign owner follow-ups", "Draft review notes", "Schedule next export"]
      }
    ],
    starterDraft: {
      id: "demo-customer-export-report",
      name: "customer-export-report-demo",
      goal:
        "Create a weekly customer export report plan with churn-risk segments, data quality checks, follow-up actions, and review gates.",
      kind: "research",
      output: "Report outline, segmentation rules, data checks, follow-up checklist, and validation steps.",
      schedule: "",
      author: "demo-operator",
      sourceLabel: "Demo Mode: Customer export report"
    }
  },
  {
    id: "team-meeting-bot",
    title: "Team meeting bot",
    audience: "Team lead / operations",
    complexity: "Beginner",
    timeEstimate: "5 min preview",
    forRoles: ["developer", "agency", "enterprise", "operator"],
    outcome:
      "A meeting-notes helper plan with agenda capture, action items, owners, reminders, and approval rules.",
    prompt:
      "Create a meeting helper that turns notes into action items, owners, reminders, and a weekly summary.",
    sampleInputs: [
      "Input: pasted meeting notes",
      "Users: team lead and project owners",
      "Must-have: action items, owners, due dates, summary",
      "Safety: manager reviews messages before sending"
    ],
    runSteps: [
      {
        id: "intake",
        title: "Defined the note flow",
        description: "Mapped where notes come from and who reviews the output.",
        tone: "done"
      },
      {
        id: "extract",
        title: "Planned action extraction",
        description: "Outlined how tasks, owners, dates, blockers, and decisions should be found.",
        tone: "done"
      },
      {
        id: "review",
        title: "Added review gates",
        description: "Required human approval before reminders or summaries are sent.",
        tone: "active"
      },
      {
        id: "next",
        title: "Waiting for provider setup",
        description: "Connect a model before AGENT33 can process real meeting notes.",
        tone: "attention"
      }
    ],
    artifacts: [
      {
        id: "workflow",
        title: "Meeting workflow",
        description: "The plain-language flow from notes to approved follow-up.",
        contents: ["Paste notes", "Extract action items", "Review owners and due dates", "Approve reminders"]
      },
      {
        id: "summary-template",
        title: "Summary template",
        description: "A useful output shape before any model is connected.",
        contents: ["Decisions made", "Action items", "Risks and blockers", "Next meeting prep"]
      },
      {
        id: "safety",
        title: "Safety rules",
        description: "Controls that protect teams from noisy automation.",
        contents: ["No messages sent automatically", "Flag uncertain owners", "Keep raw notes private", "Require final review"]
      }
    ],
    starterDraft: {
      id: "demo-team-meeting-bot",
      name: "team-meeting-bot-demo",
      goal:
        "Design a meeting-notes workflow that extracts action items, owners, reminders, summaries, and human review gates.",
      kind: "automation-loop",
      output: "Workflow plan, action-item template, summary format, safety rules, and setup checklist.",
      schedule: "",
      author: "demo-operator",
      sourceLabel: "Demo Mode: Team meeting bot"
    }
  }
];

export function getDefaultDemoScenario(): DemoScenario {
  if (DEMO_SCENARIOS.length === 0) {
    throw new Error("No demo scenarios are available. At least one is required.");
  }

  return DEMO_SCENARIOS[0];
}

export function findDemoScenario(id: string): DemoScenario {
  return DEMO_SCENARIOS.find((scenario) => scenario.id === id) ?? getDefaultDemoScenario();
}
