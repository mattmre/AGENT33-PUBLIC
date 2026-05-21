export interface ModelUsage {
  tokens: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  invocations: number;
}

export interface DailyActivity {
  date: string;
  sessions: number;
  tokens: number;
  cost_usd: number;
}

export interface InsightsReport {
  total_sessions: number;
  total_tokens: number;
  total_cost_usd: number;
  avg_session_duration_seconds: number;
  tool_usage: Record<string, number>;
  model_usage: Record<string, ModelUsage>;
  daily_activity: DailyActivity[];
  period_days: number;
  generated_at: string;
}
