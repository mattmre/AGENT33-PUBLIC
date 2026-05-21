import { useMemo, useState } from "react";

import type { ApiResult } from "../../types";
import {
  asWorkflowCreateResponse,
  asWorkflowScheduleResponse,
  createLoopWorkflow,
  scheduleLoopWorkflow
} from "./api";
import {
  buildLoopWorkflow,
  buildScheduleInputs,
  formFromResearchLaunchPlan,
  formFromPreset,
  getPreset,
  LOOP_PRESETS,
  normalizeCron,
  RESEARCH_LAUNCH_PLANS
} from "./presets";
import type {
  ImprovementLoopForm,
  ImprovementLoopPreset,
  ImprovementLoopPresetId,
  LoopWorkflowRequest,
  ResearchLaunchPlan,
  ResearchLauncherId,
  WorkflowCreateResponse,
  WorkflowScheduleResponse
} from "./types";

interface ImprovementLoopsPanelProps {
  token: string;
  apiKey: string;
  onOpenSetup: () => void;
  onOpenOperations: () => void;
  onOpenWorkflowStarter: () => void;
  onResult: (label: string, result: ApiResult) => void;
}

export function ImprovementLoopsPanel({
  token,
  apiKey,
  onOpenSetup,
  onOpenOperations,
  onOpenWorkflowStarter,
  onResult
}: ImprovementLoopsPanelProps): JSX.Element {
  const [presetId, setPresetId] = useState<ImprovementLoopPresetId>("competitive-research");
  const [form, setForm] = useState<ImprovementLoopForm>(() => formFromPreset(getPreset("competitive-research")));
  const [preview, setPreview] = useState<LoopWorkflowRequest | null>(null);
  const [createdWorkflow, setCreatedWorkflow] = useState<WorkflowCreateResponse | null>(null);
  const [scheduledWorkflow, setScheduledWorkflow] = useState<WorkflowScheduleResponse | null>(null);
  const [loadingAction, setLoadingAction] = useState<"create" | "schedule" | null>(null);
  const [launchingPlan, setLaunchingPlan] = useState<ResearchLauncherId | null>(null);
  const [error, setError] = useState("");

  const preset = useMemo(() => getPreset(presetId), [presetId]);
  const hasCredentials = token.trim() !== "" || apiKey.trim() !== "";
  const canCreate = form.goal.trim() !== "";
  const canSchedule = canCreate && normalizeCron(form.schedule) !== "";

  function applyPreset(nextPresetId: ImprovementLoopPresetId): void {
    const nextPreset = getPreset(nextPresetId);
    setPresetId(nextPresetId);
    setForm(formFromPreset(nextPreset));
    setPreview(null);
    setCreatedWorkflow(null);
    setScheduledWorkflow(null);
    setError("");
  }

  function updateField<K extends keyof ImprovementLoopForm>(key: K, value: ImprovementLoopForm[K]): void {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function handlePreview(): void {
    if (!canCreate) {
      setError("Describe the improvement loop goal first.");
      return;
    }
    setError("");
    setPreview(buildLoopWorkflow(preset, form));
  }

  async function createOrScheduleLoop(
    targetPreset: ImprovementLoopPreset,
    targetForm: ImprovementLoopForm,
    alsoSchedule: boolean
  ): Promise<void> {
    const targetGoal = targetForm.goal.trim();
    const targetSchedule = normalizeCron(targetForm.schedule);

    if (targetGoal === "") {
      setError("Describe the improvement loop goal first.");
      return;
    }
    if (alsoSchedule && targetSchedule === "") {
      setError("Add a cron schedule before creating an automatic loop.");
      return;
    }

    const workflow = buildLoopWorkflow(targetPreset, targetForm);
    setPreview(workflow);
    setError("");
    setLoadingAction(alsoSchedule ? "schedule" : "create");
    setCreatedWorkflow(null);
    setScheduledWorkflow(null);

    try {
      const createResult = await createLoopWorkflow(workflow, token, apiKey);
      onResult("Improvement Loops - Create Workflow", createResult);
      const createResponse = asWorkflowCreateResponse(createResult.data);

      if (createResult.ok && createResponse !== null) {
        setCreatedWorkflow(createResponse);
      } else if (createResult.status === 409) {
        setCreatedWorkflow({
          name: workflow.name,
          version: workflow.version,
          step_count: workflow.steps.length,
          created: false
        });
      } else {
        setError(`Workflow creation failed (${createResult.status})`);
        return;
      }

      if (alsoSchedule) {
        const scheduleResult = await scheduleLoopWorkflow(
          workflow.name,
          targetSchedule,
          buildScheduleInputs(targetPreset, targetForm),
          token,
          apiKey
        );
        onResult("Improvement Loops - Schedule Workflow", scheduleResult);
        const scheduleResponse = asWorkflowScheduleResponse(scheduleResult.data);
        if (!scheduleResult.ok || scheduleResponse === null) {
          setError(`Workflow schedule failed (${scheduleResult.status})`);
          return;
        }
        setScheduledWorkflow(scheduleResponse);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown improvement loop error";
      setError(message);
    } finally {
      setLoadingAction(null);
    }
  }

  async function handleCreate(alsoSchedule: boolean): Promise<void> {
    await createOrScheduleLoop(preset, form, alsoSchedule);
  }

  async function handleLaunchPlan(plan: ResearchLaunchPlan): Promise<void> {
    const launchPreset = getPreset(plan.presetId);
    const launchForm = formFromResearchLaunchPlan(plan);

    setPresetId(plan.presetId);
    setForm(launchForm);
    setLaunchingPlan(plan.id);
    try {
      await createOrScheduleLoop(launchPreset, launchForm, true);
    } finally {
      setLaunchingPlan(null);
    }
  }

  if (!hasCredentials) {
    return (
      <section className="improvement-loops-panel">
        <div className="onboarding-callout onboarding-callout-error">
          <h3>Connect to the engine first</h3>
          <p>Add an API key or operator token before creating recurring improvement loops.</p>
          <button onClick={onOpenSetup}>Open integrations and API access</button>
        </div>
      </section>
    );
  }

  return (
    <section className="improvement-loops-panel">
      <header className="improvement-loops-hero">
        <div>
          <h2>Improvement Loops</h2>
          <p>
            Turn AGENT-33 into an automatic research and improvement system. Pick a plain-language
            loop, tune the goal, then create or schedule a governed workflow.
          </p>
        </div>
        <div className="improvement-loops-badge">Autonomous, review-gated</div>
      </header>

      <section className="research-launchers" aria-label="Recommended research launchers">
        <div className="research-launchers-heading">
          <div>
            <h3>Recommended research launchers</h3>
            <p>Skip the JSON and cron tuning. These launchers create and schedule implementation-ready research loops.</p>
          </div>
          <button type="button" onClick={onOpenOperations}>
            View active schedules
          </button>
        </div>
        <div className="research-launcher-grid">
          {RESEARCH_LAUNCH_PLANS.map((plan) => (
            <article className="research-launcher-card" key={plan.id}>
              <div>
                <h4>{plan.title}</h4>
                <p>{plan.summary}</p>
              </div>
              <div className="detail-field">
                <span className="detail-label">Cadence</span>
                <span>{plan.cadenceLabel}</span>
              </div>
              <button
                type="button"
                onClick={() => void handleLaunchPlan(plan)}
                disabled={loadingAction !== null || launchingPlan !== null}
              >
                {launchingPlan === plan.id ? "Scheduling..." : plan.buttonLabel}
              </button>
            </article>
          ))}
        </div>
      </section>

      <div className="improvement-loops-grid">
        <aside className="improvement-loop-presets" aria-label="Improvement loop presets">
          {LOOP_PRESETS.map((loopPreset) => (
            <button
              type="button"
              key={loopPreset.id}
              className={loopPreset.id === presetId ? "improvement-loop-preset active" : "improvement-loop-preset"}
              onClick={() => applyPreset(loopPreset.id)}
            >
              <strong>{loopPreset.title}</strong>
              <span>{loopPreset.summary}</span>
              <small>{loopPreset.cadenceLabel}</small>
            </button>
          ))}
        </aside>

        <form className="improvement-loop-form" onSubmit={(event) => event.preventDefault()}>
          <label>
            Workflow name
            <input value={form.workflowName} onChange={(event) => updateField("workflowName", event.target.value)} />
          </label>
          <label>
            Loop goal
            <textarea rows={5} value={form.goal} onChange={(event) => updateField("goal", event.target.value)} />
          </label>
          <label>
            Expected output
            <textarea rows={3} value={form.output} onChange={(event) => updateField("output", event.target.value)} />
          </label>
          <label>
            Automatic schedule
            <input
              value={form.schedule}
              onChange={(event) => updateField("schedule", event.target.value)}
              placeholder="0 9 * * 1"
            />
          </label>
          <label>
            Author
            <input value={form.author} onChange={(event) => updateField("author", event.target.value)} />
          </label>
          <div className="improvement-loop-actions">
            <button type="button" onClick={handlePreview} disabled={!canCreate || loadingAction !== null}>
              Preview loop
            </button>
            <button type="button" onClick={() => void handleCreate(false)} disabled={!canCreate || loadingAction !== null}>
              {loadingAction === "create" ? "Creating..." : "Create workflow"}
            </button>
            <button type="button" onClick={() => void handleCreate(true)} disabled={!canSchedule || loadingAction !== null}>
              {loadingAction === "schedule" ? "Scheduling..." : "Create and schedule"}
            </button>
          </div>
        </form>

        <aside className="improvement-loop-results" aria-label="Improvement loop results">
          {error ? <p className="ops-hub-error" role="alert">{error}</p> : null}
          {createdWorkflow ? (
            <div className="review-action-success">
              {createdWorkflow.created ? "Created" : "Using existing"} {createdWorkflow.name} with{" "}
              {createdWorkflow.step_count} steps.
            </div>
          ) : null}
          {scheduledWorkflow ? (
            <div className="review-action-success">
              Scheduled {scheduledWorkflow.workflow_name} as {scheduledWorkflow.job_id} ({scheduledWorkflow.schedule_expr}).
            </div>
          ) : null}

          <article className="improvement-loop-card">
            <h3>Loop preview</h3>
            {preview === null ? (
              <p>Choose Preview loop to see the workflow AGENT-33 will create.</p>
            ) : (
              <>
                <div className="detail-field">
                  <span className="detail-label">Workflow</span>
                  <span>{preview.name}</span>
                </div>
                <div className="detail-field">
                  <span className="detail-label">Schedule</span>
                  <span>{preview.triggers.schedule ?? "Manual only"}</span>
                </div>
                <ol className="workflow-step-list">
                  {preview.steps.map((step) => (
                    <li key={step.id}>
                      <strong>{step.name}</strong>
                      <span>{step.agent ?? step.action}</span>
                    </li>
                  ))}
                </ol>
              </>
            )}
          </article>

          <article className="improvement-loop-card">
            <h3>Focus areas</h3>
            <div className="improvement-loop-tags">
              {preset.focusAreas.map((area) => (
                <span key={area}>{area}</span>
              ))}
            </div>
            <div className="improvement-loop-actions">
              <button type="button" onClick={onOpenOperations}>Open operations hub</button>
              <button type="button" onClick={onOpenWorkflowStarter}>Open workflow starter</button>
            </div>
          </article>
        </aside>
      </div>
    </section>
  );
}
