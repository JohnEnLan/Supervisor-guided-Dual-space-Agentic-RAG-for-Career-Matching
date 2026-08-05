import { expect, test, type Page, type Route } from "@playwright/test";

const ME = {
  user_id: "user-e2e-0001",
  status: "active",
  is_admin: true,
  display_name: "考官",
  created_at: "2026-08-01T08:00:00Z",
};

function authAnd(page: Page, handler: (path: string, route: Route) => Promise<void> | void) {
  return page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path.endsWith("/me")) return json(ME);
    if (path.endsWith("/me/profile")) return json({ profile: {}, updated_at: null });
    if (path.endsWith("/me/sessions"))
      return json({ sessions: [], page: 1, page_size: 30, has_more: false });
    return handler(path, route);
  });
}

test("renders a privacy-safe read-only monitoring board", async ({ page }) => {
  await authAnd(page, async (path, route) => {
    const json = (body: unknown) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    if (path.endsWith("/capabilities"))
      return json({ api_version: "v1", dual_space_enabled: true, execution_durability: "process_local", explain_enabled: true, monitoring_enabled: true });
    if (path.endsWith("/monitoring/overview"))
      return json({ window_hours: 24, generated_at: "2026-07-13T12:00:00Z", total_runs: 12, completion_rate: 0.75, failure_rate: 0.08, warning_rate: 0.16, duration_p50_ms: 12000, duration_p95_ms: 42000, average_recommendation_count: 4.4, jd_evidence_coverage_rate: 1, implicit_usage_rate: 0.5, reordered_run_count: 3, status_counts: { completed: 9, failed: 1 }, stage_latencies: [{ stage: "retrieval", p50_ms: 2000, p95_ms: 6000 }] });
    return json({ window_hours: 24, generated_at: "2026-07-13T12:00:00Z", runs: [{ run_id: "run-safe-001", status: "completed", stage: "result", recommendation_count: 5, duration_ms: 24000, error_code: null, warning_codes: [], created_at: "2026-07-13T11:59:00Z", started_at: "2026-07-13T11:59:01Z", finished_at: "2026-07-13T11:59:25Z", updated_at: "2026-07-13T11:59:25Z" }] });
  });
  await page.goto("/app/settings/monitoring");
  await expect(page.getByRole("heading", { name: "运行效果与工作量监控" })).toBeVisible();
  await expect(page.getByText("JD 证据覆盖率")).toBeVisible();
  await expect(page.getByText("run-safe-001")).toBeVisible();
  await expect(page.getByRole("button", { name: /删除|修改/ })).toHaveCount(0);
});

test("does not call monitoring data routes when capability is disabled", async ({ page }) => {
  let dataCalls = 0;
  await authAnd(page, (path, route) => {
    if (path.endsWith("/capabilities"))
      return route.fulfill({ contentType: "application/json", body: JSON.stringify({ api_version: "v1", dual_space_enabled: true, execution_durability: "process_local", explain_enabled: false, monitoring_enabled: false }) });
    dataCalls += 1;
    return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "disabled" }) });
  });
  await page.goto("/app/settings/monitoring");
  await expect(page.getByRole("heading", { name: "运行监控未开启" })).toBeVisible();
  expect(dataCalls).toBe(0);
});
