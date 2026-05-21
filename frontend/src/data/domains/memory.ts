import type { DomainConfig } from "../../types";

export const memoryDomain: DomainConfig = {
  id: "memory",
  title: "Memory",
  description: "RAG search and session memory controls.",
  operations: [
    {
      id: "memory-search",
      title: "Search Memory",
      method: "POST",
      path: "/v1/memory/search",
      description: "Search indexed memory.",
      defaultBody: JSON.stringify(
        {
          query: "release checklist",
          level: "index",
          top_k: 5
        },
        null,
        2
      )
    },
    {
      id: "memory-observations",
      title: "Session Observations",
      method: "GET",
      path: "/v1/memory/sessions/{session_id}/observations",
      description: "List observations for a session.",
      defaultPathParams: {
        session_id: "session-123"
      }
    },
    {
      id: "memory-summarize",
      title: "Summarize Session",
      method: "POST",
      path: "/v1/memory/sessions/{session_id}/summarize",
      description: "Create/update session summary.",
      defaultPathParams: {
        session_id: "session-123"
      },
      defaultBody: "{}"
    }
  ]
};
