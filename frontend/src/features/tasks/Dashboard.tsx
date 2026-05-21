import { useState, useEffect } from "react";
import { getRuntimeConfig } from "../../lib/api";

export function TasksDashboard({ token }: { token: string | null }) {
    const [workflows, setWorkflows] = useState<any[]>([]);
    const [loading, setLoading] = useState(false);
    const { API_BASE_URL } = getRuntimeConfig();

    const loadWorkflows = async () => {
        if (!token) return;
        setLoading(true);
        try {
            const res = await fetch(`${API_BASE_URL}/v1/workflows`, {
                headers: { Authorization: `Bearer ${token}` }
            });
            const data = await res.json();
            setWorkflows(data);
        } catch (e) {
            console.error("Failed to load workflows:", e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadWorkflows();
    }, [token]);

    return (
        <div className="tasks-dashboard">
            <h3>Tasks & Automation</h3>
            <p>Active multi-step execution graphs in progress.</p>
            <button onClick={loadWorkflows} disabled={loading} style={{ marginBottom: "15px" }}>
                {loading ? "Loading Workflows..." : "Refresh Table"}
            </button>

            <div className="workflows-list">
                {workflows.length === 0 ? (
                    <p>No active flows found.</p>
                ) : (
                    <ul>
                        {workflows.map((wf, i) => (
                            <li key={i} style={{ padding: "10px", borderBottom: "1px solid #ccc" }}>
                                <strong>{wf.id}</strong>: {wf.status}
                            </li>
                        ))}
                    </ul>
                )}
            </div>
        </div>
    );
}
