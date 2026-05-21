import type { OutcomeMetricType, OutcomeTrend, SubmitIntakeRequest } from "./types";

export function metricLabel(metric: OutcomeMetricType): string {
  const labels: Record<OutcomeMetricType, string> = {
    success_rate: "Success Rate",
    quality_score: "Quality Score",
    latency_ms: "Latency (ms)",
    cost_usd: "Cost (USD)"
  };
  return labels[metric];
}

export function formatMetricValue(metric: OutcomeMetricType, value: number): string {
  if (metric === "latency_ms") {
    return `${value.toFixed(0)} ms`;
  }
  if (metric === "cost_usd") {
    return `$${value.toFixed(2)}`;
  }
  return value.toFixed(2);
}

export function filterTrends(
  trends: OutcomeTrend[],
  metricFilter: OutcomeMetricType | "all"
): OutcomeTrend[] {
  if (metricFilter === "all") {
    return trends;
  }
  return trends.filter((trend) => trend.metric_type === metricFilter);
}

export function decliningTrends(trends: OutcomeTrend[]): OutcomeTrend[] {
  return trends.filter((trend) => trend.direction === "declining");
}

export function sparklinePoints(values: number[], width: number, height: number): string {
  if (values.length === 0) {
    return "";
  }
  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = max - min || 1;
  return values
    .map((value, index) => {
      const x = (index / Math.max(values.length - 1, 1)) * width;
      const y = height - ((value - min) / range) * height;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

export function buildDeclineIntakePayload(
  trend: OutcomeTrend,
  domain: string,
  submittedBy: string
): SubmitIntakeRequest {
  const metric = metricLabel(trend.metric_type);
  const domainLabel = domain || "all domains";
  const previous = formatMetricValue(trend.metric_type, trend.previous_avg);
  const current = formatMetricValue(trend.metric_type, trend.current_avg);

  return {
    title: `Investigate declining ${metric} (${domainLabel})`,
    summary: `${metric} declined in ${domainLabel}. Previous average: ${previous}, current average: ${current}.`,
    source: "outcomes-dashboard:decline-trigger",
    submitted_by: submittedBy,
    research_type: "internal",
    category: "quality",
    urgency: "high",
    impact_areas: [trend.metric_type, domainLabel],
    affected_phases: [30],
    priority_score: 8
  };
}
