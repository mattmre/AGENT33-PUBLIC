import { useCallback } from "react";

export interface ParameterDef {
  type: string;
  description?: string;
  required?: boolean;
  default?: unknown;
}

interface ParameterFillStepProps {
  inputs: Record<string, ParameterDef>;
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
}

function formatLabel(key: string): string {
  return key
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\b\w/g, (m) => m.toUpperCase());
}

function renderField(
  key: string,
  def: ParameterDef,
  value: unknown,
  onFieldChange: (key: string, val: unknown) => void
): JSX.Element {
  const label = formatLabel(key);
  const helpText = def.description ?? "";

  if (def.type === "integer") {
    return (
      <label key={key}>
        {label}
        {def.required && <span className="wizard-required">*</span>}
        <input
          type="number"
          aria-label={label}
          value={typeof value === "number" ? value : ""}
          onChange={(e) => onFieldChange(key, parseInt(e.target.value, 10) || 0)}
        />
        {helpText && <span className="wizard-help">{helpText}</span>}
      </label>
    );
  }

  if (def.type === "object") {
    const textVal =
      typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 2);
    return (
      <label key={key} className="wizard-textarea">
        {label}
        {def.required && <span className="wizard-required">*</span>}
        <textarea
          aria-label={label}
          rows={4}
          value={textVal}
          onChange={(e) => {
            try {
              onFieldChange(key, JSON.parse(e.target.value));
            } catch {
              onFieldChange(key, e.target.value);
            }
          }}
        />
        {helpText && <span className="wizard-help">{helpText}</span>}
      </label>
    );
  }

  if (def.type === "array") {
    const items = Array.isArray(value) ? value : [];
    const textVal = items.join(", ");
    return (
      <label key={key}>
        {label}
        {def.required && <span className="wizard-required">*</span>}
        <input
          type="text"
          aria-label={label}
          value={textVal}
          placeholder="Comma-separated values"
          onChange={(e) =>
            onFieldChange(
              key,
              e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean)
            )
          }
        />
        {helpText && <span className="wizard-help">{helpText}</span>}
      </label>
    );
  }

  // Default: string
  return (
    <label key={key}>
      {label}
      {def.required && <span className="wizard-required">*</span>}
      <input
        type="text"
        aria-label={label}
        value={typeof value === "string" ? value : ""}
        onChange={(e) => onFieldChange(key, e.target.value)}
      />
      {helpText && <span className="wizard-help">{helpText}</span>}
    </label>
  );
}

export function ParameterFillStep({
  inputs,
  values,
  onChange
}: ParameterFillStepProps): JSX.Element {
  const onFieldChange = useCallback(
    (key: string, val: unknown) => {
      onChange({ ...values, [key]: val });
    },
    [values, onChange]
  );

  const entries = Object.entries(inputs);

  if (entries.length === 0) {
    return (
      <section className="wizard-step-content">
        <h3>Parameters</h3>
        <p className="wizard-muted">This template has no configurable inputs.</p>
      </section>
    );
  }

  const missingRequired = entries.filter(
    ([key, def]) =>
      def.required &&
      (values[key] === undefined || values[key] === "" || values[key] === null)
  );

  return (
    <section className="wizard-step-content">
      <h3>Fill Parameters</h3>
      <p>Configure the template inputs. Required fields are marked with *.</p>
      <div className="wizard-form-grid">
        {entries.map(([key, def]) => renderField(key, def, values[key], onFieldChange))}
      </div>
      {missingRequired.length > 0 && (
        <p className="wizard-warning" role="alert">
          Missing required fields: {missingRequired.map(([k]) => formatLabel(k)).join(", ")}
        </p>
      )}
    </section>
  );
}

export function buildDefaultValues(inputs: Record<string, ParameterDef>): Record<string, unknown> {
  const defaults: Record<string, unknown> = {};
  for (const [key, def] of Object.entries(inputs)) {
    if (def.default !== undefined && def.default !== null) {
      defaults[key] = def.default;
    }
  }
  return defaults;
}

export function validateRequiredInputs(
  inputs: Record<string, ParameterDef>,
  values: Record<string, unknown>
): boolean {
  return Object.entries(inputs).every(([key, def]) => {
    if (!def.required) return true;
    const val = values[key];
    return val !== undefined && val !== null && val !== "";
  });
}
