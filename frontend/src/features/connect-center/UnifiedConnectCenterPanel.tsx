import { useCallback, useEffect, useMemo, useState } from "react";

import type { ApiResult } from "../../types";
import { asOnboardingStatus, fetchOnboardingStatus } from "../onboarding/api";
import type { OnboardingStatus } from "../onboarding/types";
import { asDoctorStatusResponse, fetchDoctorStatus } from "./api";
import {
  buildConnectCards,
  buildDoctorChecks,
  buildFirstSuccessPath,
  buildLiveDoctorChecks,
  getConnectScore
} from "./helpers";
import type { ConnectStatus, ConnectTarget, DoctorCheckStatus } from "./types";

interface UnifiedConnectCenterPanelProps {
  token: string;
  apiKey: string;
  onNavigate: (target: ConnectTarget) => void;
  onResult: (label: string, result: ApiResult) => void;
}

function statusLabel(status: ConnectStatus): string {
  const labels: Record<ConnectStatus, string> = {
    ready: "Ready",
    attention: "Needs attention",
    unknown: "Unknown"
  };
  return labels[status];
}

function doctorStatusLabel(status: DoctorCheckStatus): string {
  const labels: Record<DoctorCheckStatus, string> = {
    ready: "Ready",
    blocked: "Blocked",
    inspect: "Inspect"
  };
  return labels[status];
}

export function UnifiedConnectCenterPanel({
  token,
  apiKey,
  onNavigate,
  onResult
}: UnifiedConnectCenterPanelProps): JSX.Element {
  const safeToken = token ?? "";
  const safeApiKey = apiKey ?? "";
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
  const [liveDoctorChecks, setLiveDoctorChecks] = useState<ReturnType<typeof buildLiveDoctorChecks>>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const hasCredentials = safeToken.trim() !== "" || safeApiKey.trim() !== "";
  const cards = useMemo(() => buildConnectCards(hasCredentials, status), [hasCredentials, status]);
  const doctorChecks = useMemo(
    () => (liveDoctorChecks.length > 0 ? liveDoctorChecks : buildDoctorChecks(cards)),
    [cards, liveDoctorChecks]
  );
  const firstSuccessPath = useMemo(() => buildFirstSuccessPath(cards), [cards]);
  const score = getConnectScore(cards);
  const nextAttention =
    cards.find((card) => card.status === "attention") ??
    cards.find((card) => card.status === "unknown") ??
    cards[0];

  const refresh = useCallback(async (): Promise<void> => {
    if (!hasCredentials) {
      setStatus(null);
      setLiveDoctorChecks([]);
      setError("");
      return;
    }

    setLoading(true);
    setError("");
    try {
      const result = await fetchOnboardingStatus(safeToken, safeApiKey);
      onResult("Connect Center - Readiness", result);
      const doctorResult = await fetchDoctorStatus(safeToken, safeApiKey);
      onResult("Doctor Center - Status", doctorResult);
      const parsed = asOnboardingStatus(result.data);
      if (!result.ok || parsed === null) {
        setError(!result.ok ? `Connection scan failed (${result.status})` : "Received invalid readiness data.");
        return;
      }
      setStatus(parsed);
      const doctorStatus = asDoctorStatusResponse(doctorResult.data);
      if (doctorResult.ok && doctorStatus !== null) {
        setLiveDoctorChecks(buildLiveDoctorChecks(doctorStatus.findings));
      }
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : "Unknown connection scan error");
    } finally {
      setLoading(false);
    }
  }, [hasCredentials, onResult, safeApiKey, safeToken]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <section className="connect-center-panel" aria-labelledby="connect-center-title">
      <header className="connect-center-hero">
        <div>
          <p className="eyebrow">Unified setup</p>
          <h2 id="connect-center-title">Connect the pieces AGENT-33 needs to work</h2>
          <p>
            One readable checklist for engine access, model providers, integrations, MCP tools,
            tool catalog visibility, and safe approvals. Each card routes to the existing setup
            surface instead of making users hunt through settings.
          </p>
        </div>
        <div className="connect-center-score">
          <strong>{loading ? "Scanning..." : score}</strong>
          <span>{hasCredentials ? "Live readiness when available" : "Add access to scan live status"}</span>
        </div>
      </header>

      <article className="connect-center-next">
        <div>
          <p className="eyebrow">Recommended next connection</p>
          <h3>{nextAttention.title}</h3>
          <p>{nextAttention.detail}</p>
        </div>
        <div className="connect-center-actions">
          <button type="button" onClick={() => void refresh()} disabled={loading}>
            {loading ? "Refreshing..." : "Refresh connection scan"}
          </button>
          <button type="button" onClick={() => onNavigate(nextAttention.target)}>
            {nextAttention.actionLabel}
          </button>
        </div>
      </article>

      {error ? (
        <p className="connect-center-error" role="alert">
          {error}
        </p>
      ) : null}

      <section className="doctor-center-panel" aria-labelledby="doctor-center-title">
        <div className="doctor-center-summary">
          <div>
            <p className="eyebrow">Doctor Center</p>
            <h3 id="doctor-center-title">First-success readiness</h3>
            <p>{firstSuccessPath.proof}</p>
          </div>
          <div className={`first-success-card ${firstSuccessPath.ready ? "first-success-card--ready" : ""}`}>
            <strong>{firstSuccessPath.title}</strong>
            <ol>
              {firstSuccessPath.steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          </div>
        </div>
        <div className="doctor-check-grid">
          {doctorChecks.map((check) => (
            <article className={`doctor-check doctor-check--${check.status}`} key={check.id}>
              <span>{doctorStatusLabel(check.status)}</span>
              <strong>{check.title}</strong>
              {check.owner ? <small>Owner: {check.owner}</small> : null}
              <p>{check.diagnosis}</p>
              <p>{check.remediation}</p>
              {check.evidenceRefs && check.evidenceRefs.length > 0 ? (
                <small>{check.evidenceRefs.join(", ")}</small>
              ) : null}
            </article>
          ))}
        </div>
      </section>

      <div className="connect-center-grid">
        {cards.map((card) => (
          <article className={`connect-card connect-card--${card.status}`} key={card.id}>
            <div className="connect-card-head">
              <span>{statusLabel(card.status)}</span>
              <strong>{card.title}</strong>
            </div>
            <h3>{card.plainLabel}</h3>
            <p>{card.detail}</p>
            <p>{card.impact}</p>
            <dl className="connect-card-verification">
              <div>
                <dt>Test</dt>
                <dd>{card.verification.testAction}</dd>
              </div>
              <div>
                <dt>Health</dt>
                <dd>{card.verification.healthExplanation}</dd>
              </div>
              <div>
                <dt>Setup</dt>
                <dd>{card.verification.setupHint}</dd>
              </div>
            </dl>
            <button type="button" onClick={() => onNavigate(card.target)}>
              {card.actionLabel}
            </button>
          </article>
        ))}
      </div>
    </section>
  );
}
