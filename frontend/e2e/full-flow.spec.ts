import { expect, test, type Page } from "@playwright/test";

/**
 * V2 群聊工作台全流程（网络全 mock）：
 * 登录 → 建会话 → 群内上传简历 → 确认档案 → 多轮咨询 → 生成确认单 →
 * 确认 Brief → 运行播报 → 结果卡片 → 反馈。
 */

const ME = {
  user_id: "user-e2e-0001",
  status: "active",
  is_admin: false,
  display_name: "测试同学",
  created_at: "2026-08-01T08:00:00Z",
};

type FlowState = {
  loggedIn: boolean;
  uploaded: boolean;
  confirmed: boolean;
  round: number;
  briefed: boolean;
  executed: boolean;
  reactions: number;
};

function installV2Api(page: Page, state: FlowState) {
  return page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

    if (path.endsWith("/capabilities"))
      return json({
        api_version: "v1",
        dual_space_enabled: true,
        execution_durability: "process_local",
        explain_enabled: false,
        monitoring_enabled: false,
      });
    if (path.endsWith("/auth/otp/request")) return json({ accepted: true, channel: "email" }, 202);
    if (path.endsWith("/auth/otp/verify")) {
      state.loggedIn = true;
      return json(ME);
    }
    if (path.endsWith("/auth/logout")) {
      state.loggedIn = false;
      return json({ logged_out: true });
    }
    if (!state.loggedIn) return json({ detail: "unauthorized" }, 401);
    if (path.endsWith("/me")) return json(ME);
    if (path.endsWith("/me/profile")) return json({ profile: {}, updated_at: null });
    if (path.endsWith("/me/sessions"))
      return json({
        sessions: [{ session_id: "sess-e2e-1", status: "active", updated_at: "2026-08-05T09:00:00Z" }],
        page: 1,
        page_size: 30,
        has_more: false,
      });
    if (path.endsWith("/sessions") && method === "POST")
      return json({ session_id: "sess-e2e-1", status: "created" });
    if (path.endsWith("/resume") && method === "POST") {
      state.uploaded = true;
      return json({ session_id: "sess-e2e-1", status: "resume_queued" }, 202);
    }
    if (path.endsWith("/resume-preview")) {
      if (!state.uploaded) return json({ detail: "processing" }, 409);
      return json({
        session_id: "sess-e2e-1",
        confirmed: state.confirmed,
        education: [{ school: "Demo University", degree: "MSc", field: "CS" }],
        experience: [{ company: "Demo Co", title: "Engineer" }],
        skills: ["Python", "SQL"],
        quality_issues: [],
        evidence_spans: [{ span_id: "R001", text: "Built a Python service." }],
      });
    }
    if (path.endsWith("/resume-confirm")) {
      state.confirmed = true;
      return json({ session_id: "sess-e2e-1", resume_version: 1, confirmed: true, confirmed_at: "2026-08-05T09:01:00Z" });
    }
    if (path.endsWith("/consult") && method === "GET")
      return json({
        transcript: Array.from({ length: state.round }, (_, index) => ({
          round: index + 1,
          user_message: `用户第 ${index + 1} 轮`,
          assistant_reply: `明白了（第 ${index + 1} 轮）。`,
          next_question: index + 1 >= 2 ? "还有想补充的吗？" : "你更看重地点还是方向？",
          phase: index === 0 ? "template" : "deepen",
        })),
        profile_draft: { current_goal: ["backend engineer"], hard_constraints: {}, soft_preferences: {}, avoid_roles: [] },
        round: state.round,
        phase: state.round === 0 ? "template" : "deepen",
        completeness: state.round >= 2 ? 1 : 0.4,
        can_finalize: state.round >= 2,
      });
    if (path.endsWith("/consult") && method === "POST") {
      state.round += 1;
      return json({
        assistant_reply: `明白了（第 ${state.round} 轮）。`,
        next_question: state.round >= 2 ? "还有想补充的吗？" : "你更看重地点还是方向？",
        phase: state.round === 1 ? "template" : "deepen",
        completeness: state.round >= 2 ? 1 : 0.4,
        can_finalize: state.round >= 2,
        round: state.round,
        profile_draft: { current_goal: ["backend engineer"], hard_constraints: {}, soft_preferences: {}, avoid_roles: [] },
      });
    }
    if (path.endsWith("/consult/finalize"))
      return json({
        career_goal: "Find backend engineer roles matching my Python experience",
        hard_constraints: { locations: ["Shanghai"] },
        soft_preferences: { preferred_industries: ["tech"] },
        avoid_roles: ["sales"],
        result_count: 5,
      });
    if (path.endsWith("/match-brief")) {
      state.briefed = true;
      return json(
        {
          run_id: "run-e2e-1",
          session_id: "sess-e2e-1",
          brief: {
            career_goal: "Find backend engineer roles matching my Python experience",
            hard_constraints: { locations: ["Shanghai"] },
            soft_preferences: { preferred_industries: ["tech"] },
            avoid_roles: ["sales"],
            result_count: 5,
            plan_version: 1,
            plan_hash: "b".repeat(64),
            created_at: "2026-08-05T09:05:00Z",
          },
        },
        201,
      );
    }
    if (path.endsWith("/execute")) {
      state.executed = true;
      return json({
        run_id: "run-e2e-1",
        session_id: "sess-e2e-1",
        status: "running",
        stage: "retrieval",
        result_ready: false,
        plan_version: 1,
        plan_hash: "b".repeat(64),
        retry_after_ms: 400,
        completed_stages: ["intent"],
        total_stages: 7,
        warning_codes: [],
        error_code: null,
      });
    }
    if (path.endsWith("/status"))
      return json({
        run_id: "run-e2e-1",
        session_id: "sess-e2e-1",
        status: state.executed ? "completed" : "plan_ready",
        stage: state.executed ? "finalization" : null,
        result_ready: state.executed,
        plan_version: 1,
        plan_hash: "b".repeat(64),
        retry_after_ms: state.executed ? null : 400,
        completed_stages: state.executed ? ["intent", "retrieval", "strategy", "verification"] : [],
        total_stages: 7,
        warning_codes: [],
        error_code: null,
      });
    if (path.endsWith("/conversation"))
      return json({
        run_id: "run-e2e-1",
        status: state.executed ? "completed" : "running",
        stage: "finalization",
        next_poll_ms: state.executed ? null : 500,
        messages: [
          { seq: 1, persona: "pm", display_name: "项目经理·PM", kind: "intro", stage: "intent", text: "任务开始，团队就位。" },
          { seq: 2, persona: "job_scout", display_name: "岗位顾问·小检", kind: "progress", stage: "retrieval", text: "硬过滤与双路召回完成。" },
          { seq: 3, persona: "pm", display_name: "项目经理·PM", kind: "result", stage: "finalization", text: "结果已通过发布核查。" },
        ],
      });
    if (path.endsWith("/result"))
      return json({
        run_id: "run-e2e-1",
        status: "completed",
        result: {
          summary: "1 evidence-grounded role recommended.",
          recommended_roles: [
            {
              job_id: "job-e2e-1",
              title: "Backend Engineer",
              company: "示例科技",
              location: "Shanghai",
              tier: "now_fit",
              concise_explanation: "你的 Python 服务经验与该岗位要求直接对应。",
              why_this_match: ["JD 要求 Python 服务开发"],
              evidence: [{ evidence_span_id: "job-e2e-1:skills:1", field: "required_skills", content: "Python, SQL required." }],
              resume_evidence: [{ evidence_span_id: "R001", field: "resume", content: "Built a Python service." }],
              source_url: null,
              listing_kind: "dataset_only",
              demo_synthetic: true,
              country_code: "CN",
            },
          ],
          resume_strategy: [{ section: "experience", suggestion: "量化你的服务性能收益。", evidence_span_ids: ["R001"] }],
          skill_gaps: [],
          career_path: [],
          warnings: [],
        },
      });
    if (path.endsWith("/reaction")) {
      state.reactions += 1;
      return json({ feedback_id: state.reactions, run_id: "run-e2e-1", status: "feedback_recorded" }, 202);
    }
    return json({ detail: `unmocked ${method} ${path}` }, 500);
  });
}

