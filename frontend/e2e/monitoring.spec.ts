import { expect, test } from "@playwright/test";

test("renders a privacy-safe read-only monitoring board", async ({ page }) => {
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const body = path.endsWith("/capabilities")
      ? { api_version: "v1", dual_space_enabled: true, execution_durability: "process_local", explain_enabled: true, monitoring_enabled: true }
      : path.endsWith("/monitoring/overview")
        ? { window_hours: 24, generated_at: "2026-07-13T12:00:00Z", total_runs: 12, completion_rate: 0.75, failure_rate: 0.08, warning_rate: 0.16, duration_p50_ms: 12000, duration_p95_ms: 42000, average_recommendation_count: 4.4, jd_evidence_coverage_rate: 1, implicit_usage_rate: 0.5, reordered_run_count: 3, status_counts: { completed: 9, failed: 1 }, stage_latencies: [{ stage: "retrieval", p50_ms: 2000, p95_ms: 6000 }] }
        : { window_hours: 24, generated_at: "2026-07-13T12:00:00Z", runs: [{ run_id: "run-safe-001", status: "completed", stage: "result", recommendation_count: 5, duration_ms: 24000, error_code: null, warning_codes: [], created_at: "2026-07-13T11:59:00Z", started_at: "2026-07-13T11:59:01Z", finished_at: "2026-07-13T11:59:25Z", updated_at: "2026-07-13T11:59:25Z" }] };
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/monitoring");
  await expect(page.getByRole("heading", { name: "运行效果与工作量监控" })).toBeVisible();
  await expect(page.getByText("JD 证据覆盖率")).toBeVisible();
  await expect(page.getByText("双空间重排")).toBeVisible();
  await expect(page.getByText("run-safe-001")).toBeVisible();
  await expect(page.getByRole("button", { name: /删除|修改/ })).toHaveCount(0);
  await expect(page.getByText(/完整简历|提示词/)).toBeVisible();
});
