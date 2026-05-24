import { useEffect, useState } from "react";

import { apiRequest } from "../../lib/api";

interface LiveVoicePanelProps {
  token: string | null;
  onOpenSetup?: () => void;
}

interface VoiceSession {
  id: string;
  room_name: string;
  state: string;
  transport: string;
  daemon_health: boolean;
  started_at: string | null;
  last_error: string;
}

interface VoiceHealthResponse {
  feature: "enabled" | "disabled";
  transport: string;
  tts_provider: string;
  stt_provider: string;
}

function extractError(data: unknown): string {
  if (typeof data === "string" && data.trim() !== "") {
    return data;
  }
  if (data instanceof Error && data.message.trim() !== "") {
    return data.message;
  }
  if (data && typeof data === "object" && "detail" in data) {
    const detail = (data as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim() !== "") {
      return detail;
    }
  }
  if (data && typeof data === "object" && "message" in data) {
    const message = (data as { message?: unknown }).message;
    if (typeof message === "string" && message.trim() !== "") {
      return message;
    }
  }
  return "Voice request failed.";
}

export function LiveVoicePanel({ token, onOpenSetup }: LiveVoicePanelProps): JSX.Element {
  const [session, setSession] = useState<VoiceSession | null>(null);
  const [error, setError] = useState("");
  const [isBusy, setIsBusy] = useState(false);
  const [isHydrating, setIsHydrating] = useState(false);
  const [voiceEnabled, setVoiceEnabled] = useState<boolean | null>(null);

  // Check voice feature health whenever token changes
  useEffect(() => {
    if (!token) {
      setVoiceEnabled(null);
      return;
    }
    let cancelled = false;

    async function checkVoiceHealth() {
      try {
        const result = await apiRequest({
          method: "GET",
          path: "/v1/voice/health",
          token: token as string
        });
        if (cancelled) return;
        if (result.ok && result.data && typeof result.data === "object") {
          const health = result.data as VoiceHealthResponse;
          setVoiceEnabled(health.feature === "enabled");
        } else {
          // If the endpoint errors, assume enabled (don't block on health check failure)
          setVoiceEnabled(true);
        }
      } catch {
        if (!cancelled) setVoiceEnabled(true);
      }
    }

    void checkVoiceHealth();
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    let cancelled = false;

    async function loadActiveSession() {
      if (!token) {
        setSession(null);
        setError("");
        return;
      }

      setIsHydrating(true);
      try {
        const result = await apiRequest({
          method: "GET",
          path: "/v1/multimodal/voice/sessions",
          token,
          query: { state: "active", limit: "1" }
        });
        if (cancelled) {
          return;
        }

        if (result.ok && Array.isArray(result.data) && result.data.length > 0) {
          setSession(result.data[0] as VoiceSession);
          setError("");
        } else if (result.ok) {
          setSession(null);
          setError("");
        } else {
          setSession(null);
          setError(extractError(result.data));
        }
      } catch (error) {
        if (cancelled) {
          return;
        }
        setSession(null);
        setError(extractError(error));
      } finally {
        if (!cancelled) {
          setIsHydrating(false);
        }
      }
    }

    void loadActiveSession();
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function startSession() {
    if (!token) {
      return;
    }
    setIsBusy(true);
    setError("");

    try {
      const result = await apiRequest({
        method: "POST",
        path: "/v1/multimodal/voice/sessions",
        token,
        body: JSON.stringify({ requested_by: "frontend-live-voice" })
      });

      if (result.ok && result.data && typeof result.data === "object") {
        setSession(result.data as VoiceSession);
      } else {
        setError(extractError(result.data));
      }
    } catch (error) {
      setError(extractError(error));
    } finally {
      setIsBusy(false);
    }
  }

  async function stopSession() {
    if (!token || !session) {
      return;
    }
    setIsBusy(true);
    setError("");

    try {
      const result = await apiRequest({
        method: "POST",
        path: "/v1/multimodal/voice/sessions/{session_id}/stop",
        token,
        pathParams: { session_id: session.id }
      });

      if (result.ok) {
        setSession(null);
      } else {
        setError(extractError(result.data));
      }
    } catch (error) {
      setError(extractError(error));
    } finally {
      setIsBusy(false);
    }
  }

  const isActive = session !== null && session.state === "active";

  return (
    <div
      className="live-voice-panel"
      style={{
        background: "linear-gradient(170deg, rgba(22, 45, 58, 0.9), rgba(10, 27, 36, 0.92))",
        border: "1px solid #30d5c8",
        borderRadius: "14px",
        padding: "0.95rem",
        boxShadow: "0 18px 34px rgba(5, 13, 17, 0.45)",
        display: "grid",
        gap: "0.8rem"
      }}
    >
      <h2 style={{ margin: 0, fontSize: "1.02rem", color: "#30d5c8" }}>🎙️ Live Voice Orchestrator</h2>
      <p style={{ margin: "0.3rem 0 0.7rem", color: "#9dc3cf", fontSize: "0.85rem" }}>
        Connect via the tenant-scoped voice daemon for an interruptible voice conversation with AGENT-33.
      </p>
      {!token ? (
        <div style={{ display: "grid", gap: "0.5rem" }}>
          <p style={{ margin: 0, fontSize: "0.82rem", color: "#f6d37b" }}>
            Sign in first to enable live voice sessions.
          </p>
          <button
            disabled
            aria-label="Connect microphone for voice session"
            style={{
              width: "fit-content",
              background: "rgba(48, 213, 200, 0.08)",
              border: "1px solid rgba(48, 213, 200, 0.28)",
              color: "#8eaab3",
              borderRadius: "8px",
              padding: "0.4rem 0.7rem",
              cursor: "not-allowed"
            }}
          >
            Connect Microphone
          </button>
          {onOpenSetup ? (
            <button
              onClick={onOpenSetup}
              style={{
                width: "fit-content",
                background: "rgba(48, 213, 200, 0.12)",
                border: "1px solid rgba(48, 213, 200, 0.5)",
                color: "#d8f7f3",
                borderRadius: "8px",
                padding: "0.4rem 0.7rem",
                cursor: "pointer"
              }}
            >
              Open Integrations Setup
            </button>
          ) : null}
        </div>
      ) : voiceEnabled === false ? (
        <div
          style={{
            background: "rgba(246, 211, 123, 0.08)",
            border: "1px solid rgba(246, 211, 123, 0.4)",
            borderRadius: "8px",
            padding: "0.75rem"
          }}
        >
          <p style={{ margin: 0, fontSize: "0.85rem", color: "#f6d37b" }}>
            Voice is not configured. Set <code>voice_daemon_transport</code>,{" "}
            <code>voice_tts_provider</code>, and <code>voice_stt_provider</code> in your
            environment to enable live voice.
          </p>
        </div>
      ) : null}

      {token && voiceEnabled !== false ? (
        <>
          <div className="voice-controls" style={{ display: "flex", gap: "1rem", alignItems: "center" }}>
            <button
              onClick={() => void (isActive ? stopSession() : startSession())}
              disabled={!token || isBusy || isHydrating || voiceEnabled === null}
              aria-label={isBusy ? "Working on voice session" : isActive ? "Disconnect voice session" : "Connect microphone for voice session"}
              style={{
                background: isActive ? "#ff6b6b" : "linear-gradient(120deg, #1d3746, #36586a 40%, #5d6a3a 100%)",
                color: "#fff",
                fontWeight: "bold",
                padding: "0.55rem 0.9rem",
                border: "1px solid #6f5c31",
                borderRadius: "10px",
                cursor: token ? "pointer" : "not-allowed"
              }}
            >
              {isBusy ? "Working..." : isActive ? "Disconnect" : "Connect Microphone"}
            </button>
            {token && !isActive && !isBusy ? (
              <span style={{ fontSize: "0.8rem", color: "#9dc3cf" }}>
                {isHydrating ? "Checking existing session..." : "Ready to start"}
              </span>
            ) : null}

            {isActive ? (
              <div className="audio-visualizer" role="status" aria-label="Listening for voice input" style={{ display: "flex", gap: "4px", alignItems: "flex-end", height: "24px" }}>
                <span className="bar" aria-hidden="true" style={{ width: "4px", height: "12px", background: "#8be9a8", display: "inline-block" }}></span>
                <span className="bar" aria-hidden="true" style={{ width: "4px", height: "20px", background: "#8be9a8", display: "inline-block", animation: "pulse 1s infinite alternate" }}></span>
                <span className="bar" aria-hidden="true" style={{ width: "4px", height: "8px", background: "#8be9a8", display: "inline-block" }}></span>
                <span style={{ fontSize: "0.8rem", color: "#8be9a8", marginLeft: "8px" }}>Listening...</span>
              </div>
            ) : null}
          </div>

          {session ? (
            <div
              style={{
                display: "grid",
                gap: "0.25rem",
                background: "rgba(6, 19, 26, 0.5)",
                borderRadius: "10px",
                padding: "0.75rem",
                color: "#cbe8f1",
                fontSize: "0.82rem"
              }}
            >
              <div>Room: {session.room_name}</div>
              <div>Transport: {session.transport}</div>
              <div>Health: {session.daemon_health ? "healthy" : "offline"}</div>
              {session.started_at ? <div>Started: {new Date(session.started_at).toLocaleString()}</div> : null}
            </div>
          ) : null}
        </>
      ) : null}

      {error ? (
        <p role="alert" style={{ margin: 0, color: "#ffb3b3", fontSize: "0.82rem" }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
