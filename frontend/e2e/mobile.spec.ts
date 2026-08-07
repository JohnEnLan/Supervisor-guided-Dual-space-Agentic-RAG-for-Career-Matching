import { expect, test, type Page } from "@playwright/test";

import { apiFixtures, RUN_STAGES } from "../src/test/apiFixtures";

async function installMobileApi(page: Page) {
  let loggedIn = false;
  let consultRound = 0;

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

    if (path.endsWith("/capabilities")) return json(apiFixtures.capabilities());
    if (path.endsWith("/auth/otp/request")) return json(apiFixtures.otpAccepted(), 202);
    if (path.endsWith("/auth/otp/verify")) {
      loggedIn = true;
      return json(apiFixtures.me());
    }
    if (!loggedIn) return json({ detail: "unauthorized" }, 401);
    if (path.endsWith("/me")) return json(apiFixtures.me());
    if (path.endsWith("/me/sessions")) return json(apiFixtures.sessions());
    if (path.endsWith("/sessions") && method === "POST") return json(apiFixtures.session());
    if (path.endsWith("/resume-preview")) return json(apiFixtures.resumePreview(true));
    if (path.endsWith("/consult") && method === "GET")
      return json(apiFixtures.consultState(consultRound));
    if (path.endsWith("/consult") && method === "POST") {
      consultRound += 1;
      return json(apiFixtures.consultTurn(consultRound));
    }
    if (path.endsWith("/status")) {
      return json(
        apiFixtures.runStatus({
          status: "completed",
          stage: "result",
          completedStages: RUN_STAGES,
          resultReady: true,
          retryAfterMs: null,
        }),
      );
    }
    if (path.endsWith("/conversation")) return json(apiFixtures.runConversation("completed", null, 8));
    if (path.endsWith("/result")) return json(apiFixtures.runResult(8));
    return json({ detail: `unmocked ${method} ${path}` }, 500);
  });
}

test("375px journey keeps navigation, consultation, and results usable", async ({ page }) => {
  await installMobileApi(page);

  await page.goto("/");
  await page.getByLabel("邮箱地址").fill("student@example.com");
  await page.getByRole("button", { name: "获取验证码" }).click();
  await page.getByLabel("验证码").fill("123456");
  await page.getByRole("button", { name: "登录 / 注册" }).click();

  await expect(page).toHaveURL(/\/app$/);
  const menuButton = page.getByRole("button", { name: "打开导航" });
  await expect(menuButton).toBeVisible();

  await menuButton.click();
  const drawer = page.getByRole("dialog", { name: "主导航" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole("button", { name: "关闭导航" })).toBeFocused();
  await expect.poll(() => page.evaluate(() => document.body.style.overflow)).toBe("hidden");
  await page.getByRole("button", { name: "关闭导航遮罩" }).click();
  await expect(drawer).not.toBeVisible();
  await expect(menuButton).toBeFocused();

  await page.getByRole("region", { name: "开始咨询" }).getByRole("button", { name: "开始新的咨询" }).click();
  const consultInput = page.getByPlaceholder(/告诉小意你的想法/);
  await expect(consultInput).toBeVisible();
  await expect(consultInput).toBeEnabled();
  await consultInput.fill("我想找后端工程师岗位");
  await expect(consultInput).toHaveValue("我想找后端工程师岗位");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("明白了（第 1 轮）。")).toBeVisible();
  await expect(consultInput).toHaveValue("");

  await page.goto("/app/sessions/sess-e2e-1?run=run-e2e-1");
  await expect(page.getByRole("heading", { name: "Backend Engineer", exact: true })).toBeVisible();
  const timeline = page.locator(".v2-timeline");
  await expect.poll(() => timeline.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
  await timeline.evaluate((element) => element.scrollTo({ top: element.scrollHeight }));
  await expect.poll(() => timeline.evaluate((element) => element.scrollTop > 0)).toBe(true);
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      ),
    )
    .toBe(true);
});
