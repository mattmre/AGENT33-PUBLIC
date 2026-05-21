import type { StarterKind } from "../workflow-starter/types";
import type { OutcomeWorkflow } from "../outcome-home/types";

export interface WorkflowCatalogFilters {
  query: string;
  kind: StarterKind | "all";
  safetyLevel: OutcomeWorkflow["safetyLevel"] | "all";
  tag: string;
}

const DEFAULT_FILTERS: WorkflowCatalogFilters = {
  query: "",
  kind: "all",
  safetyLevel: "all",
  tag: "all"
};

export function getDefaultWorkflowCatalogFilters(): WorkflowCatalogFilters {
  return { ...DEFAULT_FILTERS };
}

export function getWorkflowCatalogTags(workflows: OutcomeWorkflow[]): string[] {
  const tags = new Set<string>();
  workflows.forEach((workflow) => workflow.tags.forEach((tag) => tags.add(tag)));
  return [...tags].sort((a, b) => a.localeCompare(b));
}

export function filterWorkflowCatalog(
  workflows: OutcomeWorkflow[],
  filters: WorkflowCatalogFilters
): OutcomeWorkflow[] {
  const queryTerms = filters.query
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .split(/\s+/)
    .filter(Boolean);

  return workflows.filter((workflow) => {
    const searchableText = [
      workflow.title,
      workflow.audience,
      workflow.summary,
      workflow.goal,
      workflow.output,
      ...workflow.deliverables,
      ...workflow.requires,
      ...workflow.tags
    ]
      .join(" ")
      .toLowerCase();

    const matchesQuery =
      queryTerms.length === 0 || queryTerms.every((term) => searchableText.includes(term));

    const matchesKind = filters.kind === "all" || workflow.kind === filters.kind;
    const matchesSafety =
      filters.safetyLevel === "all" || workflow.safetyLevel === filters.safetyLevel;
    const matchesTag = filters.tag === "all" || workflow.tags.includes(filters.tag);

    return matchesQuery && matchesKind && matchesSafety && matchesTag;
  });
}
