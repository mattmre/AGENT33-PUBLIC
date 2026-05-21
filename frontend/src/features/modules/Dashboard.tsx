import { useState, useEffect } from "react";
import { getRuntimeConfig } from "../../lib/api";

export function ModulesDashboard({ token }: { token: string | null }) {
    const [skills, setSkills] = useState<any[]>([]);
    const [loading, setLoading] = useState(false);
    const { API_BASE_URL } = getRuntimeConfig();

    const loadSkills = async () => {
        if (!token) return;
        setLoading(true);
        try {
            const res = await fetch(`${API_BASE_URL}/v1/skills`, {
                headers: { Authorization: `Bearer ${token}` }
            });
            const data = await res.json();
            setSkills(data);
        } catch (e) {
            console.error("Failed to load skills:", e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadSkills();
    }, [token]);

    return (
        <div className="modules-dashboard">
            <h3>Modules & Capabilities</h3>
            <p>Active registered skills available to AGENT-33.</p>
            <button onClick={loadSkills} disabled={loading} style={{ marginBottom: "15px" }}>
                {loading ? "Loading..." : "Refresh Status"}
            </button>

            <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left" }}>
                <thead>
                    <tr style={{ background: "#f5f5f5" }}>
                        <th style={{ padding: "8px", border: "1px solid #ddd" }}>Module Name</th>
                        <th style={{ padding: "8px", border: "1px solid #ddd" }}>Description</th>
                    </tr>
                </thead>
                <tbody>
                    {skills.length === 0 ? (
                        <tr>
                            <td colSpan={2} style={{ padding: "8px", textAlign: "center", border: "1px solid #ddd" }}>No modules loaded.</td>
                        </tr>
                    ) : (
                        skills.map((s, i) => (
                            <tr key={i}>
                                <td style={{ padding: "8px", border: "1px solid #ddd" }}><strong>{s.name}</strong></td>
                                <td style={{ padding: "8px", border: "1px solid #ddd" }}>{s.description}</td>
                            </tr>
                        ))
                    )}
                </tbody>
            </table>
        </div>
    );
}
