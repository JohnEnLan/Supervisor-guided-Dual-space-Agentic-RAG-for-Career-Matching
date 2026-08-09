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
  parsed: boolean;
  confirmed: boolean;
  round: number;
  briefed: boolean;
  executed: boolean;
  reactions: number;
  reactionOutcomes: string[];
  statusPoll: number;
  manualStatusStage: number | null;
  createdSessions: number;
};

function createFlowState(overrides: Partial<FlowState> = {}): FlowState {
  return {
    loggedIn: false,
    uploaded: false,
    // B2：既有场景里 uploaded=true 语义是"档案已就绪"，默认同步视为已解析
    parsed: overrides.parsed ?? overrides.uploaded ?? false,
    confirmed: false,
    round: 0,
    briefed: false,
    executed: false,
    reactions: 0,
    reactionOutcomes: [],
    statusPoll: 0,
    manualStatusStage: null,
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
      // B2 两步确认制：上传返回 200 待确认解析，不再 202 自动入队
      state.uploaded = true;
      state.parsed = false;
      return json(apiFixtures.resumeUploaded());
    }
    if (path.endsWith("/resume-upload") && method === "GET") {
      if (state.uploaded && !state.parsed) return json(apiFixtures.resumeUploaded());
      return json({ detail: "no pending resume upload" }, 404);
    }
    if (path.endsWith("/resume/parse") && method === "POST") {
      // 契约校验：必须回传预览所得 generation，否则按后端语义 409
      const body = request.postDataJSON() as { generation?: number };
      if (body?.generation !== 1) return json({ detail: "resume_changed" }, 409);
      state.parsed = true;
      return json(apiFixtures.resumeAccepted(), 202);
    }
    if (path.endsWith("/resume-progress") && method === "GET") {
      // B3：mock 里确认解析即刻 ready，进度按会话状态给自洽终态/空态
      if (!state.uploaded) {
        return json(
          apiFixtures.resumeProgress({
            generation: null,
            status: "pending",
            events: [],
          }),
        );
      }
      if (!state.parsed) {
        return json(
          apiFixtures.resumeProgress({ status: "resume_uploaded", events: [] }),
        );
      }
      return json(apiFixtures.resumeProgress());
    }
    if (path.endsWith("/resume-preview")) {
      // 生产真实契约：从未上传 = resume_missing；已上传未确认解析 =
      // resume_unparsed（B2）；确认解析后即视为 ready（mock 跳过归一化耗时）
      if (!state.uploaded) return json({ detail: "resume_missing" }, 409);
      if (!state.parsed) return json({ detail: "resume_unparsed" }, 409);
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
      const stageIndex =
        state.manualStatusStage ?? Math.min(state.statusPoll, RUN_STAGES.length - 1);
      const completed = RUN_STAGES.slice(0, stageIndex);
      const done = stageIndex === RUN_STAGES.length - 1;
      if (state.manualStatusStage == null) state.statusPoll += 1;
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
    if (path.endsWith("/conversation")) {
      const conversationDone =
        state.manualStatusStage === RUN_STAGES.length - 1 || state.statusPoll >= RUN_STAGES.length;
      return json(
        apiFixtures.runConversation(
          conversationDone ? "completed" : "running",
          conversationDone ? null : 50,
          VALID_OUTCOMES.length,
        ),
      );
    }
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

  // B1 R7：真实首访路径 —— / 重定向 /welcome，跳过后落首页，再进登录
  await page.goto("/");
  await expect(page).toHaveURL(/\/welcome$/);
  await page.getByRole("button", { name: "跳过介绍 →" }).click();
  await expect(page.getByRole("heading", { name: /交给一支为你服务的团队/ })).toBeVisible();
  await page.getByRole("button", { name: "进入应用" }).first().click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("邮箱地址").fill("student@example.com");
  await page.getByRole("button", { name: "获取验证码" }).click();
  await page.getByLabel("验证码").fill("123456");
  await page.getByRole("button", { name: "登录 / 注册" }).click();

  await expect(page).toHaveURL(/\/app$/);
  const emptyGuide = page.getByRole("region", { name: "开始咨询" });
  await expect(emptyGuide.getByRole("listitem")).toHaveCount(3);
  await expect(page.getByText("已创建 1 次咨询")).toBeVisible();
  await emptyGuide.getByRole("button", { name: "开始新的咨询" }).click();
  await expect(page.getByRole("heading", { name: "职业规划服务群" })).toBeVisible();

  // B2 两步确认制：📎 选文件 → 用户气泡「确认上传」→ 预览卡「确认解析」
  await page.setInputFiles('input[type="file"]', {
    name: "resume.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Python engineer resume"),
  });
  await page.getByRole("button", { name: "确认上传" }).click();
  await expect(page.getByText(/解析会调用 AI 整理档案/)).toBeVisible();
  await page.getByRole("button", { name: "确认解析" }).click();
  await page.getByRole("button", { name: "查看完整档案" }).click();
  const resumeProfile = page.getByRole("region", { name: "完整简历档案" });
  for (const heading of ["教育经历", "工作经历", "项目经历", "技能", "档案质量提示", "原文证据"]) {
    await expect(resumeProfile.getByRole("heading", { name: heading })).toBeVisible();
  }
  await expect(resumeProfile.getByText("Career Arbor")).toBeVisible();
  await expect(page.getByText(/📎 重新上传/)).toBeVisible();
  await page.getByRole("button", { name: "确认简历档案" }).click();
  await expect(page.getByText(/✅ 简历档案已确认/)).toBeVisible();
  await expect(
    page.getByText(
      '现在告诉我你的求职方向吧——目标岗位、期望地点、签证情况，一句话说清也行；不确定的话切到"探索方向"，我们一起梳理。',
    ),
  ).toBeVisible();

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
  const briefSummary = page.locator(".v2-brief");
  await expect(briefSummary.getByText("需求摘要（Match Brief）")).toBeVisible();
  await expect(briefSummary).toContainText("目标");
  await expect(briefSummary).toContainText("硬条件地点 Shanghai、不需要签证担保");
  await expect(briefSummary).toContainText("排序偏好preferred_industries tech");
  await expect(briefSummary).toContainText("暂不考虑sales");
  await expect(briefSummary).toContainText("结果数量5");
  await expect(briefSummary).not.toContainText('{"');
  await expect(briefSummary).not.toContainText('":');

  await confirmBriefButton.click();

  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("last_run:user-e2e-0001:sess-e2e-1")))
    .toBe("run-e2e-1");
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("title:user-e2e-0001:sess-e2e-1")))
    .toBe("Find backend");

  await expect(page.getByText(/岗位分析完成：Now Fit 1 个、Stretch Fit 3 个/)).toBeVisible();
  await expect(page.getByText(/结果已发布。投递后欢迎回来/)).toContainText("不构成 offer 承诺");
  expect(state.statusPoll).toBeGreaterThanOrEqual(RUN_STAGES.length);
  // 静态 PM 欢迎语常驻 1 条；run 播报的 intro 被去重后不得出现第 2 条
  await expect(page.getByText(/欢迎来到职业规划服务群。我是项目经理 PM/)).toHaveCount(1);
  const resultTable = page.getByRole("table", { name: "岗位推荐列表" });
  await expect(resultTable).toBeVisible();
  for (const heading of ["#", "分层", "岗位名", "公司·地点", "语料标签"]) {
    await expect(resultTable.getByRole("columnheader", { name: heading })).toBeVisible();
  }
  await expect(page.getByRole("article")).toHaveCount(0);
  await expect(page.getByText("①", { exact: true })).toBeVisible();
  await expect(page.getByText("4.", { exact: true })).toBeVisible();
  await expect(page.getByText("现在就投").first()).toBeVisible();
  await expect(page.getByText("混合检索（BM25+语义双路）")).toBeVisible();
  await expect(page.getByText("支持双空间增强")).toBeVisible();
  await resultTable.getByRole("button", { name: "查看 Backend Engineer 详情" }).click();
  const firstJobCard = page.getByRole("article", { name: "Backend Engineer 详情" });
  await expect(firstJobCard).toBeVisible();
  await expect(firstJobCard.getByRole("button", { name: "被拒" })).toHaveCount(0);
  await page.getByRole("button", { name: "演示数据 · CN" }).first().click();
  await expect(page.getByText(/合成演示语料/).first()).toBeVisible();
  const sourceLink = page.getByRole("link", { name: "查看原岗位 ↗" }).first();
  await expect(sourceLink).toHaveAttribute("href", "https://jobs.example.com/e2e-backend");
  await expect(sourceLink).toHaveAttribute("rel", "noopener noreferrer");

  const resultActions = page.getByRole("group", { name: "结果后续行动" });
  await expect(resultActions.getByRole("button")).toHaveCount(3);
  await resultActions.getByRole("button", { name: "查看第 1 名的证据" }).click();
  const evidenceButton = page.getByRole("button", { name: "查看证据" }).first();
  await expect(page.getByText("Python, SQL required.")).toBeVisible();
  await expect(page.getByText("出自 JD 原文").first()).toBeVisible();
  await evidenceButton.click();
  await expect(page.getByText("Python, SQL required.")).not.toBeVisible();

  await resultActions.getByRole("button", { name: "更新申请进展" }).click();
  await expect(page.getByRole("button", { name: "被拒" }).first()).toBeFocused();
  await firstJobCard.getByRole("button", { name: "收起进展" }).click();
  await resultActions.getByRole("button", { name: "新建咨询细化方向" }).click();
  await expect(page.getByRole("dialog", { name: "新建咨询确认" })).toBeVisible();
  await page.getByRole("button", { name: "保留当前页面" }).click();

  const outcomeLabels = ["被拒", "过筛", "面试", "Offer"];
  for (const [index, label] of outcomeLabels.entries()) {
    const title = index === 0 ? "Backend Engineer" : `Backend Engineer ${index + 1}`;
    const rowToggle = resultTable.getByRole("button", { name: `查看 ${title} 详情` });
    if ((await rowToggle.getAttribute("aria-expanded")) !== "true") await rowToggle.click();
    const card = page.getByRole("article", { name: `${title} 详情` });
    await expect(card.getByRole("button", { name: label })).toHaveCount(0);
    await card.getByRole("button", { name: "提交进展" }).click();
    const submitProgress = card.getByRole("button", { name: "提交进展" });
    await expect(submitProgress).toBeDisabled();
    await card.getByRole("button", { name: label }).click();
    await expect(submitProgress).toBeEnabled();
    await submitProgress.click();
    await expect(card.getByText(/已记录/)).toBeVisible();
  }
  expect(state.reactionOutcomes).toEqual([...VALID_OUTCOMES]);
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth),
  ).toBe(false);

  await page.getByRole("link", { name: /测试同学/ }).click();
  await page.getByRole("link", { name: /Find backend/ }).click();
  await expect(page).toHaveURL(/\/app\/sessions\/sess-e2e-1\?run=run-e2e-1$/);
  await expect(page.getByRole("heading", { name: "Backend Engineer", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page.getByRole("button", { name: "登录 / 注册" })).toBeVisible();
  expect(
    await page.evaluate(() => localStorage.getItem("last_run:user-e2e-0001:sess-e2e-1")),
  ).toBeNull();
  expect(
    await page.evaluate(() => localStorage.getItem("title:user-e2e-0001:sess-e2e-1")),
  ).toBeNull();
});