test("v2 group-chat journey: login to evidence-backed results", async ({ page }) => {
  const state: FlowState = {
    loggedIn: false,
    uploaded: false,
    confirmed: false,
    round: 0,
    briefed: false,
    executed: false,
    reactions: 0,
  };
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

  await page.getByRole("button", { name: "生成确认单" }).click();
  await expect(page.getByText("Match Brief 确认单")).toBeVisible();
  await page.getByRole("button", { name: "确认无误，开始匹配" }).click();

  await expect(page.getByText("结果已通过发布核查。")).toBeVisible();
  await expect(page.getByText("Backend Engineer")).toBeVisible();
  await expect(page.getByText("现在就投")).toBeVisible();
  await expect(page.getByText("演示数据 · CN")).toBeVisible();

  await page.getByRole("button", { name: "查看证据" }).click();
  await expect(page.getByText("Python, SQL required.")).toBeVisible();
  await page.getByRole("button", { name: "关闭证据" }).click();

  await page.getByRole("button", { name: "提交反馈" }).click();
  await expect(page.getByText(/反馈已记录/)).toBeVisible();

  expect(
    await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth),
  ).toBe(false);
});

test("unauthenticated /app visit returns to landing login", async ({ page }) => {
  const state: FlowState = {
    loggedIn: false,
    uploaded: false,
    confirmed: false,
    round: 0,
    briefed: false,
    executed: false,
    reactions: 0,
  };
  await installV2Api(page, state);
  await page.goto("/app");
  await expect(page.getByRole("button", { name: "登录 / 注册" })).toBeVisible();
});

test("refresh mid-consultation restores transcript from GET consult", async ({ page }) => {
  const state: FlowState = {
    loggedIn: true,
    uploaded: true,
    confirmed: true,
    round: 2,
    briefed: false,
    executed: false,
    reactions: 0,
  };
  await installV2Api(page, state);
  await page.goto("/app/sessions/sess-e2e-1");
  await expect(page.getByText("明白了（第 1 轮）。")).toBeVisible();
  await expect(page.getByText("明白了（第 2 轮）。")).toBeVisible();
  await expect(page.getByRole("button", { name: "生成确认单" })).toBeVisible();
});
