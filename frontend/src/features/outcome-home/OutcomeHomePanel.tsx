import { useCallback, useEffect, useMemo, useState } from "react";

import type { ApiResult } from "../../types";
import { asOnboardingStatus, fetchOnboardingStatus } from "../onboarding/api";
import type { OnboardingStatus } from "../onboarding/types";
import type { WorkflowStarterDraft } from "../workflow-starter/types";
import { getRoleProfile } from "../role-intake/data";
import type { UserRoleId } from "../role-intake/types";
import {
  OUTCOME_WORKFLOWS,
  buildCustomWorkflowDraft,
  buildWorkflowDraft,
  getFeaturedWorkflows
} from "./catalog";
import type { OutcomeWorkflow } from "./types";

interface OutcomeHomePanelProps {
  selectedRole?: UserRoleId | null;
  token: string;
  apiKey: string;
  onOpenSetup: () => void;
  onOpenModels: () => void;
  onOpenDemo: () => void;
  onOpenChat: () => void;
  onOpenOperations: () => void;
  onOpenWorkflowStarter: (draft?: WorkflowStarterDraft) => void;
  onOpenLoops: () => void;
  onOpenMcp: () => void;
  onOpenAdvanced: () => void;
  onResult: (label: string, result: ApiResult) => void;
}

interface ReadinessCard {
  label: string;
  status: "ready" | "attention" | "unknown";
  detail: string;
  action: string;
  onAction: () => void;
}

function getReadinessLabel(status: OnboardingStatus | null): string {
  if (status === null || status.total_count === 0) {
    return "Readiness unknown";
  }
  return `${Math.round((status.completed_count / status.total_count) * 100)}% ready`;
}

function findStepStatus(status: OnboardingStatus | null, stepId: string): boolean | null {
  const step = status?.steps.find((item) => item.step_id === stepId);
  return step?.completed ?? null;
}

function renderWorkflowCard(
  workflow: OutcomeWorkflow,
  onUseWorkflow: (workflow: OutcomeWorkflow) => void
): JSX.Element {
  return (
    <article className="outcome-workflow-card" key={workflow.id}>
      <div>
        <div className="outcome-workflow-meta">
          <span>{workflow.audience}</span>
          <span>{workflow.estimatedTime}</span>
        </div>
        <h4>{workflow.title}</h4>
        <p>{workflow.summary}</p>
      </div>
      <div className="outcome-workflow-deliverables">
        {workflow.deliverables.slice(0, 3).map((deliverable) => (
          <span key={deliverable}>{deliverable}</span>
        ))}
      </div>
      <div className="outcome-workflow-footer">
        <span className="outcome-safety-pill">{workflow.safetyLevel}</span>
        <button type="button" onClick={() => onUseWorkflow(workflow)}>
          Use this workflow
        </button>
      </div>
    </article>
  );
}

