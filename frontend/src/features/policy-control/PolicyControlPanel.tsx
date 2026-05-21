import { useEffect, useState } from "react";

const BASE_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? "";

interface PolicyShard {
  id: string;
  label: string;
  mode: string;
}

interface CollaborationMode {
  id: string;
  label: string;
  detail: string;
}

interface ActivePolicy {
  tool_use_mode: string;
  evidence_required: boolean;
  review_authority: string;
  policy_shards: PolicyShard[];
  collaboration_modes: CollaborationMode[];
}

async function fetchActivePolicy(token: string): Promise<ActivePolicy | null> {
  try {
    const res = await fetch(`${BASE_URL}/v1/policy/active`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) return null;
    return (await res.json()) as ActivePolicy;
  } catch {
    return null;
  }
}

interface PolicyControlPanelProps {
  token?: string;
}

export function PolicyControlPanel({ token = "" }: PolicyControlPanelProps): JSX.Element {
  const [policy, setPolicy] = useState<ActivePolicy | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!token) return;

    let cancelled = false;
    setLoading(true);
    setError(false);

    void fetchActivePolicy(token).then((data) => {
      if (cancelled) return;
      if (data) {
        setPolicy(data);
      } else {
        setError(true);
      }
      setLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, [token]);

  const shards = policy?.policy_shards ?? [];
  const modes = policy?.collaboration_modes ?? [];

  return (
    <section className="policy-control-panel" aria-label="Policy control plane">
      <header className="policy-control-header">
        <div>
          <p className="eyebrow">Policy</p>
          <h3>Authority, gates, and collaboration modes</h3>
          <p>Inspect the active policy posture before allowing autonomous or mutating work.</p>
        </div>
      </header>

      {loading && <p className="policy-loading">Loading active policy…</p>}

      {error && (
        <p className="policy-unavailable">
          Policy state unavailable — engine unreachable.
        </p>
      )}

      {!loading && !error && (
        <div className="policy-control-grid">
          <article>
            <h4>Active policy shards</h4>
            <div className="policy-control-list">
              {shards.map((shard) => (
                <div key={shard.id}>
                  <strong>{shard.label}</strong>
                  <span>{shard.id}</span>
                  <p>{shard.mode}</p>
                </div>
              ))}
            </div>
          </article>
          <article>
            <h4>Collaboration modes</h4>
            <div className="policy-control-list">
              {modes.map((mode) => (
                <div key={mode.id}>
                  <strong>{mode.label}</strong>
                  <span>{mode.id}</span>
                  <p>{mode.detail}</p>
                </div>
              ))}
            </div>
          </article>
        </div>
      )}
    </section>
  );
}
