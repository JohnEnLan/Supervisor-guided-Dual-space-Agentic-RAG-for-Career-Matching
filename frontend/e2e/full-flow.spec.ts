import { expect, test, type Page } from "@playwright/test";

import { apiFixtures, RUN_STAGES } from "../src/test/apiFixtures";

/**
 * V2 群聊工作台全流程（网络全 mock）：
 * 登录 → 建会话 → 群内上传简历 → 确认档案 → 多轮咨询 → 生成确认单 →
 * 确认 Brief → 运行播报 → 结果卡片 → 反馈。
 */

const VALID_OUTCOMES = ["rejected", "passed_screen", "interview", "offer"] as const;

type FlowState = {
  loggedIn: boolean;
  uploaded: boolean;
  confirmed: boolean;
  round: number;
  briefed: boolean;
  executed: boolean;
  reactions: number;
  reactionOutcomes: string[];
  statusPoll: number;
  createdSessions: number;
};

function createFlowState(overrides: Partial<FlowState> = {}): FlowState {
  return {
    loggedIn: false,
    uploaded: false,
    confirmed: false,
    round: 0,
    briefed: false,
    executed: false,
    reactions: 0,
    reactionOutcomes: [],
    statusPoll: 0,
    createdSessions: 0,
    ...overrides,
  };
}

function installV2Api(page: Page, state: FlowState) {
  return page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

    if (path.endsWith("/capabilities")) return json(apiFixtures.capabilities());
    if (path.endsWith("/auth/otp/request")) return json(apiFixtures.otpAccepted(), 202);
    if (path.endsWith("/auth/otp/verify")) {
      state.loggedIn = true;
      return json(apiFixtures.me());
    }
    if (path.endsWith("/auth/logout")) {
      state.loggedIn = false;
      // 真实契约是 204 无响应体（generated.ts logout），mock 对齐避免掩盖前端对空体的处理
      return route.fulfill({ status: 204, body: "" });
    }
    if (!state.loggedIn) return json({ detail: "unauthorized" }, 401);
    if (path.endsWith("/me")) return json(apiFixtures.me());
    if (path.endsWith("/me/profile")) return json(apiFixtures.profile());
    if (path.endsWith("/me/sessions")) return json(apiFixtures.sessions());
    if (path.endsWith("/sessions") && method === "POST") {
      state.createdSessions += 1;
      return json(apiFixtures.session(`sess-e2e-${state.createdSessions}`));
    }
    if (path.endsWith("/resume") && method === "POST") {
      state.uploaded = true;
      return json(apiFixtures.resumeAccepted(), 202);
    }
    if (path.endsWith("/resume-preview")) {
      if (!state.uploaded) return json({ detail: "processing" }, 409);
      return json(apiFixtures.resumePreview(state.confirmed));
    }
    if (path.endsWith("/resume-confirm")) {
      state.confirmed = true;
      return json(apiFixtures.resumeConfirm());
    }
    if (path.endsWith("/consult") && method === "GET")
      return json(apiFixtures.consultState(state.round));
    if (path.endsWith("/consult") && method === "POST") {
      state.round += 1;
      return json(apiFixtures.consultTurn(state.round));
    }
    if (path.endsWith("/consult/finalize")) return json(apiFixtures.consultFinalize());
    if (path.endsWith("/match-brief")) {
      state.briefed = true;
      return json(apiFixtures.matchBrief(), 201);
    }
    if (path.endsWith("/execute")) {
      state.executed = true;
      state.statusPoll = 0;
      return json(
        apiFixtures.runStatus({
          status: "running",
          stage: "resume",
          completedStages: [],
          resultReady: false,
          retryAfterMs: 50,
        }),
      );
    }
    if (path.endsWith("/status")) {
      if (!state.executed)
        return json(
          apiFixtures.runStatus({
            status: "plan_ready",
            stage: "plan",
            completedStages: [],
            resultReady: false,
            retryAfterMs: 50,
          }),
        );
      const stageIndex = Math.min(state.statusPoll, RUN_STAGES.length - 1);
      const completed = RUN_STAGES.slice(0, stageIndex);
      const done = stageIndex === RUN_STAGES.length - 1;
      state.statusPoll += 1;
      return json(
        apiFixtures.runStatus({
          status: done ? "completed" : "running",
          stage: RUN_STAGES[stageIndex],
          completedStages: done ? RUN_STAGES : completed,
          resultReady: done,
          retryAfterMs: done ? null : 50,
        }),
      );
    }
    if (path.endsWith("/conversation"))
      return json(
        apiFixtures.runConversation(
          state.statusPoll >= RUN_STAGES.length ? "completed" : "running",
          state.statusPoll >= RUN_STAGES.length ? null : 50,
        ),
      );
    if (path.endsWith("/result")) return json(apiFixtures.runResult(VALID_OUTCOMES.length));
    if (path.endsWith("/reaction")) {
      const body = request.postDataJSON() as { outcome?: unknown };
      if (!VALID_OUTCOMES.includes(body.outcome as (typeof VALID_OUTCOMES)[number])) {
        return json({ detail: "invalid outcome" }, 422);
      }
      state.reactions += 1;
      state.reactionOutcomes.push(String(body.outcome));
      return json(apiFixtures.reaction(state.reactions), 202);
    }
    return json({ detail: `unmocked ${method} ${path}` }, 500);
  });
}