export function OutcomeHomePanel({
  selectedRole,
  token,
  apiKey,
  onOpenSetup,
  onOpenModels,
  onOpenDemo,
  onOpenChat,
  onOpenOperations,
  onOpenWorkflowStarter,
  onOpenLoops,
  onOpenMcp,
  onOpenAdvanced,
  onResult
}: OutcomeHomePanelProps): JSX.Element {
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
  const [goal, setGoal] = useState("");
  const [selectedTag, setSelectedTag] = useState("featured");
  const [loadingStatus, setLoadingStatus] = useState(false);
  const [error, setError] = useState("");
  const roleProfile = useMemo(() => getRoleProfile(selectedRole), [selectedRole]);

  const hasCredentials = token.trim() !== "" || apiKey.trim() !== "";

  const loadStatus = useCallback(async (): Promise<void> => {
    if (!hasCredentials) {
      setStatus(null);
      setError("");
      return;
    }

    setLoadingStatus(true);
    try {
      const result = await fetchOnboardingStatus(token, apiKey);
      onResult("Outcome Home - Readiness", result);
      const parsed = asOnboardingStatus(result.data);
      if (!result.ok || parsed === null) {
        setError(`Readiness check failed (${result.status})`);
        return;
      }
      setStatus(parsed);
      setError("");
    } catch (loadError) {
      const message = loadError instanceof Error ? loadError.message : "Unknown readiness error";
      setError(message);
    } finally {
      setLoadingStatus(false);
    }
  }, [apiKey, hasCredentials, onResult, token]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const readinessCards = useMemo<ReadinessCard[]>(() => {
    const databaseReady = findStepStatus(status, "OB-01");
    const modelReady = findStepStatus(status, "OB-02");
    const apiReady = findStepStatus(status, "OB-08");

    return [
      {
        label: "Engine access",
        status: hasCredentials ? "ready" : "attention",
        detail: hasCredentials ? "Credentials are saved for this browser." : "Add a token or API key first.",
        action: hasCredentials ? "Review access" : "Connect access",
        onAction: onOpenSetup
      },
      {
        label: "Model provider",
        status: modelReady === true ? "ready" : modelReady === false ? "attention" : "unknown",
        detail:
          modelReady === true
            ? "A model provider is available for workflows."
            : modelReady === false
              ? "Connect OpenRouter, Ollama, or another provider before building."
              : "Model provider readiness is still pending or unknown.",
        action: "Connect model",
        onAction: onOpenModels
      },
      {
        label: "Runtime memory",
        status: databaseReady === true ? "ready" : databaseReady === false ? "attention" : "unknown",
        detail:
          databaseReady === true
            ? "Durable state is available for agent work."
            : "Postgres readiness is still pending or unknown.",
        action: "Check setup",
        onAction: onOpenSetup
      },
      {
        label: "Safe operations",
        status: apiReady === true ? "ready" : apiReady === false ? "attention" : "unknown",
        detail:
          apiReady === true
            ? "API protection is configured for automation."
            : "Review API and approval safety before long-running work.",
        action: "Open safety",
        onAction: onOpenOperations
      }
    ];
  }, [hasCredentials, onOpenModels, onOpenOperations, onOpenSetup, status]);

  const tagOptions = useMemo(() => {
    const tags = new Set<string>(["featured"]);
    OUTCOME_WORKFLOWS.forEach((workflow) => workflow.tags.forEach((tag) => tags.add(tag)));
    return [...tags];
  }, []);

  const workflows = useMemo(() => {
    if (selectedTag === "featured") {
      if (roleProfile !== null) {
        const roleWorkflows = OUTCOME_WORKFLOWS.filter((workflow) =>
          roleProfile.workflowIds.includes(workflow.id)
        );
        return roleWorkflows.length > 0 ? roleWorkflows : getFeaturedWorkflows();
      }
      return getFeaturedWorkflows();
    }
    return OUTCOME_WORKFLOWS.filter((workflow) => workflow.tags.includes(selectedTag));
  }, [roleProfile, selectedTag]);

  function handleUseWorkflow(workflow: OutcomeWorkflow): void {
    onOpenWorkflowStarter(buildWorkflowDraft(workflow));
  }

  function handleCustomGoal(): void {
    if (goal.trim() === "") {
      return;
    }
    onOpenWorkflowStarter(buildCustomWorkflowDraft(goal));
  }

  return (
    <section className="outcome-home-panel" aria-labelledby="outcome-home-title">
      <header className="outcome-home-hero">
        <div>
          <p className="eyebrow">Outcome-first autopilot</p>
          <h2 id="outcome-home-title">
            {roleProfile === null
              ? "What do you want AGENT-33 to build or run?"
              : `${roleProfile.title} path: what should AGENT-33 help you do first?`}
          </h2>
          <p>
            Pick a proven workflow, describe an outcome in plain language, or connect the missing
            pieces. AGENT-33 will route you into a review-gated workflow instead of making you hunt
            through raw settings.
          </p>
        </div>
        <div className="outcome-home-score">
          <strong>{getReadinessLabel(status)}</strong>
          <span>{loadingStatus ? "Refreshing readiness..." : "Model, runtime, and safety readiness"}</span>
        </div>
      </header>

      {error ? (
        <article className="onboarding-callout onboarding-callout-error" role="alert">
          <h3>Readiness is unavailable</h3>
          <p>{error}</p>
          <button type="button" onClick={() => void loadStatus()}>
            Try again
          </button>
        </article>
      ) : null}

      {roleProfile !== null ? (
        <article className="outcome-role-callout" aria-label="Selected role guidance">
          <div>
            <p className="eyebrow">Your selected role</p>
            <h3>{roleProfile.headline}</h3>
            <p>{roleProfile.summary}</p>
          </div>
          <div className="role-pill-row">
            {roleProfile.setupFocus.map((item) => (
              <span key={item}>{item}</span>
            ))}
          </div>
        </article>
      ) : null}

      <div className="outcome-goal-card">
        <div>
          <h3>Start from your own outcome</h3>
          <p>
            Do not worry about workflow syntax. Describe the result you want, then let Workflow
            Starter turn it into a plan with steps and review gates.
          </p>
        </div>
        <textarea
          rows={3}
          value={goal}
          onChange={(event) => setGoal(event.target.value)}
          placeholder="Example: Build a customer support dashboard with ticket trends, SLA alerts, and an admin view."
        />
        <div className="outcome-goal-actions">
          <button type="button" onClick={onOpenDemo}>
            Try demo mode first
          </button>
          <button type="button" onClick={handleCustomGoal} disabled={goal.trim() === ""}>
            Turn this into a workflow
          </button>
          <button type="button" onClick={onOpenChat}>
            Ask in chat instead
          </button>
        </div>
      </div>

      <section className="outcome-readiness-grid" aria-label="Readiness checklist">
        {readinessCards.map((card) => (
          <article className={`outcome-readiness-card ${card.status}`} key={card.label}>
            <span>{card.status === "ready" ? "Ready" : card.status === "attention" ? "Needs attention" : "Unknown"}</span>
            <h3>{card.label}</h3>
            <p>{card.detail}</p>
            <button type="button" onClick={card.onAction}>
              {card.action}
            </button>
          </article>
        ))}
      </section>

      <section className="outcome-catalog-section" aria-labelledby="workflow-catalog-title">
        <div className="outcome-section-head">
          <div>
            <p className="eyebrow">Baked-in workflows</p>
            <h3 id="workflow-catalog-title">Start with a proven system</h3>
            <p>
              These cards are the first layer of the workflow catalog: pre-filled outcomes that route
              into Workflow Starter with plain-language goals, outputs, and safety expectations.
            </p>
          </div>
          <div className="outcome-tag-filter" aria-label="Workflow category filter">
            {tagOptions.map((tag) => (
              <button
                type="button"
                key={tag}
                className={selectedTag === tag ? "active" : ""}
                onClick={() => setSelectedTag(tag)}
              >
                {tag === "featured" ? "Featured" : tag}
              </button>
            ))}
          </div>
        </div>
        <div className="outcome-workflow-grid">
          {workflows.map((workflow) => renderWorkflowCard(workflow, handleUseWorkflow))}
        </div>
      </section>

      <section className="outcome-next-actions" aria-label="Common next actions">
        <button type="button" onClick={onOpenModels}>
          Connect model
        </button>
        <button type="button" onClick={onOpenDemo}>
          Try demo without setup
        </button>
        <button type="button" onClick={onOpenMcp}>
          Check MCP health
        </button>
        <button type="button" onClick={onOpenLoops}>
          Schedule research loops
        </button>
        <button type="button" onClick={onOpenAdvanced}>
          Open advanced controls
        </button>
      </section>
    </section>
  );
}
