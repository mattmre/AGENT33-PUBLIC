import type { DomainConfig } from "../../types";

export const modulesDomain: DomainConfig = {
    id: "modules",
    title: "Modules & Capabilities",
    description: "Manage and monitor loaded capabilities, add-ons, and agent skills.",
    operations: [
        {
            id: "list_skills",
            title: "List Skills",
            description: "Get all currently registered agent skills.",
            method: "GET",
            path: "/v1/skills"
        }
    ]
};