test("unauthenticated /app visit returns to landing login", async ({ page }) => {
  const state = createFlowState();
  await installV2Api(page, state);
  await page.goto("/app");
  await expect(page.getByRole("button", { name: "登录 / 注册" })).toBeVisible();
});

test("session quota exhaustion shows truthful copy without an invented limit", async ({ page }) => {
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
  await page.getByRole("button", { name: "新的咨询", exact: true }).click();
  const quotaDialog = page.getByRole("dialog", { name: "额度已用完" });
  await expect(quotaDialog).toContainText("当前账户的咨询额度已用完");
  await expect(quotaDialog).not.toContainText(/3 次|¥/);
  await page.getByRole("button", { name: "知道了" }).click();
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

test("consult refetch renders a finalizable PM note with its action CTA", async ({ page }) => {
  const state = createFlowState({ loggedIn: true, uploaded: true, confirmed: true, round: 2 });
  const noteText = "必填信息已完整，可以生成确认单。";
  let consultGets = 0;
  await installV2Api(page, state);
  await page.route("**/api/v1/sessions/sess-e2e-1/consult", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    consultGets += 1;
    const response = apiFixtures.consultState(state.round, {
      supervisor_notes:
        consultGets >= 2
          ? [
              apiFixtures.supervisorNote({
                trigger: "finalizable",
                text: noteText,
              }),
            ]
          : undefined,
    });
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(response),
    });
  });

  await page.goto("/app/sessions/sess-e2e-1");
  await expect(page.getByText(noteText, { exact: true })).toHaveCount(0);

  const input = page.getByPlaceholder(/告诉小意你的想法/);
  await input.fill("我也偏好平台工程方向");
  await page.getByRole("button", { name: "发送" }).click();

  await expect.poll(() => consultGets).toBeGreaterThanOrEqual(2);
  const noteBubble = page.getByText(noteText, { exact: true }).locator("..");
  await expect(noteBubble).toBeVisible();
  const finalizableCta = noteBubble.getByRole("button", { name: "生成确认单" });
  await expect(finalizableCta).toBeEnabled();
  await finalizableCta.click();
  await expect(page.getByText("需求摘要（Match Brief）")).toBeVisible();
});

