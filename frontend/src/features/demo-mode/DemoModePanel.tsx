import { useEffect, useMemo, useState } from "react";

import type { WorkflowStarterDraft } from "../workflow-starter/types";
import type { UserRoleId } from "../role-intake/types";
import { DEMO_SCENARIOS, findDemoScenario, getDefaultDemoScenario } from "./demoScenarios";

interface DemoModePanelProps {
  selectedRole?: UserRoleId | null;
  onOpenModels: () => void;
  onOpenWorkflowCatalog: () => void;
  onOpenWorkflowStarter: (draft?: WorkflowStarterDraft) => void;
}

export function DemoModePanel({
  selectedRole,
  onOpenModels,
  onOpenWorkflowCatalog,
  onOpenWorkflowStarter
}: DemoModePanelProps): JSX.Element {
  const [selectedId, setSelectedId] = useState(getDefaultDemoScenario().id);
  const visibleScenarios = useMemo(() => {
    if (!selectedRole) {
      return DEMO_SCENARIOS;
    }
    const filtered = DEMO_SCENARIOS.filter(
      (item) => item.forRoles === undefined || item.forRoles.includes(selectedRole)
    );
    return filtered.length > 0 ? filtered : DEMO_SCENARIOS;
  }, [selectedRole]);
  const scenario = useMemo(
    () =>
      visibleScenarios.find((item) => item.id === selectedId) ??
      visibleScenarios[0] ??
      findDemoScenario(selectedId),
    [selectedId, visibleScenarios]
  );
  const scenarioIndex = Math.max(
    visibleScenarios.findIndex((item) => item.id === scenario.id) + 1,
    1
  );

  useEffect(() => {
    if (!visibleScenarios.some((item) => item.id === selectedId)) {
      setSelectedId(visibleScenarios[0]?.id ?? getDefaultDemoScenario().id);
    }
  }, [selectedId, visibleScenarios]);

  return (
    <section className="demo-mode-panel" aria-labelledby="demo-mode-title">
      <header className="demo-mode-hero">
        <div>
          <p className="eyebrow">No-setup demo mode</p>
          <h2 id="demo-mode-title">See a first successful run before connecting anything</h2>
          <p>
            Demo Mode uses static sample data to show how AGENT33 should feel once a model and
            workspace are connected: clear intake, visible progress, reviewable artifacts, and a
            safe next action.
          </p>
        </div>
        <div className="demo-mode-score">
          <strong>0 credentials needed</strong>
          <span>Offline preview with no model calls</span>
        </div>
      </header>

      <div className="demo-mode-layout">
        <aside className="demo-mode-picker" aria-label="Demo scenarios">
          <h3>Choose a sample outcome</h3>
          {visibleScenarios.map((item) => (
            <button
              key={item.id}
              type="button"
              className={item.id === scenario.id ? "active" : ""}
              onClick={() => setSelectedId(item.id)}
              aria-pressed={item.id === scenario.id}
            >
              <strong>{item.title}</strong>
              <span>{item.audience}</span>
              <small>
                {item.complexity} · {item.timeEstimate} · {item.artifacts.length} artifacts
              </small>
            </button>
          ))}
        </aside>

        <div className="demo-mode-workspace">
          <article className="demo-mode-card demo-mode-brief">
            <div>
              <p className="eyebrow">{scenario.audience}</p>
              <h3>{scenario.title}</h3>
              <div className="demo-scenario-meta" aria-label="Selected demo details">
                <span>
                  {scenarioIndex} of {visibleScenarios.length}
                </span>
                <span>{scenario.complexity}</span>
                <span>{scenario.timeEstimate}</span>
                <span>{scenario.artifacts.length} artifacts</span>
              </div>
              <p>{scenario.outcome}</p>
            </div>
            <blockquote>{scenario.prompt}</blockquote>
            <div className="demo-mode-inputs">
              {scenario.sampleInputs.map((input, index) => (
                <span key={`${scenario.id}-input-${index}`}>{input}</span>
              ))}
            </div>
          </article>

          <article className="demo-mode-card">
            <h3>Simulated run timeline</h3>
            <ol className="demo-run-timeline">
              {scenario.runSteps.map((step) => (
                <li key={step.id} className={`demo-run-step demo-run-step--${step.tone}`}>
                  <strong>{step.title}</strong>
                  <span>{step.description}</span>
                </li>
              ))}
            </ol>
          </article>

          <section className="demo-artifact-grid" aria-label="Demo artifacts">
            {scenario.artifacts.map((artifact) => (
              <article key={artifact.id} className="demo-mode-card demo-artifact-card">
                <h3>{artifact.title}</h3>
                <p>{artifact.description}</p>
                <ul>
                  {artifact.contents.map((item, index) => (
                    <li key={`${artifact.id}-${index}`}>{item}</li>
                  ))}
                </ul>
              </article>
            ))}
          </section>

          <article className="demo-mode-card demo-mode-next">
            <div>
              <h3>Ready to make it real?</h3>
              <p>
                Keep exploring without setup, or connect a model and send this sample into Workflow
                Starter as an editable draft.
              </p>
            </div>
            <div className="demo-mode-actions">
              <button type="button" onClick={onOpenModels}>
                Connect a model
              </button>
              <button type="button" onClick={onOpenWorkflowCatalog}>
                Browse workflow catalog
              </button>
              <button type="button" onClick={() => onOpenWorkflowStarter(scenario.starterDraft)}>
                Customize this demo
              </button>
            </div>
          </article>
        </div>
      </div>
    </section>
  );
}
