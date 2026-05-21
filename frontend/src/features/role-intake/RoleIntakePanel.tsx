import { useMemo, useState } from "react";

import { DEMO_SCENARIOS } from "../demo-mode/demoScenarios";
import { OUTCOME_WORKFLOWS } from "../outcome-home/catalog";
import type { WorkflowStarterDraft } from "../workflow-starter/types";
import { buildWorkflowDraftFromBrief } from "./builders";
import { ROLE_PROFILES, getRoleProfile } from "./data";
import type { ProductBrief, UserRoleId } from "./types";

interface RoleIntakePanelProps {
  selectedRole: UserRoleId | null;
  onSelectRole: (roleId: UserRoleId) => void;
  onOpenDemo: () => void;
  onOpenModels: () => void;
  onOpenWorkflowCatalog: () => void;
  onOpenWorkflowStarter: (draft?: WorkflowStarterDraft) => void;
}

interface BriefFormState {
  title: string;
  idea: string;
  audience: string;
  startingPoint: string;
  desiredOutput: string;
  safetyScope: string;
}

const EMPTY_FORM: BriefFormState = {
  title: "",
  idea: "",
  audience: "",
  startingPoint: "",
  desiredOutput: "",
  safetyScope: "Plan first. Ask before creating files, sending messages, or changing production data."
};

function buildBrief(roleId: UserRoleId, form: BriefFormState): ProductBrief {
  return {
    id: Date.now().toString(36),
    roleId,
    title: form.title.trim(),
    idea: form.idea.trim(),
    audience: form.audience.trim(),
    startingPoint: form.startingPoint.trim(),
    desiredOutput: form.desiredOutput.trim(),
    safetyScope: form.safetyScope.trim(),
    createdAt: new Date().toISOString()
  };
}

