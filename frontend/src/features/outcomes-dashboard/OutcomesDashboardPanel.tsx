import { useCallback, useEffect, useMemo, useState } from "react";

import type { ApiResult } from "../../types";
import {
  asOutcomeDashboardResponse,
  asOutcomeTrend,
  fetchOutcomeTrend,
  fetchOutcomesDashboard,
  submitImprovementIntake
} from "./api";
import {
  buildDeclineIntakePayload,
  decliningTrends,
  filterTrends,
  formatMetricValue,
  metricLabel,
  sparklinePoints
} from "./helpers";
import type {
  OutcomeDashboardResponse,
  OutcomeMetricType,
  OutcomeTrend,
  SubmitIntakeRequest
} from "./types";

interface OutcomesDashboardPanelProps {
  token: string;
  apiKey: string;
  onResult: (label: string, result: ApiResult) => void;
}

function TrendSparkline({ values }: { values: number[] }): JSX.Element {
  if (values.length < 2) {
    return <span className="trend-empty">Not enough samples</span>;
  }
  return (
    <svg className="trend-sparkline" viewBox="0 0 100 32" preserveAspectRatio="none" role="img" aria-label={`Trend sparkline with ${values.length} data points`}>
      <polyline points={sparklinePoints(values, 100, 28)} fill="none" stroke="currentColor" />
    </svg>
  );
}

