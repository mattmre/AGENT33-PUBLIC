import { useMemo, useState } from "react";

import type { ApiResult } from "../../types";
import {
  asSkillDiscoveryResponse,
  asToolDiscoveryResponse,
  asWorkflowResolutionResponse,
  discoverSkills,
  discoverTools,
  resolveWorkflows
} from "./api";
import { buildResourceManifest } from "./resourceManifest";
import type {
  FabricPlan,
  ResourceManifestStatus,
  SkillDiscoveryMatch,
  ToolDiscoveryMatch,
  WorkflowResolutionMatch
} from "./types";

interface ToolFabricPanelProps {
  token: string;
  apiKey: string;
  onOpenSetup: () => void;
  onOpenTools: () => void;
  onOpenSkills: () => void;
  onOpenWorkflowStarter: () => void;
  onResult: (label: string, result: ApiResult) => void;
}

function scoreLabel(score: number): string {
  return `${Math.round(score * 100)}% match`;
}

function topNames(
  tools: ToolDiscoveryMatch[],
  skills: SkillDiscoveryMatch[],
  workflows: WorkflowResolutionMatch[]
): string {
  const names = [
    ...tools.slice(0, 2).map((item) => item.name),
    ...skills.slice(0, 2).map((item) => item.name),
    ...workflows.slice(0, 1).map((item) => item.name)
  ];
  return names.length > 0 ? names.join(", ") : "No matching runtime assets yet";
}

function manifestStatusLabel(status: ResourceManifestStatus): string {
  const labels: Record<ResourceManifestStatus, string> = {
    ready: "Ready",
    "needs-review": "Review",
    missing: "Missing"
  };
  return labels[status];
}

