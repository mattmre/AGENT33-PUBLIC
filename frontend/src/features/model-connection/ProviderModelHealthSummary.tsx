import type { ProviderPresetId } from "./presets";

export type LocalProviderHealthState = "available" | "empty" | "unavailable" | "error";
export type LocalModelHealthState = "ready" | "needs_attention" | "unavailable";

export interface LocalProviderHealth {
  provider: "ollama" | "lm-studio" | "local-orchestration";
  label: string;
  state: LocalProviderHealthState;
  ok: boolean;
  baseUrl: string;
  defaultModel: string;
  modelCount: number;
  message: string;
  action: string;
}

export interface LocalModelHealth {
  overallState: LocalModelHealthState;
  summary: string;
  readyProviderCount: number;
  attentionProviderCount: number;
  totalModelCount: number;
  providers: LocalProviderHealth[];
}

interface ProviderModelHealthSummaryProps {
  health: LocalModelHealth | null;
  isLoading: boolean;
  hasCredentials: boolean;
  selectedPresetId: ProviderPresetId;
  selectedProviderName: string;
  onRefresh: () => void;
}

const STATE_LABELS: Record<LocalProviderHealthState, string> = {
  available: "Ready",
  empty: "Needs a model",
  unavailable: "Offline",
  error: "Check setup"
};

const STATE_TONES: Record<LocalProviderHealthState, "success" | "warning" | "error"> = {
  available: "success",
  empty: "warning",
  unavailable: "error",
  error: "error"
};

export function ProviderModelHealthSummary({
  health,
  isLoading,
  hasCredentials,
  selectedPresetId,
  selectedProviderName,
  onRefresh
}: ProviderModelHealthSummaryProps): JSX.Element {
  const providers = health?.providers ?? [];
  const selectedLocalProvider =
    selectedPresetId === "ollama" ||
    selectedPresetId === "lm-studio" ||
    selectedPresetId === "local-runtime"
      ? selectedProviderName
      : "";
  const summary = hasCredentials
    ? health?.summary ??
      "Check Ollama, LM Studio, and the startup runtime before choosing a local model."
    : "Connect engine access first so AGENT-33 can check local model health.";

  return (
    <section className="model-health-summary" aria-labelledby="model-health-summary-title">
      <div className="model-health-summary-head">
        <div>
          <p className="eyebrow">Local model health</p>
          <h3 id="model-health-summary-title">One place to see what can run now</h3>
          <p>{summary}</p>
        </div>
        <button type="button" onClick={onRefresh} disabled={!hasCredentials || isLoading}>
          {isLoading ? "Checking..." : "Refresh local health"}
        </button>
      </div>

      <div className="model-health-kpis" aria-label="Local runtime readiness">
        <span>
          <strong>{health?.readyProviderCount ?? 0}</strong>
          ready
        </span>
        <span>
          <strong>{health?.totalModelCount ?? 0}</strong>
          models detected
        </span>
        <span>
          <strong>{health?.attentionProviderCount ?? 0}</strong>
          need attention
        </span>
      </div>

      <div className="model-health-provider-grid">
        {providers.map((provider) => (
          <article
            key={provider.provider}
            className={`model-health-provider model-health-provider--${STATE_TONES[provider.state]}`}
          >
            <div>
              <strong>{provider.label}</strong>
              <span>{STATE_LABELS[provider.state]}</span>
            </div>
            <p>{provider.message}</p>
            <small>
              {provider.modelCount} {provider.modelCount === 1 ? "model" : "models"} detected
              {provider.baseUrl ? ` at ${provider.baseUrl}` : ""}
            </small>
            {provider.defaultModel ? <small>Configured default: {provider.defaultModel}</small> : null}
            <small>{provider.action}</small>
          </article>
        ))}
      </div>

      {selectedLocalProvider ? (
        <p className="model-health-summary-note">
          You are editing {selectedLocalProvider}; refresh after changing its Base URL or loading a
          model.
        </p>
      ) : (
        <p className="model-health-summary-note">
          Cloud providers still use the Test connection button; this card only checks local runtimes.
        </p>
      )}
    </section>
  );
}
