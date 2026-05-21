import type {
  ImprovementLoopForm,
  ImprovementLoopPreset,
  ImprovementLoopPresetId,
  LoopWorkflowRequest,
  ResearchLaunchPlan,
  ResearchLauncherId
} from "./types";

export const LOOP_PRESETS: ImprovementLoopPreset[] = [
  {
    id: "competitive-research",
    title: "Competitive research loop",
    summary: "Track agent OS, MCP, workflow UX, and community agent repo changes on a recurring cadence.",
    defaultWorkflowName: "weekly-competitive-agent-scan",
    defaultGoal:
      "Research OpenHands-style agents, Hermes-like agents, MCP ecosystems, agent OS runtimes, and workflow UX changes. Compare them with AGENT-33 and propose concrete product improvements.",
    defaultOutput:
      "Competitive brief with source notes, feature gaps, likely competitor direction, and ranked AGENT-33 improvement proposals.",
    defaultCron: "0 9 * * 1",
    cadenceLabel: "Weekly Monday scan",
    focusAreas: ["agent OS", "MCP servers", "workflow UX", "research loops", "community adoption"]
  },
  {
    id: "platform-improvement",
    title: "Automatic platform improvement loop",
    summary: "Review build health, release quality, operator friction, and roadmap drift before proposing safe fixes.",
    defaultWorkflowName: "weekly-platform-improvement-loop",
    defaultGoal:
      "Review AGENT-33 delivery signals, failing checks, roadmap drift, support friction, and operator outcomes. Propose safe improvement work with tests and rollback notes.",
    defaultOutput:
      "Improvement queue with evidence, severity, suggested owner role, validation plan, and safety notes.",
    defaultCron: "0 10 * * 2",
    cadenceLabel: "Weekly Tuesday review",
    focusAreas: ["build health", "operator friction", "roadmap drift", "test coverage", "safe rollout"]
  },
  {
    id: "operator-ux-review",
    title: "Operator UX review loop",
    summary: "Continuously audit the layman onboarding path, destructive actions, and plain-language workflow affordances.",
    defaultWorkflowName: "weekly-operator-ux-review",
    defaultGoal:
      "Walk the AGENT-33 operator path like a new non-technical user. Identify confusing JSON/API surfaces, risky defaults, unclear decisions, and missing guided actions.",
    defaultOutput:
      "UX findings with before/after recommendations, destructive-use risks, and a ranked implementation queue.",
    defaultCron: "0 11 * * 3",
    cadenceLabel: "Weekly Wednesday UX review",
    focusAreas: ["onboarding", "plain language", "safe defaults", "review flows", "workflow creation"]
  }
];

export const RESEARCH_LAUNCH_PLANS: ResearchLaunchPlan[] = [
  {
    id: "weekly-competitive-scan",
    presetId: "competitive-research",
    title: "Weekly competitive scan",
    summary: "Track agent OS, MCP, workflow UX, and community agent momentum every Monday.",
    workflowName: "weekly-competitive-agent-scan",
    goal:
      "Research OpenHands-style agents, Hermes-like agents, MCP ecosystems, agent OS runtimes, and workflow UX changes. Compare the last six months of movement with AGENT-33 and identify likely competitor direction.",
    output:
      "Operator-ready competitive brief with source notes, feature gap severity, likely competitor direction, and ranked AGENT-33 implementation proposals.",
    schedule: "0 9 * * 1",
    cadenceLabel: "Every Monday at 09:00",
    buttonLabel: "Schedule weekly scan"
  },
  {
    id: "weekly-operator-ux-watch",
    presetId: "operator-ux-review",
    title: "Weekly layman UX watch",
    summary: "Audit the non-technical operator path for confusing or destructive defaults every Wednesday.",
    workflowName: "weekly-operator-ux-watch",
    goal:
      "Walk AGENT-33 like a first-time layman operator. Find JSON/API surfaces, risky actions, unclear choices, missing presets, and places where community agent tools feel easier.",
    output:
      "Ranked UX implementation queue with before/after wording, safe-default recommendations, validation steps, and destructive-use risk notes.",
    schedule: "0 11 * * 3",
    cadenceLabel: "Every Wednesday at 11:00",
    buttonLabel: "Schedule UX watch"
  },
  {
    id: "monthly-agent-os-horizon",
    presetId: "competitive-research",
    title: "Monthly Agent OS horizon scan",
    summary: "Look ahead at containerized agent workspaces, adaptive tools, MCP servers, and agent operating systems.",
    workflowName: "monthly-agent-os-horizon-scan",
    goal:
      "Research emerging agent operating systems, contained Linux agent workspaces, adaptive tool environments, MCP server trends, and tool-use efficiency techniques. Compare them with AGENT-33 Agent OS and propose durable advantages.",
    output:
      "Horizon report with architecture opportunities, toolchain recommendations, adoption risks, and a prioritized AGENT-33 Agent OS roadmap.",
    schedule: "0 10 1 * *",
    cadenceLabel: "First day of each month at 10:00",
    buttonLabel: "Schedule horizon scan"
  }
];

