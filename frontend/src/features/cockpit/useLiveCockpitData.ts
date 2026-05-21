import { useEffect, useState } from "react";

import { fetchLiveAgents, fetchLiveSessions, fetchLiveWorkflowRuns } from "./api";

export interface LiveCockpitData {
  activeSessions: number;
  runningWorkflows: number;
  activeAgents: number;
  loading: boolean;
}

export function useLiveCockpitData(token: string): LiveCockpitData {
  const [activeSessions, setActiveSessions] = useState(0);
  const [runningWorkflows, setRunningWorkflows] = useState(0);
  const [activeAgents, setActiveAgents] = useState(0);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!token) return;

    let cancelled = false;
    setLoading(true);

    void Promise.all([
      fetchLiveSessions(token),
      fetchLiveWorkflowRuns(token),
      fetchLiveAgents(token)
    ]).then(([sessions, workflows, agents]) => {
      if (cancelled) return;
      setActiveSessions(sessions.filter((s) => s.status === "active").length);
      setRunningWorkflows(workflows.filter((w) => w.status === "running").length);
      setActiveAgents(agents.filter((a) => a.status === "ready" || a.status === "active").length);
      setLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, [token]);

  return { activeSessions, runningWorkflows, activeAgents, loading };
}
