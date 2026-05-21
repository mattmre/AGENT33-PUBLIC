import type { DomainConfig } from "../../types";

export const healthDomain: DomainConfig = {
  id: "overview",
  title: "Health",
  description: "Cluster health and channel checks.",
  operations: [
    {
      id: "health",
      title: "System Health",
      method: "GET",
      path: "/health",
      description: "Aggregate service health.",
      instructionalText: "Run this operation to verify that the core AGENT-33 engine and its connected services are currently online and responding.",
      uxHint: "health"
    },
    {
      id: "health-channels",
      title: "Channel Health",
      method: "GET",
      path: "/health/channels",
      description: "Messaging channel adapters health.",
      instructionalText: "Run this operation to check the connection status of external messaging platforms like Signal, iMessage, and Discord.",
      uxHint: "health-channels"
    }
  ]
};