export function getPreset(id: ImprovementLoopPresetId): ImprovementLoopPreset {
  return LOOP_PRESETS.find((preset) => preset.id === id) ?? LOOP_PRESETS[0];
}

export function getResearchLaunchPlan(id: ResearchLauncherId): ResearchLaunchPlan {
  return RESEARCH_LAUNCH_PLANS.find((plan) => plan.id === id) ?? RESEARCH_LAUNCH_PLANS[0];
}

export function slugify(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 64);
}

export function normalizeCron(value: string): string {
  return value.trim().replace(/^cron:\s*/i, "");
}

export function formFromPreset(preset: ImprovementLoopPreset): ImprovementLoopForm {
  return {
    workflowName: preset.defaultWorkflowName,
    goal: preset.defaultGoal,
    output: preset.defaultOutput,
    schedule: preset.defaultCron,
    author: "operator"
  };
}

export function formFromResearchLaunchPlan(plan: ResearchLaunchPlan): ImprovementLoopForm {
  return {
    workflowName: plan.workflowName,
    goal: plan.goal,
    output: plan.output,
    schedule: plan.schedule,
    author: "operator"
  };
}

export function buildLoopWorkflow(
  preset: ImprovementLoopPreset,
  form: ImprovementLoopForm
): LoopWorkflowRequest {
  const name = slugify(form.workflowName) || preset.defaultWorkflowName;
  const goal = form.goal.trim() || preset.defaultGoal;
  const output = form.output.trim() || preset.defaultOutput;
  const schedule = normalizeCron(form.schedule);

  return {
    name,
    version: "1.0.0",
    description: `${preset.title}: ${goal}`.slice(0, 500),
    triggers: {
      manual: true,
      schedule: schedule || null
    },
    inputs: {
      goal: {
        type: "string",
        description: "Plain-language loop goal",
        required: true,
        default: goal
      },
      focus_areas: {
        type: "array",
        description: "Areas the loop should inspect every run",
        required: false,
        default: preset.focusAreas
      },
      expected_output: {
        type: "string",
        description: "Operator-readable output contract",
        required: true,
        default: output
      }
    },
    outputs: {
      summary: {
        type: "string",
        description: output,
        required: true
      },
      recommendations: {
        type: "array",
        description: "Ranked improvement proposals for human review",
        required: true
      }
    },
    steps: [
      {
        id: "scope",
        name: "Scope the recurring loop",
        action: "invoke-agent",
        agent: "planner",
        inputs: {
          goal,
          cadence: preset.cadenceLabel,
          focus_areas: preset.focusAreas
        },
        depends_on: []
      },
      {
        id: "research",
        name: "Collect current evidence",
        action: "invoke-agent",
        agent: "researcher",
        inputs: {
          goal,
          source_requirement: "Use current, attributable evidence and label assumptions.",
          focus_areas: preset.focusAreas
        },
        depends_on: ["scope"]
      },
      {
        id: "compare",
        name: "Compare against AGENT-33",
        action: "invoke-agent",
        agent: "analyst",
        inputs: {
          goal,
          source_step: "research",
          dimensions: ["usability", "safety", "tool coverage", "workflow depth", "competitive advantage"]
        },
        depends_on: ["research"]
      },
      {
        id: "propose",
        name: "Propose safe improvements",
        action: "invoke-agent",
        agent: "planner",
        inputs: {
          goal,
          source_step: "compare",
          output,
          constraints: "No destructive change without approval. Include validation and rollback notes."
        },
        depends_on: ["compare"]
      },
      {
        id: "review",
        name: "Hold for human-safe review",
        action: "validate",
        inputs: {
          criteria:
            "Recommendations are evidence-backed, non-destructive by default, and ready for operator review before implementation."
        },
        depends_on: ["propose"]
      }
    ],
    execution: {
      mode: "dependency-aware",
      continue_on_error: false,
      fail_fast: true,
      dry_run: false
    },
    metadata: {
      author: form.author.trim() || "operator",
      tags: ["operator-loop", "improvement-cycle", preset.id]
    }
  };
}

export function buildScheduleInputs(
  preset: ImprovementLoopPreset,
  form: ImprovementLoopForm
): Record<string, unknown> {
  return {
    goal: form.goal.trim() || preset.defaultGoal,
    focus_areas: preset.focusAreas,
    expected_output: form.output.trim() || preset.defaultOutput,
    cadence: preset.cadenceLabel
  };
}
