export const APP_TAB_IDS = [
  "guide",
  "start",
  "demo",
  "connect",
  "models",
  "setup",
  "operations",
  "review",
  "safety",
  "policy",
  "chat",
  "voice",
  "catalog",
  "starter",
  "skills",
  "resources",
  "fabric",
  "tools",
  "builder",
  "spawner",
  "loops",
  "outcomes",
  "analytics",
  "impact",
  "marketplace",
  "plugins",
  "mcp",
  "advanced",
  "design-kit",
  "planning",
  "support",
  "sandboxing"
] as const;

export type AppTab = (typeof APP_TAB_IDS)[number];

export interface AppTabConfig {
  readonly id: AppTab;
  readonly label: string;
  readonly description: string;
}

export interface AppTabGroup {
  readonly id: string;
  readonly label: string;
  readonly description: string;
  readonly tabs: ReadonlyArray<AppTabConfig>;
}

export interface AppPrimaryNavItem {
  readonly id: AppTab;
  readonly description: string;
}

export const DEFAULT_APP_TAB: AppTab = "guide";
export const ROLE_SELECTED_DEFAULT_APP_TAB: AppTab = "start";

export const APP_TAB_GROUPS: ReadonlyArray<AppTabGroup> = [
  {
    id: "launch",
    label: "Launch",
    description: "Set role, orient the operator, and choose the safest first move.",
    tabs: [
      {
        id: "guide",
        label: "Guide / Intake",
        description: "State your role, objective, and what kind of help you need first."
      },
      {
        id: "start",
        label: "Home / Next Step",
        description: "Return to the launchpad and resume the most likely next action."
      },
      {
        id: "demo",
        label: "Demo Mode",
        description: "Preview a guided run before touching live workflows or approvals."
      }
    ]
  },
  {
    id: "connect",
    label: "Connect",
    description: "Prepare models, integrations, and credentials before you launch work.",
    tabs: [
      {
        id: "connect",
        label: "Connect Models",
        description: "See the overall connection center for providers, runtimes, and readiness."
      },
      {
        id: "models",
        label: "Models",
        description: "Choose a default model, test it, and prefer local or free paths when possible."
      },
      {
        id: "setup",
        label: "Integrations",
        description: "Add tokens, messaging, and service-level access needed by the cockpit."
      }
    ]
  },
  {
    id: "operate",
    label: "Operate",
    description: "Run sessions, review decisions, and work inside the live operator surfaces.",
    tabs: [
      {
        id: "operations",
        label: "Sessions & Runs",
        description: "Track active work, current blockers, and reviewable artifacts."
      },
      {
        id: "review",
        label: "Review Queue",
        description: "Process candidate assets and triage handoff items that need judgment."
      },
      {
        id: "safety",
        label: "Safety & Approvals",
        description: "Approve guarded actions, inspect risk posture, and review protected routes."
      },
      {
        id: "policy",
        label: "Policy",
        description: "Inspect active authority, completion gates, and collaboration modes."
      },
      {
        id: "chat",
        label: "Chat",
        description: "Work directly with the agent runtime in the core text console."
      },
      {
        id: "voice",
        label: "Voice",
        description: "Switch to live voice interaction for guided conversations and handoffs."
      }
    ]
  },
  {
    id: "build",
    label: "Build",
    description: "Choose workflows, assemble capabilities, and create reusable systems.",
    tabs: [
      {
        id: "catalog",
        label: "Workflow Catalog",
        description: "Start from prebuilt outcome systems instead of composing raw tools."
      },
      {
        id: "starter",
        label: "Workflows",
        description: "Launch an outcome path with guided setup and runtime checks."
      },
      {
        id: "skills",
        label: "Skill Wizard",
        description: "Author or install skills without dropping into the raw control plane."
      },
      {
        id: "resources",
        label: "Resources",
        description: "Browse packs, plugins, skills, workflows, prompts, policies, evals, and datasets together."
      },
      {
        id: "fabric",
        label: "Tool Fabric",
        description: "Discover tools, skills, and workflows that fit the current objective."
      },
      {
        id: "tools",
        label: "Tools",
        description: "Inspect the live tool catalog, schemas, and callable surfaces."
      },
      {
        id: "builder",
        label: "Builder",
        description: "Compose an agent with capabilities and preview the final definition."
      },
      {
        id: "spawner",
        label: "Spawner",
        description: "Design sub-agent delegation flows and parent-child execution patterns."
      }
    ]
  },
  {
    id: "improve",
    label: "Improve",
    description: "Evaluate outcomes, measure impact, and close the loop on quality.",
    tabs: [
      {
        id: "loops",
        label: "Improvement Loops",
        description: "Schedule recurring inspection, remediation, and upgrade runs."
      },
      {
        id: "outcomes",
        label: "Outcomes",
        description: "Review the outcome ledger, trend lines, and decline-triggered actions."
      },
      {
        id: "analytics",
        label: "Analytics",
        description: "Inspect usage, throughput, and session-level performance patterns."
      },
      {
        id: "impact",
        label: "Impact",
        description: "Measure ROI, effect size, and whether the system is paying for itself."
      },
      {
        id: "marketplace",
        label: "Marketplace",
        description: "Browse packs and outcome systems that can extend the current workspace."
      }
    ]
  },
  {
    id: "admin",
    label: "Admin",
    description: "Inspect extension health, plugin lifecycle, and quarantined raw controls.",
    tabs: [
      {
        id: "plugins",
        label: "Plugins",
        description: "Manage plugin and extension lifecycle, diagnostics, tenant config, and events."
      },
      {
        id: "mcp",
        label: "MCP Health",
        description: "Check connected tool servers, sync posture, and discovery status."
      },
      {
        id: "advanced",
        label: "Advanced",
        description: "Enter the raw control plane only for edge cases and deep operator work."
      },
      {
        id: "design-kit",
        label: "Design Kit",
        description: "Inspect reusable AGENT-33 design-system surfaces and cockpit references."
      }
    ]
  },
  {
    id: "workspace",
    label: "Workspace",
    description: "Plan work, run sandboxed steps, and access operator support.",
    tabs: [
      {
        id: "planning",
        label: "Planning",
        description: "Compose multi-step plans and break down goals into agent-executable tasks."
      },
      {
        id: "support",
        label: "Support",
        description: "Access guided troubleshooting, escalation paths, and operator documentation."
      },
      {
        id: "sandboxing",
        label: "Sandboxing",
        description: "Run code and agent steps in an isolated environment before promoting to live workflows."
      }
    ]
  }
];

