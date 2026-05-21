import { useEffect, useState } from "react";

import { apiRequest } from "../lib/api";

interface HealthSnapshot {
  status: string;
  services?: Record<string, string>;
}

export function HealthPanel(): JSX.Element {
  const [health, setHealth] = useState<HealthSnapshot | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let canceled = false;

    async function load(): Promise<void> {
      try {
        const result = await apiRequest({
          method: "GET",
          path: "/health"
        });
        if (!canceled && result.ok && typeof result.data === "object" && result.data !== null) {
          setHealth(result.data as HealthSnapshot);
          setError("");
        } else if (!canceled) {
          setError(`Health check failed (${result.status})`);
        }
      } catch (err) {
        if (!canceled) {
          setError(err instanceof Error ? err.message : "Health check error");
        }
      }
    }

    load();
    const timer = window.setInterval(load, 5000);
    return () => {
      canceled = true;
      window.clearInterval(timer);
    };
  }, []);

  function getStatusIcon(status: string): JSX.Element {
    const s = status.toLowerCase();
    switch (s) {
      case "ok":
      case "healthy":
        return <span className="rh-icon connected" role="img" aria-label="Connected and working"><span aria-hidden="true">🟢</span></span>;
      case "degraded":
      case "unavailable":
      case "error":
        return <span className="rh-icon error" role="img" aria-label="Not working"><span aria-hidden="true">🔴</span></span>;
      case "configured":
        return <span className="rh-icon pending" role="img" aria-label="Set up and not connected"><span aria-hidden="true">🟡</span></span>;
      case "unconfigured":
      default:
        return <span className="rh-icon inactive" role="img" aria-label="Not set up"><span aria-hidden="true">⚪</span></span>;
    }
  }

  return (
    <section className="health-panel">
      <h2>Runtime Health</h2>
      {error ? <pre className="error-box" role="alert">{error}</pre> : null}
      {health ? (
        <div className="runtime-health-grid">
          <div className="runtime-health-card">
            <h3>OVERALL</h3>
            <div className="rh-state">
              {getStatusIcon(health.status)}
              <span className={`rh-text ${health.status.toLowerCase()}`}>{health.status}</span>
            </div>
          </div>
          {Object.entries(health.services ?? {}).map(([name, status]) => (
            <div className="runtime-health-card" key={name}>
              <h3>{name.toUpperCase()}</h3>
              <div className="rh-state">
                {getStatusIcon(status)}
                <span className={`rh-text ${status.toLowerCase()}`}>{status}</span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p>Loading health...</p>
      )}
    </section>
  );
}
