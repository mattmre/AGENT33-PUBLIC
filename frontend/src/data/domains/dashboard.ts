import type { DomainConfig } from "../../types";

export const dashboardDomain: DomainConfig = {
  id: "dashboard",
  title: "Dashboard",
  description: "Operational dashboard metrics and lineage.",
  operations: [
    {
      id: "dashboard-page",
      title: "Dashboard HTML",
      method: "GET",
      path: "/v1/dashboard/",
      description: "Fetch dashboard page."
    },
    {
      id: "dashboard-metrics",
      title: "Dashboard Metrics",
      method: "GET",
      path: "/v1/dashboard/metrics",
      description: "Fetch dashboard metrics."
    },
    {
      id: "dashboard-lineage",
      title: "Dashboard Lineage",
      method: "GET",
      path: "/v1/dashboard/lineage/{workflow_id}",
      description: "Fetch workflow lineage.",
      defaultPathParams: {
        workflow_id: "hello-flow"
      }
    }
  ]
};
