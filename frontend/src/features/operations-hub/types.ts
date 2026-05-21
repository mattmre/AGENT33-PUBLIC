export interface OperationsHubProcessSummary {
  id: string;
  type: string;
  status: string;
  started_at: string;
  name: string;
  metadata?: Record<string, unknown>;
}

export interface OperationsHubResponse {
  timestamp: string;
  active_count: number;
  processes: OperationsHubProcessSummary[];
}

export interface OperationsHubProcessAction {
  step_id: string;
  action_count: number;
  completed_at: string | null;
}

export interface OperationsHubProcessDetail extends OperationsHubProcessSummary {
  actions?: OperationsHubProcessAction[];
}

export type OperationsHubControlAction = "pause" | "resume" | "cancel";
export type OperationsHubSessionAction = "resume" | "checkpoint";

export interface RecoverySessionSummary {
  session_id: string;
  purpose: string;
  status: string;
  started_at: string;
  updated_at: string;
  ended_at: string | null;
  task_count: number;
  tasks_completed: number;
  event_count: number;
  parent_session_id: string | null;
  tenant_id: string;
}

export interface RecoveryReplaySummary {
  total_events: number;
  by_type: Record<string, number>;
  duration_seconds: number;
  first_event_at: string;
  last_event_at: string;
}

export type OperationsTimelineTone = "active" | "attention" | "done" | "neutral";

export interface OperationsTimelineItem {
  id: string;
  processId: string;
  title: string;
  description: string;
  timestamp: string;
  tone: OperationsTimelineTone;
}

export interface OperationsTimelineSummary {
  total: number;
  active: number;
  attention: number;
  done: number;
  primaryMessage: string;
  nextAction: string;
}

export interface OperationsReviewableOutputPlan {
  statusLabel: string;
  primaryAction: string;
  fixAction: string;
  reviewGate: string;
  budgetLabel: string;
  artifacts: string[];
}

export interface IngestionAssetSummary {
  id: string;
  name: string;
  asset_type: string;
  status: string;
  confidence: string;
  source_uri: string | null;
  tenant_id: string;
  created_at: string;
  updated_at: string;
  validated_at: string | null;
  published_at: string | null;
  revoked_at: string | null;
  revocation_reason: string | null;
  metadata: Record<string, unknown>;
}

export interface IngestionAssetHistoryEntry {
  asset_id: string;
  tenant_id: string;
  from_status: string;
  to_status: string;
  event_type: string;
  operator: string;
  reason: string;
  details: Record<string, unknown>;
  occurred_at: string;
}

export interface IngestionAssetHistoryResponse {
  asset: IngestionAssetSummary;
  history: IngestionAssetHistoryEntry[];
}
