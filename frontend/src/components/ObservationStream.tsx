import { useEffect, useState } from "react";
import { getRuntimeConfig } from "../lib/api";

interface Observation {
    id: string;
    agent_name: string;
    event_type: string;
    content: string;
    timestamp: string;
}

export function ObservationStream({ token }: { token: string | null }): JSX.Element {
    const [events, setEvents] = useState<Observation[]>([]);
    const { API_BASE_URL } = getRuntimeConfig();

    useEffect(() => {
        if (!token) return;

        let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
        let isActive = true;

        async function connect() {
            try {
                const response = await fetch(`${API_BASE_URL}/v1/operations/stream`, {
                    headers: { Authorization: `Bearer ${token}` }
                });

                if (!response.ok || !response.body) return;

                reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = "";

                while (isActive) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const parts = buffer.split("\n\n");
                    buffer = parts.pop() || "";

                    for (const part of parts) {
                        if (part.startsWith("data: ")) {
                            try {
                                const data = JSON.parse(part.substring(6));

                                // We are particularly interested in Phase 34 mechanics
                                if (data.event_type === "handoff_context_wipe" ||
                                    data.event_type === "tool_call" && data.content.includes("deploy_a2a_subordinate") ||
                                    data.event_type === "tool_call" && data.content.includes("tldr_read_enforcer")) {

                                    setEvents(prev => [data, ...prev].slice(0, 10));
                                }
                            } catch (e) {
                                // Parse error
                            }
                        }
                    }
                }
            } catch (err) {
                // Handle fetch error
            }
        }

        connect();

        return () => {
            isActive = false;
            if (reader) {
                reader.cancel().catch(() => { });
            }
        };
    }, [token, API_BASE_URL]);

    if (events.length === 0) return <></>;

    return (
        <div className="observation-stream" role="log" aria-label="Live core mechanics" aria-live="polite">
            <h3>Live Core Mechanics</h3>
            <div className="observation-list">
                {events.map((ev) => (
                    <div key={ev.id} className={`observation-item ${ev.event_type}`}>
                        <div className="observation-header">
                            <span className="observation-time">{new Date(ev.timestamp).toLocaleTimeString()}</span>
                            {ev.agent_name && <span className="observation-agent">{ev.agent_name}</span>}
                            <span className="observation-type">
                                {ev.event_type === "handoff_context_wipe" ? <><span aria-hidden="true">🔄</span> Handoff Wipe</> :
                                    ev.content.includes("a2a") ? <><span aria-hidden="true">🤖</span> A2A Subordinate</> : <><span aria-hidden="true">📄</span> AST Extraction</>}
                            </span>
                        </div>
                        <pre className="observation-content">{ev.content}</pre>
                    </div>
                ))}
            </div>
        </div>
    );
}
