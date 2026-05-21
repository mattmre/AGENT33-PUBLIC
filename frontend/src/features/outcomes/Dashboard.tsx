import { useState, useEffect } from "react";
import { getRuntimeConfig } from "../../lib/api";

interface TrendDetail {
    metric_id: string;
    trend_direction: string;
    change_percentage: number;
}

export function Dashboard({ token }: { token: string | null }) {
    const [trends, setTrends] = useState<TrendDetail[]>([]);
    const { API_BASE_URL } = getRuntimeConfig();

    const fetchTrends = async () => {
        if (!token) return;
        try {
            const res = await fetch(`${API_BASE_URL}/v1/outcomes/trends?domain=all`, {
                headers: { Authorization: `Bearer ${token}` }
            });
            if (res.ok) {
                const data = await res.json();
                // Assuming data is an array of trend objects
                setTrends(Array.isArray(data) ? data : data.trends || []);
            }
        } catch (e) {
            console.error("Failed to fetch trends:", e);
        }
    };

    const triggerImprovement = async (metric_id: string) => {
        if (!token) return;
        try {
            await fetch(`${API_BASE_URL}/v1/outcomes/improvements`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: `Bearer ${token}`
                },
                body: JSON.stringify({ metric_id, context: "Triggered from Dashboard UI" })
            });
            alert(`Autonomous improvement loop triggered for ${metric_id}`);
        } catch (e) {
            console.error("Failed to trigger improvement:", e);
        }
    };

    useEffect(() => {
        fetchTrends();
    }, [token]);

    return (
        <div className="outcomes-dashboard">
            <h3>Outcome Trends</h3>
            {trends.length === 0 ? (
                <p>No trends available for this window.</p>
            ) : (
                <div className="metrics-grid">
                    {trends.map((t) => (
                        <div key={t.metric_id} className={`metric-card ${t.trend_direction}`}>
                            <h4>{t.metric_id}</h4>
                            <div className="trend-value">
                                {t.change_percentage > 0 ? "+" : ""}
                                {t.change_percentage}%
                            </div>
                            {t.trend_direction === "down" && (
                                <button
                                    className="btn-improve"
                                    onClick={() => triggerImprovement(t.metric_id)}
                                >
                                    Trigger AI Improvement
                                </button>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
