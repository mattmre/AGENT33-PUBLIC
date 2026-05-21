import type { OnboardingStatus } from "../onboarding/types";
import type {
  ConnectCard,
  ConnectStatus,
  DoctorCheck,
  DoctorStatusFinding,
  FirstSuccessPath
} from "./types";

const STEP_DATABASE = "OB-01";
const STEP_MODELS = "OB-02";
const STEP_SAFETY = "OB-08";

function findStep(status: OnboardingStatus | null, stepId: string): boolean | null {
  const step = status?.steps.find((item) => item.step_id === stepId);
  return step?.completed ?? null;
}

function statusFromStep(status: OnboardingStatus | null, stepId: string): ConnectStatus {
  const completed = findStep(status, stepId);
  if (completed === true) {
    return "ready";
  }
  if (completed === false) {
    return "attention";
  }
  return "unknown";
}

export function buildConnectCards(hasCredentials: boolean, status: OnboardingStatus | null): ConnectCard[] {
  return [
    {
      id: "engine-access",
      title: "Engine access",
      plainLabel: "Is engine access saved in this browser?",
      status: hasCredentials ? "ready" : "attention",
      detail: hasCredentials
        ? "An operator token or API key is saved for this browser session."
        : "Add an operator token or API key before checking live readiness.",
      impact: "Required before the UI can inspect setup, save provider settings, or run workflows.",
      actionLabel: hasCredentials ? "Review access" : "Connect access",
      target: "setup",
      verification: {
        testAction: "Refresh connection scan with the saved token or API key.",
        healthExplanation: hasCredentials
          ? "Browser access is present; live setup checks can run."
          : "Live health is blocked until access is saved.",
        setupHint: "Start here before testing GitHub, MCP, models, or workflow launch."
      }
    },
    {
      id: "model-provider",
      title: "Model provider",
      plainLabel: "Can AGENT-33 call a model?",
      status: hasCredentials ? statusFromStep(status, STEP_MODELS) : "attention",
      detail: "Connect OpenRouter first, or use a local OpenAI-compatible model path in the next setup round.",
      impact: "Required for real workflow generation, chat, research loops, and agent work.",
      actionLabel: "Open model setup",
      target: "models",
      verification: {
        testAction: "Run model health refresh and confirm at least one provider is ready.",
        healthExplanation: "Model readiness controls whether workflows can generate plans or agent output.",
        setupHint: "Use OpenRouter first for the fastest cloud path, then add local runtimes if needed."
      }
    },
    {
      id: "runtime-memory",
      title: "Runtime and memory",
      plainLabel: "Can agent work keep durable state?",
      status: hasCredentials ? statusFromStep(status, STEP_DATABASE) : "unknown",
      detail: "Checks whether the runtime database and state path are ready for longer agent work.",
      impact: "Important for multi-step work, replay, recovery, and long-running workflows.",
      actionLabel: "Open integrations",
      target: "setup",
      verification: {
        testAction: "Refresh onboarding readiness and confirm the runtime database check.",
        healthExplanation: "Durable state is required for recovery, replay, and future evidence ledger work.",
        setupHint: "Fix runtime storage before starting long-running Agent OS sessions."
      }
    },
    {
      id: "mcp-tools",
      title: "MCP tools and skills",
      plainLabel: "Can AGENT-33 use its tool network?",
      status: "unknown",
      detail: "Use MCP Health to inspect proxy servers, tool discovery, CLI sync, and tool fabric readiness.",
      impact: "Unlocks richer research, code analysis, browser automation, and external workflow tools.",
      actionLabel: "Check MCP health",
      target: "mcp",
      verification: {
        testAction: "Refresh MCP Health and inspect proxy, tool, and CLI sync status.",
        healthExplanation: "Unknown MCP state means tools may be hidden or unavailable at run time.",
        setupHint: "For GitHub-backed workflows, verify the GitHub MCP/tool bridge before launching."
      }
    },
    {
      id: "tool-catalog",
      title: "Tool catalog",
      plainLabel: "Can users see what tools are available?",
      status: "unknown",
      detail: "Browse available tools and schemas before granting more autonomy.",
      impact: "Makes capabilities discoverable without asking users to understand raw imports or JSON schemas.",
      actionLabel: "Browse tools",
      target: "tools",
      verification: {
        testAction: "Open the catalog and confirm expected schemas are visible.",
        healthExplanation: "Tool visibility is the operator-facing proof that connectors are usable.",
        setupHint: "Check GitHub and file/workspace tools before PR-producing workflows."
      }
    },
    {
      id: "safety-approvals",
      title: "Safety and approvals",
      plainLabel: "Will risky work ask before acting?",
      status: hasCredentials ? statusFromStep(status, STEP_SAFETY) : "unknown",
      detail: "Review API protection, approval defaults, and beginner/pro controls before automation runs.",
      impact: "Protects users from destructive operations while keeping productive paths visible.",
      actionLabel: "Open safety",
      target: "safety",
      verification: {
        testAction: "Review approval defaults and confirm risky actions are gated.",
        healthExplanation: "Safety readiness decides whether connector actions can run without surprise.",
        setupHint: "Use PR-first or approval-required modes for GitHub write operations."
      }
    }
  ];
}

