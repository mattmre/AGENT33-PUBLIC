export type OutcomeMetricType = "success_rate" | "quality_score" | "latency_ms" | "cost_usd" | "failure_class";

export interface WeekOverWeekStat {
  metric_type: OutcomeMetricType;
  current_week_avg: number;
  previous_week_avg: number;
  pct_change: number;
}

export interface FailureModeStat {
  failure_class: string;
  count: number;
}

export interface OutcomeSummary {
  total_events: number;
  domains: string[];
  event_types: string[];
  metric_counts: Record<string, number>;
}

export interface DashboardResponse {
  summary: OutcomeSummary;
  week_over_week: WeekOverWeekStat[];
  top_failure_modes: FailureModeStat[];
}

export interface ROIResponse {
  total_invocations: number;
  success_count: number;
  failure_count: number;
  estimated_hours_saved: number;
  estimated_value_usd: number;
  success_rate: number;
  avg_latency_ms: number;
}

export interface PackImpactEntry {
  pack_name: string;
  sessions_applied: number;
  success_rate_with_pack: number;
  success_rate_without_pack: number;
  delta: number;
}

export interface PackImpactResponse {
  packs: PackImpactEntry[];
}
