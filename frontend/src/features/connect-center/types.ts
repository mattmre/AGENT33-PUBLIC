export type ConnectStatus = "ready" | "attention" | "unknown";

export type ConnectTarget = "models" | "setup" | "mcp" | "tools" | "safety" | "advanced";

export interface ConnectCard {
  id: string;
  title: string;
  plainLabel: string;
  status: ConnectStatus;
  detail: string;
  impact: string;
  actionLabel: string;
  target: ConnectTarget;
  verification: {
    testAction: string;
    healthExplanation: string;
    setupHint: string;
  };
}

export type DoctorCheckStatus = "ready" | "blocked" | "inspect";

export interface DoctorCheck {
  id: string;
  title: string;
  status: DoctorCheckStatus;
  diagnosis: string;
  remediation: string;
  owner?: string;
  evidenceRefs?: string[];
}

export interface FirstSuccessPath {
  title: string;
  ready: boolean;
  steps: string[];
  proof: string;
}

export interface DoctorStatusFinding {
  id: string;
  category: string;
  severity: "ok" | "warning" | "error";
  owner: string;
  message: string;
  fix_action: string;
  stale_age_seconds: number;
  evidence_refs: string[];
}

export interface DoctorStatusResponse {
  overall: "ok" | "warning" | "error";
  generated_at: string;
  findings: DoctorStatusFinding[];
}
