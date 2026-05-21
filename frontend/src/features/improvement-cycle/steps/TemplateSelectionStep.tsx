import type { WorkflowPresetDefinition } from "../../../types";

interface TemplateSelectionStepProps {
  presets: readonly WorkflowPresetDefinition[];
  selectedPresetId: string;
  onSelect: (presetId: string) => void;
  customYaml: string;
  onCustomYamlChange: (yaml: string) => void;
}

function getStepCount(preset: WorkflowPresetDefinition): number {
  const steps = preset.workflowDefinition?.steps;
  return Array.isArray(steps) ? steps.length : 0;
}

function getInputNames(preset: WorkflowPresetDefinition): string[] {
  const inputs = preset.workflowDefinition?.inputs;
  if (typeof inputs === "object" && inputs !== null && !Array.isArray(inputs)) {
    return Object.keys(inputs as Record<string, unknown>);
  }
  return [];
}

export function TemplateSelectionStep({
  presets,
  selectedPresetId,
  onSelect,
  customYaml,
  onCustomYamlChange
}: TemplateSelectionStepProps): JSX.Element {
  return (
    <section className="wizard-step-content">
      <h3>Select Template</h3>
      <p>Choose a canonical improvement-cycle template or paste custom YAML.</p>
      <div className="wizard-template-grid" role="radiogroup" aria-label="Template selection">
        {presets.map((preset) => (
          <article
            key={preset.id}
            role="radio"
            aria-checked={selectedPresetId === preset.id}
            aria-label={preset.label}
            tabIndex={0}
            className={[
              "wizard-template-card",
              selectedPresetId === preset.id ? "wizard-template-selected" : ""
            ]
              .filter(Boolean)
              .join(" ")}
            onClick={() => onSelect(preset.id)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect(preset.id);
              }
            }}
          >
            <h4>{preset.label}</h4>
            <p className="wizard-muted">{preset.description}</p>
            <div className="wizard-meta">
              <span>Steps: {getStepCount(preset)}</span>
              <span>Source: {preset.sourcePath}</span>
            </div>
            {getInputNames(preset).length > 0 && (
              <div className="wizard-meta">
                <span>
                  Inputs: {getInputNames(preset).join(", ")}
                </span>
              </div>
            )}
          </article>
        ))}

        <article
          role="radio"
          aria-checked={selectedPresetId === "custom"}
          aria-label="Custom template"
          tabIndex={0}
          className={[
            "wizard-template-card",
            selectedPresetId === "custom" ? "wizard-template-selected" : ""
          ]
            .filter(Boolean)
            .join(" ")}
          onClick={() => onSelect("custom")}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onSelect("custom");
            }
          }}
        >
          <h4>Custom</h4>
          <p className="wizard-muted">Paste raw JSON or YAML workflow definition.</p>
        </article>
      </div>

      {selectedPresetId === "custom" && (
        <label className="wizard-textarea">
          Custom workflow definition
          <textarea
            aria-label="Custom workflow YAML"
            rows={12}
            value={customYaml}
            onChange={(e) => onCustomYamlChange(e.target.value)}
            placeholder="Paste your workflow definition here..."
          />
        </label>
      )}
    </section>
  );
}