test("v2 group-chat journey: login to evidence-backed results", async ({ page }) => {
  const state = createFlowState();
  await installV2Api(page, state);

  await page.goto("/");
  await expect(page.getByRole("heading", { name: /交给一支为你服务的团队/ })).toBeVisible();
  await page.getByLabel("邮箱地址").fill("student@example.com");
  await page.getByRole("button", { name: "获取验证码" }).click();
  await page.getByLabel("验证码").fill("123456");
  await page.getByRole("button", { name: "登录 / 注册" }).click();

  await expect(page).toHaveURL(/\/app$/);
  await page.getByRole("button", { name: "新的咨询" }).click();
  await expect(page.getByRole("heading", { name: "职业规划服务群" })).toBeVisible();

  await page.setInputFiles('input[type="file"]', {
    name: "resume.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Python engineer resume"),
  });
  await page.getByRole("button", { name: "确认简历档案" }).click();

  const input = page.getByPlaceholder(/告诉小意你的想法/);
  await input.fill("我想在上海找后端开发");
  await input.press("Enter");
  await expect(page.getByText("明白了（第 1 轮）。")).toBeVisible();
  await input.fill("希望是科技公司，不考虑销售岗");
  await input.press("Enter");
  await expect(page.getByText("明白了（第 2 轮）。")).toBeVisible();

  const confirmBriefButton = page.getByRole("button", { name: "确认无误，开始匹配" });
  await page.getByRole("button", { name: "生成确认单" }).click();
  await expect(confirmBriefButton).toBeVisible();

  // 生成确认单后继续咨询：旧确认单必须作废，防止确认到过期画像
  await input.fill("补充：我也接受苏州的机会");
  await input.press("Enter");
  await expect(page.getByText("明白了（第 3 轮）。")).toBeVisible();
  await expect(confirmBriefButton).not.toBeVisible();
  await page.getByRole("button", { name: "生成确认单" }).click();
  await expect(confirmBriefButton).toBeVisible();

  await confirmBriefButton.click();

  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("last_run:user-e2e-0001:sess-e2e-1")))
    .toBe("run-e2e-1");

  await expect(page.getByText("结果已通过发布核查。")).toBeVisible();
  expect(state.statusPoll).toBeGreaterThanOrEqual(RUN_STAGES.length);
  await expect(page.getByText("任务开始，团队就位。")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Backend Engineer", exact: true })).toBeVisible();
  await expect(page.getByText("现在就投").first()).toBeVisible();
  await expect(page.getByText("演示数据 · CN").first()).toBeVisible();

  await page.getByRole("button", { name: "查看证据" }).first().click();
  await expect(page.getByText("Python, SQL required.")).toBeVisible();
  await page.getByRole("button", { name: "关闭证据" }).click();

  const outcomeLabels = ["被拒", "过筛", "面试", "Offer"];
  const jobCards = page.locator(".v2-job-card");
  await expect(jobCards).toHaveCount(outcomeLabels.length);
  for (const [index, label] of outcomeLabels.entries()) {
    const card = jobCards.nth(index);
    await expect(card.getByRole("button", { name: "提交进展" })).toBeDisabled();
    await card.getByRole("button", { name: label }).click();
    await card.getByRole("button", { name: "提交进展" }).click();
    await expect(card.getByText(/进展已记录/)).toBeVisible();
  }
  expect(state.reactionOutcomes).toEqual([...VALID_OUTCOMES]);
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth),
  ).toBe(false);

  await page.getByRole("link", { name: /测试同学/ }).click();
  await page.getByRole("link", { name: /会话 sess-e2e/ }).click();
  await expect(page).toHaveURL(/\/app\/sessions\/sess-e2e-1\?run=run-e2e-1$/);
  await expect(page.getByRole("heading", { name: "Backend Engineer", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page.getByRole("button", { name: "登录 / 注册" })).toBeVisible();
  expect(
    await page.evaluate(() => localStorage.getItem("last_run:user-e2e-0001:sess-e2e-1")),
  ).toBeNull();
});

