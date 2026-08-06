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

test("renders a privacy-safe read-only monitoring board", async ({ page }) => {
  await authAnd(page, async (path, route) => {
    const json = (body: unknown) =>
      route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    if (path.endsWith("/capabilities"))
      return json(apiFixtures.capabilities({ explain_enabled: true, monitoring_enabled: true }));
    if (path.endsWith("/monitoring/overview")) return json(apiFixtures.monitoringOverview());
    return json(apiFixtures.recentRuns());
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
      return route.fulfill({ contentType: "application/json", body: JSON.stringify(apiFixtures.capabilities()) });
    dataCalls += 1;
    return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "disabled" }) });
  });
  await page.goto("/app/settings/monitoring");
  await expect(page.getByRole("heading", { name: "运行监控未开启" })).toBeVisible();
  expect(dataCalls).toBe(0);
});
