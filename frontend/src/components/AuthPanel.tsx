import { useState } from "react";

import { apiRequest } from "../lib/api";

interface AuthPanelProps {
  token: string;
  apiKey: string;
  onTokenChange: (token: string) => void;
  onApiKeyChange: (apiKey: string) => void;
}

export function AuthPanel({
  token,
  apiKey,
  onTokenChange,
  onApiKeyChange
}: AuthPanelProps): JSX.Element {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  async function login(): Promise<void> {
    setError("");
    setIsLoading(true);
    try {
      const result = await apiRequest({
        method: "POST",
        path: "/v1/auth/token",
        body: JSON.stringify({ username, password })
      });
      if (!result.ok || typeof result.data !== "object" || result.data === null) {
        setError(`Login failed (${result.status})`);
        return;
      }
      const maybeToken = (result.data as Record<string, unknown>).access_token;
      if (typeof maybeToken !== "string" || maybeToken.trim() === "") {
        setError("No access_token in login response.");
        return;
      }
      onTokenChange(maybeToken);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <section className="auth-panel">
      <h2>Access Control</h2>
      <p>
        Use login for seeded local credentials, or paste a token/API key for shared or production
        environments.
      </p>
      <div className="auth-grid">
        <label>
          Username
          <input value={username} onChange={(e) => setUsername(e.target.value)} />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <button onClick={login} disabled={isLoading}>
          {isLoading ? "Signing in..." : "Sign In"}
        </button>
      </div>
      <label>
        Bearer Token
        <textarea
          value={token}
          onChange={(e) => onTokenChange(e.target.value)}
          rows={3}
          placeholder="Paste JWT token"
        />
      </label>
      <label>
        API Key (optional)
        <input
          value={apiKey}
          onChange={(e) => onApiKeyChange(e.target.value)}
          placeholder="a33_xxx..."
        />
      </label>
      {error ? <pre className="error-box" role="alert">{error}</pre> : null}
    </section>
  );
}
