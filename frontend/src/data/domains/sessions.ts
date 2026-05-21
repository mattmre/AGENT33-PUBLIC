import type { DomainConfig } from "../../types";

export const sessionsDomain: DomainConfig = {
    id: "sessions",
    title: "Session Logs & Alignment",
    description: "View historic session data, agent alignment check-ins, and execution logs.",
    operations: [
        {
            id: "list_sessions",
            title: "List Sessions",
            description: "Get all recorded agent sessions.",
            method: "GET",
            path: "/v1/sessions"
        },
        {
            id: "get_observations",
            title: "Get Observations",
            description: "List raw observations for a session.",
            method: "GET",
            path: "/v1/memory/sessions/{session_id}/observations",
            defaultPathParams: {
                session_id: "session-123"
            }
        }
    ]
};