test("required-slot chips follow consultation data and keep visa=false complete", async ({ page }) => {
  const state = createFlowState({ loggedIn: true, uploaded: true, confirmed: true });
  await installV2Api(page, state);
  await page.goto("/app/sessions/sess-e2e-1");

  await expect(page.getByRole("button", { name: "目标：待补充" })).toHaveAttribute(
    "data-complete",
    "false",
  );
  await expect(page.getByRole("button", { name: "地点：待补充" })).toHaveAttribute(
    "data-complete",
    "false",
  );
  await expect(page.getByRole("button", { name: "签证：待补充" })).toHaveAttribute(
    "data-complete",
    "false",
  );

  const input = page.getByPlaceholder(/告诉小意你的想法/);
  await input.fill("我想在上海找后端开发");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByRole("button", { name: "目标：backend engineer" })).toHaveAttribute(
    "data-complete",
    "true",
  );
  await expect(page.getByRole("button", { name: "地点：Shanghai" })).toHaveAttribute(
    "data-complete",
    "true",
  );
  await expect(page.getByRole("button", { name: "签证：待补充" })).toHaveAttribute(
    "data-complete",
    "false",
  );

  await input.fill("我不需要签证担保");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByRole("button", { name: "签证：不需担保" })).toHaveAttribute(
    "data-complete",
    "true",
  );
});

