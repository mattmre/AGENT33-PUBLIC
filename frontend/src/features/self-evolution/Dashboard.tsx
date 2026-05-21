import { useState } from "react";
import { getRuntimeConfig } from "../../lib/api";

interface TuningProposal {
    id: string;
    status: string;
    proposal_type: string;
    summary: string;
    created_at: string;
    completed_at: string;
    approved_at: string | null;
    approved_by: string | null;
    sample_size: number;
    before_values: Record<string, unknown>;
    after_values: Record<string, unknown>;
    deltas: Record<string, unknown>;
}

export function EvolutionDashboard({ token }: { token: string | null }) {
    const [proposals, setProposals] = useState<TuningProposal[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const { API_BASE_URL } = getRuntimeConfig();

    const loadProposals = async () => {
        if (!token) return;
        setLoading(true);
        setError(null);
        try {
            const resp = await fetch(`${API_BASE_URL}/v1/improvements/proposals`, {
                headers: {
                    Authorization: `Bearer ${token}`
                }
            });
            if (!resp.ok) {
                throw new Error(`Server returned ${resp.status}`);
            }
            const data = await resp.json();
            setProposals(data.proposals ?? []);
        } catch (e) {
            setError(e instanceof Error ? e.message : "Failed to load proposals");
        } finally {
            setLoading(false);
        }
    };

    const generateProposal = async () => {
        if (!token) return;
        setLoading(true);
        setError(null);
        try {
            const resp = await fetch(`${API_BASE_URL}/v1/improvements/proposals/generate`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${token}`
                }
            });
            if (!resp.ok) {
                const body = await resp.json().catch(() => ({}));
                throw new Error(body.detail ?? `Server returned ${resp.status}`);
            }
            // Reload list after generating
            await loadProposals();
        } catch (e) {
            setError(e instanceof Error ? e.message : "Failed to generate proposal");
            setLoading(false);
        }
    };

    return (
        <div className="evolution-dashboard">
            <h3>Self-Evolution & Security Engine</h3>
            <div className="action-bar">
                <button onClick={generateProposal} className="btn-primary" disabled={!token || loading}>
                    Generate Improvement Proposal
                </button>
                <button onClick={loadProposals} disabled={!token || loading}>
                    Refresh Proposals
                </button>
            </div>

            {error && <p className="error-message" role="alert">{error}</p>}
            {loading && <p>Loading...</p>}

            <div className="proposals-list">
                <h4>Self-Improvement Proposals (Tuning Calibrations)</h4>
                {proposals.length === 0 ? (
                    <p>No proposals yet. Click &ldquo;Generate Improvement Proposal&rdquo; to run the tuning loop sandbox.</p>
                ) : (
                    <ul>
                        {proposals.map(proposal => (
                            <li key={proposal.id} className="proposal-card">
                                <strong>{proposal.proposal_type}: {proposal.status}</strong>
                                <p>{proposal.summary}</p>
                                <p>Sample size: {proposal.sample_size} &mdash; Created: {new Date(proposal.created_at).toLocaleString()}</p>
                                {proposal.approved_by && (
                                    <p>Approved by {proposal.approved_by} at {proposal.approved_at ? new Date(proposal.approved_at).toLocaleString() : "—"}</p>
                                )}
                            </li>
                        ))}
                    </ul>
                )}
            </div>
        </div>
    );
}
