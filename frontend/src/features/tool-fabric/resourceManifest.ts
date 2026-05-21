import type {
  FabricPlan,
  ResourceManifest,
  ResourceManifestItem,
  ResourceManifestStatus,
  SkillDiscoveryMatch,
  ToolDiscoveryMatch,
  WorkflowResolutionMatch
} from "./types";

function statusFromScore(score: number): ResourceManifestStatus {
  if (score >= 0.75) {
    return "ready";
  }
  if (score > 0) {
    return "needs-review";
  }
  return "missing";
}

function toolTrust(tool: ToolDiscoveryMatch): string {
  return tool.status === "active"
    ? "Callable tool is active in discovery."
    : `Tool is ${tool.status}; require operator review before use.`;
}

function skillTrust(skill: SkillDiscoveryMatch): string {
  return skill.pack ? `Skill is provided by pack ${skill.pack}.` : "Skill is runtime-local or unpacked.";
}

function workflowTrust(workflow: WorkflowResolutionMatch): string {
  return workflow.source_path
    ? `Workflow source is ${workflow.source_path}.`
    : "Workflow source path is unavailable.";
}

function itemEvidence(kind: ResourceManifestItem["kind"], label: string): string {
  return `${kind}:${label} must appear in the run ledger proof before completion is accepted.`;
}

function toolItem(tool: ToolDiscoveryMatch): ResourceManifestItem {
  return {
    id: `tool:${tool.name}`,
    label: tool.name,
    kind: "tool",
    status: statusFromScore(tool.score),
    trustSummary: toolTrust(tool),
    compatibilitySummary: `${Math.round(tool.score * 100)}% objective match with ${tool.tags.length} tag${tool.tags.length === 1 ? "" : "s"}.`,
    evidenceReceipt: itemEvidence("tool", tool.name)
  };
}

function skillItem(skill: SkillDiscoveryMatch): ResourceManifestItem {
  return {
    id: `skill:${skill.name}`,
    label: skill.name,
    kind: "skill",
    status: statusFromScore(skill.score),
    trustSummary: skillTrust(skill),
    compatibilitySummary: `${Math.round(skill.score * 100)}% objective match; install or author a replacement if missing.`,
    evidenceReceipt: itemEvidence("skill", skill.name)
  };
}

function workflowItem(workflow: WorkflowResolutionMatch): ResourceManifestItem {
  return {
    id: `workflow:${workflow.source}:${workflow.name}`,
    label: workflow.name,
    kind: "workflow",
    status: statusFromScore(workflow.score),
    trustSummary: workflowTrust(workflow),
    compatibilitySummary: `${Math.round(workflow.score * 100)}% workflow match from ${workflow.source}.`,
    evidenceReceipt: itemEvidence("workflow", workflow.name)
  };
}

export function buildResourceManifest(plan: FabricPlan): ResourceManifest {
  const items = [
    ...plan.tools.slice(0, 3).map(toolItem),
    ...plan.skills.slice(0, 2).map(skillItem),
    ...plan.workflows.slice(0, 2).map(workflowItem)
  ];
  const readyCount = items.filter((item) => item.status === "ready").length;
  const reviewCount = items.filter((item) => item.status === "needs-review").length;

  return {
    objective: plan.objective,
    items,
    summary:
      items.length === 0
        ? "No resource manifest yet; resolve an objective to collect compatible tools, skills, and workflows."
        : `${readyCount} ready resource${readyCount === 1 ? "" : "s"}, ${reviewCount} requiring review.`
  };
}
