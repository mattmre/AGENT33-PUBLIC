import type { DomainConfig } from "../../types";

export const operationsHubDomain: DomainConfig = {
    id: "operations",
    title: "Operations Hub",
    description: "Monitor and manage autonomous agent lifecycle loops and tracking.",
    operations: [
        {
            id: "operations-hub-overview",
            title: "Hub Overview",
            method: "GET",
            path: "/v1/operations/hub",
            description: "Unified operations-hub view with active process counts, optional trace/budget/improvement/workflow inclusions.",
            defaultQuery: {
                include: "traces,budgets",
                limit: "100"
            }
        },
        {
            id: "operations-process-detail",
            title: "Process Detail",
            method: "GET",
            path: "/v1/operations/processes/{process_id}",
            description: "Retrieve detail for a single process including actions and metadata.",
            defaultPathParams: {
                process_id: "replace-with-process-id"
            }
        },
        {
            id: "operations-process-control",
            title: "Process Control",
            method: "POST",
            path: "/v1/operations/processes/{process_id}/control",
            description: "Execute lifecycle controls (pause, resume, cancel) against a running process.",
            defaultPathParams: {
                process_id: "replace-with-process-id"
            },
            defaultBody: JSON.stringify({
                action: "pause",
                reason: ""
            }, null, 2)
        },
        {
            id: "ingestion-review-queue",
            title: "Ingestion Review Queue",
            method: "GET",
            path: "/v1/ingestion/review-queue",
            description: "List candidate assets awaiting operator review."
        },
        {
            id: "ingestion-asset-history",
            title: "Asset History",
            method: "GET",
            path: "/v1/ingestion/candidates/{asset_id}/history",
            description: "Retrieve the current asset record plus its event timeline.",
            defaultPathParams: {
                asset_id: "replace-with-asset-id"
            }
        },
        {
            id: "ingestion-review-approve",
            title: "Approve Review Asset",
            method: "POST",
            path: "/v1/ingestion/review-queue/{asset_id}/approve",
            description: "Approve a pending-review asset and advance it to validated.",
            defaultPathParams: {
                asset_id: "replace-with-asset-id"
            },
            defaultBody: JSON.stringify({
                operator: "operator-ui",
                reason: "Validated after review"
            }, null, 2)
        },
        {
            id: "ingestion-review-reject",
            title: "Reject Review Asset",
            method: "POST",
            path: "/v1/ingestion/review-queue/{asset_id}/reject",
            description: "Reject a pending-review asset and revoke it with an operator reason.",
            defaultPathParams: {
                asset_id: "replace-with-asset-id"
            },
            defaultBody: JSON.stringify({
                operator: "operator-ui",
                reason: "Rejected after review"
            }, null, 2)
        },
        {
            id: "ingestion-notification-hooks",
            title: "Notification Hooks",
            method: "GET",
            path: "/v1/ingestion/notification-hooks",
            description: "List configured webhook-style notification hooks for ingestion events."
        }
    ]
};
