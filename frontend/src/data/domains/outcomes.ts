import type { DomainConfig } from "../../types";

export const outcomesDomain: DomainConfig = {
    id: "outcomes",
    title: "Outcomes Dashboard",
    description: "Monitor user outcome trends and trigger autonomous improvements.",
    operations: [
        {
            id: "outcomes-list-trends",
            title: "List Outcome Trends",
            method: "GET",
            path: "/v1/outcomes/trends",
            description: "Retrieve aggregated metric trends over a time window.",
            defaultQuery: {
                domain: "all",
                window_days: "7"
            }
        },
        {
            id: "outcomes-trigger-improvement",
            title: "Trigger Autonomous Improvement",
            method: "POST",
            path: "/v1/outcomes/improvements",
            description: "Trigger a background agent loop to analyze metric decline and propose codebase improvements.",
            defaultBody: JSON.stringify({
                metric_id: "retention_rate",
                context: "15% drop over 3 days"
            }, null, 2)
        }
    ]
};
