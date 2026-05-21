import { useCallback, useEffect, useMemo, useState } from "react";

import type { ApiResult } from "../../types";
import { asOnboardingStatus, fetchOnboardingStatus } from "./api";
import type { OnboardingStatus, OnboardingStep } from "./types";

interface OnboardingPanelProps {
  token: string;
  apiKey: string;
  onOpenSetup: () => void;
  onOpenChat: () => void;
  onOpenOperations: () => void;
  onOpenWorkflows?: () => void;
  onResult: (label: string, result: ApiResult) => void;
}

interface Guidance {
  why: string;
  action: string;
  command?: string;
}

const STEP_GUIDANCE: Record<string, Guidance> = {
  "OB-01": {
    why: "AGENT-33 needs durable memory before agents can safely remember work or recover from restarts.",
    action: "Start PostgreSQL and set DATABASE_URL in your environment.",
    command: "DATABASE_URL=postgresql+asyncpg://agent33:agent33@localhost:5432/agent33"
  },
  "OB-02": {
    why: "At least one model provider must be available before chat, workflows, and skills can run.",
    action: "Connect Ollama, OpenRouter, or an OpenAI-compatible provider.",
    command: "OLLAMA_BASE_URL=http://localhost:11434"
  },
  "OB-03": {
    why: "Agent definitions tell the runtime which assistants are available and what each one can do.",
    action: "Load the bundled agent definitions or point AGENT_DEFINITIONS_DIR at your definitions folder.",
    command: "AGENT_DEFINITIONS_DIR=engine/agent-definitions"
  },
  "OB-04": {
    why: "The default JWT secret allows anyone with repo defaults to mint tokens.",
    action: "Replace JWT_SECRET with a long random value before sharing the server.",
    command: "JWT_SECRET=<generate-a-long-random-secret>"
  },
  "OB-05": {
    why: "Backups protect operator state, generated artifacts, and recovery checkpoints.",
    action: "Choose a writable backup directory.",
    command: "BACKUP_DIR=.agent33/backups"
  },
  "OB-06": {
    why: "Redis powers runtime cache and session state used by higher-level operator workflows.",
    action: "Start Redis and set REDIS_URL.",
    command: "REDIS_URL=redis://localhost:6379/0"
  },
  "OB-07": {
    why: "NATS carries workflow and event-stream messages between subsystems.",
    action: "Start NATS and set NATS_URL.",
    command: "NATS_URL=nats://localhost:4222"
  },
  "OB-08": {
    why: "The API key protects non-browser integrations and automation clients.",
    action: "Replace API_SECRET_KEY with a strong random value.",
    command: "API_SECRET_KEY=<generate-a-long-random-secret>"
  }
};

/** Step IDs with the highest priority appear first in the pending list. */
const STEP_PRIORITY: Record<string, number> = {
  "OB-02": 0 // model connection is the most actionable first step
};

function sortByPriority(steps: OnboardingStep[]): OnboardingStep[] {
  return [...steps].sort((a, b) => {
    const pa = STEP_PRIORITY[a.step_id] ?? 99;
    const pb = STEP_PRIORITY[b.step_id] ?? 99;
    return pa !== pb ? pa - pb : a.step_id.localeCompare(b.step_id);
  });
}

function getStepGuidance(step: OnboardingStep): Guidance {
  return (
    STEP_GUIDANCE[step.step_id] ?? {
      why: step.description,
      action: step.remediation || "Review this item in the setup guide."
    }
  );
}

function getCompletionLabel(status: OnboardingStatus | null): string {
  if (status === null || status.total_count === 0) {
    return "0% ready";
  }
  return `${Math.round((status.completed_count / status.total_count) * 100)}% ready`;
}

