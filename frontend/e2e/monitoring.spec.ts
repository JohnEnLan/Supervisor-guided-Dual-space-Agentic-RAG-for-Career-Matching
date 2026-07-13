import { expect, test } from "@playwright/test";

test("renders a privacy-safe read-only monitoring board", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 900 });
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
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false);
});

test("does not call monitoring data routes when capability is disabled", async ({ page }) => {
  let dataCalls = 0;
  await page.route("**/api/v1/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/capabilities")) return route.fulfill({ contentType: "application/json", body: JSON.stringify({ api_version: "v1", dual_space_enabled: true, execution_durability: "process_local", explain_enabled: false, monitoring_enabled: false }) });
    dataCalls += 1;
    return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "disabled" }) });
  });
  await page.goto("/monitoring");
  await expect(page.getByRole("heading", { name: "运行监控未开启" })).toBeVisible();
  expect(dataCalls).toBe(0);
});

test("shows a retry action after monitoring network failure and recovers", async ({ page }) => {
  let overviewCalls = 0;
  const overview = { window_hours: 24, generated_at: "2026-07-13T12:00:00Z", total_runs: 1, completion_rate: 1, failure_rate: 0, warning_rate: 0, duration_p50_ms: 1000, duration_p95_ms: 1000, average_recommendation_count: 3, jd_evidence_coverage_rate: 1, implicit_usage_rate: 0, reordered_run_count: 0, status_counts: { completed: 1 }, stage_latencies: [] };
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/capabilities")) return route.fulfill({ contentType: "application/json", body: JSON.stringify({ api_version: "v1", dual_space_enabled: true, execution_durability: "process_local", explain_enabled: false, monitoring_enabled: true }) });
    if (path.endsWith("/monitoring/overview")) { overviewCalls += 1; if (overviewCalls <= 2) return route.abort("failed"); return route.fulfill({ contentType: "application/json", body: JSON.stringify(overview) }); }
    return route.fulfill({ contentType: "application/json", body: JSON.stringify({ window_hours: 24, generated_at: overview.generated_at, runs: [] }) });
  });
  await page.goto("/monitoring");
  await expect(page.getByRole("heading", { name: "监控数据暂时不可用" })).toBeVisible();
  await page.getByRole("button", { name: "重试" }).click();
  await expect(page.getByText("运行总量")).toBeVisible();
  expect(overviewCalls).toBeGreaterThanOrEqual(3);
});
