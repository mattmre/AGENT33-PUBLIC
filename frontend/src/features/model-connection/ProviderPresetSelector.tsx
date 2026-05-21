import type { ProviderPreset, ProviderPresetId } from "./presets";

interface ProviderPresetSelectorProps {
  presets: ProviderPreset[];
  selectedPresetId: ProviderPresetId;
  onSelectPreset: (preset: ProviderPreset) => void;
}

export function ProviderPresetSelector({
  presets,
  selectedPresetId,
  onSelectPreset
}: ProviderPresetSelectorProps): JSX.Element {
  return (
    <section className="model-wizard-card model-provider-paths" aria-labelledby="provider-paths-title">
      <span>Step 0</span>
      <div>
        <h3 id="provider-paths-title">Pick your model provider path</h3>
        <p>Choose the setup that matches how you want AGENT-33 to call a model.</p>
      </div>
      <div className="provider-preset-grid" role="group" aria-label="Provider setup paths">
        {presets.map((preset) => (
          <button
            type="button"
            key={preset.id}
            className={`provider-preset-card${selectedPresetId === preset.id ? " active" : ""}`}
            aria-pressed={selectedPresetId === preset.id}
            onClick={() => onSelectPreset(preset)}
          >
            <span className="provider-preset-badge">{preset.badge}</span>
            <strong>{preset.name}</strong>
            <span>{preset.description}</span>
            <small>
              {preset.bestFor} · {preset.setupTime}
            </small>
          </button>
        ))}
      </div>
    </section>
  );
}
