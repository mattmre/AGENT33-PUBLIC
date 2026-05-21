import { useMemo, useState } from "react";

import type { ApiResult } from "../../types";
import {
  asSkillDiscoveryResponse,
  asSkillDraftResponse,
  createSkillDraft,
  discoverSkills
} from "./api";
import type { SkillDiscoveryMatch, SkillDraftRequest, SkillDraftResponse } from "./types";

interface SkillWizardPanelProps {
  token: string;
  apiKey: string;
  onOpenSetup: () => void;
  onResult: (label: string, result: ApiResult) => void;
}

function splitLines(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function splitComma(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function buildRequest(form: SkillWizardFormState, install: boolean): SkillDraftRequest {
  return {
    name: form.name,
    description: form.description,
    use_case: form.useCase,
    workflow_steps: splitLines(form.workflowSteps),
    success_criteria: splitLines(form.successCriteria),
    allowed_tools: splitComma(form.allowedTools),
    approval_required_for: splitLines(form.approvalRequiredFor),
    tags: splitComma(form.tags),
    category: form.category,
    author: form.author,
    autonomy_level: form.autonomyLevel.trim() || null,
    invocation_mode: form.invocationMode,
    execution_context: form.executionContext,
    install,
    overwrite: form.overwrite
  };
}

interface SkillWizardFormState {
  name: string;
  description: string;
  useCase: string;
  workflowSteps: string;
  successCriteria: string;
  allowedTools: string;
  approvalRequiredFor: string;
  tags: string;
  category: string;
  author: string;
  autonomyLevel: string;
  invocationMode: "user-only" | "llm-only" | "both";
  executionContext: "inline" | "fork";
  overwrite: boolean;
}

const DEFAULT_FORM: SkillWizardFormState = {
  name: "",
  description: "",
  useCase: "",
  workflowSteps: "",
  successCriteria: "",
  allowedTools: "",
  approvalRequiredFor: "file deletion\nshell commands that change system state",
  tags: "",
  category: "operator-authored",
  author: "operator",
  autonomyLevel: "supervised",
  invocationMode: "both",
  executionContext: "inline",
  overwrite: false
};

export function SkillWizardPanel({
  token,
  apiKey,
  onOpenSetup,
  onResult
}: SkillWizardPanelProps): JSX.Element {
  const [form, setForm] = useState<SkillWizardFormState>(DEFAULT_FORM);
  const [draft, setDraft] = useState<SkillDraftResponse | null>(null);
  const [matches, setMatches] = useState<SkillDiscoveryMatch[]>([]);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loadingAction, setLoadingAction] = useState<"preview" | "install" | "discover" | null>(null);

  const hasCredentials = token.trim() !== "" || apiKey.trim() !== "";
  const canSubmit = useMemo(() => {
    return form.name.trim() !== "" && form.description.trim() !== "" && form.useCase.trim() !== "";
  }, [form.description, form.name, form.useCase]);

  function updateField<K extends keyof SkillWizardFormState>(
    key: K,
    value: SkillWizardFormState[K]
  ): void {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function handleDraft(install: boolean): Promise<void> {
    if (!canSubmit) {
      setError("Name, description, and plain-language goal are required.");
      return;
    }
    setError("");
    setSuccess("");
    setLoadingAction(install ? "install" : "preview");
    try {
      const result = await createSkillDraft(buildRequest(form, install), token, apiKey);
      onResult(install ? "Skill Wizard - Install" : "Skill Wizard - Preview", result);
      const response = asSkillDraftResponse(result.data);
      if (!result.ok || response === null) {
        setError(`Skill ${install ? "install" : "preview"} failed (${result.status})`);
        return;
      }
      setDraft(response);
      if (response.installed) {
        setSuccess(`${response.skill.name} installed and registered for runtime use.`);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown skill wizard error";
      setError(message);
    } finally {
      setLoadingAction(null);
    }
  }

  async function handleDiscover(): Promise<void> {
    const query = [form.name, form.description, form.useCase].filter(Boolean).join(" ");
    if (query.trim() === "") {
      setError("Describe the skill first so AGENT-33 can look for existing matches.");
      return;
    }
    setError("");
    setLoadingAction("discover");
    try {
      const result = await discoverSkills(query, token, apiKey);
      onResult("Skill Wizard - Discover Similar Skills", result);
      const response = asSkillDiscoveryResponse(result.data);
      if (!result.ok || response === null) {
        setError(`Skill discovery failed (${result.status})`);
        return;
      }
      setMatches(response.matches);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown skill discovery error";
      setError(message);
    } finally {
      setLoadingAction(null);
    }
  }

  if (!hasCredentials) {
    return (
      <section className="skill-wizard-panel">
        <div className="onboarding-callout onboarding-callout-error">
          <h3>Connect to the engine first</h3>
          <p>Add an API key or operator token before creating runtime skills.</p>
          <button onClick={onOpenSetup}>Open integrations and API access</button>
        </div>
      </section>
    );
  }

  return (
    <section className="skill-wizard-panel">
      <header className="skill-wizard-hero">
        <div>
          <h2>Skill Wizard</h2>
          <p>
            Turn a plain-language operating procedure into a validated AGENT-33 skill. The wizard
            handles the technical manifest and can install the skill into the runtime registry.
          </p>
        </div>
        <div className="skill-wizard-badge">No JSON required</div>
      </header>

      <div className="skill-wizard-grid">
        <form className="skill-wizard-form" onSubmit={(event) => event.preventDefault()}>
          <div className="skill-wizard-section">
            <h3>1. Describe the capability</h3>
            <label>
              Skill name
              <input
                value={form.name}
                onChange={(event) => updateField("name", event.target.value)}
                placeholder="Research brief writer"
              />
            </label>
            <label>
              Short description
              <input
                value={form.description}
                onChange={(event) => updateField("description", event.target.value)}
                placeholder="Creates sourced research briefs from operator questions."
              />
            </label>
            <label>
              Plain-language goal
              <textarea
                rows={4}
                value={form.useCase}
                onChange={(event) => updateField("useCase", event.target.value)}
                placeholder="When a user asks for market research, gather sources, compare claims, and produce a concise brief."
              />
            </label>
          </div>

          <div className="skill-wizard-section">
            <h3>2. Define the workflow</h3>
            <label>
              Steps, one per line
              <textarea
                rows={5}
                value={form.workflowSteps}
                onChange={(event) => updateField("workflowSteps", event.target.value)}
                placeholder={"Clarify the research question\nSearch for current sources\nCompare findings\nReturn a brief with citations"}
              />
            </label>
            <label>
              Done when, one per line
              <textarea
                rows={3}
                value={form.successCriteria}
                onChange={(event) => updateField("successCriteria", event.target.value)}
                placeholder={"The answer includes sources\nOpen risks or unknowns are called out"}
              />
            </label>
          </div>

          <div className="skill-wizard-section">
            <h3>3. Pick tools and safety defaults</h3>
            <label>
              Allowed tools, comma-separated
              <input
                value={form.allowedTools}
                onChange={(event) => updateField("allowedTools", event.target.value)}
                placeholder="web_search, memory_search, filesystem_read"
              />
            </label>
            <label>
              Approval required before, one per line
              <textarea
                rows={3}
                value={form.approvalRequiredFor}
                onChange={(event) => updateField("approvalRequiredFor", event.target.value)}
              />
            </label>
            <div className="skill-wizard-inline">
              <label>
                Tags
                <input
                  value={form.tags}
                  onChange={(event) => updateField("tags", event.target.value)}
                  placeholder="research, operator"
                />
              </label>
              <label>
                Category
                <input
                  value={form.category}
                  onChange={(event) => updateField("category", event.target.value)}
                />
              </label>
            </div>
            <div className="skill-wizard-inline">
              <label>
                Invocation
                <select
                  value={form.invocationMode}
                  onChange={(event) =>
                    updateField("invocationMode", event.target.value as SkillWizardFormState["invocationMode"])
                  }
                >
                  <option value="both">User or agent</option>
                  <option value="user-only">User only</option>
                  <option value="llm-only">Agent only</option>
                </select>
              </label>
              <label>
                Runtime
                <select
                  value={form.executionContext}
                  onChange={(event) =>
                    updateField("executionContext", event.target.value as SkillWizardFormState["executionContext"])
                  }
                >
                  <option value="inline">Inline</option>
                  <option value="fork">Isolated sub-agent</option>
                </select>
              </label>
            </div>
            <label className="skill-wizard-check">
              <input
                type="checkbox"
                checked={form.overwrite}
                onChange={(event) => updateField("overwrite", event.target.checked)}
              />
              Replace an existing operator-authored skill with the same name
            </label>
          </div>

          <div className="skill-wizard-actions">
            <button type="button" onClick={() => void handleDiscover()} disabled={loadingAction !== null}>
              {loadingAction === "discover" ? "Finding matches..." : "Find similar skills"}
            </button>
            <button type="button" onClick={() => void handleDraft(false)} disabled={!canSubmit || loadingAction !== null}>
              {loadingAction === "preview" ? "Generating..." : "Preview skill"}
            </button>
            <button type="button" onClick={() => void handleDraft(true)} disabled={!canSubmit || loadingAction !== null}>
              {loadingAction === "install" ? "Installing..." : "Install skill"}
            </button>
          </div>
        </form>

        <aside className="skill-wizard-preview" aria-label="Skill wizard results">
          {error ? <p className="ops-hub-error" role="alert">{error}</p> : null}
          {success ? <p className="review-action-success">{success}</p> : null}

          <div className="skill-wizard-card">
            <h3>Existing matches</h3>
            {matches.length === 0 ? <p>No similar skills loaded yet. Search before installing to avoid duplicates.</p> : null}
            {matches.map((match) => (
              <article key={match.name} className="skill-match-card">
                <h4>{match.name}</h4>
                <p>{match.description || "No description provided."}</p>
                <span>{Math.round(match.score * 100)}% match{match.pack ? ` · ${match.pack}` : ""}</span>
              </article>
            ))}
          </div>

          <div className="skill-wizard-card">
            <h3>Generated skill</h3>
            {draft === null ? (
              <p>Preview or install a skill to see the generated operator-facing summary.</p>
            ) : (
              <>
                <div className="detail-field">
                  <span className="detail-label">Runtime name</span>
                  <span>{draft.skill.name}</span>
                </div>
                <div className="detail-field">
                  <span className="detail-label">Command</span>
                  <span>/{draft.skill.command_name ?? draft.skill.name}</span>
                </div>
                <div className="detail-field">
                  <span className="detail-label">Tools</span>
                  <span>{draft.skill.allowed_tools.length ? draft.skill.allowed_tools.join(", ") : "Guidance only"}</span>
                </div>
                <div className="detail-field">
                  <span className="detail-label">Install path</span>
                  <span>{draft.path ?? "Not installed yet"}</span>
                </div>
                {draft.warnings.map((warning) => (
                  <p key={warning} className="ops-hub-warning">{warning}</p>
                ))}
                <details className="skill-wizard-technical">
                  <summary>Show generated SKILL.md</summary>
                  <pre>{draft.markdown}</pre>
                </details>
              </>
            )}
          </div>
        </aside>
      </div>
    </section>
  );
}
