import { useEffect, useMemo, useState } from "react";

import type { ApiResult } from "../../types";
import type { OnboardingStatus } from "../onboarding/types";
import { openOperationsRecoveryPanel } from "../operations-hub/recoveryNavigation";
import {
  asSkillDiscoveryResponse,
  asWorkflowCreateResponse,
  asWorkflowResolutionResponse,
  asWorkflowStarterModelHealth,
  asWorkflowStarterOnboardingStatus,
  asWorkflowStarterSessionSummaries,
  createWorkflow,
  discoverSkills,
  fetchWorkflowStarterIncompleteSessions,
  fetchWorkflowStarterModelHealth,
  fetchWorkflowStarterReadiness,
  resolveWorkflows
} from "./api";
import type {
  SkillDiscoveryMatch,
  StarterKind,
  WorkflowStarterDraft,
  WorkflowStarterModelHealth,
  WorkflowStarterReadinessStatus,
  WorkflowStarterSessionSummary,
  WorkflowCreateResponse,
  WorkflowResolutionMatch,
  WorkflowStarterRequest
} from "./types";

interface WorkflowStarterPanelProps {
  token: string;
  apiKey: string;
  onOpenSetup: () => void;
  onOpenSpawner: () => void;
  onOpenOperations: () => void;
  initialDraft?: WorkflowStarterDraft | null;
  onResult: (label: string, result: ApiResult) => void;
}

interface StarterForm {
  name: string;
  goal: string;
  kind: StarterKind;
  output: string;
  schedule: string;
  author: string;
}

interface LaunchReadinessCard {
  id: string;
  label: string;
  status: WorkflowStarterReadinessStatus;
  detail: string;
  actionLabel: string;
  onAction: () => void;
}

const DEFAULT_FORM: StarterForm = {
  name: "",
  goal: "",
  kind: "research",
  output: "Brief summary with sources, decisions, risks, and next actions",
  schedule: "",
  author: "operator"
};

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isApiResultLike(value: unknown): value is ApiResult {
  return (
    isObject(value) &&
    typeof value.status === "number" &&
    typeof value.ok === "boolean" &&
    "data" in value
  );
}

function slugify(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 64);
}

function titleForKind(kind: StarterKind): string {
  switch (kind) {
    case "improvement-loop":
      return "Automatic improvement loop";
    case "automation-loop":
      return "Repeatable automation loop";
    default:
      return "Research workflow";
  }
}

function buildSteps(form: StarterForm): WorkflowStarterRequest["steps"] {
  if (form.kind === "improvement-loop") {
    return [
      {
        id: "observe",
        name: "Collect signals",
        action: "invoke-agent",
        agent: "researcher",
        inputs: { goal: form.goal, output: form.output },
        depends_on: []
      },
      {
        id: "propose",
        name: "Propose improvements",
        action: "invoke-agent",
        agent: "planner",
        inputs: { goal: form.goal, source_step: "observe" },
        depends_on: ["observe"]
      },
      {
        id: "review",
        name: "Human-safe review",
        action: "validate",
        inputs: { criteria: "No destructive changes without approval; summarize rollback path." },
        depends_on: ["propose"]
      }
    ];
  }
  if (form.kind === "automation-loop") {
    return [
      {
        id: "plan",
        name: "Plan the run",
        action: "invoke-agent",
        agent: "planner",
        inputs: { goal: form.goal },
        depends_on: []
      },
      {
        id: "execute",
        name: "Execute supervised work",
        action: "invoke-agent",
        agent: "operator",
        inputs: { goal: form.goal, output: form.output },
        depends_on: ["plan"]
      },
      {
        id: "validate",
        name: "Validate and report",
        action: "validate",
        inputs: { criteria: form.output },
        depends_on: ["execute"]
      }
    ];
  }
  return [
    {
      id: "scope",
      name: "Clarify scope",
      action: "invoke-agent",
      agent: "planner",
      inputs: { goal: form.goal },
      depends_on: []
    },
    {
      id: "research",
      name: "Research and compare sources",
      action: "invoke-agent",
      agent: "researcher",
      inputs: { goal: form.goal, source_requirement: "current, attributable sources" },
      depends_on: ["scope"]
    },
    {
      id: "synthesize",
      name: "Synthesize answer",
      action: "invoke-agent",
      agent: "writer",
      inputs: { output: form.output },
      depends_on: ["research"]
    },
    {
      id: "review",
      name: "Review before handoff",
      action: "validate",
      inputs: { criteria: "Sources cited, assumptions labeled, next steps clear." },
      depends_on: ["synthesize"]
    }
  ];
}