export function OnboardingPanel({
  token,
  apiKey,
  onOpenSetup,
  onOpenChat,
  onOpenOperations,
  onOpenWorkflows,
  onResult
}: OnboardingPanelProps): JSX.Element {
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);

  const hasCredentials = token.trim() !== "" || apiKey.trim() !== "";

  const loadStatus = useCallback(async (): Promise<void> => {
    if (!hasCredentials) {
      setStatus(null);
      setError("");
      return;
    }
    setLoading(true);
    try {
      const result = await fetchOnboardingStatus(token, apiKey);
      onResult("Onboarding - Status", result);
      const parsed = asOnboardingStatus(result.data);
      if (!result.ok || parsed === null) {
        setError(`Failed to load onboarding status (${result.status})`);
        return;
      }
      setStatus(parsed);
      setError("");
    } catch (loadError) {
      const message = loadError instanceof Error ? loadError.message : "Unknown onboarding error";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [apiKey, hasCredentials, onResult, token]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const pendingSteps = useMemo(
    () => sortByPriority(status?.steps.filter((step) => !step.completed) ?? []),
    [status]
  );
  const completedSteps = useMemo(
    () => status?.steps.filter((step) => step.completed) ?? [],
    [status]
  );
  const progressStyle = useMemo(() => {
    const width =
      status === null || status.total_count === 0
        ? "0%"
        : `${Math.round((status.completed_count / status.total_count) * 100)}%`;
    return { width };
  }, [status]);

  return (
    <section className="onboarding-panel" aria-labelledby="onboarding-title">
      <header className="onboarding-hero">
        <div>
          <p className="eyebrow">Start here</p>
          <h2 id="onboarding-title">Get AGENT-33 ready without touching JSON</h2>
          <p>
            This checklist turns the runtime health checks into plain-language setup steps so a new
            operator can reach the first useful workflow safely.
          </p>
        </div>
        <div className="onboarding-score" aria-label={`Onboarding ${getCompletionLabel(status)}`}>
          <strong>{getCompletionLabel(status)}</strong>
          <span>
            {status === null
              ? "Connect credentials to inspect setup."
              : `${status.completed_count} of ${status.total_count} checks complete`}
          </span>
        </div>
      </header>

      <div className="onboarding-progress" aria-hidden="true">
        <span style={progressStyle} />
      </div>

      {!hasCredentials ? (
        <article className="onboarding-callout" role="status">
          <h3>Connect to the engine first</h3>
          <p>
            Paste a JWT or API key in Integrations so AGENT-33 can inspect your setup. This does
            not change anything; it only reads readiness checks.
          </p>
          <button onClick={onOpenSetup}>Open Integrations</button>
        </article>
      ) : null}

      {error ? (
        <article className="onboarding-callout onboarding-callout-error" role="alert">
          <h3>Onboarding status is unavailable</h3>
          <p>{error}</p>
          <button onClick={() => void loadStatus()}>Try again</button>
        </article>
      ) : null}

      {loading ? <p className="ops-hub-loading">Checking runtime readiness...</p> : null}

      {status?.overall_complete ? (
        <article className="onboarding-callout onboarding-callout-success">
          <h3>Ready for operator workflows</h3>
          <p>
            Core setup is complete. Start a chat, review live operations, or install packs from the
            marketplace.
          </p>
          <div className="onboarding-actions">
            {onOpenWorkflows ? (
              <button onClick={onOpenWorkflows}>Run your first workflow</button>
            ) : null}
            <button onClick={onOpenChat}>Open Chat Central</button>
            <button onClick={onOpenOperations}>Review Operations</button>
          </div>
        </article>
      ) : null}

      {pendingSteps.length > 0 ? (
        <div className="onboarding-section">
          <div className="onboarding-section-head">
            <h3>Next fixes</h3>
            <p>Handle these first. Each card explains why it matters and what to change.</p>
          </div>
          <div className="onboarding-step-grid">
            {pendingSteps.map((step) => {
              const guidance = getStepGuidance(step);
              return (
                <article className="onboarding-step-card pending" key={step.step_id}>
                  <div className="onboarding-step-title">
                    <span className="onboarding-step-badge">{step.step_id}</span>
                    <span>{step.category}</span>
                  </div>
                  <h4>{step.title}</h4>
                  <p>{step.description}</p>
                  <div className="onboarding-guidance">
                    <strong>Why it matters</strong>
                    <p>{guidance.why}</p>
                    <strong>Do this next</strong>
                    <p>{step.remediation || guidance.action}</p>
                    {guidance.command ? <code>{guidance.command}</code> : null}
                  </div>
                </article>
              );
            })}
          </div>
        </div>
      ) : null}

      {completedSteps.length > 0 ? (
        <div className="onboarding-section">
          <button
            className="onboarding-advanced-toggle"
            onClick={() => setShowAdvanced((value) => !value)}
            aria-expanded={showAdvanced}
          >
            {showAdvanced ? "Hide completed checks" : "Show completed checks"}
          </button>
          {showAdvanced ? (
            <div className="onboarding-step-grid compact">
              {completedSteps.map((step) => (
                <article className="onboarding-step-card complete" key={step.step_id}>
                  <div className="onboarding-step-title">
                    <span className="onboarding-step-badge">{step.step_id}</span>
                    <span>{step.category}</span>
                  </div>
                  <h4>{step.title}</h4>
                  <p>{step.description}</p>
                </article>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      <footer className="onboarding-footer">
        <button onClick={() => void loadStatus()} disabled={!hasCredentials || loading}>
          Refresh checklist
        </button>
        <button onClick={onOpenOperations}>Open Operations Hub</button>
      </footer>
    </section>
  );
}