test("unauthenticated /app visit returns to landing login", async ({ page }) => {
  const state = createFlowState();
  await installV2Api(page, state);
  await page.goto("/app");
  await expect(page.getByRole("button", { name: "登录 / 注册" })).toBeVisible();
});

test("session quota exhaustion shows the paywall modal", async ({ page }) => {
  const state = createFlowState({ loggedIn: true });
  await installV2Api(page, state);
  await page.route("**/api/v1/sessions", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 402,
          contentType: "application/json",
          body: JSON.stringify({ detail: "session_quota_exceeded" }),
        })
      : route.fallback(),
  );

  await page.goto("/app");
  await page.getByRole("button", { name: "新的咨询" }).click();
  await expect(page.getByText("咨询额度已用完")).toBeVisible();
  await expect(page.getByRole("button", { name: /升级额度/ })).toBeVisible();
  await page.getByRole("button", { name: "稍后再说" }).click();
  await expect(page.getByText("咨询额度已用完")).not.toBeVisible();
});

test("refresh mid-consultation restores transcript from GET consult", async ({ page }) => {
  const state = createFlowState({ loggedIn: true, uploaded: true, confirmed: true, round: 2 });
  await installV2Api(page, state);
  await page.goto("/app/sessions/sess-e2e-1");
  await expect(page.getByText("明白了（第 1 轮）。")).toBeVisible();
  await expect(page.getByText("明白了（第 2 轮）。")).toBeVisible();
  await expect(page.getByRole("button", { name: "生成确认单" })).toBeVisible();
});

for (const terminalStatus of ["failed", "stale", "cancelled"] as const) {
  test(`${terminalStatus} run exits through a newly created session`, async ({ page }) => {
    const state = createFlowState({
      loggedIn: true,
      uploaded: true,
      confirmed: true,
      executed: true,
      createdSessions: 1,
    });
    await installV2Api(page, state);
    await page.route("**/api/v1/runs/run-terminal/status", (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          ...apiFixtures.runStatus({
            status: terminalStatus,
            stage: "retrieval",
            completedStages: ["resume", "intent"],
            resultReady: false,
            retryAfterMs: null,
          }),
          run_id: "run-terminal",
          error_code: terminalStatus === "cancelled" ? null : "RUN_INTERRUPTED",
        }),
      }),
    );

    await page.goto("/app/sessions/sess-e2e-1?run=run-terminal");
    await expect(page.getByRole("button", { name: "新建咨询重试" })).toBeVisible();
    await page.getByRole("button", { name: "新建咨询重试" }).click();
    await expect(page.getByRole("dialog", { name: "新建咨询确认" })).toContainText(
      "会消耗一次咨询额度",
    );
    await page.getByRole("button", { name: "确认新建咨询" }).click();

    await expect(page).toHaveURL(/\/app\/sessions\/sess-e2e-2$/);
    expect(state.createdSessions).toBe(2);
  });
}
