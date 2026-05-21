import type { OutcomeWorkflow } from "../outcome-home/types";
import type { WorkflowStarterDraft } from "../workflow-starter/types";
import { productizeWorkflow } from "../outcome-home/productization";

interface ProductWorkflowDetailProps {
  workflow: OutcomeWorkflow;
  onUseWorkflow: (workflow: OutcomeWorkflow) => void;
  onOpenSetup: () => void;
  onOpenOperations: () => void;
}

const RISK_LABELS = {
  low: "Low risk",
  medium: "Review needed",
  high: "High autonomy"
} as const;

export function ProductWorkflowDetail({
  workflow,
  onUseWorkflow,
  onOpenSetup,
  onOpenOperations
}: ProductWorkflowDetailProps): JSX.Element {
  const product = productizeWorkflow(workflow);

  return (
    <aside className="workflow-catalog-detail product-workflow-detail" aria-label="Selected workflow details">
      <div>
        <p className="eyebrow">{workflow.audience}</p>
        <h3>{workflow.title}</h3>
        <p>{workflow.summary}</p>
      </div>

      <section className="product-workflow-estimates" aria-label="Workflow estimates">
        <span>{product.estimate.duration}</span>
        <span>{product.estimate.cost}</span>
        <span className={`product-risk product-risk--${product.estimate.risk}`}>
          {RISK_LABELS[product.estimate.risk]}
        </span>
      </section>

      <section>
        <h4>What you need before launch</h4>
        <ul>
          {product.inputs.map((input) => (
            <li key={input.id}>
              <strong>{input.label}</strong>
              <span>{input.required ? " Required" : " Optional"}</span>
              <small>{input.helperText}</small>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h4>Example outputs</h4>
        <div className="product-output-grid">
          {product.exampleOutputs.map((output) => (
            <article key={output.title}>
              <strong>{output.title}</strong>
              <span>{output.format}</span>
              <pre>{output.preview}</pre>
            </article>
          ))}
        </div>
      </section>

      <section>
        <h4>Dry-run preview</h4>
        <ol className="product-dry-run-list">
          {product.dryRunSteps.map((step) => (
            <li key={step.id}>
              <strong>{step.title}</strong>
              <span>{step.description}</span>
            </li>
          ))}
        </ol>
      </section>

      <section>
        <h4>Starter pack</h4>
        <ul>
          {product.starterPack.map((item) => (
            <li key={item.label}>
              <strong>{item.label}</strong>
              <small>{item.reason}</small>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h4>What AGENT-33 will prepare</h4>
        <p>{workflow.output}</p>
      </section>

      <section>
        <h4>Before launch</h4>
        <ul>
          {workflow.requires.map((requirement) => (
            <li key={requirement}>{requirement}</li>
          ))}
        </ul>
      </section>

      <div className="workflow-catalog-tag-row">
        {workflow.tags.map((tag) => (
          <span key={tag}>{tag}</span>
        ))}
      </div>

      <div className="workflow-catalog-actions">
        <button type="button" onClick={() => onUseWorkflow(workflow)}>
          Customize in Workflow Starter
        </button>
        <button type="button" onClick={onOpenSetup}>
          Connect models first
        </button>
        <button type="button" onClick={onOpenOperations}>
          View running work
        </button>
      </div>
    </aside>
  );
}

export type ProductWorkflowDraftBuilder = (workflow: OutcomeWorkflow) => WorkflowStarterDraft;