function packContextLabel(draft: WorkflowStarterDraft | null): string {
  return draft?.sourcePack ? ` from ${draft.sourcePack}` : "";
}

function sourceTags(draft: WorkflowStarterDraft | null): string[] {
  if (!draft) {
    return [];
  }

  return [
    draft.sourcePack ? `pack:${draft.sourcePack}` : null,
    draft.sourcePackVersion ? `pack-version:${draft.sourcePackVersion}` : null,
    draft.sourceOutcomeId ? `outcome:${draft.sourceOutcomeId}` : null
  ].filter((tag): tag is string => tag !== null);
}

function buildWorkflow(
  form: StarterForm,
  draft: WorkflowStarterDraft | null = null
): WorkflowStarterRequest {
  const fallbackName = `${form.kind}-${Date.now().toString(36)}`;
  const name = slugify(form.name) || slugify(form.goal) || fallbackName;
  return {
    name,
    version: "1.0.0",
    description: `${titleForKind(form.kind)}: ${form.goal}`.slice(0, 500),
    triggers: {
      manual: true,
      schedule: form.schedule.trim() || null
    },
    inputs: {
      goal: {
        type: "string",
        description: "Plain-language operator goal",
        required: true,
        default: form.goal
      }
    },
    outputs: {
      summary: {
        type: "string",
        description: form.output,
        required: true
      }
    },
    steps: buildSteps(form),
    execution: {
      mode: "dependency-aware",
      continue_on_error: false,
      fail_fast: true,
      dry_run: false
    },
    metadata: {
      author: form.author.trim() || "operator",
      tags: ["operator-starter", form.kind, ...sourceTags(draft)]
    }
  };
}

function findPendingOnboardingStep(status: OnboardingStatus | null): string {
  const nextStep = status?.steps.find((step) => !step.completed);
  return nextStep?.title ?? "";
}

function findOnboardingStepCompleted(status: OnboardingStatus | null, stepId: string): boolean | null {
  const step = status?.steps.find((item) => item.step_id === stepId);
  return step?.completed ?? null;
}

function selectResumeCandidate(
  sessions: WorkflowStarterSessionSummary[] | null
): WorkflowStarterSessionSummary | null {
  if (sessions === null || sessions.length === 0) {
    return null;
  }
  return [...sessions].sort((left, right) => {
    const leftAt = Date.parse(left.updated_at);
    const rightAt = Date.parse(right.updated_at);
    return Number.isFinite(rightAt) && Number.isFinite(leftAt) ? rightAt - leftAt : 0;
  })[0] ?? null;
}

function formatSessionTimestamp(value: string): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) {
    return value;
  }
  return new Date(timestamp).toLocaleString();
}

function statusLabel(status: WorkflowStarterReadinessStatus): string {
  switch (status) {
    case "ready":
      return "Ready";
    case "attention":
      return "Needs attention";
    default:
      return "Unknown";
  }
}

function getRecommendedRuntimeLabel(
  onboardingStatus: OnboardingStatus | null,
  modelHealth: WorkflowStarterModelHealth | null,
  readinessLoaded: boolean
): string {
  if (!readinessLoaded) {
    return "Refresh launch checks to inspect a live runtime.";
  }
  const providerReady = findOnboardingStepCompleted(onboardingStatus, "OB-02");
  if (modelHealth === null) {
    return providerReady === true
      ? "A model provider is registered. Refresh again for local runtime detail."
      : "Runtime readiness is unavailable.";
  }
  const readyProvider = modelHealth.providers.find((provider) => provider.state === "available");
  if (readyProvider) {
    return `${readyProvider.label} is ready with ${readyProvider.modelCount} detected ${
      readyProvider.modelCount === 1 ? "model" : "models"
    }.`;
  }
  return providerReady === true ? `A model provider is registered. ${modelHealth.summary}` : modelHealth.summary;
}