export const APP_PRIMARY_NAV_ITEMS: ReadonlyArray<AppPrimaryNavItem> = [
  {
    id: "guide",
    description: "Tell AGENT-33 what you want and get the safest next step."
  },
  {
    id: "start",
    description: "Beginner launchpad for setup, demo runs, and common outcomes."
  },
  {
    id: "operations",
    description: "Watch active work, recent results, and operator handoffs."
  },
  {
    id: "starter",
    description: "Pick a prebuilt strategy instead of assembling tools manually."
  },
  {
    id: "models",
    description: "Set up providers, local models, and readiness checks."
  },
  {
    id: "safety",
    description: "Review risks, decisions, and protected actions before work runs."
  }
];

const APP_PRIMARY_TAB_ID_SET = new Set<AppTab>(APP_PRIMARY_NAV_ITEMS.map((item) => item.id));

export const APP_SECONDARY_NAV_GROUPS: ReadonlyArray<AppTabGroup> = APP_TAB_GROUPS.map((group) => ({
  ...group,
  tabs: group.tabs.filter((tab) => !APP_PRIMARY_TAB_ID_SET.has(tab.id))
})).filter((group) => group.tabs.length > 0);

const APP_TAB_ID_SET = new Set<string>(APP_TAB_IDS);
const APP_TAB_CONFIG_MAP = new Map<AppTab, AppTabConfig>(
  APP_TAB_GROUPS.flatMap((group) => group.tabs.map((tab) => [tab.id, tab] as const))
);
const APP_TAB_GROUP_MAP = new Map<AppTab, AppTabGroup>(
  APP_TAB_GROUPS.flatMap((group) => group.tabs.map((tab) => [tab.id, group] as const))
);

export function isAppTab(value: string): value is AppTab {
  return APP_TAB_ID_SET.has(value);
}

export function getAppTabLabel(tabId: AppTab): string {
  return APP_TAB_CONFIG_MAP.get(tabId)?.label ?? tabId;
}

export function getAppTabDescription(tabId: AppTab): string {
  return APP_TAB_CONFIG_MAP.get(tabId)?.description ?? "";
}

export function getAppTabGroup(tabId: AppTab): AppTabGroup | null {
  return APP_TAB_GROUP_MAP.get(tabId) ?? null;
}

export function isPrimaryAppTab(tabId: AppTab): boolean {
  return APP_PRIMARY_TAB_ID_SET.has(tabId);
}

export function isSecondaryAppTab(tabId: AppTab): boolean {
  return !APP_PRIMARY_TAB_ID_SET.has(tabId);
}
