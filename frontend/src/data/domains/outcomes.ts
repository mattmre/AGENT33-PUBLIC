import type { DomainConfig } from "../../types";

export const outcomesDomain: DomainConfig = {
  id: "outcomes",
  title: "Outcomes Dashboard",
  description: "Monitor user outcome events, trends, launch friction, and ROI.",
  operations: [
    {
      id: "outcomes-get-trend",
      title: "Get Outcome Trend",
      method: "GET",
      path: "/v1/outcomes/trends/{metric_type}",
      description: "Retrieve a metric trend over the recent event window.",
      schemaInfo: {
        parameters: [
          { name: "metric_type", type: "string", description: "Metric type such as success_rate, quality_score, latency_ms, or cost_usd.", required: true },
          { name: "domain", type: "string", description: "Optional outcome domain filter.", required: false },
          { name: "window", type: "number", description: "Number of recent matching events to include.", required: false }
        ]
      },
      defaultPathParams: {
        metric_type: "success_rate"
      },
      defaultQuery: {
        domain: "all",
        window: "20"
      }
    },
    {
      id: "outcomes-record-event",
      title: "Record Outcome Event",
      method: "POST",
      path: "/v1/outcomes/events",
      description: "Record an outcome metric event for later dashboard and trend analysis.",
      defaultBody: JSON.stringify(
        {
          domain: "operator-workflow",
          event_type: "workflow_completed",
          metric_type: "success_rate",
          value: 1,
          metadata: {
            source: "advanced-control-plane"
          }
        },
        null,
        2
      )
    },
    {
      id: "outcomes-dashboard",
      title: "Outcome Dashboard",
      method: "GET",
      path: "/v1/outcomes/dashboard",
      description: "Fetch summary cards, recent events, and per-metric trend snapshots.",
      defaultQuery: {
        domain: "all",
        window: "20",
        recent_limit: "10"
      }
    }
  ]
};