test("resume conflicts preserve the draft and recover through processing, updated, and error states", async ({
  page,
}) => {
  const state = createFlowState({ loggedIn: true, uploaded: true, confirmed: true, round: 2 });
  await installV2Api(page, state);
  let previewState: "ready" | "processing" | "updated" | "error" = "ready";
  let previewRefetches = 0;
  let consultGets = 0;
  let consultPosts = 0;

  await page.route("**/api/v1/sessions/sess-e2e-1/resume-preview", async (route) => {
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (previewState === "processing") {
      previewRefetches += 1;
      previewState = "updated";
      return json({ detail: "resume_processing" }, 409);
    }
    if (previewState === "error") {
      previewRefetches += 1;
      return json({ detail: "resume_error" }, 409);
    }
    return json(apiFixtures.resumePreview(state.confirmed));
  });
  await page.route("**/api/v1/sessions/sess-e2e-1/consult", async (route) => {
    const method = route.request().method();
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (method === "GET") {
      consultGets += 1;
      return json(apiFixtures.consultState(state.round));
    }
    if (method === "POST") {
      consultPosts += 1;
      state.confirmed = false;
      if (consultPosts === 1) {
        previewState = "processing";
        return json({ detail: "resume_changed" }, 409);
      }
      previewState = "error";
      return json({ detail: "resume_error" }, 409);
    }
    return route.fallback();
  });

  await page.goto("/app/sessions/sess-e2e-1");
  // 恢复期 placeholder 会切换（"请先上传并确认简历"），用稳定的结构定位器
  // 贯穿全程，才能断言草稿在各恢复态之间保留。
  const input = page.locator(".v2-composer textarea");
  await expect(input).toBeVisible();
  await expect(input).toHaveAttribute("placeholder", /告诉小意你的想法/);
  const consultGetsBeforeConflict = consultGets;
  await page.getByRole("button", { name: "生成确认单" }).click();
  await expect(page.getByText("需求摘要（Match Brief）")).toBeVisible();

  await input.fill("这段输入需要由我确认后重试");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("新简历处理中")).toBeVisible();
  await expect(input).toHaveValue("这段输入需要由我确认后重试");
  await expect(page.getByText("需求摘要（Match Brief）")).toHaveCount(0);
  await expect.poll(() => previewRefetches).toBeGreaterThan(0);
  await expect.poll(() => consultGets).toBeGreaterThan(consultGetsBeforeConflict);

  await expect(page.getByText("简历已更新，本轮未提交；请确认新档案后重试")).toBeVisible({
    timeout: 6000,
  });
  expect(consultPosts).toBe(1);
  await page.getByRole("button", { name: "确认简历档案" }).click();
  await expect(input).toBeEnabled();
  expect(consultPosts).toBe(1);

  await page.getByRole("button", { name: "发送" }).click();
  // F2 后该文案在简历区与输入区各出现一次（行为正确），锁定 role=status 那条
  await expect(page.getByRole("status").filter({ hasText: "旧档案已作废，请重传" })).toBeVisible();
  await expect(input).toHaveValue("这段输入需要由我确认后重试");
  expect(consultPosts).toBe(2);
});

