import { expect, test, type Page, type Route } from "@playwright/test";

import { apiFixtures } from "../src/test/apiFixtures";

function authAnd(page: Page, handler: (path: string, route: Route) => Promise<void> | void) {
  return page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path.endsWith("/me")) return json(apiFixtures.me(true));
    if (path.endsWith("/me/profile")) return json(apiFixtures.profile());
    if (path.endsWith("/me/sessions")) return json(apiFixtures.sessions(null));
    return handler(path, route);
  });
}

// B5 R9：旧监控路由重定向进管理控制台；监控板只读且经 admin 保护的
// /api/v1/monitoring/*（用户侧 capability 旗不再门控 admin 视图）。
test("old monitoring route redirects to the admin read-only board", async ({ page }) => {
  await authAnd(page, async (path, route) => {
    const json = (body: unknown) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    if (path.endsWith("/capabilities"))
      return json(apiFixtures.capabilities({ explain_enabled: true, monitoring_enabled: true }));
    if (path.endsWith("/monitoring/overview")) return json(apiFixtures.monitoringOverview());
    return json(apiFixtures.recentRuns());
  });
  await page.goto("/app/settings/monitoring");
  await page.waitForURL(/\/admin\?tab=monitoring/);
  await expect(page.getByRole("heading", { name: "运行监控" })).toBeVisible();
  await expect(page.getByText("JD 证据覆盖率")).toBeVisible();
  await expect(page.getByText("run-safe-001")).toBeVisible();
  await expect(page.getByRole("button", { name: /删除|修改/ })).toHaveCount(0);
});

test("admin monitoring board degrades read-only when data routes return 404", async ({ page }) => {
  await authAnd(page, (path, route) => {
    if (path.endsWith("/capabilities"))
      return route.fulfill({ contentType: "application/json", body: JSON.stringify(apiFixtures.capabilities()) });
    return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "disabled" }) });
  });
  await page.goto("/app/settings/monitoring");
  await page.waitForURL(/\/admin\?tab=monitoring/);
  await expect(page.getByText("监控数据暂时不可用。")).toBeVisible();
  await expect(page.getByRole("button", { name: /删除|修改/ })).toHaveCount(0);
});