function getResumeSummary(
  sessions: WorkflowStarterSessionSummary[] | null,
  readinessLoaded: boolean
): string {
  if (!readinessLoaded) {
    return "Refresh launch checks to see whether a suspended or crashed run should be resumed first.";
  }
  if (sessions === null) {
    return "Resume status is unavailable.";
  }
  if (sessions.length === 0) {
    return "No suspended or crashed session is waiting for recovery.";
  }
  const candidate = selectResumeCandidate(sessions);
  if (candidate === null) {
    return "A resumable session exists, but the latest record could not be summarized.";
  }
  const purpose = candidate.purpose.trim() || candidate.session_id;
  return `${purpose} is ${candidate.status} and can be resumed from the Session recovery panel in Operations.`;
}

function buildLaunchReadinessCards(params: {
  readinessLoaded: boolean;
  onboardingStatus: OnboardingStatus | null;
  modelHealth: WorkflowStarterModelHealth | null;
  incompleteSessions: WorkflowStarterSessionSummary[] | null;
  onOpenSetup: () => void;
  onOpenOperations: () => void;
  onOpenRecovery: () => void;
}): LaunchReadinessCard[] {
  const {
    readinessLoaded,
    onboardingStatus,
    modelHealth,
    incompleteSessions,
    onOpenSetup,
    onOpenOperations,
    onOpenRecovery
  } = params;
  const resumeCandidate = selectResumeCandidate(incompleteSessions);
  const providerReady = findOnboardingStepCompleted(onboardingStatus, "OB-02");
  const localModelReady = modelHealth?.overallState === "ready" && modelHealth.readyProviderCount > 0;
  const modelReady = providerReady === true || localModelReady;
  const onboardingReady = onboardingStatus?.overall_complete === true;
  const nextOnboardingFix = findPendingOnboardingStep(onboardingStatus);

  const onboardingCard: LaunchReadinessCard = {
    id: "operator-readiness",
    label: "Operator and workspace readiness",
    status: !readinessLoaded
      ? "unknown"
      : onboardingStatus === null
        ? "unknown"
        : onboardingReady
          ? "ready"
          : "attention",
    detail: !readinessLoaded
      ? "Refresh launch checks to inspect the live onboarding checklist."
      : onboardingStatus === null
        ? "Onboarding status could not be loaded from the engine."
        : onboardingReady
          ? `${onboardingStatus.completed_count} of ${onboardingStatus.total_count} onboarding checks are complete.`
          : `${onboardingStatus.completed_count} of ${onboardingStatus.total_count} onboarding checks are complete. Next fix: ${nextOnboardingFix || "review setup guidance"}.`,
    actionLabel: onboardingReady ? "Review setup" : "Open setup",
    onAction: onOpenSetup
  };

  const modelCard: LaunchReadinessCard = {
    id: "model-readiness",
    label: "Model readiness",
    status: !readinessLoaded
      ? "unknown"
      : modelReady
          ? "ready"
        : providerReady === false
          ? "attention"
          : modelHealth === null
            ? "unknown"
          : "attention",
    detail: !readinessLoaded
      ? "Refresh launch checks to inspect local and provider-backed model paths."
      : modelHealth === null
        ? providerReady === true
          ? "At least one provider is registered. Refresh again if you want the local runtime summary."
          : "Model health could not be loaded from the engine."
        : providerReady === true
          ? `A model provider is registered. ${modelHealth.summary}`
          : modelHealth.summary,
    actionLabel: modelReady ? "Review setup" : "Open setup",
    onAction: onOpenSetup
  };

  const hostExecutionCard: LaunchReadinessCard = {
    id: "host-execution",
    label: "Host execution posture",
    status: !readinessLoaded
      ? "unknown"
      : onboardingStatus === null
        ? "unknown"
        : resumeCandidate !== null || !modelReady || !onboardingReady
          ? "attention"
          : "ready",
    detail: !readinessLoaded
      ? "Host execution stays opt-in until you refresh live launch checks."
      : onboardingStatus === null
        ? "Host execution remains opt-in until launch prerequisites can be confirmed."
        : resumeCandidate !== null
          ? "Finish or resume the existing incomplete run before starting another host-backed loop."
          : !modelReady
            ? "Host execution remains opt-in until a runnable model path is available."
            : !onboardingReady
              ? "Host execution remains opt-in until core onboarding checks are complete."
              : "Core prerequisites are ready. Host execution is still operator-triggered and review-gated.",
    actionLabel: "Open operations hub",
    onAction: onOpenOperations
  };

  const resumeCard: LaunchReadinessCard = {
    id: "resume-path",
    label: "Resume prior work",
    status: !readinessLoaded
      ? "unknown"
      : incompleteSessions === null
        ? "unknown"
        : incompleteSessions.length > 0
          ? "attention"
          : "ready",
    detail: !readinessLoaded
      ? "Refresh launch checks to see whether a suspended or crashed session should be resumed."
      : incompleteSessions === null
        ? "Session recovery status could not be loaded from the engine."
        : incompleteSessions.length === 0
          ? "No suspended or crashed session is waiting for recovery."
          : `${resumeCandidate?.purpose.trim() || resumeCandidate?.session_id || "A prior session"} is ${resumeCandidate?.status || "recoverable"} and was last updated ${resumeCandidate ? formatSessionTimestamp(resumeCandidate.updated_at) : "recently"}. Open the recovery panel before starting a new run.`,
    actionLabel: incompleteSessions !== null && incompleteSessions.length > 0 ? "Open recovery panel" : "Review operations",
    onAction: incompleteSessions !== null && incompleteSessions.length > 0 ? onOpenRecovery : onOpenOperations
  };

  return [onboardingCard, modelCard, hostExecutionCard, resumeCard];
}