export function ToolFabricPanel({
  token,
  apiKey,
  onOpenSetup,
  onOpenTools,
  onOpenSkills,
  onOpenWorkflowStarter,
  onResult
}: ToolFabricPanelProps): JSX.Element {
  const [objective, setObjective] = useState("");
  const [plan, setPlan] = useState<FabricPlan | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const hasCredentials = token.trim() !== "" || apiKey.trim() !== "";
  const canResolve = useMemo(() => objective.trim().length > 0, [objective]);
  const resourceManifest = useMemo(
    () => buildResourceManifest(plan ?? { objective: "", tools: [], skills: [], workflows: [] }),
    [plan]
  );

  async function handleResolve(): Promise<void> {
    const trimmedObjective = objective.trim();
    if (trimmedObjective === "") {
      setError("Describe what you want AGENT-33 to do first.");
      return;
    }
    setError("");
    setLoading(true);
    try {
      const [toolResult, skillResult, workflowResult] = await Promise.all([
        discoverTools(trimmedObjective, token, apiKey),
        discoverSkills(trimmedObjective, token, apiKey),
        resolveWorkflows(trimmedObjective, token, apiKey)
      ]);
      onResult("Tool Fabric - Discover Tools", toolResult);
      onResult("Tool Fabric - Discover Skills", skillResult);
      onResult("Tool Fabric - Resolve Workflows", workflowResult);

      const toolResponse = asToolDiscoveryResponse(toolResult.data);
      const skillResponse = asSkillDiscoveryResponse(skillResult.data);
      const workflowResponse = asWorkflowResolutionResponse(workflowResult.data);

      if (!toolResult.ok || toolResponse === null) {
        setError(`Tool discovery failed (${toolResult.status})`);
        return;
      }
      if (!skillResult.ok || skillResponse === null) {
        setError(`Skill discovery failed (${skillResult.status})`);
        return;
      }
      if (!workflowResult.ok || workflowResponse === null) {
        setError(`Workflow resolution failed (${workflowResult.status})`);
        return;
      }

      setPlan({
        objective: trimmedObjective,
        tools: toolResponse.matches,
        skills: skillResponse.matches,
        workflows: workflowResponse.matches
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown tool fabric error";
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  if (!hasCredentials) {
    return (
      <section className="tool-fabric-panel">
        <div className="onboarding-callout onboarding-callout-error">
          <h3>Connect to the engine first</h3>
          <p>Add an API key or operator token before resolving tools, skills, and workflows.</p>
          <button onClick={onOpenSetup}>Open integrations and API access</button>
        </div>
      </section>
    );
  }

  return (
    <section className="tool-fabric-panel">
      <header className="tool-fabric-hero">
        <div>
          <h2>Adaptive Tool Fabric</h2>
          <p>
            Describe an objective once and AGENT-33 will map it to available runtime tools, skills,
            and workflow templates. This turns MCP/tool discovery into a plain-language operator flow.
          </p>
        </div>
        <div className="tool-fabric-badge">MCP-ready discovery</div>
      </header>

      <div className="tool-fabric-query">
        <label>
          What do you want to accomplish?
          <textarea
            rows={4}
            value={objective}
            onChange={(event) => setObjective(event.target.value)}
            placeholder="Research competitor agent OS changes, compare workflow UX, and propose safe improvements."
          />
        </label>
        <div className="tool-fabric-actions">
          <button type="button" onClick={() => void handleResolve()} disabled={!canResolve || loading}>
            {loading ? "Resolving..." : "Resolve tool plan"}
          </button>
          <button type="button" onClick={onOpenTools}>Browse full tool catalog</button>
        </div>
      </div>

      {error ? <p className="ops-hub-error" role="alert">{error}</p> : null}

      <div className="tool-fabric-grid">
        <article className="tool-fabric-summary">
          <h3>Recommended fabric</h3>
          {plan === null ? (
            <p>Run a resolution to see the best tools, skills, and workflows for the objective.</p>
          ) : (
            <>
              <p>{plan.objective}</p>
              <strong>{topNames(plan.tools, plan.skills, plan.workflows)}</strong>
              <div className="tool-fabric-actions">
                <button type="button" onClick={onOpenSkills}>Author missing skill</button>
                <button type="button" onClick={onOpenWorkflowStarter}>Create workflow</button>
              </div>
            </>
          )}
        </article>

        <section className="resource-manifest-panel" aria-labelledby="resource-manifest-title">
          <div>
            <p className="eyebrow">Resource manifest</p>
            <h3 id="resource-manifest-title">Trust, compatibility, and proof</h3>
            <p>{resourceManifest.summary}</p>
          </div>
          <div className="resource-manifest-list">
            {resourceManifest.items.length === 0 ? (
              <p>Resolve an objective to build a reviewable manifest.</p>
            ) : null}
            {resourceManifest.items.map((item) => (
              <article className={`resource-manifest-item resource-manifest-item--${item.status}`} key={item.id}>
                <div>
                  <span>{manifestStatusLabel(item.status)}</span>
                  <strong>{item.label}</strong>
                  <small>{item.kind}</small>
                </div>
                <p>{item.trustSummary}</p>
                <p>{item.compatibilitySummary}</p>
                <p>{item.evidenceReceipt}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="tool-fabric-column">
          <h3>Tools</h3>
          {plan?.tools.length === 0 ? <p>No matching tools found.</p> : null}
          {(plan?.tools ?? []).map((tool) => (
            <article key={tool.name} className="tool-fabric-card">
              <div>
                <h4>{tool.name}</h4>
                <span>{tool.status} · {scoreLabel(tool.score)}</span>
              </div>
              <p>{tool.description || "No description provided."}</p>
              {tool.tags.length > 0 ? <small>{tool.tags.join(", ")}</small> : null}
            </article>
          ))}
        </section>

        <section className="tool-fabric-column">
          <h3>Skills</h3>
          {plan?.skills.length === 0 ? <p>No matching skills found.</p> : null}
          {(plan?.skills ?? []).map((skill) => (
            <article key={skill.name} className="tool-fabric-card">
              <div>
                <h4>{skill.name}</h4>
                <span>{scoreLabel(skill.score)}{skill.pack ? ` · ${skill.pack}` : ""}</span>
              </div>
              <p>{skill.description || "No description provided."}</p>
              {skill.tags.length > 0 ? <small>{skill.tags.join(", ")}</small> : null}
            </article>
          ))}
        </section>

        <section className="tool-fabric-column">
          <h3>Workflows</h3>
          {plan?.workflows.length === 0 ? <p>No matching workflows found.</p> : null}
          {(plan?.workflows ?? []).map((workflow) => (
            <article key={`${workflow.source}-${workflow.name}`} className="tool-fabric-card">
              <div>
                <h4>{workflow.name}</h4>
                <span>{workflow.source} · {scoreLabel(workflow.score)}</span>
              </div>
              <p>{workflow.description || "No description provided."}</p>
              {workflow.tags.length > 0 ? <small>{workflow.tags.join(", ")}</small> : null}
            </article>
          ))}
        </section>
      </div>
    </section>
  );
}
