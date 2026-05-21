export type OutcomeMetricType = "success_rate" | "quality_score" | "latency_ms" | "cost_usd";
export type TrendDirection = "improving" | "stable" | "declining";

export interface OutcomeTrend {
  metric_type: OutcomeMetricType;
  domain: string;
  window: number;
  direction: TrendDirection;
  sample_size: number;
  values: number[];
  previous_avg: number;
  current_avg: number;
}

export interface OutcomeEvent {
  id: string;
  tenant_id: string;
  domain: string;
  event_type: string;
  metric_type: OutcomeMetricType;
  value: number;
  occurred_at: string;
  metadata: Record<string, unknown>;
}

export interface OutcomeSummary {
  total_events: number;
  domains: string[];
  event_types: string[];
  metric_counts: Record<string, number>;
}

export interface OutcomeDashboardResponse {
  trends: OutcomeTrend[];
  recent_events: OutcomeEvent[];
  summary: OutcomeSummary;
}

export interface SubmitIntakeRequest {
  title: string;
  summary: string;
  source: string;
  submitted_by: string;
  research_type: string;
  category: string;
  urgency: string;
  impact_areas: string[];
  affected_phases: number[];
  priority_score: number;
}