function getLaunchBadgeLabel(cards: LaunchReadinessCard[], readinessLoaded: boolean): string {
  if (!readinessLoaded) {
    return "Live launch checks available";
  }
  const readyCount = cards.filter((card) => card.status === "ready").length;
  return `${readyCount} of ${cards.length} checks ready`;
}

const LIFECYCLE_LABELS = [
  ["brief", "Brief"],
  ["plan", "Plan"],
  ["preview", "Preview"],
  ["handoff", "Execution handoff"]
] as const;

export function WorkflowStarterPanel({
  token,
  apiKey,
  onOpenSetup,
  onOpenSpawner,
  onOpenOperations,
  initialDraft = null,
  onResult
}: WorkflowStarterPanelProps): JSX.Element {
  const [form, setForm] = useState<StarterForm>(DEFAULT_FORM);
  const [workflowPreview, setWorkflowPreview] = useState<WorkflowStarterRequest | null>(null);
  const [createdWorkflow, setCreatedWorkflow] = useState<WorkflowCreateResponse | null>(null);
  const [workflowMatches, setWorkflowMatches] = useState<WorkflowResolutionMatch[]>([]);
  const [skillMatches, setSkillMatches] = useState<SkillDiscoveryMatch[]>([]);
  const [loadingAction, setLoadingAction] = useState<"recommend" | "create" | null>(null);
  const [loadingReadiness, setLoadingReadiness] = useState(false);
  const [error, setError] = useState("");
  const [readinessError, setReadinessError] = useState("");
  const [readinessLoaded, setReadinessLoaded] = useState(false);
  const [onboardingStatus, setOnboardingStatus] = useState<OnboardingStatus | null>(null);
  const [modelHealth, setModelHealth] = useState<WorkflowStarterModelHealth | null>(null);
  const [incompleteSessions, setIncompleteSessions] = useState<WorkflowStarterSessionSummary[] | null>(null);

  const hasCredentials = token.trim() !== "" || apiKey.trim() !== "";
  const canBuild = useMemo(() => form.goal.trim() !== "", [form.goal]);
  const resumeCandidate = useMemo(
    () => selectResumeCandidate(incompleteSessions),
    [incompleteSessions]
  );

  useEffect(() => {
    if (initialDraft === null) {
      setForm(DEFAULT_FORM);
      setWorkflowPreview(null);
      setCreatedWorkflow(null);
      setWorkflowMatches([]);
      setSkillMatches([]);
      setError("");
      return;
    }
    setForm({
      name: initialDraft.name,
      goal: initialDraft.goal,
      kind: initialDraft.kind,
      output: initialDraft.output,
      schedule: initialDraft.schedule ?? "",
      author: initialDraft.author ?? "operator"
    });
    setWorkflowPreview(null);
    setCreatedWorkflow(null);
    setWorkflowMatches([]);
    setSkillMatches([]);
    setError("");
  }, [initialDraft]);

  function updateField<K extends keyof StarterForm>(key: K, value: StarterForm[K]): void {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function refreshLaunchReadiness(): Promise<void> {
    if (!hasCredentials) {
      return;
    }

    setLoadingReadiness(true);
    setReadinessError("");
    try {
      const [onboardingResult, modelHealthResult, incompleteSessionsResult] =
        await Promise.allSettled([
          fetchWorkflowStarterReadiness(token, apiKey),
          fetchWorkflowStarterModelHealth(token, apiKey),
          fetchWorkflowStarterIncompleteSessions(token, apiKey)
        ]);

      const onboardingPayload =
        onboardingResult.status === "fulfilled" && isApiResultLike(onboardingResult.value)
          ? onboardingResult.value
          : null;
      const modelPayload =
        modelHealthResult.status === "fulfilled" && isApiResultLike(modelHealthResult.value)
          ? modelHealthResult.value
          : null;
      const incompletePayload =
        incompleteSessionsResult.status === "fulfilled" && isApiResultLike(incompleteSessionsResult.value)
          ? incompleteSessionsResult.value
          : null;

      if (onboardingPayload !== null) {
        onResult("Workflow Starter - Onboarding Readiness", onboardingPayload);
      }
      if (modelPayload !== null) {
        onResult("Workflow Starter - Model Health", modelPayload);
      }
      if (incompletePayload !== null) {
        onResult("Workflow Starter - Incomplete Sessions", incompletePayload);
      }

      const nextOnboardingStatus =
        onboardingPayload?.ok === true
          ? asWorkflowStarterOnboardingStatus(onboardingPayload.data)
          : null;
      const nextModelHealth =
        modelPayload?.ok === true ? asWorkflowStarterModelHealth(modelPayload.data) : null;
      const nextIncompleteSessions =
        incompletePayload?.ok === true
          ? asWorkflowStarterSessionSummaries(incompletePayload.data)
          : null;

      setOnboardingStatus(nextOnboardingStatus);
      setModelHealth(nextModelHealth);
      setIncompleteSessions(nextIncompleteSessions);
      setReadinessLoaded(true);

      const failedChecks = [
        nextOnboardingStatus === null ? "onboarding" : null,
        nextModelHealth === null ? "model health" : null,
        nextIncompleteSessions === null ? "session recovery" : null
      ].filter((label): label is string => label !== null);

      if (failedChecks.length > 0) {
        setReadinessError(
          `Some launch checks could not be loaded: ${failedChecks.join(", ")}. Unknown cards stay neutral until the next refresh.`
        );
      }
    } catch (loadError) {
      setReadinessLoaded(true);
      setOnboardingStatus(null);
      setModelHealth(null);
      setIncompleteSessions(null);
      setReadinessError(
        loadError instanceof Error ? loadError.message : "Launch checks could not be refreshed."
      );
    } finally {
      setLoadingReadiness(false);
    }
  }

  async function handleRecommend(): Promise<void> {
    if (!canBuild) {
      setError("Describe the workflow goal first.");
      return;
    }
    setError("");
    setLoadingAction("recommend");
    const query = `${titleForKind(form.kind)} ${form.goal} ${form.output}`;
    try {
      const [workflowResult, skillResult] = await Promise.all([
        resolveWorkflows(query, token, apiKey),
        discoverSkills(query, token, apiKey)
      ]);
      const contextLabel = packContextLabel(initialDraft);
      onResult(`Workflow Starter - Resolve Workflows${contextLabel}`, workflowResult);
      onResult(`Workflow Starter - Discover Skills${contextLabel}`, skillResult);
      const workflows = asWorkflowResolutionResponse(workflowResult.data);
      const skills = asSkillDiscoveryResponse(skillResult.data);
      if (!workflowResult.ok || workflows === null) {
        setError(`Workflow recommendations failed (${workflowResult.status})`);
        return;
      }
      if (!skillResult.ok || skills === null) {
        setError(`Skill recommendations failed (${skillResult.status})`);
        return;
      }
      setWorkflowMatches(workflows.matches);
      setSkillMatches(skills.matches);
      setWorkflowPreview(buildWorkflow(form, initialDraft));
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown workflow starter error";
      setError(message);
    } finally {
      setLoadingAction(null);
    }
  }

  async function handleCreate(): Promise<void> {
    if (!canBuild) {
      setError("Describe the workflow goal first.");
      return;
    }
    const workflow = workflowPreview ?? buildWorkflow(form, initialDraft);
    setError("");
    setLoadingAction("create");
    try {
      const result = await createWorkflow(workflow, token, apiKey);
      onResult(`Workflow Starter - Create Workflow${packContextLabel(initialDraft)}`, result);
      const response = asWorkflowCreateResponse(result.data);
      if (!result.ok || response === null) {
        setError(`Workflow creation failed (${result.status})`);
        return;
      }
      setWorkflowPreview(workflow);
      setCreatedWorkflow(response);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown workflow creation error";
      setError(message);
    } finally {
      setLoadingAction(null);
    }
  }

  function handleOpenRecovery(): void {
    openOperationsRecoveryPanel(onOpenOperations);
  }

  const launchReadinessCards = buildLaunchReadinessCards({
    readinessLoaded,
    onboardingStatus,
    modelHealth,
    incompleteSessions,
    onOpenSetup,
    onOpenOperations,
    onOpenRecovery: handleOpenRecovery
  });
  const recommendedRuntime = getRecommendedRuntimeLabel(
    onboardingStatus,
    modelHealth,
    readinessLoaded
  );
  const resumeSummary = getResumeSummary(incompleteSessions, readinessLoaded);
  const lifecyclePlan = initialDraft?.lifecyclePlan ?? null;

  if (!hasCredentials) {
    return (
      <section className="workflow-starter-panel">
        <div className="onboarding-callout onboarding-callout-error">
          <h3>Connect to the engine first</h3>
          <p>Add an API key or operator token before creating workflows.</p>
          <button onClick={onOpenSetup}>Open integrations and API access</button>
        </div>
      </section>
    );
  }

  return (
    <section className="workflow-starter-panel">
      <header className="workflow-starter-hero">
        <div>
          <h2>Workflow Starter</h2>
          <p>
            Start research, improvement, and repeatable operator loops from a goal. AGENT-33 builds
            a validated workflow definition and lets you pull live launch checks before handing work
            over to the engine.
          </p>
          {initialDraft?.sourceLabel ? (
            <div className="workflow-starter-source">
              <span>Loaded starter: {initialDraft.sourceLabel}</span>
              {initialDraft.sourcePack ? (
                <span>
                  Pack: {initialDraft.sourcePack}
                  {initialDraft.sourcePackVersion ? ` v${initialDraft.sourcePackVersion}` : ""}
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
        <div className="workflow-starter-badge">
          {loadingReadiness ? "Refreshing launch checks..." : getLaunchBadgeLabel(launchReadinessCards, readinessLoaded)}
        </div>
      </header>

      <div className="workflow-starter-grid">
        <form className="workflow-starter-form" onSubmit={(event) => event.preventDefault()}>
          <label>
            Workflow type
            <select value={form.kind} onChange={(event) => updateField("kind", event.target.value as StarterKind)}>
              <option value="research">Research workflow</option>
              <option value="improvement-loop">Automatic improvement loop</option>
              <option value="automation-loop">Repeatable automation loop</option>
            </select>
          </label>
          <label>
            Workflow name
            <input
              value={form.name}
              onChange={(event) => updateField("name", event.target.value)}
              placeholder="weekly-agent-market-scan"
            />
          </label>
          <label>
            Goal
            <textarea
              rows={5}
              value={form.goal}
              onChange={(event) => updateField("goal", event.target.value)}
              placeholder="Track agent OS and MCP changes weekly, compare competitors, and recommend platform improvements."
            />
          </label>
          <label>
            Expected output
            <textarea
              rows={3}
              value={form.output}
              onChange={(event) => updateField("output", event.target.value)}
            />
          </label>
          <label>
            Optional schedule
            <input
              value={form.schedule}
              onChange={(event) => updateField("schedule", event.target.value)}
              placeholder="cron: 0 9 * * 1"
            />
          </label>
          <div className="workflow-starter-actions">
            <button type="button" onClick={() => void handleRecommend()} disabled={!canBuild || loadingAction !== null}>
              {loadingAction === "recommend" ? "Building..." : "Recommend plan"}
            </button>
            <button type="button" onClick={() => void handleCreate()} disabled={!canBuild || loadingAction !== null}>
              {loadingAction === "create" ? "Creating..." : "Create workflow"}
            </button>
          </div>
        </form>

        <aside className="workflow-starter-results" aria-label="Workflow starter results">
          {error ? <p className="ops-hub-error" role="alert">{error}</p> : null}
          {createdWorkflow ? (
            <div className="review-action-success">
              {createdWorkflow.name} created with {createdWorkflow.step_count} steps.
            </div>
          ) : null}

          <div className="workflow-starter-card">
            <div className="outcome-section-head">
              <div>
                <h3>Launch readiness</h3>
                <p>Use live engine checks before you create or hand off a new loop.</p>
              </div>
              <button type="button" onClick={() => void refreshLaunchReadiness()} disabled={loadingReadiness}>
                {loadingReadiness ? "Refreshing..." : "Refresh launch checks"}
              </button>
            </div>
            {readinessError ? <p className="ops-hub-error" role="alert">{readinessError}</p> : null}
            <div className="outcome-readiness-grid" aria-label="Workflow launch readiness">
              {launchReadinessCards.map((card) => (
                <article className={`outcome-readiness-card ${card.status}`} key={card.id}>
                  <span>{statusLabel(card.status)}</span>
                  <h3>{card.label}</h3>
                  <p>{card.detail}</p>
                  <button type="button" onClick={card.onAction}>
                    {card.actionLabel}
                  </button>
                </article>
              ))}
            </div>
          </div>

          <div className="workflow-starter-card">
            <h3>Recommended workflow</h3>
            {workflowPreview === null ? (
              <p>Describe a goal and choose Recommend plan to preview the workflow.</p>
            ) : (
              <>
                <div className="detail-field">
                  <span className="detail-label">Runtime name</span>
                  <span>{workflowPreview.name}</span>
                </div>
                <div className="detail-field">
                  <span className="detail-label">Steps</span>
                  <span>{workflowPreview.steps.length}</span>
                </div>
                <div className="detail-field">
                  <span className="detail-label">Recommended runtime</span>
                  <span>{recommendedRuntime}</span>
                </div>
                <div className="detail-field">
                  <span className="detail-label">Resume before relaunch</span>
                  <span>{resumeSummary}</span>
                </div>
                <ol className="workflow-step-list">
                  {workflowPreview.steps.map((step) => (
                    <li key={step.id}>
                      <strong>{step.name}</strong>
                      <span>{step.action.replace("-", " ")}</span>
                    </li>
                  ))}
                </ol>
                <div className="workflow-starter-actions">
                  <button type="button" onClick={onOpenSpawner}>Open visual spawner</button>
                  <button type="button" onClick={resumeCandidate !== null ? handleOpenRecovery : onOpenOperations}>
                    {resumeCandidate !== null ? "Open recovery panel" : "Open operations hub"}
                  </button>
                </div>
              </>
            )}
          </div>

          {lifecyclePlan ? (
            <div className="workflow-starter-card product-builder-lifecycle" aria-label="Product builder lifecycle">
              <h3>Product builder lifecycle</h3>
              <div className="product-builder-lifecycle-grid">
                {LIFECYCLE_LABELS.map(([key, label]) => (
                  <article key={key}>
                    <h4>{label}</h4>
                    <ul>
                      {lifecyclePlan[key].map((item, index) => (
                        <li key={`${key}-${index}`}>{item}</li>
                      ))}
                    </ul>
                  </article>
                ))}
              </div>
            </div>
          ) : null}

          <div className="workflow-starter-card">
            <h3>Matching templates and skills</h3>
            {workflowMatches.length === 0 && skillMatches.length === 0 ? (
              <p>No recommendations loaded yet.</p>
            ) : null}
            {workflowMatches.map((match) => (
              <article key={`${match.source}-${match.name}`} className="workflow-match-card">
                <h4>{match.name}</h4>
                <p>{match.description || "No description provided."}</p>
                <span>{match.source} · {Math.round(match.score * 100)}% match</span>
              </article>
            ))}
            {skillMatches.map((match) => (
              <article key={`skill-${match.name}`} className="workflow-match-card">
                <h4>{match.name}</h4>
                <p>{match.description || "No description provided."}</p>
                <span>skill · {Math.round(match.score * 100)}% match</span>
              </article>
            ))}
          </div>
        </aside>
      </div>
    </section>
  );
}