export function OutcomesDashboardPanel({
  token,
  apiKey,
  onResult
}: OutcomesDashboardPanelProps): JSX.Element {
  const [domainFilter, setDomainFilter] = useState("");
  const [windowSize, setWindowSize] = useState(20);
  const [metricFilter, setMetricFilter] = useState<OutcomeMetricType | "all">("all");
  const [dashboard, setDashboard] = useState<OutcomeDashboardResponse | null>(null);
  const [selectedTrend, setSelectedTrend] = useState<OutcomeTrend | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showIntakeForm, setShowIntakeForm] = useState(false);
  const [submittedBy, setSubmittedBy] = useState("dashboard-operator");
  const [intakeDraft, setIntakeDraft] = useState<SubmitIntakeRequest | null>(null);
  const [intakeStatus, setIntakeStatus] = useState("");
  const [submittingIntake, setSubmittingIntake] = useState(false);

  const loadDashboard = useCallback(async (): Promise<void> => {
    if (!token && !apiKey) {
      return;
    }
    setLoading(true);
    try {
      const result = await fetchOutcomesDashboard(token, apiKey, domainFilter, windowSize);
      onResult("Outcomes Dashboard", result);
      const parsed = asOutcomeDashboardResponse(result.data);
      if (!result.ok || parsed === null) {
        setError(`Unable to load dashboard (${result.status})`);
        return;
      }
      setError("");
      setDashboard(parsed);
      const firstTrend = filterTrends(parsed.trends, metricFilter)[0] ?? null;
      setSelectedTrend(firstTrend);
    } catch (loadError) {
      const message = loadError instanceof Error ? loadError.message : "Unknown outcomes error";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [apiKey, domainFilter, metricFilter, onResult, token, windowSize]);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  const visibleTrends = useMemo(() => {
    return filterTrends(dashboard?.trends ?? [], metricFilter);
  }, [dashboard?.trends, metricFilter]);

  const declining = useMemo(() => {
    return decliningTrends(visibleTrends);
  }, [visibleTrends]);

  async function refreshTrend(metricType: OutcomeMetricType): Promise<void> {
    const result = await fetchOutcomeTrend(token, apiKey, metricType, domainFilter, windowSize);
    onResult(`Outcome Trend ${metricType}`, result);
    const parsed = asOutcomeTrend(result.data);
    if (result.ok && parsed) {
      setSelectedTrend(parsed);
    }
  }

  function openDeclineIntake(trend: OutcomeTrend): void {
    setIntakeDraft(buildDeclineIntakePayload(trend, domainFilter, submittedBy));
    setShowIntakeForm(true);
    setIntakeStatus("");
  }

  async function submitDeclineIntake(): Promise<void> {
    if (intakeDraft === null) {
      return;
    }
    setSubmittingIntake(true);
    try {
      const result = await submitImprovementIntake(token, apiKey, intakeDraft);
      onResult("Submit Improvement Intake", result);
      if (!result.ok) {
        setIntakeStatus(`Failed to submit intake (${result.status})`);
        return;
      }
      setIntakeStatus("Improvement intake submitted successfully.");
      setShowIntakeForm(false);
    } catch (submitError) {
      const message = submitError instanceof Error ? submitError.message : "Unknown submit error";
      setIntakeStatus(message);
    } finally {
      setSubmittingIntake(false);
    }
  }

  return (
    <section className="outcomes-dashboard-panel">
      <header className="outcomes-head">
        <div>
          <h2>Outcomes Dashboard</h2>
          <p>Trend analysis, domain filtering, and decline-triggered improvements.</p>
        </div>
        <div className="outcomes-filters">
          <label>
            Domain
            <input
              placeholder="all domains"
              value={domainFilter}
              onChange={(event) => setDomainFilter(event.target.value)}
            />
          </label>
          <label>
            Window
            <select
              value={windowSize}
              onChange={(event) => setWindowSize(Number(event.target.value) || 20)}
            >
              <option value={10}>10 samples</option>
              <option value={20}>20 samples</option>
              <option value={40}>40 samples</option>
            </select>
          </label>
          <label>
            Metric
            <select
              value={metricFilter}
              onChange={(event) =>
                setMetricFilter(event.target.value as OutcomeMetricType | "all")
              }
            >
              <option value="all">All metrics</option>
              <option value="success_rate">Success Rate</option>
              <option value="quality_score">Quality Score</option>
              <option value="latency_ms">Latency (ms)</option>
              <option value="cost_usd">Cost (USD)</option>
            </select>
          </label>
          <button onClick={() => loadDashboard()} disabled={loading}>
            Refresh
          </button>
        </div>
      </header>

      {error ? <p className="outcomes-error" role="alert">{error}</p> : null}

      {dashboard ? (
        <div className="outcomes-summary">
          <span>Total events: {dashboard.summary.total_events}</span>
          <span>Domains: {dashboard.summary.domains.join(", ") || "n/a"}</span>
        </div>
      ) : null}

      {declining.length > 0 ? (
        <section className="decline-alert">
          <h3>Declining trend detected</h3>
          <p>
            {metricLabel(declining[0].metric_type)} is declining. Create a linked improvement intake to
            begin mitigation.
          </p>
          <button onClick={() => openDeclineIntake(declining[0])}>Create Improvement Intake</button>
        </section>
      ) : null}

      {showIntakeForm && intakeDraft ? (
        <section className="intake-form">
          <h3>Create Improvement Intake</h3>
          <label>
            Submitted By
            <input
              value={submittedBy}
              onChange={(event) => {
                setSubmittedBy(event.target.value);
                setIntakeDraft({ ...intakeDraft, submitted_by: event.target.value });
              }}
            />
          </label>
          <label>
            Title
            <input
              value={intakeDraft.title}
              onChange={(event) => setIntakeDraft({ ...intakeDraft, title: event.target.value })}
            />
          </label>
          <label>
            Summary
            <textarea
              rows={4}
              value={intakeDraft.summary}
              onChange={(event) => setIntakeDraft({ ...intakeDraft, summary: event.target.value })}
            />
          </label>
          <div className="intake-actions">
            <button onClick={() => submitDeclineIntake()} disabled={submittingIntake}>
              {submittingIntake ? "Submitting..." : "Submit Intake"}
            </button>
            <button onClick={() => setShowIntakeForm(false)} type="button">
              Cancel
            </button>
          </div>
        </section>
      ) : null}

      {intakeStatus ? <p className="outcomes-note">{intakeStatus}</p> : null}

      <div className="trend-grid">
        {visibleTrends.map((trend) => (
          <article
            key={trend.metric_type}
            className={`trend-card ${selectedTrend?.metric_type === trend.metric_type ? "selected" : ""}`}
            onClick={() => {
              void refreshTrend(trend.metric_type);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                void refreshTrend(trend.metric_type);
              }
            }}
            tabIndex={0}
            role="button"
            aria-pressed={selectedTrend?.metric_type === trend.metric_type}
          >
            <header>
              <h3>{metricLabel(trend.metric_type)}</h3>
              <span className={`trend-direction trend-${trend.direction}`}>{trend.direction}</span>
            </header>
            <TrendSparkline values={trend.values} />
            <p>
              Prev: {formatMetricValue(trend.metric_type, trend.previous_avg)} | Current:{" "}
              {formatMetricValue(trend.metric_type, trend.current_avg)}
            </p>
          </article>
        ))}
      </div>

      <section className="events-panel">
        <h3>Recent Events</h3>
        {(dashboard?.recent_events ?? []).length === 0 ? (
          <p className="outcomes-note">No events recorded for current filters.</p>
        ) : (
          <div className="events-table">
            {(dashboard?.recent_events ?? []).map((event) => (
              <article key={event.id} className="event-row">
                <p className="event-time">{new Date(event.occurred_at).toLocaleString()}</p>
                <p>{event.domain}</p>
                <p>{metricLabel(event.metric_type)}</p>
                <p>{formatMetricValue(event.metric_type, event.value)}</p>
              </article>
            ))}
          </div>
        )}
      </section>
    </section>
  );
}