test("PM service announcement advances four persona sections from all seven contract stages", async ({
  page,
}) => {
  const state = createFlowState({
    loggedIn: true,
    uploaded: true,
    confirmed: true,
    executed: true,
    manualStatusStage: 0,
  });
  await installV2Api(page, state);
  await page.goto("/app/sessions/sess-e2e-1?run=run-e2e-1");

  const card = page.getByRole("region", { name: "服务进度" });
  await expect(card).toBeVisible();
  await expect(page.getByRole("region", { name: "服务进度" })).toHaveCount(1);
  await expect(card.locator(".v2-progress-list > li")).toHaveCount(4);
  await expect(card).not.toContainText(/耗时|秒|分钟/);

  const stages = [
    ["资料已就绪·系统处理", "小意 · 需求确认"],
    ["PM 正在复核小意已确认的需求", "小意 · 需求确认"],
    ["小检正在筛选岗位", "小检 · 岗位筛选"],
    ["小策正在整理规划建议", "小策 · 规划建议"],
    ["PM 正在核查匹配结果", "PM · 核查发布"],
    ["系统正在整理发布材料", "PM · 核查发布"],
  ] as const;

  for (const [index, [detail, section]] of stages.entries()) {
    state.manualStatusStage = index;
    const currentSection = card.locator('.v2-progress-list > li[data-state="current"]');
    await expect(currentSection).toContainText(section);
    await expect(currentSection).toContainText(detail);
    await expect(page.locator(".v2-progress-message")).toHaveAttribute("data-sticky", "true");
  }

  state.manualStatusStage = RUN_STAGES.length - 1;
  await expect(card.getByRole("status", { name: "服务运行状态" })).toHaveText("已发布");
  await expect(card.locator('.v2-progress-list > li[data-state="complete"]')).toHaveCount(4);
  await expect(page.locator(".v2-progress-message")).toHaveCount(0);
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