export function RoleIntakePanel({
  selectedRole,
  onSelectRole,
  onOpenDemo,
  onOpenModels,
  onOpenWorkflowCatalog,
  onOpenWorkflowStarter
}: RoleIntakePanelProps): JSX.Element {
  const [form, setForm] = useState<BriefFormState>(EMPTY_FORM);
  const [error, setError] = useState("");
  const activeRole = useMemo(
    () => getRoleProfile(selectedRole) ?? ROLE_PROFILES[0],
    [selectedRole]
  );

  const recommendedWorkflows = useMemo(
    () => OUTCOME_WORKFLOWS.filter((workflow) => activeRole.workflowIds.includes(workflow.id)),
    [activeRole]
  );
  const recommendedDemos = useMemo(
    () => DEMO_SCENARIOS.filter((scenario) => activeRole.demoScenarioIds.includes(scenario.id)),
    [activeRole]
  );

  function updateField(field: keyof BriefFormState, value: string): void {
    setForm((current) => ({ ...current, [field]: value }));
    setError("");
  }

  function handleSubmit(): void {
    const requiredFields: Array<keyof BriefFormState> = [
      "title",
      "idea",
      "audience",
      "desiredOutput"
    ];
    const missingField = requiredFields.find((field) => form[field].trim() === "");

    if (missingField) {
      setError("Complete the title, idea, users, and desired output before creating a workflow.");
      return;
    }

    const brief = buildBrief(activeRole.id, form);
    onSelectRole(activeRole.id);
    onOpenWorkflowStarter(buildWorkflowDraftFromBrief(brief));
  }

  return (
    <section className="role-intake-panel" aria-labelledby="role-intake-title">
      <header className="role-intake-hero">
        <div>
          <p className="eyebrow">Guided start path</p>
          <h2 id="role-intake-title">Tell AGENT-33 who you are before choosing tools</h2>
          <p>
            Pick a plain-language role, see the right workflows first, then turn your idea into a
            reviewable starter brief without touching JSON, settings, or agent internals.
          </p>
        </div>
        <div className="role-intake-score">
          <strong>5 role paths</strong>
          <span>Founder, developer, agency, enterprise, and operator presets</span>
        </div>
      </header>

      <div className="role-intake-grid">
        <aside className="role-picker" aria-label="Choose your role">
          <h3>Choose the closest role</h3>
          {ROLE_PROFILES.map((profile) => (
            <button
              type="button"
              key={profile.id}
              className={profile.id === activeRole.id ? "active" : ""}
              aria-pressed={profile.id === activeRole.id}
              onClick={() => onSelectRole(profile.id)}
            >
              <strong>{profile.title}</strong>
              <span>{profile.headline}</span>
            </button>
          ))}
        </aside>

        <div className="role-intake-workspace">
          <article className="role-path-card">
            <div>
              <p className="eyebrow">Recommended path</p>
              <h3>{activeRole.headline}</h3>
              <p>{activeRole.summary}</p>
            </div>
            <div className="role-pill-row">
              {activeRole.bestFor.map((item) => (
                <span key={item}>{item}</span>
              ))}
            </div>
            <div className="role-recommendation-grid">
              <section aria-label="Recommended workflows">
                <h4>Start with these workflows</h4>
                {recommendedWorkflows.map((workflow) => (
                  <p key={workflow.id}>
                    <strong>{workflow.title}</strong> - {workflow.summary}
                  </p>
                ))}
              </section>
              <section aria-label="Recommended demos">
                <h4>Preview these demos</h4>
                {recommendedDemos.map((scenario) => (
                  <p key={scenario.id}>
                    <strong>{scenario.title}</strong> - {scenario.outcome}
                  </p>
                ))}
              </section>
            </div>
            <div className="role-action-row">
              <button type="button" onClick={onOpenDemo}>
                Try matching demos
              </button>
              <button type="button" onClick={onOpenWorkflowCatalog}>
                Browse all workflows
              </button>
              <button type="button" onClick={onOpenModels}>
                Connect model when ready
              </button>
            </div>
          </article>

          <article className="role-path-card guided-brief-card">
            <div>
              <p className="eyebrow">Guided idea intake</p>
              <h3>Turn your idea into a starter brief</h3>
              <p>
                Answer five practical prompts. AGENT-33 will send a structured draft into Workflow
                Starter with safety gates already included.
              </p>
            </div>

            {error ? (
              <p className="role-intake-error" role="alert">
                {error}
              </p>
            ) : null}

            <label>
              <span>1. Name the thing you want</span>
              <input
                value={form.title}
                onChange={(event) => updateField("title", event.target.value)}
                placeholder="Example: Client portal MVP"
              />
            </label>
            <label>
              <span>2. Describe the idea in plain language</span>
              <textarea
                rows={3}
                value={form.idea}
                onChange={(event) => updateField("idea", event.target.value)}
                placeholder="Example: A portal where clients fill out intake forms and see project status."
              />
            </label>
            <label>
              <span>3. Who uses it?</span>
              <input
                value={form.audience}
                onChange={(event) => updateField("audience", event.target.value)}
                placeholder="Example: business owner, client, project assistant"
              />
            </label>
            <label>
              <span>4. What do you already have?</span>
              <input
                value={form.startingPoint}
                onChange={(event) => updateField("startingPoint", event.target.value)}
                placeholder="Example: notes, CSV export, repo, screenshots, nothing yet"
              />
            </label>
            <label>
              <span>5. What should AGENT-33 produce first?</span>
              <input
                value={form.desiredOutput}
                onChange={(event) => updateField("desiredOutput", event.target.value)}
                placeholder="Example: product brief, screen list, first implementation tasks"
              />
            </label>
            <label>
              <span>Safety and scope</span>
              <textarea
                rows={2}
                value={form.safetyScope}
                onChange={(event) => updateField("safetyScope", event.target.value)}
              />
            </label>

            <div className="role-action-row">
              <button type="button" onClick={handleSubmit}>
                Create guided workflow draft
              </button>
              <button
                type="button"
                onClick={() => {
                  setForm(EMPTY_FORM);
                  setError("");
                }}
              >
                Reset brief
              </button>
            </div>
          </article>
        </div>
      </div>
    </section>
  );
}
