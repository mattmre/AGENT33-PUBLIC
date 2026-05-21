import { useState, useEffect } from "react";
import { getRuntimeConfig } from "../../lib/api";
import {
    buildRunDashboardCards,
    type RunDashboardCard,
} from "./runSummary";

export function SessionsDashboard({ token }: { token: string | null }) {
    const [runs, setRuns] = useState<RunDashboardCard[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    const { API_BASE_URL } = getRuntimeConfig();

    const loadSessions = async () => {
        if (!token) return;
        setLoading(true);
        setError("");
        try {
            const res = await fetch(`${API_BASE_URL}/v1/sessions`, {
                headers: { Authorization: `Bearer ${token}` }
            });
            if (!res.ok) {
                throw new Error(`Session API returned ${res.status}`);
            }
            const data = await res.json();
            setRuns(buildRunDashboardCards(Array.isArray(data) ? data : []));
        } catch (e) {
            setError(e instanceof Error ? e.message : "Failed to load sessions.");
            setRuns([]);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadSessions();
    }, [token]);

    return (
        <div className="sessions-dashboard">
            <header className="sessions-dashboard-hero">
                <div>
                    <p className="eyebrow">Run Dashboard</p>
                    <h3>Agent runs, outcomes, and artifacts</h3>
                    <p>Review what ran, what happened, what artifacts exist, and what to do next.</p>
                </div>
                <button onClick={loadSessions} disabled={loading}>
                    {loading ? "Loading..." : "Refresh runs"}
                </button>
            </header>

            {error ? <p className="sessions-dashboard-error" role="alert">{error}</p> : null}

            <div className="run-dashboard-grid" aria-label="Agent run cards">
                {runs.length === 0 ? (
                    <article className="run-dashboard-empty">
                        <h4>No run history found yet</h4>
                        <p>Run a workflow or refresh after connecting the sessions API.</p>
                    </article>
                ) : (
                    runs.map((run) => (
                        <article key={run.id} className={`run-dashboard-card run-dashboard-card--${run.status}`}>
                            <div className="run-dashboard-card-head">
                                <div>
                                    <span>{run.agent}</span>
                                    <h4>{run.title}</h4>
                                </div>
                                <strong>{run.status}</strong>
                            </div>
                            <p>{run.outcome}</p>
                            <dl>
                                <div>
                                    <dt>Run ID</dt>
                                    <dd>{run.id}</dd>
                                </div>
                                <div>
                                    <dt>Updated</dt>
                                    <dd>{run.updatedAt}</dd>
                                </div>
                            </dl>
                            <section>
                                <h5>Artifacts</h5>
                                <div className="run-artifact-row">
                                    {run.artifacts.map((artifact) => (
                                        <span key={artifact}>{artifact}</span>
                                    ))}
                                </div>
                            </section>
                            <section>
                                <h5>Proof</h5>
                                <div className="run-artifact-row">
                                    {run.proofItems.length === 0 ? <span>Proof pending</span> : null}
                                    {run.proofItems.map((item) => (
                                        <span key={item}>{item}</span>
                                    ))}
                                </div>
                                <div className="run-proof-panel" aria-label={`Proof details for ${run.id}`}>
                                    {run.proofSections.length === 0 ? (
                                        <p>Proof details pending.</p>
                                    ) : (
                                        run.proofSections.map((section) => (
                                            <div key={section.label} className="run-proof-section">
                                                <div>
                                                    <strong>{section.label}</strong>
                                                    <span>{section.count}</span>
                                                </div>
                                                <ul>
                                                    {section.items.map((item) => (
                                                        <li key={item}>{item}</li>
                                                    ))}
                                                </ul>
                                            </div>
                                        ))
                                    )}
                                </div>
                            </section>
                            <section>
                                <h5>Next actions</h5>
                                <ul>
                                    {run.nextActions.map((action) => (
                                        <li key={action}>{action}</li>
                                    ))}
                                </ul>
                            </section>
                            <a className="run-result-link" href={run.resultPath}>
                                Open result detail
                            </a>
                            <p className="run-replay-hint">{run.replayHint}</p>
                        </article>
                    ))
                )}
            </div>
        </div>
    );
}
