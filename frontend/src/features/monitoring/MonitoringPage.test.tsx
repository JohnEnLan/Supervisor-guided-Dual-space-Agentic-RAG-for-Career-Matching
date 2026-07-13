import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { MonitoringOverview, RecentRuns } from "../../api/queries";
import { MonitoringContent, MonitoringUnavailable } from "./MonitoringPage";

const overview: MonitoringOverview = {
  window_hours: 24,
  generated_at: "2026-07-13T12:00:00Z",
  total_runs: 12,
  completion_rate: 0.75,
  failure_rate: 0.08,
  warning_rate: 0.16,
  duration_p50_ms: 12000,
  duration_p95_ms: 42000,
  average_recommendation_count: 4.4,
  jd_evidence_coverage_rate: 1,
  implicit_usage_rate: 0.5,
  reordered_run_count: 3,
  status_counts: { completed: 9 },
  stage_latencies: [{ stage: "retrieval", p50_ms: 2000, p95_ms: 6000 }],
};
const runs: RecentRuns = { window_hours: 24, generated_at: overview.generated_at, runs: [] };

describe("MonitoringPage", () => {
  it("shows a capability-off state without mutation controls", () => {
    render(<MonitoringUnavailable />);
    expect(screen.getByText("运行监控未开启")).toBeInTheDocument();
    expect(screen.queryByText("删除运行")).not.toBeInTheDocument();
  });

  it("renders volume, latency, quality and dual-space metrics", () => {
    render(<MonitoringContent overview={overview} runs={runs} />);
    expect(screen.getByText("运行总量")).toBeInTheDocument();
    expect(screen.getByText("P95 总耗时")).toBeInTheDocument();
    expect(screen.getByText("JD 证据覆盖率")).toBeInTheDocument();
    expect(screen.getByText("双空间重排")).toBeInTheDocument();
  });
});
