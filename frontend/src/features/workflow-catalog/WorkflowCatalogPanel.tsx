import { useMemo, useState } from "react";

import { OUTCOME_WORKFLOWS, buildWorkflowDraft } from "../outcome-home/catalog";
import type { OutcomeWorkflow } from "../outcome-home/types";
import type { WorkflowStarterDraft } from "../workflow-starter/types";
import { ProductWorkflowDetail } from "./ProductWorkflowDetail";
import {
  filterWorkflowCatalog,
  getDefaultWorkflowCatalogFilters,
  getWorkflowCatalogTags,
  type WorkflowCatalogFilters
} from "./filters";

interface WorkflowCatalogPanelProps {
  onOpenWorkflowStarter: (draft?: WorkflowStarterDraft) => void;
  onOpenSetup: () => void;
  onOpenOperations: () => void;
}

const KIND_LABELS: Record<WorkflowCatalogFilters["kind"], string> = {
  all: "All workflow types",
  research: "Research",
  "improvement-loop": "Improvement loop",
  "automation-loop": "Automation loop"
};

const SAFETY_LABELS: Record<WorkflowCatalogFilters["safetyLevel"], string> = {
  all: "All safety levels",
  "Plan-only": "Plan-only",
  "Review-gated": "Review-gated",
  "Autopilot-ready": "Autopilot-ready"
};

function getWorkflowKeyFacts(workflow: OutcomeWorkflow): string[] {
  return [
    workflow.kind.replace("-", " "),
    workflow.safetyLevel,
    workflow.estimatedTime,
    `${workflow.deliverables.length} deliverables`
  ];
}

export function WorkflowCatalogPanel({
  onOpenWorkflowStarter,
  onOpenSetup,
  onOpenOperations
}: WorkflowCatalogPanelProps): JSX.Element {
  const [filters, setFilters] = useState<WorkflowCatalogFilters>(getDefaultWorkflowCatalogFilters);
  const [selectedId, setSelectedId] = useState(OUTCOME_WORKFLOWS[0]?.id ?? "");

  const tags = useMemo(() => getWorkflowCatalogTags(OUTCOME_WORKFLOWS), []);
  const workflows = useMemo(() => filterWorkflowCatalog(OUTCOME_WORKFLOWS, filters), [filters]);
  const selectedWorkflow = useMemo(
    () =>
      workflows.find((workflow) => workflow.id === selectedId) ?? workflows[0] ?? null,
    [selectedId, workflows]
  );

  function updateFilter<K extends keyof WorkflowCatalogFilters>(
    key: K,
    value: WorkflowCatalogFilters[K]
  ): void {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  function resetFilters(): void {
    setFilters(getDefaultWorkflowCatalogFilters());
    setSelectedId(OUTCOME_WORKFLOWS[0]?.id ?? "");
  }

  function useWorkflow(workflow: OutcomeWorkflow): void {
    onOpenWorkflowStarter(buildWorkflowDraft(workflow));
  }

  return (
    <section className="workflow-catalog-panel" aria-labelledby="workflow-catalog-page-title">
      <header className="workflow-catalog-hero">
        <div>
          <p className="eyebrow">Workflow Catalog</p>
          <h2 id="workflow-catalog-page-title">Pick a complete system, not a blank prompt</h2>
          <p>
            Browse baked-in workflows with clear inputs, outputs, safety posture, and launch paths.
            Each card opens in Workflow Starter as an editable plan before anything runs.
          </p>
        </div>
        <div className="workflow-catalog-stats" aria-label="Catalog size">
          <strong>{OUTCOME_WORKFLOWS.length}</strong>
          <span>ready-to-customize workflows</span>
        </div>
      </header>

      <div className="workflow-catalog-controls">
        <label>
          Search outcomes
          <input
            value={filters.query}
            onChange={(event) => updateFilter("query", event.target.value)}
            placeholder="landing page, security review, SaaS, enterprise program..."
          />
        </label>
        <label>
          Workflow type
          <select
            value={filters.kind}
            onChange={(event) =>
              updateFilter("kind", event.target.value as WorkflowCatalogFilters["kind"])
            }
          >
            {Object.entries(KIND_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Safety
          <select
            value={filters.safetyLevel}
            onChange={(event) =>
              updateFilter("safetyLevel", event.target.value as WorkflowCatalogFilters["safetyLevel"])
            }
          >
            {Object.entries(SAFETY_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Category
          <select value={filters.tag} onChange={(event) => updateFilter("tag", event.target.value)}>
            <option value="all">All categories</option>
            {tags.map((tag) => (
              <option key={tag} value={tag}>
                {tag}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="workflow-catalog-layout">
        <div className="workflow-catalog-list" aria-label="Workflow catalog results">
          <div className="workflow-catalog-results-head">
            <span>{workflows.length} workflows match</span>
            <button type="button" onClick={resetFilters}>
              Reset filters
            </button>
          </div>
          {workflows.length === 0 ? (
            <article className="workflow-catalog-empty">
              <h3>No workflow matches yet</h3>
              <p>Clear filters or try a broader outcome like product, data, research, or release.</p>
              <button type="button" onClick={resetFilters}>
                Show all workflows
              </button>
            </article>
          ) : null}
          {workflows.map((workflow) => (
            <button
              type="button"
              key={workflow.id}
              className={`workflow-catalog-card ${workflow.id === selectedWorkflow?.id ? "active" : ""}`}
              onClick={() => setSelectedId(workflow.id)}
            >
              <span>{workflow.audience}</span>
              <strong>{workflow.title}</strong>
              <small>{workflow.summary}</small>
              <div>
                {getWorkflowKeyFacts(workflow).map((fact) => (
                  <em key={fact}>{fact}</em>
                ))}
              </div>
            </button>
          ))}
        </div>

        {selectedWorkflow ? (
          <ProductWorkflowDetail
            workflow={selectedWorkflow}
            onUseWorkflow={useWorkflow}
            onOpenSetup={onOpenSetup}
            onOpenOperations={onOpenOperations}
          />
        ) : null}
      </div>
    </section>
  );
}