export function getConnectScore(cards: ConnectCard[]): string {
  const knownCards = cards.filter((card) => card.status !== "unknown");
  if (knownCards.length === 0) {
    return "Readiness unknown";
  }
  const readyCount = knownCards.filter((card) => card.status === "ready").length;
  return `${readyCount} of ${knownCards.length} known checks ready`;
}

function findCard(cards: ConnectCard[], id: string): ConnectCard | undefined {
  return cards.find((card) => card.id === id);
}

function doctorStatus(card: ConnectCard | undefined): DoctorCheck["status"] {
  if (card?.status === "ready") {
    return "ready";
  }
  if (card?.status === "attention") {
    return "blocked";
  }
  return "inspect";
}

export function buildDoctorChecks(cards: ConnectCard[]): DoctorCheck[] {
  const engineAccess = findCard(cards, "engine-access");
  const modelProvider = findCard(cards, "model-provider");
  const runtimeMemory = findCard(cards, "runtime-memory");
  const mcpTools = findCard(cards, "mcp-tools");
  const safetyApprovals = findCard(cards, "safety-approvals");

  return [
    {
      id: "doctor-access",
      title: "Access and live scan",
      status: doctorStatus(engineAccess),
      diagnosis: engineAccess?.verification.healthExplanation ?? "Browser access has not been checked.",
      remediation:
        engineAccess?.status === "ready"
          ? "Keep the saved access available while testing setup."
          : "Connect engine access before running any first-success check."
    },
    {
      id: "doctor-generation",
      title: "Model generation path",
      status: doctorStatus(modelProvider),
      diagnosis: modelProvider?.verification.healthExplanation ?? "Model readiness has not been checked.",
      remediation:
        modelProvider?.status === "ready"
          ? "Use the ready provider for the safe first-success task."
          : "Open model setup and finish one provider health check before launching generated work."
    },
    {
      id: "doctor-recovery",
      title: "Recovery and evidence path",
      status: runtimeMemory?.status === "ready" ? "ready" : "inspect",
      diagnosis: runtimeMemory?.verification.healthExplanation ?? "Durable runtime state has not been checked.",
      remediation:
        runtimeMemory?.status === "ready"
          ? "Result pages can attach proof from saved run state."
          : "Refresh onboarding readiness and inspect runtime storage before long-running work."
    },
    {
      id: "doctor-tools",
      title: "Tool and safety path",
      status:
        mcpTools?.status === "attention" || safetyApprovals?.status === "attention"
          ? "blocked"
          : mcpTools?.status === "ready" && safetyApprovals?.status === "ready"
            ? "ready"
            : "inspect",
      diagnosis: "Tool access and approval posture decide whether connector actions can run safely.",
      remediation:
        safetyApprovals?.status === "attention"
          ? "Review approval defaults before allowing connector actions."
          : "Inspect MCP Health and tool catalog visibility before PR-producing workflows."
    }
  ];
}

export function buildFirstSuccessPath(cards: ConnectCard[]): FirstSuccessPath {
  const checks = buildDoctorChecks(cards);
  const blockingCheck = checks.find((check) => check.status === "blocked");
  const inspectCount = checks.filter((check) => check.status === "inspect").length;
  const ready = blockingCheck === undefined && inspectCount === 0;

  if (ready) {
    return {
      title: "Run a safe first-success workflow",
      ready: true,
      steps: [
        "Open Workflow Starter with the verified model provider.",
        "Launch a read-only planning task that produces one result page.",
        "Confirm the result page shows a proof item from the run ledger."
      ],
      proof: "Success is a completed run with a result page and at least one evidence item."
    };
  }

  return {
    title: blockingCheck ? `Fix ${blockingCheck.title.toLowerCase()} first` : "Inspect unknown setup checks first",
    ready: false,
    steps: [
      blockingCheck?.remediation ?? "Refresh connection scan, MCP Health, and onboarding readiness.",
      "Re-run the Doctor Center checks after the setup surface reports ready.",
      "Then launch the safe first-success workflow from Workflow Starter."
    ],
    proof: "Do not treat setup as complete until the first-success task has durable proof."
  };
}

function liveDoctorStatus(finding: DoctorStatusFinding): DoctorCheck["status"] {
  if (finding.severity === "ok") {
    return "ready";
  }
  if (finding.severity === "error") {
    return "blocked";
  }
  return "inspect";
}

export function buildLiveDoctorChecks(findings: DoctorStatusFinding[] | null): DoctorCheck[] {
  if (findings === null) {
    return [];
  }
  return findings.map((finding) => ({
    id: `live-${finding.id}`,
    title: `${finding.category} check`,
    status: liveDoctorStatus(finding),
    diagnosis: finding.message,
    remediation: finding.fix_action,
    owner: finding.owner,
    evidenceRefs: finding.evidence_refs
  }));
}
