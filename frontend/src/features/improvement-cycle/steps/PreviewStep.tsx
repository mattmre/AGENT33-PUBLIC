import { useState } from "react";
import type { WorkflowPresetDefinition } from "../../../types";

interface PreviewStepProps {
  preset: WorkflowPresetDefinition | null;
  filledParams: Record<string, unknown>;
  canExecute: boolean;
  onExecute: () => void;
  isBusy: boolean;
}

function formatValue(val: unknown): string {
  if (val === null || val === undefined) return "(empty)";
  if (typeof val === "string") return val;
  return JSON.stringify(val);
}

export function PreviewStep({
  preset,
  filledParams,
  canExecute,
  onExecute,
  isBusy
}: PreviewStepProps): JSX.Element {
  const [showRawYaml, setShowRawYaml] = useState(false);

  if (!preset) {
    return (
      <section className="wizard-step-content">
        <h3>Preview</h3>
        <p className="wizard-muted">No template selected. Go back to select one.</p>
      </section>
    );
  }

  const paramEntries = Object.entries(filledParams);

  return (
    <section className="wizard-step-content">
      <h3>Preview</h3>

      <div className="wizard-preview-summary">
        <h4>Template</h4>
        <table className="wizard-table">
          <tbody>
            <tr>
              <td>Name</td>
              <td>{preset.workflowName}</td>
            </tr>
            <tr>
              <td>Description</td>
              <td>{preset.description}</td>
            </tr>
            <tr>
              <td>Source</td>
              <td>{preset.sourcePath}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div className="wizard-preview-params">
        <h4>Filled Parameters</h4>
        {paramEntries.length === 0 ? (
          <p className="wizard-muted">No parameters configured.</p>
        ) : (
          <table className="wizard-table">
            <thead>
              <tr>
                <th>Parameter</th>
                <th>Value</th>
              </tr>
            </thead>
            <tbody>
              {paramEntries.map(([key, val]) => (
                <tr key={key}>
                  <td>{key}</td>
                  <td>{formatValue(val)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="wizard-preview-raw">
        <button
          type="button"
          className="wizard-link-button"
          onClick={() => setShowRawYaml(!showRawYaml)}
        >
          {showRawYaml ? "Hide" : "Show"} raw definition
        </button>
        {showRawYaml && (
          <pre className="wizard-code-block">
            {JSON.stringify(preset.workflowDefinition, null, 2)}
          </pre>
        )}
      </div>

      <div className="wizard-actions">
        <button disabled={!canExecute || isBusy} onClick={onExecute}>
          {isBusy ? "Executing..." : "Register and Execute"}
        </button>
      </div>
    </section>
  );
}
