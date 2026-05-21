import type { DomainConfig } from "../../types";

export const researchDomain: DomainConfig = {
    id: "research",
    title: "Research & Objectives",
    description: "Explore agent-synthesized findings, long-term goals, and RAG knowledge vectors.",
    operations: [
        {
            id: "search_memory",
            title: "Search Knowledge Base",
            description: "Query the agent's PGVector RAG memory.",
            method: "POST",
            path: "/v1/memory/search",
            defaultBody: JSON.stringify({
                query: "latest research findings",
                level: "full",
                top_k: 10
            }, null, 2)
        }
    ]
};
