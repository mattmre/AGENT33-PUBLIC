import type { DomainConfig } from "../../types";

export const tasksDomain: DomainConfig = {
    id: "tasks",
    title: "Tasks & Workflows",
    description: "Manage granular tasks, automation flows, and active objectives.",
    operations: [
        {
            id: "list_workflows",
            title: "List Workflows",
            description: "View all active agent workflows.",
            method: "GET",
            path: "/v1/workflows"
        }
    ]
};
